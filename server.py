"""
fetch-mcp-server
-----------------
A minimal, single-purpose MCP server with one tool: fetch_url.
Given a URL, it downloads the page and returns clean, readable text
(HTML stripped of nav/script/style/ads), suitable for feeding into an
LLM prompt.

Run locally (stdio, for testing with Claude Desktop / Claude Code):
    python server.py

Run as a remote server (for claude.ai custom connectors):
    MCP_TRANSPORT=streamable-http PORT=8000 python server.py
"""

import os
import ipaddress
import socket
import httpx
from bs4 import BeautifulSoup
import html2text
from urllib.parse import urlparse
from mcp.server.fastmcp import FastMCP

MAX_BYTES = 3_000_000          # don't download more than ~3 MB
MAX_OUTPUT_CHARS = 60_000      # cap the returned text so it fits comfortably in a prompt
TIMEOUT_SECONDS = 15
USER_AGENT = "fetch-mcp-server/1.0 (+https://modelcontextprotocol.io)"

# Tags that never contain the content worth reading.
STRIP_TAGS = ["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe"]


def extract_readable_text(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Prefer a <main> or <article> region if the page has one — usually the actual content.
    main = soup.find("main") or soup.find("article") or soup.body or soup

    converter = html2text.HTML2Text()
    converter.ignore_images = True
    converter.ignore_emphasis = False
    converter.body_width = 0  # don't hard-wrap lines
    text = converter.handle(str(main))

    # Collapse excess blank lines.
    lines = [ln.rstrip() for ln in text.splitlines()]
    cleaned, blank_run = [], 0
    for ln in lines:
        if ln.strip() == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        cleaned.append(ln)
    return "\n".join(cleaned).strip()


def is_safe_public_host(url: str) -> tuple[bool, str]:
    """
    Resolve the URL's hostname and refuse anything pointing at a private,
    loopback, link-local, or otherwise internal address — prevents this
    public endpoint being used to probe internal infrastructure or cloud
    metadata services (e.g. 169.254.169.254).
    """
    hostname = urlparse(url).hostname
    if not hostname:
        return False, "no hostname in URL"
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False, f"could not resolve hostname '{hostname}'"

    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, f"'{hostname}' resolves to a non-public address ({ip_str})"
    return True, ""


mcp = FastMCP(
    name="fetch-mcp-server",
    instructions="Fetches a web page and returns its readable text content, with HTML/nav/scripts stripped.",
)


@mcp.tool()
async def fetch_url(url: str) -> str:
    """
    Fetch a web page and return its readable text content.

    Args:
        url: The full URL to fetch, including the scheme (e.g. "https://example.org/about").

    Returns:
        The page's readable text (HTML tags, scripts, nav, and ads stripped).
        Truncated if the page is very long. Returns a clear error message
        (not an exception) if the page can't be fetched or isn't text/HTML.
    """
    if not (url.startswith("http://") or url.startswith("https://")):
        return f"Error: '{url}' is not a valid http(s) URL."

    safe, reason = is_safe_public_host(url)
    if not safe:
        return f"Error: refusing to fetch this URL ({reason})."

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=TIMEOUT_SECONDS) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code >= 400:
                    return f"Error: request to {url} returned HTTP {resp.status_code}."

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type and "application/xhtml" not in content_type:
                    return (
                        f"Error: {url} returned content-type '{content_type}', "
                        "which this tool doesn't parse (it only reads HTML pages)."
                    )

                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total > MAX_BYTES:
                        break
                raw = b"".join(chunks)
    except httpx.TimeoutException:
        return f"Error: timed out fetching {url}."
    except httpx.RequestError as e:
        return f"Error: could not reach {url} ({e.__class__.__name__})."

    try:
        html = raw.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        html = raw.decode("utf-8", errors="replace")

    text = extract_readable_text(html, url)

    if not text:
        return f"Error: fetched {url} successfully but found no readable text content."

    if len(text) > MAX_OUTPUT_CHARS:
        text = text[:MAX_OUTPUT_CHARS] + "\n\n[truncated — page continues beyond this point]"

    return f"Content fetched from {url}:\n\n{text}"


if __name__ == "__main__":
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("PORT", "8000"))
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
