from __future__ import annotations
import asyncio
import httpx
import json
import logging
from typing import AsyncGenerator

log = logging.getLogger("memoria.llm")


class LLMService:
    def __init__(self):
        self._active_config = None
        self._vision_model = ""

    def set_config(self, config: dict):
        self._active_config = config
        self._vision_model = config.get("vision_model", "")

    def is_ready(self) -> bool:
        return self._active_config is not None

    def _get_config_for_messages(self, messages: list[dict]) -> dict:
        """Return config with vision_model swapped in if the CURRENT user message has images."""
        cfg = dict(self._active_config)
        if not self._vision_model:
            return cfg
        # Only check the last user message (current), not historical messages
        for m in reversed(messages):
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    if any(item.get("type") == "image_url" for item in content):
                        cfg["model"] = self._vision_model
                        log.info("Vision model activated: %s", self._vision_model)
                        return cfg
                break
        return cfg

    def _is_anthropic(self, url: str) -> bool:
        """Detect if the API uses Anthropic format."""
        return "anthropic" in url.lower() or "/messages" in url

    @staticmethod
    def _is_mimo(url: str) -> bool:
        """Detect MiMo API (uses api-key header)."""
        return "xiaomimimo.com" in url.lower()

    @staticmethod
    def _mimo_openai_url(url: str) -> str:
        """Convert MiMo Anthropic URL to OpenAI format."""
        # /anthropic/v1/messages -> /v1/chat/completions
        if "/anthropic" in url:
            return url.replace("/anthropic/v1/messages", "/v1/chat/completions")
        return url

    def _build_headers(self, cfg: dict, anthropic: bool) -> dict:
        if self._is_mimo(cfg["base_url"]):
            return {
                "Content-Type": "application/json",
                "api-key": cfg["api_key"]
            }
        if anthropic:
            return {
                "Content-Type": "application/json",
                "x-api-key": cfg["api_key"],
                "anthropic-version": "2023-06-01"
            }
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}"
        }

    def _build_body(self, cfg: dict, messages: list[dict],
                    max_tokens: int, stream: bool, anthropic: bool) -> dict:
        if anthropic:
            # Anthropic format: system is a separate top-level field
            # MUST NOT include system messages in the messages array
            system_parts = []
            chat_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_parts.append(m["content"])
                elif m["role"] in ("user", "assistant"):
                    content = m["content"]
                    # Convert OpenAI vision format to Anthropic format
                    if isinstance(content, list):
                        content = self._convert_to_anthropic_content(content)
                    chat_messages.append({"role": m["role"], "content": content})
            # Anthropic requires messages to start with 'user' role
            if chat_messages and chat_messages[0]["role"] != "user":
                chat_messages.insert(0, {"role": "user", "content": "..."})
            body = {
                "model": cfg["model"],
                "messages": chat_messages,
                "max_tokens": max_tokens,
                "stream": stream
            }
            if system_parts:
                body["system"] = "\n".join(system_parts)
            if cfg.get("temperature"):
                body["temperature"] = cfg["temperature"]
            return body
        else:
            return {
                "model": cfg["model"],
                "messages": messages,
                "stream": stream,
                "max_tokens": max_tokens,
                "temperature": cfg.get("temperature", 0.8)
            }

    @staticmethod
    def _convert_to_anthropic_content(content: list) -> list:
        """Convert OpenAI vision format to Anthropic vision format."""
        result = []
        for item in content:
            if item.get("type") == "image_url":
                url = item.get("image_url", {}).get("url", "")
                if url.startswith("data:"):
                    # data:image/jpeg;base64,XXX
                    parts = url.split(",", 1)
                    if len(parts) == 2:
                        media_type = parts[0].split(":")[1].split(";")[0]
                        result.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": parts[1]
                            }
                        })
                else:
                    result.append({
                        "type": "image",
                        "source": {"type": "url", "url": url}
                    })
            elif item.get("type") == "text":
                result.append(item)
        return result

    def _parse_stream_chunk(self, line: str, anthropic: bool) -> str | None:
        """Parse a single SSE line and return content chunk or None."""
        if anthropic:
            # Anthropic SSE format: event: content_block_delta\ndata: {"delta":{"text":"..."}}
            if not line.startswith("data:"):
                return None
            data = line[5:].strip()
            if not data:
                return None
            try:
                obj = json.loads(data)
                if obj.get("type") == "content_block_delta":
                    return obj.get("delta", {}).get("text", "")
            except json.JSONDecodeError:
                pass
            return None
        else:
            # OpenAI SSE format: data: {"choices":[{"delta":{"content":"..."}}]}
            if not line.startswith("data:"):
                return None
            data = line[5:].strip()
            if data == "[DONE]":
                return "__DONE__"
            try:
                obj = json.loads(data)
                choices = obj.get("choices", [])
                if not choices:
                    return None
                return choices[0].get("delta", {}).get("content", "")
            except (json.JSONDecodeError, IndexError, KeyError):
                return None

    def _parse_response(self, data: dict, anthropic: bool) -> str:
        """Extract content from non-streaming response."""
        if anthropic:
            # Anthropic: {"content":[{"type":"text","text":"..."}]}
            content_blocks = data.get("content", [])
            texts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
            return "".join(texts)
        else:
            choices = data.get("choices", [])
            if not choices:
                return ""
            return choices[0].get("message", {}).get("content", "")

    async def stream(self, messages: list[dict], max_tokens: int = 2048) -> AsyncGenerator[str, None]:
        if not self._active_config:
            raise ValueError("API未配置")

        cfg = self._get_config_for_messages(messages)
        is_mimo = self._is_mimo(cfg["base_url"])
        # MiMo API: always use OpenAI format, convert URL if needed
        if is_mimo:
            url = self._mimo_openai_url(cfg["base_url"])
            anthropic = False
        else:
            url = cfg["base_url"]
            anthropic = self._is_anthropic(url)
        headers = self._build_headers(cfg, anthropic)
        body = self._build_body(cfg, messages, max_tokens, True, anthropic)

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), verify=False, trust_env=False) as client:
            async with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code != 200:
                    error_text = ""
                    async for chunk in resp.aiter_bytes():
                        error_text += chunk.decode("utf-8", errors="replace")
                    raise ValueError(f"API错误 {resp.status_code}: {error_text[:300]}")

                buffer = ""
                async for chunk in resp.aiter_bytes():
                    text = chunk.decode("utf-8", errors="replace")
                    buffer += text
                    lines = buffer.split("\n")
                    buffer = lines.pop() if lines else ""
                    for line in lines:
                        line = line.strip()
                        if not line:
                            continue
                        result = self._parse_stream_chunk(line, anthropic)
                        if result == "__DONE__":
                            return
                        if result:
                            yield result

    async def generate(self, messages: list[dict], max_tokens: int = 2048,
                       max_retries: int = 2) -> str:
        if not self._active_config:
            raise ValueError("API未配置")

        cfg = self._get_config_for_messages(messages)
        is_mimo = self._is_mimo(cfg["base_url"])
        if is_mimo:
            url = self._mimo_openai_url(cfg["base_url"])
            anthropic = False
        else:
            url = cfg["base_url"]
            anthropic = self._is_anthropic(url)
        headers = self._build_headers(cfg, anthropic)
        body = self._build_body(cfg, messages, max_tokens, False, anthropic)

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), verify=False, trust_env=False) as client:
                    resp = await client.post(url, headers=headers, json=body)
                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("retry-after", 2 * (attempt + 1)))
                        log.warning("Rate limited, retrying in %ds (attempt %d/%d)", retry_after, attempt + 1, max_retries + 1)
                        await asyncio.sleep(retry_after)
                        last_error = ValueError(f"API限流 {resp.status_code}")
                        continue
                    if resp.status_code != 200:
                        raise ValueError(f"API错误 {resp.status_code}: {resp.text[:300]}")
                    resp_text = resp.content.decode("utf-8", errors="replace")
                    data = json.loads(resp_text)
                    return self._parse_response(data, anthropic)
            except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError) as e:
                last_error = e
                if attempt < max_retries:
                    wait = 2 ** attempt
                    log.warning("LLM call failed (%s), retrying in %ds (attempt %d/%d)", e, wait, attempt + 1, max_retries + 1)
                    await asyncio.sleep(wait)
            except ValueError:
                raise

        raise last_error

    async def test_connection(self, config: dict) -> bool:
        url = config["base_url"]
        is_mimo = self._is_mimo(url)
        if is_mimo:
            url = self._mimo_openai_url(url)
            anthropic = False
        else:
            anthropic = self._is_anthropic(url)
        headers = self._build_headers(config, anthropic)
        body = self._build_body(config, [{"role": "user", "content": "ping"}], 5, False, anthropic)

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0), verify=False, trust_env=False) as client:
            try:
                resp = await client.post(url, headers=headers, json=body)
            except httpx.ConnectError:
                raise ValueError(f"无法连接到 {url}，请检查地址是否正确")
            except httpx.TimeoutException:
                raise ValueError(f"连接超时: {url}")

            if resp.status_code == 404:
                raise ValueError(
                    f"404 未找到。请检查API地址是否完整。\n"
                    f"当前地址: {url}\n"
                    f"OpenAI格式: .../v1/chat/completions\n"
                    f"Anthropic格式: .../v1/messages"
                )
            if resp.status_code == 401:
                raise ValueError("401 认证失败，请检查API Key是否正确")
            if resp.status_code == 403:
                raise ValueError("403 无权限，请检查API Key或账户余额")
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}: {resp.content.decode('utf-8', errors='replace')[:300]}")
            return True


llm_service = LLMService()
