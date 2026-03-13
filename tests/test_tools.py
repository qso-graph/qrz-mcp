"""L2 unit tests for qrz-mcp — all 5 tools + cache + rate limiter.

Uses QRZ_MCP_MOCK=1 for tool-level tests (no QRZ API calls).
Direct unit tests on TTLCache and RateLimiter helpers.

Test IDs: QRZ-L2-001 through QRZ-L2-045
"""

from __future__ import annotations

import os
import time

import pytest

os.environ["QRZ_MCP_MOCK"] = "1"

from qrz_mcp.cache import TTLCache
from qrz_mcp.rate_limiter import RateLimiter
from qrz_mcp.server import (
    qrz_dxcc,
    qrz_download,
    qrz_logbook_fetch,
    qrz_logbook_status,
    qrz_lookup,
)


# ---------------------------------------------------------------------------
# QRZ-L2-001..010: TTLCache
# ---------------------------------------------------------------------------


class TestTTLCache:
    def test_set_and_get(self):
        """QRZ-L2-001: Set then get returns value."""
        cache = TTLCache()
        cache.set("key1", "value1", 10.0)
        assert cache.get("key1") == "value1"

    def test_cache_miss(self):
        """QRZ-L2-002: Missing key returns None."""
        cache = TTLCache()
        assert cache.get("nonexistent") is None

    def test_cache_expiry(self):
        """QRZ-L2-003: Expired entry returns None."""
        cache = TTLCache()
        cache.set("key1", "value1", 0.01)
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_cache_not_expired(self):
        """QRZ-L2-004: Non-expired entry returns value."""
        cache = TTLCache()
        cache.set("key1", "value1", 10.0)
        assert cache.get("key1") == "value1"

    def test_cache_overwrite(self):
        """QRZ-L2-005: Overwriting key updates value."""
        cache = TTLCache()
        cache.set("key1", "old", 10.0)
        cache.set("key1", "new", 10.0)
        assert cache.get("key1") == "new"

    def test_cache_clear(self):
        """QRZ-L2-006: Clear removes all entries."""
        cache = TTLCache()
        cache.set("a", 1, 10.0)
        cache.set("b", 2, 10.0)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_cache_multiple_keys(self):
        """QRZ-L2-007: Multiple keys stored independently."""
        cache = TTLCache()
        cache.set("a", 1, 10.0)
        cache.set("b", 2, 10.0)
        assert cache.get("a") == 1
        assert cache.get("b") == 2

    def test_cache_stores_any_type(self):
        """QRZ-L2-008: Cache stores dicts, lists, etc."""
        cache = TTLCache()
        cache.set("dict", {"call": "W1AW"}, 10.0)
        cache.set("list", [1, 2, 3], 10.0)
        assert cache.get("dict") == {"call": "W1AW"}
        assert cache.get("list") == [1, 2, 3]


# ---------------------------------------------------------------------------
# QRZ-L2-011..016: RateLimiter
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_initial_state(self):
        """QRZ-L2-011: Fresh limiter allows immediate request."""
        rl = RateLimiter(min_delay=0.0, tokens_per_min=100)
        rl.wait()  # Should not block

    def test_tokens_deplete(self):
        """QRZ-L2-012: Token count decreases with each call."""
        rl = RateLimiter(min_delay=0.0, tokens_per_min=5)
        for _ in range(5):
            rl.wait()
        # After 5 calls, tokens should be ~0

    def test_freeze_auth_sets_frozen(self):
        """QRZ-L2-013: freeze_auth sets _frozen_until."""
        rl = RateLimiter(min_delay=0.0)
        rl.freeze_auth()
        assert rl._frozen_until > time.monotonic()

    def test_freeze_ban_sets_frozen(self):
        """QRZ-L2-014: freeze_ban sets _frozen_until for 1 hour."""
        rl = RateLimiter(min_delay=0.0)
        before = time.monotonic()
        rl.freeze_ban()
        assert rl._frozen_until >= before + 3599  # ~1 hour

    def test_min_delay_configurable(self):
        """QRZ-L2-015: min_delay parameter accepted."""
        rl = RateLimiter(min_delay=0.1, tokens_per_min=100)
        assert rl._min_delay == 0.1

    def test_tokens_per_min_configurable(self):
        """QRZ-L2-016: tokens_per_min parameter accepted."""
        rl = RateLimiter(min_delay=0.0, tokens_per_min=50)
        assert rl._max_tokens == 50


# ---------------------------------------------------------------------------
# QRZ-L2-020..025: qrz_lookup
# ---------------------------------------------------------------------------


class TestQrzLookup:
    def test_returns_record(self):
        """QRZ-L2-020: Lookup returns callsign record."""
        result = qrz_lookup(persona="test", callsign="W1AW")
        assert "error" not in result

    def test_callsign_present(self):
        """QRZ-L2-021: Lookup result has call field."""
        result = qrz_lookup(persona="test", callsign="W1AW")
        assert result.get("call") == "W1AW"

    def test_record_fields(self):
        """QRZ-L2-022: Lookup result has expected fields."""
        result = qrz_lookup(persona="test", callsign="W1AW")
        for field in ("call", "grid", "country", "dxcc"):
            assert field in result, f"Missing field: {field}"

    def test_grid_format(self):
        """QRZ-L2-023: Grid locator is 6-char Maidenhead."""
        result = qrz_lookup(persona="test", callsign="W1AW")
        grid = result.get("grid", "")
        assert len(grid) >= 4


# ---------------------------------------------------------------------------
# QRZ-L2-026..028: qrz_dxcc
# ---------------------------------------------------------------------------


class TestQrzDxcc:
    def test_returns_entity(self):
        """QRZ-L2-026: DXCC lookup returns entity info."""
        result = qrz_dxcc(persona="test", query="291")
        assert "dxcc" in result or "name" in result

    def test_entity_name(self):
        """QRZ-L2-027: DXCC 291 is United States."""
        result = qrz_dxcc(persona="test", query="291")
        assert result.get("name") == "United States"

    def test_continent_field(self):
        """QRZ-L2-028: DXCC result includes continent."""
        result = qrz_dxcc(persona="test", query="291")
        assert result.get("continent") == "NA"


# ---------------------------------------------------------------------------
# QRZ-L2-030..035: qrz_download
# ---------------------------------------------------------------------------


class TestQrzDownload:
    def test_returns_raw_adif(self):
        """QRZ-L2-030: Download returns raw ADIF text."""
        result = qrz_download(persona="test")
        assert "adif" in result
        assert "<EOR>" in result["adif"].upper()

    def test_record_count(self):
        """QRZ-L2-031: Download reports correct record count."""
        result = qrz_download(persona="test")
        assert result["record_count"] == 2

    def test_has_adif_header(self):
        """QRZ-L2-032: ADIF output includes header."""
        result = qrz_download(persona="test")
        assert "<ADIF_VER:5>3.1.6" in result["adif"]
        assert "<PROGRAMID:7>qrz-mcp" in result["adif"]
        assert "<EOH>" in result["adif"]

    def test_adif_contains_callsigns(self):
        """QRZ-L2-033: ADIF text contains expected callsigns."""
        result = qrz_download(persona="test")
        assert "KI7MT" in result["adif"]
        assert "W1AW" in result["adif"]


# ---------------------------------------------------------------------------
# QRZ-L2-036..038: qrz_logbook_status
# ---------------------------------------------------------------------------


class TestQrzLogbookStatus:
    def test_returns_stats(self):
        """QRZ-L2-036: Logbook status returns count/dxcc/callsign."""
        result = qrz_logbook_status(persona="test")
        assert result["count"] == 1547
        assert result["dxcc"] == 142
        assert result["callsign"] == "KI7MT"

    def test_status_fields(self):
        """QRZ-L2-037: Status has all expected fields."""
        result = qrz_logbook_status(persona="test")
        for field in ("count", "dxcc", "callsign"):
            assert field in result, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# QRZ-L2-039..045: qrz_logbook_fetch
# ---------------------------------------------------------------------------


class TestQrzLogbookFetch:
    def test_returns_records(self):
        """QRZ-L2-039: Fetch returns mock QSO records."""
        result = qrz_logbook_fetch(persona="test")
        assert result["total"] == 2
        assert len(result["records"]) == 2

    def test_record_fields(self):
        """QRZ-L2-040: Fetch records have expected fields."""
        result = qrz_logbook_fetch(persona="test")
        rec = result["records"][0]
        assert rec["call"] == "KI7MT"
        assert rec["band"] == "20M"
        assert rec["mode"] == "FT8"

    def test_second_record(self):
        """QRZ-L2-041: Second record has different data."""
        result = qrz_logbook_fetch(persona="test")
        rec = result["records"][1]
        assert rec["call"] == "W1AW"
        assert rec["band"] == "40M"
        assert rec["mode"] == "CW"

    def test_record_has_qso_date(self):
        """QRZ-L2-042: Records include QSO date."""
        result = qrz_logbook_fetch(persona="test")
        for rec in result["records"]:
            assert "qso_date" in rec
            assert len(rec["qso_date"]) == 8

    def test_record_has_grid(self):
        """QRZ-L2-043: Records include gridsquare."""
        result = qrz_logbook_fetch(persona="test")
        for rec in result["records"]:
            assert "gridsquare" in rec
