# Changelog

All notable changes to `qrz-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `qrz_logbook_fetch` and `qrz_download` returned 0 records for non-empty
  logbooks ([#3](https://github.com/qso-graph/qrz-mcp/issues/3)). QRZ
  HTML-escapes the ADIF payload, so its `&` characters (`&lt;`, `&gt;`,
  `&amp;`) were treated as `key=value` delimiters and shredded the payload
  before ADIF parsing ran. `_parse_kv` now splits only at an `&` that starts a
  new `KEY=` pair and unescapes each value individually, which also preserves a
  literal `&` inside QSO comments.
- `_parse_adif_records` no longer stalls or rewinds when a declared field
  length overruns the buffer.

### Changed
- Mock fixtures now use QRZ's real wire format (HTML-escaped ADIF in a raw
  `&`-delimited body) and are decoded through the same parsing path as live
  responses, so this class of regression fails the suite instead of passing
  silently.
- Added regression tests QRZ-L2-049 through QRZ-L2-054.

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
