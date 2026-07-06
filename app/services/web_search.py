"""Web search service — provider-agnostic, pluggable search backend.

Supports multiple search providers. All results are returned as plain text,
so the downstream LLM never needs to know which provider was used.

Backends:
  - bing:       Bing Web Search API (Azure). Recommended for production in China.
  - bing_html:  Scrape cn.bing.com public search. **No API key needed, works in China.**
  - duckduckgo: Free, no API key needed. Blocked/unreliable in China.
  - custom:     Any JSON search endpoint.

Usage:
    from app.services.web_search import WebSearch
    svc = WebSearch()
    results = await svc.search("合肥天气")
    context = svc.format_results(results)
"""
import logging
import re
from typing import List, Dict, Optional

import httpx
from app.core.settings import settings

logger = logging.getLogger(__name__)

# ── Result type ─────────────────────────────────────────────────────


class WebSearchResult(Dict):
    """Shape of a single web search result."""
    title: str
    url: str
    snippet: str


# ── Service ─────────────────────────────────────────────────────────


class WebSearch:
    """Provider-agnostic web search. Configured via settings.web_search_*."""

    def __init__(self):
        self.enabled = settings.web_search_enabled
        self.provider = settings.web_search_provider
        self.api_key = settings.web_search_api_key
        self.api_url = settings.web_search_api_url
        self.max_results = settings.web_search_max_results
        self.timeout = httpx.Timeout(15.0, connect=5.0)

    # ── Public API ──────────────────────────────────────────────────

    async def search(self, query: str) -> List[Dict]:
        """Search the web. Returns a list of {title, url, snippet} dicts.
        Returns empty list when disabled, on error, or no results.
        """
        if not self.enabled:
            logger.debug("[web_search] disabled, skipping")
            return []

        provider_map = {
            "bing": self._search_bing,
            "bing_html": self._search_bing_html,
            "duckduckgo": self._search_duckduckgo,
            "custom": self._search_custom,
        }
        handler = provider_map.get(self.provider)
        if not handler:
            logger.warning(f"[web_search] unknown provider '{self.provider}', skipping")
            return []

        try:
            logger.info(f"[web_search] searching via {self.provider}: {query[:80]}...")
            results = await handler(query)
            logger.info(f"[web_search] {self.provider} returned {len(results)} results")
            return results[:self.max_results]
        except Exception as e:
            logger.warning(f"[web_search] {self.provider} failed: {e}")
            return []

    def format_results(self, results: List[Dict]) -> str:
        """Format search results as plain text context for LLM injection."""
        if not results:
            return ""
        parts: List[str] = []
        for i, r in enumerate(results):
            title = r.get("title", "未知").strip()
            url = r.get("url", "")
            snippet = r.get("snippet", "").strip()
            parts.append(
                f"[网络来源{i + 1}: {title}]({url})\n"
                f"{snippet}"
            )
        return "\n\n---\n\n".join(parts)

    # ── Bing Web Search API (Azure) ────────────────────────────────

    async def _search_bing(self, query: str) -> List[Dict]:
        if not self.api_key:
            logger.warning("[web_search] Bing provider selected but WEB_SEARCH_API_KEY is empty")
            return []

        url = self.api_url or "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        params = {"q": query, "count": self.max_results, "mkt": "zh-CN"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet", ""),
            })
        return results

    # ── Bing Public HTML (cn.bing.com, no API key, works in China) ─

    async def _search_bing_html(self, query: str) -> List[Dict]:
        """Scrape cn.bing.com/search HTML — no API key needed, works in China.

        Parses search result cards from the HTML. Fragile to Bing layout changes,
        but requires zero configuration — just works if cn.bing.com is accessible.
        """
        url = "https://cn.bing.com/search"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        params = {"q": query, "cc": "cn", "mkt": "zh-CN"}

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            html = resp.text

        results = []

        # Bing result cards: <li class="b_algo"> ... <h2>...<a href="...">title</a>...</h2> ... <p>snippet</p>
        # Split on <li class="b_algo" to isolate each result
        blocks = re.split(r'<li\s+class="b_algo"[^>]*>', html, flags=re.IGNORECASE)

        for block in blocks[1:]:  # Skip everything before the first result
            # Skip non-result blocks (CSS/style links)
            if '<h2' not in block and '<h2>' not in block:
                continue

            title = ""
            url = ""
            snippet = ""

            # Extract URL and title from <a href="..." ...>title</a> inside <h2>
            m = re.search(
                r'<h2[^>]*>.*?<a .*?href="([^"]+)"[^>]*>(.*?)</a>',
                block, re.DOTALL | re.IGNORECASE
            )
            if m:
                url = m.group(1)
                # Strip HTML tags from title (e.g. <strong>bold</strong>)
                title = re.sub(r'<[^>]+>', '', m.group(2)).strip()

            # Extract snippet from <p> inside b_caption
            m = re.search(r'class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
                          block, re.DOTALL | re.IGNORECASE)
            if m:
                snippet = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                # Clean up HTML entities
                snippet = snippet.replace('&ensp;', ' ').replace('&#0183;', '·')

            if title or snippet:
                results.append({
                    "title": title[:200] or "搜索结果",
                    "url": url or "",
                    "snippet": snippet[:500],
                })

            if len(results) >= self.max_results:
                break

        if not results:
            logger.warning("[web_search] bing_html returned no results — page structure may have changed")
            # Fallback: try extracting any <h2><a> pattern
            results = self._extract_bing_fallback(html)

        return results

    def _extract_bing_fallback(self, html: str) -> List[Dict]:
        """Fallback parser: extract any <h2><a> result links from the page."""
        results = []
        for m in re.finditer(
            r'<h2[^>]*>.*?<a .*?href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            html, re.DOTALL | re.IGNORECASE
        ):
            url = m.group(1)
            title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
            if title and url and "bing.com" not in url and "microsoft.com" not in url:
                # Skip known non-result links
                if any(skip in url for skip in ['go.microsoft', 'bing.com']):
                    continue
                # Get surrounding snippet if available
                snippet = ""
                after_tag = html[m.end():m.end()+500]
                sm = re.search(r'<p[^>]*>(.*?)</p>', after_tag, re.DOTALL)
                if sm:
                    snippet = re.sub(r'<[^>]+>', '', sm.group(1)).strip()[:300]
                results.append({
                    "title": title[:200],
                    "url": url,
                    "snippet": snippet,
                })
                if len(results) >= self.max_results:
                    break
        return results

    # ── DuckDuckGo (free, no key) ──────────────────────────────────

    async def _search_duckduckgo(self, query: str) -> List[Dict]:
        """DuckDuckGo instant answer API — no API key needed."""
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []

        # Abstract (summary from infobox / Wikipedia)
        abstract = data.get("AbstractText", "")
        abstract_src = data.get("AbstractSource", "")
        if abstract:
            results.append({
                "title": f"摘要 ({abstract_src})" if abstract_src else "摘要",
                "url": data.get("AbstractURL", ""),
                "snippet": abstract[:500],
            })

        # Related topics (organic results)
        for topic in data.get("RelatedTopics", []):
            if "Text" in topic:
                results.append({
                    "title": topic.get("Text", "")[:100],
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                })
            elif "Topics" in topic:
                for sub in topic["Topics"][:3]:
                    results.append({
                        "title": sub.get("Text", "")[:100],
                        "url": sub.get("FirstURL", ""),
                        "snippet": sub.get("Text", ""),
                    })

        return results

    # ── Custom (any OpenAI-compatible search endpoint) ──────────────

    async def _search_custom(self, query: str) -> List[Dict]:
        """Call a custom search endpoint.
        Expects the endpoint to return a list of {title, url, snippet} objects.
        """
        url = self.api_url or "http://localhost:8080/search"
        params = {"q": query, "count": self.max_results}

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()

        # Support both list and {results: [...]} shapes
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("results", data.get("items", []))

        logger.warning(f"[web_search] custom endpoint returned unexpected type: {type(data)}")
        return []
