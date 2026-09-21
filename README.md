# fetch-mcp-server

A minimal MCP (Model Context Protocol) server with exactly one tool:

**`fetch_url(url)`** — downloads a web page and returns its readable text
(scripts, nav, ads, and other boilerplate stripped out), so an LLM can read
it without choking on raw HTML.

Built and tested against `mcp` 1.30.0 (the SDK's v1 line — the code pins
`mcp<2` since v2 renamed the API this was written against).

## What's in here

- `server.py` — the whole server, one file
- `requirements.txt` — Python dependencies
- `Dockerfile` — for deploying to any container host

## Run it locally first

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

By default this starts over **stdio** — the transport Claude Desktop and
Claude Code use for local MCP servers. To try it there, point your
`claude_desktop_config.json` (or Claude Code's MCP config) at this
command, e.g.:

```json
{
  "mcpServers": {
    "fetch": {
      "command": "/full/path/to/venv/bin/python",
      "args": ["/full/path/to/server.py"]
    }
  }
}
```

## Run it as a remote server (what claude.ai's connectors need)

claude.ai's custom connectors call a server over the network, not over
stdio, so for that you need the **streamable-http** transport instead:

```bash
MCP_TRANSPORT=streamable-http PORT=8000 python server.py
```

This serves the MCP endpoint at `http://<host>:8000/mcp`.

## Deploy it somewhere with a public HTTPS URL

Any container host works. Using the included `Dockerfile`:

**Render** (free tier available)
1. Push this folder to a GitHub repo.
2. New → Web Service → connect the repo → it detects the `Dockerfile`.
3. Leave the port as `8000` (matches `EXPOSE 8000` and the default `$PORT`).
4. Deploy. Render gives you a `https://your-service.onrender.com` URL —
   your MCP endpoint is `https://your-service.onrender.com/mcp`.

**Railway / Fly.io** — same idea: push the repo, deploy from the
`Dockerfile`, note the public URL, append `/mcp`.

**Your own server** — build and run the image directly:
```bash
docker build -t fetch-mcp-server .
docker run -p 8000:8000 fetch-mcp-server
```
then put it behind HTTPS (a reverse proxy like Caddy or nginx with a
certificate, or a platform load balancer) since claude.ai requires HTTPS
for custom connectors.

## Add it to claude.ai

In your organization's connector settings, add a **custom connector**
pointing at `https://<your-deployed-host>/mcp`. Exact menu wording varies
by plan — support.claude.com has the current steps.

## A security note

This server has **no authentication** — anyone who knows its URL can make
it fetch any public page. That's usually fine for an internal tool used
by a small team, but:
- Don't put anything sensitive in the responses it returns.
- If you want it locked down, the natural next step is adding a bearer
  token check in `server.py` (reject requests missing a header you set)
  before you rely on it more broadly.
- It refuses non-HTML responses and caps how much it downloads and
  returns, but it does not block requests to internal/private network
  addresses (e.g. `http://localhost`, `http://169.254.169.254`,
  `http://10.x.x.x`) — worth adding that check too if this server will
  ever run somewhere with access to internal infrastructure.

## Testing a full round trip yourself

```bash
MCP_TRANSPORT=streamable-http PORT=8000 python server.py &
python3 - <<'EOF'
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    async with streamablehttp_client("http://127.0.0.1:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("fetch_url", {"url": "https://example.org"})
            print(result.content[0].text[:500])

asyncio.run(main())
EOF
```
