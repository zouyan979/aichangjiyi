"""Weather service using wttr.in (free, no API key needed)."""
from __future__ import annotations
import json
import time
import logging
import httpx
from ..database import get_db

log = logging.getLogger("memoria.weather")

WTTR_URL = "https://wttr.in"
CACHE_TTL = 1800  # 30 minutes
REQUEST_TIMEOUT = 10


class WeatherService:
    def __init__(self):
        self._cache: tuple[float, str] | None = None

    def get_city(self) -> str:
        """Get configured city. Empty string = auto-detect from IP."""
        db = get_db()
        row = db.execute("SELECT value FROM app_settings WHERE key='weather_city'").fetchone()
        return row["value"] if row else ""

    def set_city(self, city: str):
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('weather_city', ?)",
            (city,)
        )
        db.commit()
        self._cache = None  # invalidate cache

    def get_weather(self) -> str | None:
        """Get current weather as a short string. Returns None on failure."""
        if self._cache:
            ts, weather = self._cache
            if time.time() - ts < CACHE_TTL:
                return weather
            self._cache = None

        city = self.get_city()

        # Try format=3 first (simplest, most reliable)
        for attempt_url in self._build_urls(city):
            try:
                resp = httpx.get(
                    attempt_url,
                    params={"format": "3", "lang": "zh"},
                    timeout=REQUEST_TIMEOUT,
                    headers={"User-Agent": "curl/8.0"},
                    follow_redirects=True
                )
                resp.raise_for_status()
                text = resp.text.strip()
                if text and "Unknown" not in text and len(text) > 3:
                    self._cache = (time.time(), text)
                    log.info("Weather: %s", text)
                    return text
            except Exception as e:
                log.warning("Weather fetch failed (%s): %s", attempt_url, e)
                continue

        return None

    def _build_urls(self, city: str) -> list[str]:
        """Build fallback URLs for weather fetching."""
        urls = []
        if city:
            urls.append(f"{WTTR_URL}/{city}")
        # Always include auto-detect as fallback
        if not city or city not in ("",):
            urls.append(WTTR_URL)
        return urls

    def get_weather_summary(self) -> str | None:
        """Get a concise weather summary for proactive messages."""
        weather = self.get_weather()
        if not weather:
            return None

        # Extract key info: temperature, conditions
        # wttr.in format: "城市: ☀️ +25°C 65% ↑10km/h 日出日落"
        parts = weather.split(":")
        if len(parts) >= 2:
            return parts[1].strip()
        return weather


weather_service = WeatherService()
