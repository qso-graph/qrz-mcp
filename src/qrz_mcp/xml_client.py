"""QRZ XML Callsign API client with session management."""

from __future__ import annotations

import os
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import __version__
from .cache import TTLCache
from .rate_limiter import RateLimiter
from .types import CallsignRecord, DxccRecord

_XML_URL = "https://xmldata.qrz.com/xml/current/"

# Cache TTLs
_CALLSIGN_TTL = 300.0  # 5 minutes
_DXCC_TTL = 3600.0  # 1 hour

# Mock XML for testing
_MOCK_CALLSIGN_XML = """<?xml version="1.0" ?>
<QRZDatabase version="1.34">
  <Callsign>
    <call>W1AW</call>
    <fname>Hiram Percy</fname>
    <name>Maxim</name>
    <grid>FN31pr</grid>
    <lat>41.714775</lat>
    <lon>-72.727260</lon>
    <dxcc>291</dxcc>
    <country>United States</country>
    <class>C</class>
    <email>w1aw@arrl.org</email>
    <eqsl>1</eqsl>
    <mqsl>1</mqsl>
    <lotw>1</lotw>
    <cqzone>5</cqzone>
    <ituzone>8</ituzone>
    <state>CT</state>
    <county>Hartford</county>
    <image>https://cdn.qrz.com/w1aw.jpg</image>
  </Callsign>
  <Session>
    <Key>mock-session-key</Key>
  </Session>
</QRZDatabase>"""

_MOCK_DXCC_XML = """<?xml version="1.0" ?>
<QRZDatabase version="1.34">
  <DXCC>
    <dxcc>291</dxcc>
    <name>United States</name>
    <continent>NA</continent>
    <cqzone>5</cqzone>
    <ituzone>8</ituzone>
    <lat>37.6</lat>
    <lon>-97.0</lon>
    <cc>US</cc>
  </DXCC>
  <Session>
    <Key>mock-session-key</Key>
  </Session>
</QRZDatabase>"""


def _is_mock() -> bool:
    return os.getenv("QRZ_MCP_MOCK") == "1"


class XmlClient:
    """QRZ XML API client with lazy session management.

    Session key is IP-bound. Re-login when response lacks <Key>.
    """

    def __init__(self, rate_limiter: RateLimiter) -> None:
        self._session_key: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._agent: str = f"qrz-mcp/{__version__}"
        self._lock = threading.Lock()
        self._rate_limiter = rate_limiter
        self._cache = TTLCache()

    def configure(self, username: str, password: str, callsign: str | None = None) -> None:
        """Set credentials. Called once per persona."""
        with self._lock:
            self._username = username
            self._password = password
            if callsign:
                self._agent = f"qrz-mcp/{__version__} ({callsign})"

    def _get(self, params: dict[str, str]) -> ET.Element:
        """HTTP GET to QRZ XML API, return parsed root element.

        Catches all urllib exceptions to prevent credential-bearing URLs
        from leaking through error messages (login puts password in query params).
        """
        self._rate_limiter.wait()
        qs = urllib.parse.urlencode(params, safe=";")
        url = f"{_XML_URL}?{qs}"
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", self._agent)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except ConnectionRefusedError:
            self._rate_limiter.freeze_ban()
            raise RuntimeError("QRZ connection refused — possible IP ban")
        except OSError as e:
            if "Connection refused" in str(e):
                self._rate_limiter.freeze_ban()
            raise RuntimeError("QRZ request failed — check network and credentials")
        return ET.fromstring(body)

    def _login(self) -> str:
        """Authenticate and return session key."""
        if not self._username or not self._password:
            raise ValueError("QRZ XML credentials not configured")

        root = self._get({
            "username": self._username,
            "password": self._password,
            "agent": self._agent,
        })

        session = root.find("Session")
        if session is None:
            raise RuntimeError("QRZ: no Session in login response")

        error = session.findtext("Error")
        if error:
            self._rate_limiter.freeze_auth()
            raise RuntimeError(f"QRZ login failed: {error}")

        key = session.findtext("Key")
        if not key:
            raise RuntimeError("QRZ: no Key in login response")

        with self._lock:
            self._session_key = key
        return key

    def _ensure_session(self) -> str:
        """Return a valid session key, logging in if needed."""
        with self._lock:
            if self._session_key:
                return self._session_key
        return self._login()

    def _request(self, params: dict[str, str], retry: bool = True) -> ET.Element:
        """Make an authenticated XML request. Re-login on session expiry."""
        key = self._ensure_session()
        params["s"] = key
        root = self._get(params)

        session = root.find("Session")
        if session is not None:
            new_key = session.findtext("Key")
            if new_key:
                with self._lock:
                    self._session_key = new_key
                return root

            error = session.findtext("Error") or ""
            if retry and ("session" in error.lower() or "timeout" in error.lower()):
                with self._lock:
                    self._session_key = None
                return self._request(params, retry=False)

            if error:
                raise RuntimeError(f"QRZ XML error: {error}")

        return root

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def lookup(self, callsign: str) -> CallsignRecord:
        """Look up a callsign. Returns structured record."""
        key = f"call:{callsign.upper()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if _is_mock():
            root = ET.fromstring(_MOCK_CALLSIGN_XML)
        else:
            root = self._request({"callsign": callsign.upper()})

        node = root.find("Callsign")
        if node is None:
            return CallsignRecord(call=callsign.upper())

        def _text(tag: str) -> str:
            return (node.findtext(tag) or "").strip()  # type: ignore[union-attr]

        def _float(tag: str) -> float | None:
            v = _text(tag)
            return float(v) if v else None

        def _int(tag: str) -> int | None:
            v = _text(tag)
            return int(v) if v else None

        def _bool(tag: str) -> bool:
            return _text(tag) in ("1", "Y", "y", "true")

        rec = CallsignRecord(
            call=_text("call"),
            fname=_text("fname"),
            name=_text("name"),
            grid=_text("grid"),
            dxcc=_int("dxcc") or 0,
            country=_text("country"),
            license_class=_text("class"),
            email=_text("email"),
            qslmgr=_text("qslmgr"),
            image=_text("image"),
            eqsl=_bool("eqsl"),
            mqsl=_bool("mqsl"),
            lotw=_bool("lotw"),
            cqzone=_int("cqzone") or 0,
            ituzone=_int("ituzone") or 0,
            iota=_text("iota"),
            county=_text("county"),
            state=_text("state"),
            born=_text("born"),
            addr1=_text("addr1"),
            addr2=_text("addr2"),
        )
        lat = _float("lat")
        lon = _float("lon")
        if lat is not None:
            rec["lat"] = lat
        if lon is not None:
            rec["lon"] = lon

        self._cache.set(key, rec, _CALLSIGN_TTL)
        return rec

    def dxcc(self, query: str) -> DxccRecord:
        """Resolve DXCC entity from callsign or numeric code."""
        key = f"dxcc:{query.upper()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        if _is_mock():
            root = ET.fromstring(_MOCK_DXCC_XML)
        else:
            root = self._request({"dxcc": query})

        node = root.find("DXCC")
        if node is None:
            return DxccRecord(name=f"Not found: {query}")

        def _text(tag: str) -> str:
            return (node.findtext(tag) or "").strip()  # type: ignore[union-attr]

        def _float(tag: str) -> float | None:
            v = _text(tag)
            return float(v) if v else None

        def _int(tag: str) -> int | None:
            v = _text(tag)
            return int(v) if v else None

        rec = DxccRecord(
            dxcc=_int("dxcc") or 0,
            name=_text("name"),
            continent=_text("continent"),
            cqzone=_int("cqzone") or 0,
            ituzone=_int("ituzone") or 0,
            cc=_text("cc"),
        )
        lat = _float("lat")
        lon = _float("lon")
        if lat is not None:
            rec["lat"] = lat
        if lon is not None:
            rec["lon"] = lon

        self._cache.set(key, rec, _DXCC_TTL)
        return rec
