"""TTS service using MiMo TTS API."""
from __future__ import annotations
import base64
import json
import logging
import httpx
from ..database import get_db

log = logging.getLogger("memoria.tts")

MAX_TEXT_LENGTH = 500


class TTSService:
    def __init__(self):
        pass

    def _get_config(self) -> dict:
        db = get_db()
        row = db.execute("SELECT value FROM app_settings WHERE key='tts_config'").fetchone()
        if row:
            return json.loads(row["value"])
        return {"enabled": False, "voice": "冰糖"}

    def update_config(self, config: dict):
        db = get_db()
        current = self._get_config()
        current.update(config)
        db.execute(
            "INSERT OR REPLACE INTO app_settings (key, value) VALUES ('tts_config', ?)",
            (json.dumps(current, ensure_ascii=False),)
        )
        db.commit()

    def _get_active_api_config(self) -> dict | None:
        db = get_db()
        row = db.execute("SELECT base_url, api_key FROM api_configs WHERE is_active=1").fetchone()
        if row:
            return {"base_url": row["base_url"], "api_key": row["api_key"]}
        return None

    def _derive_tts_url(self, base_url: str) -> str | None:
        """Derive TTS endpoint from the chat base_url."""
        if "/v1/chat/completions" in base_url:
            return base_url
        # Extract domain: https://token-plan-cn.xiaomimimo.com/anthropic/v1/messages
        # -> https://token-plan-cn.xiaomimimo.com/v1/chat/completions
        if "xiaomimimo.com" in base_url:
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            return f"{parsed.scheme}://{parsed.netloc}/v1/chat/completions"
        if "/v1/messages" in base_url:
            return base_url.replace("/v1/messages", "/v1/chat/completions")
        return None

    def is_available(self) -> bool:
        cfg = self._get_active_api_config()
        if not cfg:
            return False
        return self._derive_tts_url(cfg["base_url"]) is not None

    def _truncate_text(self, text: str) -> str:
        if len(text) <= MAX_TEXT_LENGTH:
            return text
        truncated = text[:MAX_TEXT_LENGTH]
        for sep in ["。", "！", "？", "!", "?", ".", "\n"]:
            idx = truncated.rfind(sep)
            if idx > MAX_TEXT_LENGTH // 2:
                return truncated[:idx + 1]
        return truncated

    async def synthesize(self, text: str, voice: str = "冰糖") -> bytes:
        api_cfg = self._get_active_api_config()
        if not api_cfg:
            raise ValueError("未配置 API")

        tts_url = self._derive_tts_url(api_cfg["base_url"])
        if not tts_url:
            raise ValueError("当前 API 不支持语音合成")

        truncated = self._truncate_text(text)
        body = {
            "model": "mimo-v2.5-tts",
            "messages": [{"role": "assistant", "content": truncated}],
            "audio": {"format": "wav", "voice": voice}
        }
        headers = {
            "Content-Type": "application/json",
            "api-key": api_cfg["api_key"]
        }

        log.info("TTS request: url=%s, voice=%s, text_len=%d", tts_url, voice, len(truncated))

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), verify=False) as client:
            resp = await client.post(tts_url, headers=headers, json=body)

            if resp.status_code != 200:
                error_text = resp.text[:300]
                log.error("TTS API error %d: %s", resp.status_code, error_text)
                raise ValueError(f"语音合成失败 {resp.status_code}: {error_text}")

            data = resp.json()
            try:
                audio_b64 = data["choices"][0]["message"]["audio"]["data"]
            except (KeyError, IndexError, TypeError) as e:
                log.error("TTS response parse error: %s, keys=%s", e, list(data.keys()))
                raise ValueError("语音合成返回格式异常")

            audio_bytes = base64.b64decode(audio_b64)
            log.info("TTS success: %d bytes audio", len(audio_bytes))
            return audio_bytes


tts_service = TTSService()
