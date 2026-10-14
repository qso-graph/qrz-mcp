"""Security test suite — qso-graph MCP Security Framework v1.0.

These tests enforce the 10 non-negotiable security guarantees.
See: https://qso-graph.io/security/
"""

import re
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src"


def _py_files():
    """Yield all .py files under src/."""
    yield from SRC_DIR.rglob("*.py")


def test_no_print_credentials():
    """Guarantee #1: Credentials never in logs (print statements)."""
    forbidden = re.compile(
        r'print\s*\(.*(?:password|api_key|creds|secret|token).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Credential print in {py_file.name}: {matches}"


def test_no_logging_credentials():
    """Guarantee #1: Credentials never in logs (logging statements)."""
    forbidden = re.compile(
        r'logging\..*\(.*(?:password|api_key|creds|secret|token).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Credential logging in {py_file.name}: {matches}"


def test_no_subprocess():
    """Guarantee #5: No command injection surface."""
    forbidden = re.compile(r'subprocess\.|os\.system|shell\s*=\s*True')
    for py_file in _py_files():
        content = py_file.read_text()
        matches = forbidden.findall(content)
        assert not matches, f"Shell execution in {py_file.name}: {matches}"


def test_all_urls_https():
    """Guarantee #7: HTTPS only for external calls.

    The one legitimate `http://` here is QRZ's XML namespace identifier,
    `_NS = "http://xmldata.qrz.com"`, which must match their schema byte for
    byte or ElementTree lookups fail. It is nothing anyone connects to.

    It is exempted as an *identifier* and not as a host. Exempting the host —
    which this check did until #39 — also passes a real plaintext connection to
    the same host, because `http://xmldata.qrz.com/xml/current/` starts with the
    excluded string. Measured: with exactly that line in `xml_client.py`, this
    test passed. The exemption therefore requires the host to be followed by a
    quote or whitespace, which the namespace is and a URL path is not.
    """
    http_url = re.compile(
        r"""http://(?!localhost|127\.0\.0\.1|::1|xmldata\.qrz\.com(?=["'\s]))"""
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = http_url.findall(content)
        assert not matches, f"Non-HTTPS URL in {py_file.name}: {matches}"


def test_error_messages_safe():
    """Guarantee #3/#10: Credentials never in error messages."""
    dangerous = re.compile(
        r'raise\s+\w+\([^)]*(?:password|api_key|creds|secret).*\)',
        re.IGNORECASE,
    )
    for py_file in _py_files():
        content = py_file.read_text()
        matches = dangerous.findall(content)
        assert not matches, f"Credential in exception in {py_file.name}: {matches}"


def test_no_eval_exec():
    """Guarantee #5: No code injection surface."""
    for py_file in _py_files():
        content = py_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if re.search(r'\b(?:eval|exec)\s*\(', stripped):
                assert False, f"eval/exec in {py_file.name}:{i}: {stripped.strip()}"


def _code_only(path: Path) -> str:
    """The file with comments and string literals removed.

    Some checks must read what the code *does*, not what it says about itself.
    `_tls.context()` carries a docstring explaining that `ssl.CERT_NONE` would
    be the wrong fix, and a plain text search cannot tell that sentence apart
    from the thing it warns against.
    """
    import tokenize

    kept = []
    with path.open("rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            kept.append(token.string)
    return " ".join(kept)


def test_tls_verification_is_never_disabled():
    """Guarantee #8: no context here stops checking certificates.

    Both paths carry a secret: the XML API puts the operator's password in the
    query string, and the logbook puts the API key in a POST body — which is no
    safer than the connection under it. `ssl.CERT_NONE` would make a failing
    call "work" by accepting any certificate from anyone, handing over
    whichever secret that call was carrying.

    Read off the source, like every check in this file: the release gate runs it
    with the package *not installed*, so nothing here may import `qrz_mcp`.
    """
    forbidden = re.compile(r"CERT_NONE|check_hostname\s*=\s*False|_create_unverified")
    for py_file in _py_files():
        matches = forbidden.findall(_code_only(py_file))
        assert not matches, f"TLS verification weakened in {py_file.name}: {matches}"


def test_the_root_set_is_carried_not_borrowed():
    """Guarantee #8: the roots come from certifi, not the host's OpenSSL store."""
    assert "cafile=certifi.where()" in (SRC_DIR / "qrz_mcp" / "_tls.py").read_text()


def test_every_outbound_call_verifies():
    """Guarantee #8: a new fetch path cannot quietly skip the context.

    Scanned across the whole package, not one file: the calls here live in two
    modules, and a check that read only one would have missed the other — which
    is how a server ends up verifying the path carrying the password and not
    the one carrying the API key.

    Line by line rather than by matching balanced parentheses: a regex for the
    whole call ends at the first ")", which is the one inside "context()", so
    it would read a call that passes no context as though it did.
    """
    calls = [(py_file.name, i, line)
             for py_file in _py_files()
             for i, line in enumerate(py_file.read_text().splitlines(), 1)
             if "urllib.request.urlopen(" in line]
    assert len(calls) >= 2, f"expected both fetch paths; found {len(calls)}"
    for filename, number, line in calls:
        assert "context=_tls.context()" in line, (
            f"{filename}:{number} opens a connection without a verifying context: "
            f"{line.strip()}"
        )


def test_certifi_is_declared_not_merely_imported():
    """An import the wheel does not declare is an ImportError at startup.

    `certifi` is imported here to pin the TLS root set (qso-graph-devel#73). An
    import is not a dependency: what a user gets from `pip install` is what
    `[project] dependencies` says, and nothing else.

    Measured 2026-10-14: `certifi` is **not** transitive through this repo's
    other dependencies. Resolved on their own, `qso-graph-auth` + `fastmcp>=4.0,<5`
    pull 87 packages and `certifi` is not among them. So the declaration is
    load-bearing — remove it and `pip install qrz-mcp` gives a server that
    cannot start, which is a hard failure rather than a latent one.

    Read off the files, like every check here: the release gate runs this suite
    with the package *not installed*, so nothing may import the package.
    """
    pyproject = (SRC_DIR.parent / "pyproject.toml").read_text()
    deps = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert re.search(r'^\s*"certifi', deps, re.MULTILINE), (
        "the package imports certifi but [project] dependencies does not declare it"
    )
