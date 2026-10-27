"""QRZ's request limits: spacing, a freeze, and what a 429 does.

Three mechanisms, asserted separately because they were once conflated: the
token bucket and minimum gap space requests out, a freeze stops them after QRZ
refuses us, and a 429 is QRZ stating its limit at runtime. See
qso-graph-devel/planning/MCP-SECURITY-FRAMEWORK.md.
"""

from __future__ import annotations

import time
import urllib.error
from email.message import Message

import pytest

from qrz_mcp import logbook_client, xml_client
from qrz_mcp.rate_limiter import RateLimited, RateLimiter, retry_after


def _http_error(url: str, code: int, **headers: str) -> urllib.error.HTTPError:
    m = Message()
    for k, v in headers.items():
        m[k.replace("_", "-")] = v
    return urllib.error.HTTPError(url, code, "nope", m, None)


def _raises(exc):
    def f(*a: object, **k: object):
        raise exc
    return f


# --- spacing is still slept, because it is short --------------------------


def test_the_minimum_gap_is_enforced() -> None:
    rl = RateLimiter(min_delay=0.05, tokens_per_min=600)
    rl.wait()
    start = time.monotonic()
    rl.wait()
    assert time.monotonic() - start >= 0.04


def test_a_token_deficit_is_waited_out_not_refused() -> None:
    """A bucket deficit at 35 a minute is under two seconds. That is spacing,
    and sleeping it is the point -- only a freeze refuses."""
    rl = RateLimiter(min_delay=0.0, tokens_per_min=600)
    for _ in range(3):
        rl.wait()  # must not raise


# --- a freeze refuses, and does not sleep --------------------------------


def test_a_freeze_refuses_instead_of_sleeping() -> None:
    """It used to sleep. An hour-long ban freeze inside a synchronous tool call
    is a hang, and the user got silence instead of a sentence."""
    rl = RateLimiter()
    rl.freeze_ban()  # one hour
    start = time.monotonic()
    with pytest.raises(RateLimited) as e:
        rl.wait()
    assert time.monotonic() - start < 1.0, "wait() slept through the freeze"
    assert e.value.retry_after > 3000
    assert str(e.value.retry_after) in str(e.value)


def test_an_auth_freeze_refuses_too() -> None:
    rl = RateLimiter()
    rl.freeze_auth()
    with pytest.raises(RateLimited) as e:
        rl.wait()
    assert 1 <= e.value.retry_after <= 60


def test_a_freeze_is_never_shortened() -> None:
    """A ban freeze outlasting an auth freeze must not be cut short by it."""
    rl = RateLimiter()
    rl.freeze_ban()
    rl.freeze_auth()
    with pytest.raises(RateLimited) as e:
        rl.wait()
    assert e.value.retry_after > 3000


def test_requests_resume_once_the_freeze_passes() -> None:
    rl = RateLimiter(min_delay=0.0)
    rl.freeze(0.05)
    with pytest.raises(RateLimited):
        rl.wait()
    time.sleep(0.08)
    rl.wait()  # must not raise


# --- Retry-After parsing -------------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, 60.0),       # absent: wait the floor, do not guess
        ("", 60.0),
        ("0", 60.0),        # "now" still gets a floor
        ("5", 60.0),        # below the floor is raised to it
        ("300", 300.0),     # honoured as stated
        ("99999", 3600.0),  # above the ceiling is capped
        ("Wed, 21 Oct 2026 07:28:00 GMT", 60.0),  # date form unparsed
        ("garbage", 60.0),
    ],
)
def test_retry_after_is_honoured_within_bounds(
    header: str | None, expected: float
) -> None:
    assert retry_after(header) == expected


def test_note_429_freezes_for_the_interval() -> None:
    rl = RateLimiter()
    assert rl.note_429("300") == 300.0
    with pytest.raises(RateLimited) as e:
        rl.wait()
    assert e.value.retry_after <= 300


# --- the wiring ----------------------------------------------------------
#
# HTTPError is an OSError, and both clients had an "except OSError" that
# rewrote every failure as a network or credentials problem. So a 429 was not
# merely unhandled: its status was discarded before anything could read it.

_XML = "https://xmldata.qrz.com/xml/current/"
_LOG = "https://logbook.qrz.com/api"


def test_a_429_on_the_xml_api_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    rl = RateLimiter(min_delay=0.0)
    cl = xml_client.XmlClient(rl)
    monkeypatch.setattr(
        xml_client.urllib.request,
        "urlopen",
        _raises(_http_error(_XML, 429, Retry_After="120")),
    )
    with pytest.raises(RateLimited) as e:
        cl._get({"s": "x"})
    assert e.value.retry_after == 120

    # And the next call does not go out at all.
    sent: list[str] = []
    monkeypatch.setattr(
        xml_client.urllib.request, "urlopen", lambda *a, **k: sent.append("x")
    )
    with pytest.raises(RateLimited):
        cl._get({"s": "x"})
    assert sent == [], "a request was sent while QRZ had told us to stop"


def test_a_429_on_the_xml_api_is_not_a_credentials_problem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rl = RateLimiter(min_delay=0.0)
    cl = xml_client.XmlClient(rl)
    monkeypatch.setattr(
        xml_client.urllib.request,
        "urlopen",
        _raises(_http_error(_XML, 429, Retry_After="90")),
    )
    with pytest.raises(RuntimeError) as e:
        cl._get({"s": "x"})
    assert "credentials" not in str(e.value).lower()
    assert "rate limiting" in str(e.value)


def test_a_500_on_the_xml_api_leaks_neither_password_nor_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The login URL carries the password in its query string."""
    rl = RateLimiter(min_delay=0.0)
    cl = xml_client.XmlClient(rl)
    monkeypatch.setattr(
        xml_client.urllib.request, "urlopen", _raises(_http_error(_XML, 500))
    )
    with pytest.raises(RuntimeError) as e:
        cl._get({"username": "KI7MT", "password": "SECRET"})
    assert "SECRET" not in str(e.value)
    assert "qrz.com" not in str(e.value)
    assert not isinstance(e.value, RateLimited)


def test_a_429_on_the_logbook_api_is_honoured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rl = RateLimiter(min_delay=0.0)
    cl = logbook_client.LogbookClient(rl)
    cl._api_key = "k"
    monkeypatch.setattr(
        logbook_client.urllib.request,
        "urlopen",
        _raises(_http_error(_LOG, 429, Retry_After="120")),
    )
    with pytest.raises(RateLimited) as e:
        cl._post({"ACTION": "STATUS"})
    assert e.value.retry_after == 120


def test_the_two_clients_share_one_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """server.py gives both the same RateLimiter, and must: the limit is QRZ's
    view of this client, not of one of its two APIs."""
    rl = RateLimiter(min_delay=0.0)
    xml = xml_client.XmlClient(rl)
    log = logbook_client.LogbookClient(rl)
    log._api_key = "k"
    monkeypatch.setattr(
        logbook_client.urllib.request,
        "urlopen",
        _raises(_http_error(_LOG, 429, Retry_After="300")),
    )
    with pytest.raises(RateLimited):
        log._post({"ACTION": "STATUS"})

    monkeypatch.setattr(
        xml_client.urllib.request, "urlopen", lambda *a, **k: pytest.fail("sent")
    )
    with pytest.raises(RateLimited):
        xml._get({"s": "x"})


def test_a_bare_503_is_an_outage_not_a_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rl = RateLimiter(min_delay=0.0)
    cl = xml_client.XmlClient(rl)
    monkeypatch.setattr(
        xml_client.urllib.request, "urlopen", _raises(_http_error(_XML, 503))
    )
    with pytest.raises(RuntimeError) as e:
        cl._get({"s": "x"})
    assert not isinstance(e.value, RateLimited)
    rl.wait()  # not frozen: an outage is not a limit
