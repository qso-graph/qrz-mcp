"""QRZ Logbook API client for status and QSO fetch."""

from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from typing import Any

from . import __version__
from .rate_limiter import RateLimiter
from .types import LogbookStatus, QsoRecord

_LOGBOOK_URL = "https://logbook.qrz.com/api"

# ADIF field marker: <FIELD:LEN>VALUE or <FIELD:LEN:TYPE>VALUE.
# Matches both the literal form and QRZ's escaped form ("&lt;call:6&gt;"), so
# a payload can be scanned without rewriting the value text around it.
_ADIF_FIELD_RE = re.compile(
    r"(?:<|&lt;)(\w+):(\d+)(?::\w+)?(?:>|&gt;)", re.IGNORECASE
)

# End-of-record / end-of-header markers, literal or escaped.
_ADIF_EOR_RE = re.compile(r"(?:<|&lt;)eor(?:>|&gt;)", re.IGNORECASE)
_ADIF_EOH_RE = re.compile(r"(?:<|&lt;)eoh(?:>|&gt;)", re.IGNORECASE)

# "ADIF" is the final key in a FETCH response and its value may contain raw
# "&", "=" and newlines, so it is taken as the entire rest of the body rather
# than split. Remaining keys are plain "&"-delimited pairs.
_ADIF_KEY_RE = re.compile(r"(?:^|&)ADIF=", re.IGNORECASE)


def _is_mock() -> bool:
    return os.getenv("QRZ_MCP_MOCK") == "1"


def _parse_kv(body: str) -> dict[str, str]:
    """Parse a QRZ logbook key=value response.

    QRZ escapes only the ADIF *markers* ("&lt;call:6&gt;"); the field values
    themselves are passed through verbatim. A value may therefore contain raw
    "&", "=", "+", "%" and newline characters, none of which are delimiters or
    encodings. Measured against live responses:

        &lt;comment:7&gt;R&R net          bare "&" inside the value
        &lt;comment:10&gt;A+B 50%20C      "+"/"%" are literal, not URL-encoded
        &lt;comment:23&gt;&amp; &lt; ...   user text kept verbatim, not an entity

    Splitting the body on every "&" shreds that payload (the original bug), and
    URL-decoding or HTML-unescaping the value corrupts it ("A+B" -> "A B",
    "&amp;" -> "&"). So the ADIF value is taken as the whole remainder of the
    body and left byte-for-byte intact; only the short scalar keys around it
    are split normally.
    """
    result: dict[str, str] = {}

    m = _ADIF_KEY_RE.search(body)
    if m:
        # Everything after "ADIF=" is payload, verbatim.
        result["ADIF"] = body[m.end():]
        body = body[: m.start()]

    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k.upper()] = v
    return result


def _parse_adif_records(adif: str) -> list[dict[str, str]]:
    """Parse ADIF text into a list of field dicts.

    Values are consumed by their declared length, never by scanning for the
    next delimiter. That is what makes arbitrary user text safe: a comment may
    contain "&", "=", "<", ">" or an entity-like literal, and none of it can be
    mistaken for structure. Markers are matched in either literal ("<call:6>")
    or QRZ-escaped ("&lt;call:6&gt;") form, so the payload never has to be
    rewritten before parsing — which is what previously corrupted values.

    Lengths are counted in characters, matching QRZ (a 12-character accented
    comment is declared as 12, not its 16-byte UTF-8 length).
    """
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    pos = 0

    # Skip the header, if present (everything up to and including <EOH>).
    eoh = _ADIF_EOH_RE.search(adif)
    if eoh:
        pos = eoh.end()

    while pos < len(adif):
        eor = _ADIF_EOR_RE.match(adif, pos)
        if eor:
            if current:
                records.append(current)
                current = {}
            pos = eor.end()
            continue

        m = _ADIF_FIELD_RE.match(adif, pos)
        if m:
            field = m.group(1).upper()
            length = int(m.group(2))
            value_start = m.end()
            # Clamp: a declared length longer than the remaining text must not
            # read past the end, and pos must never rewind before the marker.
            value_end = min(value_start + length, len(adif))
            current[field] = adif[value_start:value_end].strip()
            pos = max(m.end(), value_end)
        else:
            pos += 1

    if current:
        records.append(current)

    return records


_ADIF_HEADER = "<ADIF_VER:5>3.1.6\n<PROGRAMID:7>qrz-mcp\n<EOH>\n"


def _records_to_adif(records: list[dict[str, str]]) -> str:
    """Serialise parsed records back to standard ADIF with literal markers.

    QRZ sends markers escaped ("&lt;call:6&gt;"), which no logger will import.
    Re-emitting from parsed records (rather than concatenating raw fragments)
    guarantees the output is a valid .adi file and that each declared length
    matches its value — including values that themselves contain "<", ">" or
    "&", which are legal ADIF payload precisely because fields are
    length-delimited.
    """
    lines: list[str] = []
    for rec in records:
        fields = "".join(f"<{k}:{len(v)}>{v}" for k, v in rec.items())
        lines.append(f"{fields}<EOR>")
    return "\n".join(lines) + ("\n" if lines else "")


def _count_records(adif_text: str) -> int:
    """Count QSO records in ADIF text via its <EOR> markers.

    Counts real markers only. A literal "<eor>" typed into a comment is part of
    a length-delimited value, so it is skipped by the field scanner and cannot
    inflate the count the way a naive substring count would.
    """
    return len(_parse_adif_records(adif_text))


def _adif_to_qso(rec: dict[str, str]) -> QsoRecord:
    """Convert a raw ADIF dict to QsoRecord."""
    qso = QsoRecord(
        call=rec.get("CALL", ""),
        band=rec.get("BAND", ""),
        mode=rec.get("MODE", ""),
        qso_date=rec.get("QSO_DATE", ""),
        time_on=rec.get("TIME_ON", ""),
    )
    if "APP_QRZLOG_LOGID" in rec:
        qso["logid"] = rec["APP_QRZLOG_LOGID"]
    if "RST_SENT" in rec:
        qso["rst_sent"] = rec["RST_SENT"]
    if "RST_RCVD" in rec:
        qso["rst_rcvd"] = rec["RST_RCVD"]
    if "GRIDSQUARE" in rec:
        qso["gridsquare"] = rec["GRIDSQUARE"]
    if "COMMENT" in rec:
        qso["comment"] = rec["COMMENT"]
    if "QSL_RCVD" in rec:
        qso["qsl_rcvd"] = rec["QSL_RCVD"]
    if "QSL_SENT" in rec:
        qso["qsl_sent"] = rec["QSL_SENT"]
    if "DXCC" in rec:
        try:
            qso["dxcc"] = int(rec["DXCC"])
        except ValueError:
            pass
    if "COUNTRY" in rec:
        qso["country"] = rec["COUNTRY"]
    if "FREQ" in rec:
        qso["freq"] = rec["FREQ"]
    return qso


# Mock responses
#
# Transcribed from live QRZ responses so mock mode exercises the real wire
# format: ADIF *markers* escaped as "&lt;...&gt;", field values passed through
# verbatim (raw "&", "+", "%" and entity-like literals all appear unmodified),
# and ADIF as the final key. Mock fetch/download decode these through the same
# _parse_kv path as live traffic, so a parser that mishandles any of it fails
# the suite instead of silently returning 0 records or corrupted text.
_MOCK_STATUS_BODY = "RESULT=OK&COUNT=1547&DXCC=142&US_STATES=48&CONFIRMED=892&OWNER=KI7MT&START=20180101&END=20260301"

# Escaped markers, verbatim values — exactly as QRZ sends it.
# The comments below are the adversarial cases confirmed against a live book:
#   "R&R net"            bare "&" in a value (not a delimiter)
#   "A+B 50%20C"         "+"/"%" are literal (not URL-encoded)
#   "&amp; &lt; literal" entity-looking user text (must not be unescaped)
_MOCK_FETCH_ADIF_ESCAPED = (
    "&lt;APP_QRZLOG_LOGID:4&gt;1001&lt;CALL:5&gt;KI7MT&lt;BAND:3&gt;20M"
    "&lt;MODE:3&gt;FT8&lt;QSO_DATE:8&gt;20260301&lt;TIME_ON:6&gt;012345"
    "&lt;RST_SENT:3&gt;-10&lt;RST_RCVD:3&gt;-12&lt;GRIDSQUARE:6&gt;DN13sa"
    "&lt;DXCC:3&gt;291&lt;COUNTRY:13&gt;United States"
    "&lt;COMMENT:7&gt;R&R net&lt;EOR&gt;\n"
    "&lt;APP_QRZLOG_LOGID:4&gt;1002&lt;CALL:4&gt;W1AW&lt;BAND:3&gt;40M"
    "&lt;MODE:2&gt;CW&lt;QSO_DATE:8&gt;20260228&lt;TIME_ON:6&gt;200000"
    "&lt;RST_SENT:3&gt;599&lt;RST_RCVD:3&gt;599&lt;GRIDSQUARE:6&gt;FN31pr"
    "&lt;DXCC:3&gt;291&lt;COUNTRY:13&gt;United States"
    "&lt;COMMENT:10&gt;A+B 50%20C&lt;EOR&gt;\n"
    "&lt;APP_QRZLOG_LOGID:4&gt;1003&lt;CALL:6&gt;PU2ORH&lt;BAND:2&gt;2m"
    "&lt;MODE:2&gt;FM&lt;QSO_DATE:8&gt;20260827&lt;TIME_ON:4&gt;1500"
    "&lt;RST_SENT:2&gt;59&lt;RST_RCVD:2&gt;59&lt;DXCC:3&gt;108"
    "&lt;COUNTRY:6&gt;Brazil"
    "&lt;COMMENT:23&gt;&amp; &lt; &gt; literal&lt;EOR&gt;\n"
)

# ADIF is the final key, and its value runs to the end of the body.
_MOCK_FETCH_BODY = (
    "RESULT=OK&COUNT=3&LOGIDS=1001,1002,1003&ADIF=" + _MOCK_FETCH_ADIF_ESCAPED
)


class LogbookClient:
    """QRZ Logbook API client."""

    def __init__(self, rate_limiter: RateLimiter) -> None:
        self._api_key: str | None = None
        self._agent = f"qrz-mcp/{__version__}"
        self._rate_limiter = rate_limiter

    def configure(self, api_key: str, callsign: str | None = None) -> None:
        """Set API key. Called once per persona."""
        self._api_key = api_key
        if callsign:
            self._agent = f"qrz-mcp/{__version__} ({callsign})"

    def _post(self, params: dict[str, str]) -> dict[str, str]:
        """POST to logbook API, return parsed key=value response."""
        if not self._api_key:
            raise ValueError("QRZ Logbook API key not configured")

        self._rate_limiter.wait()
        params["KEY"] = self._api_key
        data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(_LOGBOOK_URL, data=data, method="POST")
        req.add_header("User-Agent", self._agent)
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except ConnectionRefusedError:
            self._rate_limiter.freeze_ban()
            raise RuntimeError("QRZ Logbook connection refused — possible IP ban")
        except OSError:
            raise RuntimeError("QRZ Logbook request failed — check network and API key")

        kv = _parse_kv(body)

        if kv.get("RESULT") == "AUTH":
            self._rate_limiter.freeze_auth()
            raise RuntimeError(f"QRZ Logbook auth failed: {kv.get('REASON', 'unknown')}")

        if kv.get("RESULT") == "FAIL":
            raise RuntimeError(f"QRZ Logbook error: {kv.get('REASON', 'unknown')}")

        return kv

    def status(self) -> LogbookStatus:
        """Get logbook statistics."""
        if _is_mock():
            kv = _parse_kv(_MOCK_STATUS_BODY)
        else:
            kv = self._post({"ACTION": "STATUS"})

        def _int(key: str) -> int:
            try:
                return int(kv.get(key, "0"))
            except ValueError:
                return 0

        return LogbookStatus(
            callsign=kv.get("OWNER", ""),
            count=_int("COUNT"),
            confirmed=_int("CONFIRMED"),
            dxcc=_int("DXCC"),
            us_states=_int("US_STATES"),
            start_date=kv.get("START", ""),
            end_date=kv.get("END", ""),
        )

    def _build_options(
        self,
        band: str | None = None,
        mode: str | None = None,
        callsign: str | None = None,
        dxcc: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        confirmed_only: bool = False,
    ) -> list[str]:
        """Build OPTION filter list for FETCH requests."""
        options: list[str] = []
        if band:
            options.append(f"BAND:{band.upper()}")
        if mode:
            options.append(f"MODE:{mode.upper()}")
        if callsign:
            options.append(f"CALL:{callsign.upper()}")
        if dxcc is not None:
            options.append(f"DXCC:{dxcc}")
        if start_date:
            options.append(f"AFTER:{start_date.replace('-', '')}")
        if end_date:
            options.append(f"BEFORE:{end_date.replace('-', '')}")
        if confirmed_only:
            options.append("STATUS:CONFIRMED")
        return options

    def fetch(
        self,
        band: str | None = None,
        mode: str | None = None,
        callsign: str | None = None,
        dxcc: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        confirmed_only: bool = False,
        limit: int = 250,
    ) -> list[QsoRecord]:
        """Fetch QSOs with filters. Transparently paginates via AFTERLOGID."""
        if _is_mock():
            # Decode the mock exactly like a live response, so mock mode
            # exercises the real key=value + escaped-ADIF parsing path.
            adif = _parse_kv(_MOCK_FETCH_BODY).get("ADIF", "")
            records = _parse_adif_records(adif)
            return [_adif_to_qso(r) for r in records[:limit]]

        all_qsos: list[QsoRecord] = []
        after_logid: str | None = None
        options = self._build_options(band, mode, callsign, dxcc, start_date, end_date, confirmed_only)

        while len(all_qsos) < limit:
            params: dict[str, str] = {"ACTION": "FETCH"}
            if options:
                params["OPTION"] = ",".join(options)
            if after_logid:
                params["AFTERLOGID"] = after_logid

            kv = self._post(params)

            adif = kv.get("ADIF", "")
            if not adif:
                break

            records = _parse_adif_records(adif)
            if not records:
                break

            for rec in records:
                if len(all_qsos) >= limit:
                    break
                all_qsos.append(_adif_to_qso(rec))

            # Pagination cursor
            logids = kv.get("LOGIDS", "")
            if logids:
                last_id = logids.split(",")[-1].strip()
                if last_id and last_id != after_logid:
                    after_logid = last_id
                else:
                    break
            else:
                break

        return all_qsos

    def download_adif(
        self,
        band: str | None = None,
        mode: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        """Download complete logbook as raw ADIF text.

        Paginates through ALL records and emits a standard ADIF document.

        QRZ returns markers HTML-escaped, so fragments are parsed and
        re-serialised with literal markers rather than concatenated verbatim —
        otherwise the ".adi" output would contain "&lt;call:6&gt;" and no
        logger could import it.
        """
        if _is_mock():
            adif = _parse_kv(_MOCK_FETCH_BODY).get("ADIF", "")
            records = _parse_adif_records(adif)
            adif_text = _ADIF_HEADER + _records_to_adif(records)
            return {"adif": adif_text, "record_count": len(records)}

        all_records: list[dict[str, str]] = []
        after_logid: str | None = None
        options = self._build_options(band=band, mode=mode, start_date=start_date, end_date=end_date)

        while True:
            params: dict[str, str] = {"ACTION": "FETCH"}
            if options:
                params["OPTION"] = ",".join(options)
            if after_logid:
                params["AFTERLOGID"] = after_logid

            kv = self._post(params)

            adif = kv.get("ADIF", "")
            if not adif:
                break

            all_records.extend(_parse_adif_records(adif))

            # Pagination cursor
            logids = kv.get("LOGIDS", "")
            if logids:
                last_id = logids.split(",")[-1].strip()
                if last_id and last_id != after_logid:
                    after_logid = last_id
                else:
                    break
            else:
                break

        adif_text = _ADIF_HEADER + _records_to_adif(all_records)
        return {"adif": adif_text, "record_count": len(all_records)}
