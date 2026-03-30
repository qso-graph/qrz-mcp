<!-- mcp-name: io.github.qso-graph/qrz-mcp -->
# qrz-mcp

MCP server for [QRZ.com](https://www.qrz.com/) — callsign lookups, DXCC entity resolution, and logbook queries through any MCP-compatible AI assistant.

Part of the [qso-graph](https://qso-graph.io/) project. Uses [qso-graph-auth](https://pypi.org/project/qso-graph-auth/) for credential management.

## Install

```bash
pip install qrz-mcp
```

## Tools

| Tool | API | Auth | Description |
|------|-----|------|-------------|
| `qrz_lookup` | XML | Session key | Callsign lookup (name, grid, DXCC, license class, QSL info, image) |
| `qrz_dxcc` | XML | Session key | DXCC entity resolution from callsign or entity code |
| `qrz_logbook_status` | Logbook | API key | Logbook stats (QSO count, DXCC total, date range) |
| `qrz_logbook_fetch` | Logbook | API key | Query QSOs with filters and transparent pagination |
| `qrz_download` | Logbook | API key | Download full logbook as ADIF |

## Quick Start

### 1. Set up credentials

qrz-mcp uses qso-graph-auth personas for credential management. QRZ has **two separate auth mechanisms** — set up whichever you need:

```bash
# Install qso-graph-auth if you haven't
pip install qso-graph-auth

# Create a persona
qso-auth persona create ki7mt --callsign KI7MT

# Enable QRZ provider
qso-auth persona provider ki7mt qrz --username KI7MT

# Set password (for XML API: qrz_lookup, qrz_dxcc)
qso-auth persona secret ki7mt qrz

# Set API key (for Logbook API: qrz_logbook_status, qrz_logbook_fetch)
qso-auth creds set --persona ki7mt --provider qrz --api-key YOUR_API_KEY
```

**XML API** (callsign lookup, DXCC) requires a QRZ XML Subscription ($35.95/yr). Free tier returns name and address only.

**Logbook API** requires an API key from QRZ Settings > API.

### 2. Configure your MCP client

qrz-mcp works with any MCP-compatible client. Add the server config and restart — tools appear automatically.

#### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows):

```json
{
  "mcpServers": {
    "qrz": {
      "command": "qrz-mcp"
    }
  }
}
```

#### Claude Code

Add to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "qrz": {
      "command": "qrz-mcp"
    }
  }
}
```

#### ChatGPT Desktop

ChatGPT supports MCP via the [OpenAI Agents SDK](https://developers.openai.com/api/docs/mcp/). Add under Settings > Apps & Connectors, or configure in your agent definition:

```json
{
  "mcpServers": {
    "qrz": {
      "command": "qrz-mcp"
    }
  }
}
```

#### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "qrz": {
      "command": "qrz-mcp"
    }
  }
}
```

#### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "qrz": {
      "command": "qrz-mcp"
    }
  }
}
```

#### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project):

```json
{
  "mcpServers": {
    "qrz": {
      "command": "qrz-mcp"
    }
  }
}
```

### 3. Ask questions

> "Look up W1AW on QRZ — what's their grid and license class?"

> "What DXCC entity is VP8PJ?"

> "How many QSOs do I have in my QRZ logbook?"

> "Show me all 20m FT8 QSOs from my QRZ logbook this year"

## Rate Limiting

QRZ enforces undocumented rate limits that can trigger **24-hour IP bans**. qrz-mcp protects you:

- 500ms minimum delay between all API calls
- Token bucket: 35 requests/minute
- 60s freeze on authentication failures
- 3600s freeze on connection refused (IP ban detection)
- In-memory response cache (5 min for callsigns, 1 hour for DXCC)

## Testing Without Credentials

Set the mock environment variable to test all 4 tools without QRZ credentials:

```bash
QRZ_MCP_MOCK=1 qrz-mcp
```

## MCP Inspector

```bash
qrz-mcp --transport streamable-http --port 8002
```

Then open the MCP Inspector at `http://localhost:8002`.

## Development

```bash
git clone https://github.com/qso-graph/qrz-mcp.git
cd qrz-mcp
pip install -e .
```

## QRZ Subscription Tiers

| Feature | Free | XML Data ($35.95/yr) |
|---------|------|---------------------|
| Callsign lookups/day | 100 | Unlimited |
| Fields returned | Name + address only | All (grid, lat/lon, DXCC, class, QSL, image) |
| Logbook API | No | Yes |
| DXCC lookup | No | Yes |

## License

GPL-3.0-or-later
