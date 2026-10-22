"""
Web tools — search, fetch pages, and global news briefings.
"""

import asyncio
import html as html_lib
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

# RSS feeds polled in parallel for the world news brief.
# (source_label, url) — explicit labels, no fragile URL scraping.
SEED_FEEDS = [
    ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("CNBC", "https://www.cnbc.com/id/100727362/device/rss/rss.html"),
    ("NYTIMES", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
    ("ALJAZEERA", "https://www.aljazeera.com/xml/rss/all.xml"),
]

_HEADERS = {"User-Agent": "Friday-AI/1.0 (voice assistant)"}

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    return html_lib.unescape(_TAG_RE.sub("", text or "")).strip()


def _truncate(text: str, limit: int = 200) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


async def _fetch_feed(client: httpx.AsyncClient, source: str, url: str) -> list[dict]:
    """Fetch and parse one RSS feed. Any failure yields an empty list."""
    try:
        response = await client.get(url, headers=_HEADERS, timeout=5.0)
        if response.status_code != 200:
            return []

        root = ET.fromstring(response.content)
        items = []
        for item in root.findall(".//item")[:5]:
            title = item.findtext("title") or ""
            description = _strip_html(item.findtext("description") or "")
            link = item.findtext("link") or ""
            if title:
                items.append({
                    "source": source,
                    "title": title.strip(),
                    "summary": _truncate(description),
                    "link": link,
                })
        return items
    except Exception:
        return []


def _unwrap_ddg_link(href: str) -> str:
    """DuckDuckGo wraps results in /l/?uddg=<real-url>; unwrap it."""
    if "uddg=" in href:
        # Handles both "/l/?uddg=..." and "//duckduckgo.com/l/?uddg=..."
        # parse_qs already URL-decodes the value.
        target = parse_qs(urlparse(href).query).get("uddg", [""])[0]
        if target:
            return target
    return href


def register(mcp):

    @mcp.tool()
    async def get_world_news() -> str:
        """
        Fetches the latest global headlines from major news outlets simultaneously.
        Use this when the user asks 'What's going on in the world?' or for recent events.
        """
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
            tasks = [_fetch_feed(client, source, url) for source, url in SEED_FEEDS]
            results_of_lists = await asyncio.gather(*tasks)

        all_articles = [item for sublist in results_of_lists for item in sublist]

        if not all_articles:
            return "The global news grid is unresponsive, boss. Unable to pull headlines."

        report = ["### GLOBAL NEWS BRIEFING (LIVE)\n"]
        for entry in all_articles[:12]:
            report.append(f"**[{entry['source']}]** {entry['title']}")
            if entry["summary"]:
                report.append(entry["summary"])
            if entry["link"]:
                report.append(f"Link: {entry['link']}")
            report.append("")

        return "\n".join(report)

    @mcp.tool()
    async def search_web(query: str) -> str:
        """
        Search the web for a given query (DuckDuckGo, no API key needed).
        Returns the top results as titles, snippets, and URLs.
        Use for current events, facts, stocks, sports scores, or any lookup.
        """
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                response = await client.get(url, headers=_HEADERS)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return f"Web search is unavailable right now ({exc.__class__.__name__}), boss."

        # Each result block has a result__a link and a result__snippet paragraph.
        results = []
        blocks = response.text.split('class="result results_links')
        for block in blocks[1:6]:  # top 5
            link_match = re.search(
                r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S
            )
            snippet_match = re.search(
                r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div|span)>', block, re.S
            )
            if not link_match:
                continue
            title = _strip_html(link_match.group(2))
            snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
            link = _unwrap_ddg_link(html_lib.unescape(link_match.group(1)))
            if title and link:
                results.append({"title": title, "snippet": snippet, "link": link})

        if not results:
            return f"No results found for: {query}"

        lines = [f"### WEB SEARCH: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            if r["snippet"]:
                lines.append(f"   {r['snippet']}")
            lines.append(f"   URL: {r['link']}\n")
        return "\n".join(lines)

    @mcp.tool()
    async def fetch_url(url: str) -> str:
        """
        Fetch a URL and return its readable text content (HTML stripped).
        Use after search_web to read a specific page in depth.
        """
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=15,
                headers=_HEADERS,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            return f"I couldn't fetch that page ({exc.__class__.__name__}), boss."

        content_type = response.headers.get("content-type", "")
        if "html" in content_type or "xhtml" in content_type:
            # Drop script/style blocks before stripping tags
            body = re.sub(
                r"<(script|style|noscript)[^>]*>.*?</\1>",
                " ",
                response.text,
                flags=re.S | re.I,
            )
            body = re.sub(r"<(br|/p|/div|/li|/h[1-6])[^>]*>", "\n", body, flags=re.I)
            text = _strip_html(body)
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        else:
            text = response.text.strip()

        if not text:
            return "That page appears to be empty, boss."

        return _truncate(text, 4000)

    @mcp.tool()
    async def open_world_monitor() -> str:
        """
        Opens the World Monitor dashboard (worldmonitor.app) in the system's web browser.
        Use this when the user wants a visual overview of global events or a real-time map.
        """
        import webbrowser

        try:
            webbrowser.open("https://worldmonitor.app/")
            return "Displaying the World Monitor on your primary screen now, boss."
        except Exception as exc:
            return f"I'm unable to initialize the visual monitor: {exc}"
