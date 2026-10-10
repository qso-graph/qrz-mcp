"""L2 unit tests for qrz-mcp logbook date filters, paging and ordering.

Covers the QRZ Logbook API behaviour documented at
https://www.qrz.com/docs/logbook/QRZLogbookAPI.html:

  * the date filter is ``BETWEEN:YYYY-MM-DD+YYYY-MM-DD`` (there is no
    AFTER/BEFORE option, and QRZ answers RESULT=FAIL without a REASON);
  * paging is ``MAX:250,AFTERLOGID:n`` inside OPTION, with n advancing to the
    highest ``app_qrzlog_logid`` seen plus one (QRZ rejects unrecognized POST
    parameters, and ADIF-type responses carry no LOGIDS key);
  * records come back oldest first.

The tests run the real ``LogbookClient._post`` against a fake
``urllib.request.urlopen`` that speaks QRZ's wire format (escaped markers,
verbatim values, ADIF as the final key), so request construction and response
parsing are both exercised. No network access.

Test IDs: QRZ-L2-060 through QRZ-L2-072
"""

from __future__ import annotations

import io
import os
import urllib.parse
from contextlib import contextmanager
from unittest import mock

import pytest

from qrz_mcp.logbook_client import LogbookClient
from qrz_mcp.rate_limiter import RateLimiter

# Non-contiguous logids, one QSO per day, so ordering and cursor bugs show up.
_TOTAL = 620  # three pages at MAX:250


def _build_db():
    import datetime

    base = datetime.date(2020, 1, 1)
    rows = []
    for i in range(_TOTAL):
        day = base + datetime.timedelta(days=i)
        rows.append(
            {
                "app_qrzlog_logid": str(5000 + i * 3),
                "call": f"K{i:04d}",
                "qso_date": day.strftime("%Y%m%d"),
                "time_on": "1200",
                "band": "20m",
                "mode": "USB",
                "comment": "R&R net" if i % 100 == 0 else "",
            }
        )
    return rows


_DB = _build_db()


def _wire(row: dict[str, str]) -> str:
    """One record as QRZ sends it: escaped markers, verbatim values."""
    fields = "".join(
        f"&lt;{k}:{len(v)}&gt;{v}" for k, v in row.items() if v != ""
    )
    return fields + "&lt;eor&gt;\n"


class _FakeQrz:
    """Stands in for logbook.qrz.com/api and records every request."""

    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []

    def urlopen(self, req, timeout=15):
        form = urllib.parse.parse_qs(req.data.decode(), keep_blank_values=True)
        params = {k: v[0] for k, v in form.items()}
        self.requests.append(params)

        # The real server rejects unrecognized parameters.
        assert set(params) <= {"KEY", "ACTION", "OPTION"}, sorted(params)

        options = dict(
            o.split(":", 1) for o in params.get("OPTION", "").split(",") if o
        )
        assert set(options) <= {
            "AFTERLOGID", "MAX", "BETWEEN", "BAND", "MODE", "CALL", "DXCC", "STATUS",
        }, sorted(options)

        after = int(options.get("AFTERLOGID", 0))
        limit = int(options.get("MAX", 10**9))
        rows = [r for r in _DB if int(r["app_qrzlog_logid"]) >= after]
        if "BETWEEN" in options:
            start, end = (d.replace("-", "") for d in options["BETWEEN"].split("+"))
            rows = [r for r in rows if start <= r["qso_date"] <= end]
        rows = rows[:limit]

        # ADIF is the final key; no LOGIDS key, as in real ADIF-type responses.
        body = f"RESULT=OK&COUNT={len(rows)}&ADIF=" + "".join(_wire(r) for r in rows)
        return _Response(body.encode())


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@contextmanager
def _live_client():
    """A LogbookClient wired to the fake QRZ, with mock mode off."""
    fake = _FakeQrz()
    client = LogbookClient(RateLimiter(min_delay=0.0, tokens_per_min=100_000))
    client.configure("TESTKEY", "W1AW")
    with mock.patch.dict(os.environ, {"QRZ_MCP_MOCK": "0"}), mock.patch(
        "urllib.request.urlopen", fake.urlopen
    ):
        yield client, fake


def _client_for_options() -> LogbookClient:
    return LogbookClient(RateLimiter(min_delay=0.0, tokens_per_min=100))


# ---------------------------------------------------------------------------
# QRZ-L2-060..063: date filter
# ---------------------------------------------------------------------------


class TestDateFilter:
    def test_between_replaces_after_before(self):
        """QRZ-L2-060: a date range is sent as BETWEEN:start+end."""
        options = _client_for_options()._build_options(
            start_date="2026-05-01", end_date="2026-07-31"
        )

        assert "BETWEEN:2026-05-01+2026-07-31" in options
        assert not any(o.startswith(("AFTER:", "BEFORE:")) for o in options)

    def test_compact_dates_are_normalised(self):
        """QRZ-L2-061: YYYYMMDD input becomes the dashed form QRZ expects."""
        options = _client_for_options()._build_options(
            start_date="20260501", end_date="20260731"
        )

        assert options == ["BETWEEN:2026-05-01+2026-07-31"]

    def test_open_ended_ranges(self):
        """QRZ-L2-062: a single bound still yields a valid BETWEEN."""
        client = _client_for_options()

        only_start = client._build_options(start_date="2026-01-01")
        only_end = client._build_options(end_date="2026-12-31")

        assert only_start == ["BETWEEN:2026-01-01+2100-12-31"]
        assert only_end == ["BETWEEN:1900-01-01+2026-12-31"]

    def test_no_dates_no_between(self):
        """QRZ-L2-063: without dates no date option is sent."""
        assert _client_for_options()._build_options(band="20m") == ["BAND:20M"]


# ---------------------------------------------------------------------------
# QRZ-L2-064..067: paging
# ---------------------------------------------------------------------------


class TestPaging:
    def test_paging_uses_options_not_parameters(self):
        """QRZ-L2-064: MAX and AFTERLOGID travel inside OPTION only."""
        with _live_client() as (client, fake):
            client.fetch(limit=5)

        first = fake.requests[0]
        assert set(first) == {"KEY", "ACTION", "OPTION"}
        assert first["OPTION"] == "MAX:5,AFTERLOGID:0"

    def test_cursor_is_highest_logid_plus_one(self):
        """QRZ-L2-065: no duplicates or gaps across pages with sparse logids.

        The fake QRZ sends no LOGIDS key (as with real ADIF-type responses), so
        the cursor must come from the records' own app_qrzlog_logid values.
        """
        with _live_client() as (client, fake):
            qsos = client.fetch(limit=10_000)

        assert len(qsos) == _TOTAL
        assert [q["logid"] for q in qsos] == [r["app_qrzlog_logid"] for r in _DB]
        assert len(fake.requests) == 3  # 250 + 250 + 120
        assert fake.requests[1]["OPTION"] == (
            f"MAX:250,AFTERLOGID:{int(_DB[249]['app_qrzlog_logid']) + 1}"
        )

    def test_short_page_stops_paging(self):
        """QRZ-L2-066: fewer records than MAX means the book is exhausted."""
        with _live_client() as (client, fake):
            client.fetch(start_date="2020-01-01", end_date="2020-01-10", limit=250)

        assert len(fake.requests) == 1

    def test_download_pages_through_everything(self):
        """QRZ-L2-067: download_adif collects every page, values intact."""
        with _live_client() as (client, fake):
            result = client.download_adif()

        assert result["record_count"] == _TOTAL
        assert len(fake.requests) == 3
        # Values are re-emitted verbatim with literal markers, not QRZ's escaped form.
        assert "<COMMENT:7>R&R net<EOR>" in result["adif"]
        assert "&lt;" not in result["adif"]


# ---------------------------------------------------------------------------
# QRZ-L2-068..072: newest_first
# ---------------------------------------------------------------------------


class TestNewestFirst:
    def test_returns_newest_records_newest_first(self):
        """QRZ-L2-068: newest_first=True returns the latest N, latest first."""
        with _live_client() as (client, _fake):
            qsos = client.fetch(limit=3, newest_first=True)

        assert [q["logid"] for q in qsos] == [
            r["app_qrzlog_logid"] for r in reversed(_DB[-3:])
        ]
        assert qsos[0]["qso_date"] > qsos[1]["qso_date"] > qsos[2]["qso_date"]

    def test_default_keeps_oldest_and_stays_small(self):
        """QRZ-L2-069: default behaviour is unchanged: oldest N, one request."""
        with _live_client() as (client, fake):
            qsos = client.fetch(limit=3)

        assert [q["logid"] for q in qsos] == [r["app_qrzlog_logid"] for r in _DB[:3]]
        assert len(fake.requests) == 1
        assert fake.requests[0]["OPTION"] == "MAX:3,AFTERLOGID:0"

    def test_newest_first_respects_date_filter(self):
        """QRZ-L2-070: newest_first composes with a date range."""
        with _live_client() as (client, _fake):
            qsos = client.fetch(
                start_date="2020-01-01", end_date="2020-01-31",
                limit=2, newest_first=True,
            )

        assert [q["qso_date"] for q in qsos] == ["20200131", "20200130"]

    def test_non_positive_limit_makes_no_request(self):
        """QRZ-L2-071: limit <= 0 returns nothing and never touches QRZ."""
        with _live_client() as (client, fake):
            assert client.fetch(limit=0) == []
            assert client.fetch(limit=-1, newest_first=True) == []

        assert fake.requests == []

    def test_tool_exposes_newest_first_in_mock_mode(self):
        """QRZ-L2-072: qrz_logbook_fetch accepts newest_first (mock data)."""
        from qrz_mcp.server import qrz_logbook_fetch

        with mock.patch.dict(os.environ, {"QRZ_MCP_MOCK": "1"}):
            result = qrz_logbook_fetch(persona="test", limit=1, newest_first=True)

        assert result["total"] == 1
        # Of the three mock QSOs, PU2ORH (20260827) is the most recent.
        assert result["records"][0]["call"] == "PU2ORH"


class TestDateValidation:
    """User dates go into QRZ's comma-separated OPTION string: only real dates pass."""

    @pytest.mark.parametrize("given,iso", [("20260501", "2026-05-01"), ("2026-05-01", "2026-05-01"), (" 20261231 ", "2026-12-31")])
    def test_accepted(self, given, iso):
        from qrz_mcp.logbook_client import _iso_date
        assert _iso_date(given) == iso

    @pytest.mark.parametrize("bad", ["2026-01-01,MAX:1", "2026-01-01+2027-01-01", "yesterday", "2026-13-01", "20260230", "", "2026/05/01"])
    def test_refused(self, bad):
        from qrz_mcp.logbook_client import _iso_date
        with pytest.raises(ValueError, match="Invalid date"):
            _iso_date(bad)
