# Changelog

All notable changes to `qrz-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `qrz_logbook_status` silently returned `0`/`""` for `dxcc`, `start_date` and
  `end_date` ([#5](https://github.com/qso-graph/qrz-mcp/issues/5)). QRZ's
  STATUS response uses `DXCC_COUNT`, `START_DATE` and `END_DATE`, but the
  client read `DXCC`, `START` and `END`. Missing keys defaulted to `0`/`""`,
  so the failure was invisible while `count`, `confirmed` and `callsign`
  continued to work. Each field is now resolved from a list of accepted
  spellings, so both the current and legacy names parse.

### Changed
- `_MOCK_STATUS_BODY` is transcribed from a live STATUS response (real key
  names, ISO dates, `BOOKID`/`BOOK_NAME`/`CALLSIGN`). The previous fixture
  encoded the names the code expected rather than the ones QRZ sends, which is
  why the suite passed while every live call returned zeros.
- Added regression tests QRZ-L2-038 and QRZ-L2-049 through QRZ-L2-054.

### Known limitation
- `us_states` still reports `0`. No US-states key appears in any observed
  STATUS response, and with only a non-US logbook available it is impossible
  to tell whether QRZ renames the field or omits it when the value is zero.
  Both plausible spellings (`US_STATES_COUNT`, `US_STATES`) are accepted so
  the value populates automatically if present. Confirming this needs a
  logbook with US states worked.

## [0.3.3] — 2026-05-16

### Added
- New tool `get_version_info` — returns `{service_name, service_version, spec_version}`
  for fleet identity attestation. Tracks [IONIS-AI/ionis-devel#49](https://github.com/IONIS-AI/ionis-devel/issues/49).
- `__spec_version__` pinned to `qrz-com-v1`.
- L2 unit tests QRZ-L2-044 through QRZ-L2-048.
- `.github/workflows/ci.yml` — PR-gating CI (py3.10-3.13 matrix).

### Changed
- `__init__.py` modernized to fleet pattern (`Final` types).

## [0.3.2] — Previous release
- See git history for changes prior to the changelog being introduced.
