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

# ADIF field regex: <FIELD:LEN>VALUE or <FIELD:LEN:TYPE>VALUE
_ADIF_FIELD_RE = re.compile(r"<(\w+):(\d+)(?::\w+)?>", re.IGNORECASE)


def _is_mock() -> bool:
    return os.getenv("QRZ_MCP_MOCK") == "1"


def _parse_kv(body: str) -> dict[str, str]:
    """Parse QRZ logbook key=value response (& delimited)."""
    result: dict[str, str] = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            result[k.upper()] = urllib.parse.unquote_plus(v)
    return result


def _parse_adif_records(adif: str) -> list[dict[str, str]]:
    """Parse ADIF text into a list of field dicts."""
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    pos = 0
    upper = adif.upper()

    # Skip header (everything before <EOH>)
    eoh = upper.find("<EOH>")
    if eoh >= 0:
        pos = eoh + 5

    while pos < len(adif):
        # Check for <EOR>
        if upper[pos:pos + 5] == "<EOR>":
            if current:
                records.append(current)
                current = {}
            pos += 5
            continue

        m = _ADIF_FIELD_RE.match(adif, pos)
        if m:
            field = m.group(1).upper()
            length = int(m.group(2))
            value_start = m.end()
            value = adif[value_start:value_start + length]
            current[field] = value.strip()
            pos = value_start + length
        else:
            pos += 1

    if current:
        records.append(current)

    return records


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
_MOCK_STATUS_BODY = "RESULT=OK&COUNT=1547&DXCC=142&US_STATES=48&CONFIRMED=892&OWNER=KI7MT&START=20180101&END=20260301"

_MOCK_FETCH_ADIF = (
    "<CALL:5>KI7MT<BAND:3>20M<MODE:3>FT8<QSO_DATE:8>20260301<TIME_ON:6>012345"
    "<RST_SENT:3>-10<RST_RCVD:3>-12<GRIDSQUARE:6>DN13sa<DXCC:3>291<COUNTRY:13>United States<EOR>"
    "<CALL:4>W1AW<BAND:3>40M<MODE:2>CW<QSO_DATE:8>20260228<TIME_ON:6>200000"
    "<RST_SENT:3>599<RST_RCVD:3>599<GRIDSQUARE:6>FN31pr<DXCC:3>291<COUNTRY:13>United States<EOR>"
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
            records = _parse_adif_records(_MOCK_FETCH_ADIF)
            return [_adif_to_qso(r) for r in records[:limit]]

        all_qsos: list[QsoRecord] = []
        after_logid: str | None = None

        while len(all_qsos) < limit:
            params: dict[str, str] = {"ACTION": "FETCH"}

            # Build OPTION filter string
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
