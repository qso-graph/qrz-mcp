# Changelog

All notable changes to `qrz-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- `qrz_logbook_fetch` and `qrz_download` returned 0 records for non-empty
  logbooks ([#3](https://github.com/qso-graph/qrz-mcp/issues/3)). QRZ escapes
  the ADIF *markers* (`&lt;call:6&gt;`) but passes field *values* through
  verbatim, so the payload contains raw `&` characters. Splitting the response
  body on every `&` shredded it, leaving `ADIF` empty before parsing began.
  `ADIF` is now read as the whole remainder of the body, and values are
  consumed by their declared length instead of by delimiter scanning.
- `qrz_download` emitted QRZ's escaped markers into the `.adi` output, so the
  "raw ADIF" could not be imported by any logger. Records are now
  re-serialised with literal markers.
- QSO values are no longer URL-decoded or HTML-unescaped. Both corrupted real
  data: `unquote_plus` turned a comment of `A+B 50%20C` into `A B 50 C`, and
  unescaping mutated operator text that legitimately contained `&amp;`.
- `_parse_adif_records` no longer stalls or rewinds when a declared field
  length overruns the buffer, and a literal `<eor>` inside a comment no longer
  truncates the record or inflates `record_count`.
- Multibyte values are handled correctly: QRZ declares lengths in characters,
  not UTF-8 bytes.

### Changed
- Mock fixtures are transcribed from live QRZ responses (escaped markers,
  verbatim values, `ADIF` as the final key) and decode through the same
  `_parse_kv` path as live traffic, so this class of regression fails the
  suite instead of passing silently.
- Added regression tests QRZ-L2-034/035 and QRZ-L2-049 through QRZ-L2-058,
  covering bare `&`, `+`/`%`, entity-like text, embedded markers, multibyte
  lengths, and `.adi` round-tripping.

All behaviour above was confirmed against a live logbook by inserting QSOs
with adversarial comments, reading them back, and deleting them afterwards.

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
