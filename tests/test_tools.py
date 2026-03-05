"""Tool tests for qrz-mcp — all 5 tools in mock mode."""

from __future__ import annotations

import os

os.environ["QRZ_MCP_MOCK"] = "1"

from qrz_mcp.server import (
    qrz_dxcc,
    qrz_download,
    qrz_logbook_fetch,
    qrz_logbook_status,
    qrz_lookup,
)


# ---------------------------------------------------------------------------
# qrz_lookup
# ---------------------------------------------------------------------------


class TestQrzLookup:
    def test_returns_record(self):
        result = qrz_lookup(persona="test", callsign="KI7MT")
        assert "call" in result or "error" not in result

    def test_callsign_present(self):
        result = qrz_lookup(persona="test", callsign="W1AW")
        assert result.get("call") == "W1AW" or "error" not in result


# ---------------------------------------------------------------------------
# qrz_dxcc
# ---------------------------------------------------------------------------


class TestQrzDxcc:
    def test_returns_entity(self):
        result = qrz_dxcc(persona="test", query="291")
        assert "dxcc" in result or "name" in result


# ---------------------------------------------------------------------------
# qrz_download
# ---------------------------------------------------------------------------


class TestQrzDownload:
    def test_returns_raw_adif(self):
        result = qrz_download(persona="test")
        assert "adif" in result
        assert "<EOR>" in result["adif"].upper()

    def test_record_count(self):
        result = qrz_download(persona="test")
        assert result["record_count"] == 2

    def test_has_adif_header(self):
        result = qrz_download(persona="test")
        assert "<ADIF_VER:5>3.1.6" in result["adif"]
        assert "<PROGRAMID:7>qrz-mcp" in result["adif"]
        assert "<EOH>" in result["adif"]

    def test_adif_contains_callsigns(self):
        result = qrz_download(persona="test")
        assert "KI7MT" in result["adif"]
        assert "W1AW" in result["adif"]


# ---------------------------------------------------------------------------
# qrz_logbook_status
# ---------------------------------------------------------------------------


class TestQrzLogbookStatus:
    def test_returns_stats(self):
        result = qrz_logbook_status(persona="test")
        assert result["count"] == 1547
        assert result["dxcc"] == 142
        assert result["callsign"] == "KI7MT"


# ---------------------------------------------------------------------------
# qrz_logbook_fetch
# ---------------------------------------------------------------------------


class TestQrzLogbookFetch:
    def test_returns_records(self):
        result = qrz_logbook_fetch(persona="test")
        assert result["total"] == 2
        assert len(result["records"]) == 2

    def test_record_fields(self):
        result = qrz_logbook_fetch(persona="test")
        rec = result["records"][0]
        assert rec["call"] == "KI7MT"
        assert rec["band"] == "20M"
        assert rec["mode"] == "FT8"
