"""qrz-mcp: MCP server for QRZ.com callsign and logbook data."""

from __future__ import annotations

import os
import sys
from typing import Any

from fastmcp import FastMCP

from adif_mcp.credentials import get_creds

from . import __version__
from .logbook_client import LogbookClient
from .rate_limiter import RateLimiter
from .xml_client import XmlClient


def _is_mock() -> bool:
    return os.getenv("QRZ_MCP_MOCK") == "1"

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
            creds = get_creds(persona, "qrz")
            if creds is None or not creds.username or not creds.password:
                raise ValueError(
                    f"No QRZ XML credentials for persona '{persona}'. "
                    "Set up with: adif-mcp creds set --persona <name> --provider qrz "
                    "--username <call> --password <pass>"
                )
            client.configure(creds.username, creds.password, callsign=creds.username)
        _xml_clients[persona] = client
    return _xml_clients[persona]


def _logbook(persona: str) -> LogbookClient:
    """Get or create a LogbookClient for a persona."""
    if persona not in _logbook_clients:
        client = LogbookClient(_rate_limiter)
        if not _is_mock():
            creds = get_creds(persona, "qrz")
            if creds is None or not creds.api_key:
                raise ValueError(
                    f"No QRZ Logbook API key for persona '{persona}'. "
                    "Set up with: adif-mcp creds set --persona <name> --provider qrz "
                    "--api-key <key>"
                )
            client.configure(creds.api_key, callsign=creds.username)
        _logbook_clients[persona] = client
    return _logbook_clients[persona]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
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
        return {"error": str(e)}


@mcp.tool()
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
        return {"error": str(e)}


@mcp.tool()
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
        return {"error": str(e)}


@mcp.tool()
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
        return {"error": str(e)}


@mcp.tool()
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
) -> dict[str, Any]:
    """Query QSOs from a QRZ logbook with optional filters.

    Transparently paginates to collect up to `limit` records.

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
        )
        return {"total": len(qsos), "records": [dict(q) for q in qsos]}
    except Exception as e:
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the qrz-mcp server."""
    transport = "stdio"
    port = 8002
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--transport" and i < len(sys.argv) - 1:
            transport = sys.argv[i + 1]
        if arg == "--port" and i < len(sys.argv) - 1:
            port = int(sys.argv[i + 1])

    if transport == "streamable-http":
        mcp.run(transport=transport, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
