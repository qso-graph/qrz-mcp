"""Conformance with the Model Context Protocol, revision 2026-07-28.

Nothing in this project's documents required this until 2026-10-11 — not
CLAUDE.md, not .claude/rules/security.md, not MCP-SECURITY-FRAMEWORK.md, not
qso-graph-spec. We documented how to *publish* an MCP server in detail and
never wrote down what makes one *valid*, which is how a missing ``isError`` and
missing annotations reached all 22 servers in the fleet unnoticed.

So these are asserted rather than trusted.

Follows ``adif-mcp``, ``solar-mcp``, ``pota-mcp``, ``wspr-mcp``, ``iota-mcp``,
``hamqth-mcp`` and ``lotw-mcp``. What is particular here is that this server
holds **two kinds** of secret for the same persona — a password for the XML API
and an API key for the logbook — and #10 settled that the logbook must never be
sent the password. Flagging errors makes the failure text client-visible, so
``TestNoFailurePathCarriesASecret`` drives a distinct sentinel for each and
asserts neither appears.

Test IDs: QRZ-C01 onward.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastmcp.exceptions import ToolError

os.environ["QRZ_MCP_MOCK"] = "1"

from qrz_mcp import server  # noqa: E402

ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

# Which secret each tool's path uses. Recorded because #10 is the thing a
# reader most needs to know about this server, and because a tool moving
# between these sets would be a security change, not a refactor.
USES_THE_PASSWORD = {"qrz_lookup", "qrz_dxcc"}
USES_THE_API_KEY = {"qrz_logbook_status", "qrz_logbook_fetch", "qrz_download"}
READS_QRZ = USES_THE_PASSWORD | USES_THE_API_KEY
ANSWERS_FROM_THE_PACKAGE = {"get_version_info"}


def _tools() -> dict[str, object]:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def _wire(tool: object) -> dict[str, object]:
    """The serialised annotations, which is what a client reads."""
    annotations = getattr(tool, "annotations", None)
    assert annotations is not None, "tool declares no annotations"
    return annotations.model_dump(by_alias=True, exclude_none=True)


def _call(name: str):
    """The underlying function of a registered tool."""
    tool = getattr(server, name)
    return getattr(tool, "fn", tool)


class TestToolAnnotations:
    def test_every_tool_declares_all_four_hints(self) -> None:
        """QRZ-C01: the defaults are pessimistic, so silence is the wrong answer."""
        for name, tool in _tools().items():
            wire = _wire(tool)
            for hint in ANNOTATION_HINTS:
                assert hint in wire, f"{name} omits {hint} on the wire; got {sorted(wire)}"

    def test_every_tool_reads_and_none_writes(self) -> None:
        """QRZ-C02: the three hints that describe effect.

        Nothing is uploaded to QRZ and no credential is written — the keyring
        is read only. ``qrz_download`` returns the ADIF as text; it saves no
        file.
        """
        for name, tool in _tools().items():
            wire = _wire(tool)
            assert wire["readOnlyHint"] is True, name
            assert wire["destructiveHint"] is False, name
            assert wire["idempotentHint"] is True, name

    def test_open_world_is_read_per_tool(self) -> None:
        """QRZ-C03: five reach qrz.com; one does not."""
        tools = _tools()
        assert set(tools) == READS_QRZ | ANSWERS_FROM_THE_PACKAGE
        for name in READS_QRZ:
            assert _wire(tools[name])["openWorldHint"] is True, name
        for name in ANSWERS_FROM_THE_PACKAGE:
            assert _wire(tools[name])["openWorldHint"] is False, name


class TestTheTwoCredentialsStaySeparate:
    """#10: the logbook authenticates with an API key and must never be sent
    the stored password.

    That decision lives in ``_logbook``'s ``prefer="api_key"``, which is one
    keyword argument. Nothing in the annotations says which tool uses which,
    and deliberately so — the specification requires clients to treat
    annotations as untrusted, so a security-relevant claim does not belong
    there. It belongs in code, asserted here.
    """

    def test_the_logbook_asks_for_the_api_key(self, monkeypatch) -> None:
        """QRZ-C05: and asks for it explicitly, not by provider default.

        ``PersonaManager.require`` picks a default per provider. Relying on
        that default would make this correct by coincidence; `prefer` states it.
        """
        asked: list[tuple[str, str | None]] = []

        def record(persona, provider, prefer=None):
            asked.append((provider, prefer))
            return ("KI7MT", "secret")

        monkeypatch.delenv("QRZ_MCP_MOCK", raising=False)
        monkeypatch.setattr(server, "_logbook_clients", {})
        monkeypatch.setattr(server, "_pm",
                            lambda: type("PM", (), {"require": staticmethod(record)})())
        server._logbook("p")
        assert asked == [("qrz_logbook", "api_key")], asked

    def test_the_xml_api_asks_for_the_password(self, monkeypatch) -> None:
        """QRZ-C06: the other half — a different provider entry entirely."""
        asked: list[tuple[str, str | None]] = []

        def record(persona, provider, prefer=None):
            asked.append((provider, prefer))
            return ("KI7MT", "secret")

        monkeypatch.delenv("QRZ_MCP_MOCK", raising=False)
        monkeypatch.setattr(server, "_xml_clients", {})
        monkeypatch.setattr(server, "_pm",
                            lambda: type("PM", (), {"require": staticmethod(record)})())
        server._xml("p")
        assert asked == [("qrz", None)], asked


class TestToolErrorsAreFlagged:
    """A tool execution error belongs in the result with ``isError: true``.

    The specification states the cost of getting this wrong: otherwise "the LLM
    would not be able to see that an error occurred and self-correct". These
    returned ``{"error": "..."}`` as a *successful* result until #33.
    """

    @pytest.fixture
    def broken(self, monkeypatch):
        """Both clients failing the way an unreachable QRZ does."""
        class Broken:
            def __getattr__(self, _name):
                def fail(*_args, **_kwargs):
                    raise RuntimeError("QRZ request failed — check network and credentials")
                return fail

        monkeypatch.setattr(server, "_xml", lambda persona: Broken())
        monkeypatch.setattr(server, "_logbook", lambda persona: Broken())

    UPSTREAM_CASES = [
        ("qrz_lookup", {"persona": "p", "callsign": "KI7MT"}),
        ("qrz_dxcc", {"persona": "p", "query": "291"}),
        ("qrz_logbook_status", {"persona": "p"}),
        ("qrz_logbook_fetch", {"persona": "p"}),
        ("qrz_download", {"persona": "p"}),
    ]

    def test_the_cases_cover_every_tool_that_reaches_qrz(self) -> None:
        """QRZ-C09: the parametrisation below cannot silently miss one."""
        assert {name for name, _ in self.UPSTREAM_CASES} == READS_QRZ

    @pytest.mark.parametrize("name,kwargs", UPSTREAM_CASES)
    def test_an_upstream_failure_is_flagged(self, broken, name, kwargs) -> None:
        """QRZ-C10: every tool that can fail, not a sample of them."""
        with pytest.raises(ToolError, match="QRZ request failed"):
            _call(name)(**kwargs)


class TestNoFailurePathCarriesASecret:
    """Two secrets, so two sentinels.

    The XML API puts the password in query parameters; the logbook sends its
    key in a POST body. Both clients already catch their exceptions and raise
    fixed messages — that was true before #33 — but the message used to sit in
    a payload and is now the failure text a client reads, so it is asserted
    rather than left to the comments that state it in prose.
    """

    PASSWORD = "p4ssw0rd-sentinel-not-real"
    API_KEY = "ap1key-sentinel-not-real"

    def test_the_xml_path_does_not_carry_the_password(self, monkeypatch) -> None:
        """QRZ-C20: urllib's own errors quote the URL, which is the hazard."""
        import urllib.request

        from qrz_mcp.xml_client import XmlClient

        client = XmlClient(server._rate_limiter)
        client.configure("KI7MT", self.PASSWORD, callsign="KI7MT")

        def explode(*_args, **_kwargs):
            raise OSError(
                f"failed opening https://xmldata.qrz.com/xml/?username=KI7MT&password={self.PASSWORD}"
            )

        monkeypatch.setattr(urllib.request, "urlopen", explode)
        monkeypatch.delenv("QRZ_MCP_MOCK", raising=False)
        monkeypatch.setattr(server, "_xml", lambda persona: client)
        with pytest.raises(ToolError) as caught:
            _call("qrz_lookup")(persona="p", callsign="KI7MT")
        assert self.PASSWORD not in str(caught.value), "the password reached the client"

    def test_the_logbook_path_does_not_carry_the_api_key(self, monkeypatch) -> None:
        """QRZ-C21: the key is in a POST body, which is better and still asserted."""
        import urllib.request

        from qrz_mcp.logbook_client import LogbookClient

        client = LogbookClient(server._rate_limiter)
        client.configure(self.API_KEY, callsign="KI7MT")

        def explode(*_args, **_kwargs):
            raise OSError(f"failed sending KEY={self.API_KEY}")

        monkeypatch.setattr(urllib.request, "urlopen", explode)
        monkeypatch.delenv("QRZ_MCP_MOCK", raising=False)
        monkeypatch.setattr(server, "_logbook", lambda persona: client)
        with pytest.raises(ToolError) as caught:
            _call("qrz_logbook_status")(persona="p")
        assert self.API_KEY not in str(caught.value), "the API key reached the client"


class TestAnEmptyAnswerIsNotAnError:
    """The distinction the specification draws."""

    def test_a_normal_lookup_is_a_successful_call(self) -> None:
        """QRZ-C30: the control, from mock mode."""
        answer = _call("qrz_lookup")(persona="p", callsign="KI7MT")
        assert isinstance(answer, dict)
        assert "error" not in answer


class TestVersionInfoShape:
    def test_it_matches_the_shape_the_fleet_returns(self) -> None:
        """QRZ-C40: the convention that drifted because nobody asserted it."""
        info = _call("get_version_info")()
        assert info["service_name"] == "qrz-mcp"
        assert info["service_version"]
        assert info["spec_version"]


class TestRegistration:
    def test_the_six_tools_a_client_sees(self) -> None:
        """QRZ-C50: calling a function directly is not proof a client can."""
        assert set(_tools()) == READS_QRZ | ANSWERS_FROM_THE_PACKAGE
