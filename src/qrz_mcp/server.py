"""qrz-mcp: MCP server for QRZ.com callsign and logbook data."""

from __future__ import annotations

import os
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from qso_graph_auth.identity import PersonaManager

from . import __spec_version__, __version__
from .logbook_client import LogbookClient
from .rate_limiter import RateLimiter
from .xml_client import XmlClient


def _is_mock() -> bool:
    return os.getenv("QRZ_MCP_MOCK") == "1"


def _pm() -> PersonaManager:
    return PersonaManager()


mcp = FastMCP(
    "qrz-mcp",
    version=__version__,
    instructions="MCP server for QRZ.com — callsign lookup, DXCC resolution, logbook queries",
)

# Shared rate limiter and clients (lazy init per persona)
_rate_limiter = RateLimiter()
_xml_clients: dict[str, XmlClient] = {}
_logbook_clients: dict[str, LogbookClient] = {}


def _xml(persona: str) -> XmlClient:
    """Get or create an XmlClient for a persona."""
    if persona not in _xml_clients:
        client = XmlClient(_rate_limiter)
        if not _is_mock():
            username, password = _pm().require(persona, "qrz")
            client.configure(username, password, callsign=username)
        _xml_clients[persona] = client
    return _xml_clients[persona]


def _logbook(persona: str) -> LogbookClient:
    """Get or create a LogbookClient for a persona."""
    if persona not in _logbook_clients:
        client = LogbookClient(_rate_limiter)
        if not _is_mock():
            # The logbook authenticates with an API key; never send a stored password (#10).
            username, api_key = _pm().require(persona, "qrz_logbook", prefer="api_key")
            client.configure(api_key, callsign=username)
        _logbook_clients[persona] = client
    return _logbook_clients[persona]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

# MCP 2026-07-28 tool annotations. The defaults are pessimistic — a tool that
# declares nothing is advertised as destructive, non-idempotent and open-world,
# and the specification tells a client to keep a human in the loop for an
# operation like that. Every tool here reads: nothing is uploaded to QRZ, and
# no credential is written — the keyring is read only.
#
# openWorldHint is true for the five that reach qrz.com and false for
# get_version_info. They are a client's UX hint and never a security control,
# so nothing here says which tools send the password and which send the API
# key — the distinction above (#10) is enforced in code, not advertised in
# metadata the specification requires clients to distrust.
_READS_QRZ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
_ANSWERS_FROM_THE_PACKAGE = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}




def _version_info_payload() -> dict[str, Any]:
    """Build the version info envelope. Pulled into a helper so tests can
    call it directly without going through the FastMCP wrapper."""
    return {
        "service_name": "qrz-mcp",
        "service_version": __version__,
        "spec_version": __spec_version__,
    }


@mcp.tool(annotations=_ANSWERS_FROM_THE_PACKAGE)
def get_version_info() -> dict[str, Any]:
    """Get qrz-mcp service version and upstream QRZ API version.

    Returns the running PyPI version of qrz-mcp and the QRZ.com XML +
    Logbook API contract in use. Use this to confirm fleet alignment
    across MCP deployments — agents can compare service_version and
    spec_version across servers to detect drift without going outside
    the MCP protocol.

    Returns:
        service_name, service_version (PyPI), and spec_version (QRZ API).
    """
    return _version_info_payload()


@mcp.tool(annotations=_READS_QRZ)
def qrz_lookup(persona: str, callsign: str) -> dict[str, Any]:
    """Look up a callsign on QRZ.com (name, grid, DXCC, license class, QSL info, image).

    Requires a QRZ XML Subscription ($35.95/yr) for full fields.

    Args:
        persona: Persona name configured in adif-mcp.
        callsign: Callsign to look up (e.g., W1AW).

    Returns:
        Structured record with station details. Fields depend on subscription tier.
    """
    try:
        return dict(_xml(persona).lookup(callsign))
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READS_QRZ)
def qrz_dxcc(persona: str, query: str) -> dict[str, Any]:
    """Resolve a DXCC entity from a callsign or numeric entity code.

    Args:
        persona: Persona name configured in adif-mcp.
        query: Callsign (e.g., VP8PJ) or DXCC code (e.g., 291).

    Returns:
        DXCC entity details (name, continent, CQ/ITU zones, coordinates).
    """
    try:
        return dict(_xml(persona).dxcc(query))
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READS_QRZ)
def qrz_logbook_status(persona: str) -> dict[str, Any]:
    """Get QRZ logbook statistics (QSO count, DXCC total, date range).

    Args:
        persona: Persona name configured in adif-mcp.

    Returns:
        Logbook stats including count, confirmed, DXCC entities, US states.
    """
    try:
        return dict(_logbook(persona).status())
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READS_QRZ)
def qrz_download(
    persona: str,
    band: str | None = None,
    mode: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Download your complete QRZ logbook as raw ADIF text.

    Returns the .adi file content — save to disk for import into your logger.
    Transparently paginates to collect all records. Rate-limited to avoid API bans.

    Args:
        persona: Persona name configured in adif-mcp.
        band: Filter by band (e.g., '20m').
        mode: Filter by mode (e.g., 'FT8').
        start_date: Date range start (YYYY-MM-DD).
        end_date: Date range end (YYYY-MM-DD).

    Returns:
        Raw ADIF text and record count.
    """
    try:
        return _logbook(persona).download_adif(
            band=band, mode=mode, start_date=start_date, end_date=end_date,
        )
    except Exception as e:
        raise ToolError(str(e)) from e


@mcp.tool(annotations=_READS_QRZ)
def qrz_logbook_fetch(
    persona: str,
    band: str | None = None,
    mode: str | None = None,
    callsign: str | None = None,
    dxcc: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    confirmed_only: bool = False,
    limit: int = 250,
    newest_first: bool = False,
) -> dict[str, Any]:
    """Query QSOs from a QRZ logbook with optional filters.

    Transparently paginates to collect up to `limit` records. QRZ returns
    records oldest first, so by default `limit` keeps the OLDEST matches. Set
    `newest_first` for the most recent QSOs instead (for example, "my last 10
    contacts" is limit=10 with newest_first=true).

    Args:
        persona: Persona name configured in adif-mcp.
        band: Filter by band (e.g., '20m').
        mode: Filter by mode (e.g., 'FT8').
        callsign: Filter by contacted station.
        dxcc: Filter by DXCC entity code.
        start_date: Date range start (YYYY-MM-DD).
        end_date: Date range end (YYYY-MM-DD).
        confirmed_only: Only return confirmed QSOs.
        limit: Maximum records to return (default 250).
        newest_first: Return the newest `limit` matches, newest first.

    Returns:
        Total count and list of QSO records.
    """
    try:
        qsos = _logbook(persona).fetch(
            band=band,
            mode=mode,
            callsign=callsign,
            dxcc=dxcc,
            start_date=start_date,
            end_date=end_date,
            confirmed_only=confirmed_only,
            limit=limit,
            newest_first=newest_first,
        )
        return {"total": len(qsos), "records": [dict(q) for q in qsos]}
    except Exception as e:
        raise ToolError(str(e)) from e


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


USAGE = """\
usage: qrz-mcp [--transport stdio|streamable-http] [--port N] [--version] [--help]

An MCP server: an AI app (Claude Desktop, Claude Code, ...) starts it and talks
to it over stdio. Run on its own it waits for that app; press Ctrl-C to stop.
Set up a client: https://github.com/qso-graph/qrz-mcp#quick-start

streamable-http binds 127.0.0.1 only: not another machine,
not a container.
"""


def main() -> None:
    """Run the qrz-mcp server."""
    # Without this the script ignored both flags and bound stdio, so
    # `--help` left a user watching a banner and a hung terminal.
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(USAGE, end="")
        return
    if "--version" in sys.argv[1:]:
        print(f"qrz-mcp {__version__}")
        return
    transport = "stdio"
    port = 8002
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--transport" and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    # Written out rather than passed through: fastmcp takes a literal, and a
    # str that happens to hold the right word is not the same thing.
    if transport == "streamable-http":
        # Where it bound, said out loud. FastMCP binds 127.0.0.1 and takes
        # no host option, so this is never reachable from another machine
        # or from outside a container. Silent before this line.
        print(
            f"qrz-mcp on http://127.0.0.1:{port}/mcp - loopback only",
            file=sys.stderr,
        )
        mcp.run(transport="streamable-http", port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
