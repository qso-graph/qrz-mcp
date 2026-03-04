"""qrz-mcp: MCP server for QRZ.com callsign and logbook data."""

from __future__ import annotations

try:
    from importlib.metadata import version

    __version__ = version("qrz-mcp")
except Exception:
    __version__ = "0.0.0-dev"
