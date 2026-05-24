"""Web search service using Tavily API."""
from __future__ import annotations
import json
import time
import logging
import httpx
from ..database import get_db

log = logging.getLogger("memoria.search")

TAVILY_ENDPOINT = "https://api.tavily.com/search"
CACHE_TTL = 1800  # 30 minutes
REQUEST_TIMEOUT = 15


class SearchService:
    def __init__(self):
        self._cache: dict[str, tuple[float, list]] = {}

    def get_config(self) -> dict:
        db = get_db()
        row = db.execute("SELECT value FROM app_settings WHERE key='search_config'").fetchone()
        if row:
            return json.loads(row["value"])
        return {"enabled": False, "tavily_api_key": ""}

    def update_config(self, config: dict):
        current = self.get_config()
        current.update(config)
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('search_config', ?)",
            (json.dumps(current, ensure_ascii=False),)
        )
        db.commit()

    def _get_api_key(self) -> str | None:
        config = self.get_config()
        key = config.get("tavily_api_key", "")
        if not key:
            return None
        # Auto-enable if key is present but toggle is off
        if not config.get("enabled"):
            config["enabled"] = True
            self.update_config({"enabled": True})
        return key

    def _check_cache(self, query: str) -> list | None:
        cached = self._cache.get(query)
        if cached:
            ts, results = cached
            if time.time() - ts < CACHE_TTL:
                return results
            del self._cache[query]
        return None

    def _set_cache(self, query: str, results: list):
        self._cache[query] = (time.time(), results)
        # Evict old entries
        if len(self._cache) > 100:
            cutoff = time.time() - CACHE_TTL
            self._cache = {k: v for k, v in self._cache.items() if v[0] > cutoff}

    async def search(self, query: str) -> list[dict] | None:
        """Search using Tavily API. Returns list of {title, url, content} or None."""
        api_key = self._get_api_key()
        if not api_key:
            return None

        cached = self._check_cache(query)
        if cached is not None:
            log.info("Search cache hit: %s", query[:50])
            return cached

        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, verify=False) as client:
                resp = await client.post(TAVILY_ENDPOINT, json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": 3,
                    "include_answer": True,
                    "search_depth": "basic"
                })
                resp.raise_for_status()
                data = resp.json()

            results = []
            answer = data.get("answer", "")
            if answer:
                results.append({"title": "AI 摘要", "url": "", "content": answer})

            for item in data.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", "")[:500]
                })

            if results:
                self._set_cache(query, results)
            log.info("Search '%s' returned %d results", query[:50], len(results))
            return results if results else None

        except httpx.HTTPStatusError as e:
            log.error("Search API error: %s %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            log.error("Search error: %s", e)
            return None

    @staticmethod
    def should_search(query: str) -> bool:
        """Quick heuristic: does this query likely need real-time info?"""
        keywords = [
            "今天", "今日", "昨天", "明天", "最新", "最近", "现在", "目前",
            "天气", "新闻", "热搜", "价格", "股价", "汇率",
            "搜索", "查一下", "查查", "帮我查", "帮我搜",
            "什么时候", "几点", "多少", "怎么样了", "发生什么",
            "2024", "2025", "2026", "2027"
        ]
        return any(kw in query for kw in keywords)


search_service = SearchService()
