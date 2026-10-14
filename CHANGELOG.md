# Changelog

All notable changes to `qrz-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] — 2026-10-14

**This release exists to carry a security-gate fix to `main`, where the gate runs.**

The fix merged to `develop` on 2026-10-12 at 19:55Z — thirteen minutes *after* 0.4.0 went
`develop` → `main` at 19:42Z. So `main` kept the broken check, this repo reported the issue closed,
and every gate run since has used the holed version. Nothing shipped wrong and no user was exposed:
the package contains only the namespace identifier, never a plaintext URL. But the check that was
supposed to prove that was not the fixed one.

A gate fix is landed when it is on `main`. If carrying it there needs a release, that release is
part of the fix — now written into `.claude/rules/security.md`.


- **Fixed: the HTTPS-only check could be passed by a plaintext connection to qrz.com.** Both the
  release gate in `publish.yml` and `test_all_urls_https` exempted the *host* `xmldata.qrz.com`,
  because QRZ's XML namespace identifier is the string `http://xmldata.qrz.com` and must match
  their schema byte for byte. But `http://xmldata.qrz.com/xml/current/` starts with the excluded
  string, so a real plaintext connection to the same host passed both checks. **Measured, not
  theorised:** with exactly that line in `xml_client.py`, the test passed and the gate did not
  fail. Both now exempt the namespace *identifier* — the host followed by a quote or whitespace,
  which an identifier is and a URL path is not.
- Nothing shipped wrong: the package contains only the namespace line, so no user was exposed. This
  was a hole in detection, not an exposure, and it does not reach the wheel — no release is needed
  for it.
- Checked across the fleet while fixing it: **no other qso-graph MCP exempts a host** in either
  check. All twenty-one others exempt loopback addresses only, so this was unique to qrz-mcp.

## [0.4.0] — 2026-10-12

**Upgrading:** a tool that fails now returns `isError: true` instead of a successful result whose
payload contained an `error` key. Anything reading `result["error"]` should read the error flag.
No decision changed.

**Worth knowing:** this server holds two secrets for one persona — a password for the XML API and
an API key for the logbook — and #10's rule that the logbook is never sent the password is now
asserted by a test rather than resting on one keyword argument.


- **`E501` is adopted** (#32, qso-graph-devel#70). It was deliberately ignored while the rules that
  find defects went in first; this is the pass of its own that deferral was waiting for. It reported
  **five lines, none of them a defect**, and all five reflowed with no name shortened — **no
  exemption was needed**, so this repo carries no `noqa` at all. Formatting and config only; the
  suite is unchanged.

- **`certifi` is carried, and both fetch paths verify against it** (#31, qso-graph-devel#73). They
  used `urllib` with no context, so they trusted whichever root store the running Python was built
  against. On macOS that is `/etc/ssl/cert.pem`, a deliberately *reduced* OpenSSL file — 128 roots
  against the system keychain's 158, and current rather than stale. **qrz.com verifies fine against
  it today**, so this was latent rather than an outage.
- **Both paths carry a secret, for different reasons.** The XML API puts the operator's password in
  the query string; the logbook puts the API key in a POST body — and a body is no safer than the
  connection under it. So `ssl.CERT_NONE` would hand over whichever secret that call was carrying,
  which is why verification is never disabled rather than merely why it should not be.
- The context lives in its own module, `_tls.py`, because the calls are in two files. The "every
  `urlopen` verifies" check scans the whole package: a check reading one file would have missed the
  other, which is how a server ends up verifying the password path and not the API-key path.
- **The logbook test double now asserts the context it is handed.** Adding `context=` broke seven
  paging tests, because `_FakeQrz.urlopen` did not accept the argument — the right kind of break. A
  stub that quietly accepts anything is how a missing context goes unnoticed in every test that
  uses it, so it now checks `CERT_REQUIRED` and `check_hostname` rather than merely tolerating the
  keyword. Removing the context from `logbook_client.py` is then caught twice over, by the static
  guard and by those seven tests.
- **`tests/test_release_gate.py`** asserts the gate suite imports nothing but the standard library
  and pytest. solar-mcp's 0.3.0 publish failed on exactly that, from the same change.

- **Tool execution errors are flagged `isError`** (#33). Every tool returned `{"error": "..."}` on
  failure, which reaches a client as a *successful* call whose payload happens to contain the word
  "error". They now raise `ToolError`, which `fastmcp` reports as `isError: true` with the message
  intact. **No decision changed — only how it is reported.**
- **Every tool declares all four annotation hints** (#33). All six are read-only, non-destructive
  and idempotent — nothing is uploaded to QRZ and no credential is written, only read.
  `openWorldHint` is true for the five that reach qrz.com and false for `get_version_info`.
- **#10 — the logbook's API key and the XML API's password stay separate — is now asserted.** That
  decision lives in one keyword argument, `prefer="api_key"`, and nothing tested it. Two checks
  now record which provider entry each path asks for, so sending the logbook the stored password
  fails a test rather than passing review. Deliberately *not* advertised in the annotations: the
  specification requires clients to treat those as untrusted, so a security-relevant claim does not
  belong there.
- **Neither secret can reach the client through an error**, asserted with a distinct sentinel for
  each. Both clients already caught their exceptions and raised fixed messages — true before #33 —
  but that message used to sit in a payload and is now the failure text a client reads.
- **`tests/test_mcp_conformance.py`** asserts all of the above.

## [0.3.9] — 2026-10-11

- **ruff and mypy run in CI** (qso-graph-devel#66), as a job the `ci-all-green` gate requires.
  Settings follow `adif-mcp`, the reference for every qso-graph Python repo, rather than a style of
  this repo's own. They run once rather than per Python version: both read the source, and neither
  answer changes with the interpreter.
- Each cache read is annotated with the record type its caller expects, two `type: ignore`
  comments that covered nothing were removed, and an unused `pytest` import left the tests.
- `E501` is deferred rather than adopted (qso-graph-devel#70): what it reports in these repos are
  widths, not defects, and some lines are long because they name a publisher's field exactly.
- `mcp.run` is given the literal fastmcp asks for rather than a `str` that happens to hold the
  right word.
- **`fastmcp` is bounded: `>=4.0,<5`** (qso-graph-devel#60). It was `>=3.0` with no upper bound, and
  these servers are run with `uvx`, which resolves fresh — so a `fastmcp` 5.0 would have reached
  every user automatically, before anything here had been run against it. The floor rises to 4.0
  because that is what is actually tested: every lock in the fleet held a 4.x, and nothing in CI
  has ever exercised 3.x. A claim of 3.x support that no test backs is not support.
- `fastmcp` is locked at 4.1.0, the current release, so CI runs against what a new install gets.
- **The published contact is `maintainers@qso-graph.io`** (qso-graph-devel#69). The `authors` field
  carried a personal address, and that field is what PyPI shows on the package page. Everything in
  qso-graph is open source and open to contribution, so the contact is the project's.

## [0.3.8] — 2026-10-07

- LICENSE: the full GPL-3.0 text. The file held only its opening and a link, so GitHub detected no licence.

## [0.3.7] — 2026-10-06

- PyPI: the Documentation link goes to this package's own page, https://qso-graph.io/servers/qrz/ (qso-graph/.github#15).
- CI: the release flow (qso-graph/.github TEMPLATES.md). Work lands on `develop`; a release is a
  PR from `develop` into `main`, and merging it publishes to PyPI and the MCP Registry, verifies both
  and tags the release. CI runs on `develop` too, and PRs into `main` must come from `develop` or a
  `security/` branch.

## [0.3.6] — 2026-10-04

Documentation only; no code changes. Released so the PyPI page shows the corrected README.

### Changed
- README: `creds set` prompts for the password and API key instead of taking them on the command line, where they land in shell history (#16).
- README: uvx only, no pip (#15).

## [0.3.5] — 2026-09-28

Thanks to three contributors: **[@MicaelJarniac](https://github.com/MicaelJarniac)** (#2, #3, #5 and
PRs #4, #6, #7) and **[@ssamjung2](https://github.com/ssamjung2)** (#9, #10), who found these on
live logbooks and sent the fixes.

### Security

- **The logbook API key could be sent as the password** (#10, reported and fixed by @ssamjung2).
  With both a password and an API key stored, the password was sent to QRZ as the logbook
  key. Fixed in qso-graph-auth 0.1.2, now required, and qrz-mcp asks for the API key
  explicitly.
- **Dates are validated strictly.** User-supplied dates go into QRZ's comma-separated `OPTION`
  string, and anything that wasn't `YYYYMMDD` passed through unchecked, so a date could add
  options of its own. Only real `YYYY-MM-DD` or `YYYYMMDD` dates are accepted now.

### Fixed

- **Date filters, paging and newest QSOs** (#9, by @ssamjung2): dates use QRZ's documented
  `BETWEEN:start+end` (every dated fetch used to fail with "unknown"); paging uses
  `MAX:250,AFTERLOGID:n` inside `OPTION`, so large logbooks page correctly; opt-in
  `newest_first` on fetch.

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

## [0.3.4] — 2026-09-28

### Added (CI hygiene)

- **MCP Registry sync** — `publish.yml` publishes to the [Official MCP Registry](https://registry.modelcontextprotocol.io)
  after each PyPI publish, using GitHub OIDC for auth. Triggered on
  `v*` tag push; no manual steps. The Registry job waits until PyPI
  serves the version, and retries. Pattern documented in
  [qso-graph/.github/TEMPLATES.md](https://github.com/qso-graph/.github/blob/main/TEMPLATES.md).
- **Registry version badge** in README — PyPI and Registry versions
  are visible side-by-side so any drift between publishing surfaces
  is immediately apparent.
- **Release gates** — the tag must match `pyproject.toml`, and a
  `verify` job fails the release unless PyPI and the MCP Registry
  both serve the new version.

### Fixed

- The Official MCP Registry listed qrz-mcp at 0.2.0. This release brings it current.

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
