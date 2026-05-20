from __future__ import annotations
import httpx
import json
from typing import AsyncGenerator


class LLMService:
    def __init__(self):
        self._active_config = None

    def set_config(self, config: dict):
        self._active_config = config

    def is_ready(self) -> bool:
        return self._active_config is not None

    def _is_anthropic(self, url: str) -> bool:
        """Detect if the API uses Anthropic format."""
        return "anthropic" in url.lower() or "/messages" in url

    def _build_headers(self, cfg: dict, anthropic: bool) -> dict:
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
                    chat_messages.append({"role": m["role"], "content": m["content"]})
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
                return obj.get("choices", [{}])[0].get("delta", {}).get("content", "")
            except json.JSONDecodeError:
                return None

    def _parse_response(self, data: dict, anthropic: bool) -> str:
        """Extract content from non-streaming response."""
        if anthropic:
            # Anthropic: {"content":[{"type":"text","text":"..."}]}
            content_blocks = data.get("content", [])
            texts = [b.get("text", "") for b in content_blocks if b.get("type") == "text"]
            return "".join(texts)
        else:
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def stream(self, messages: list[dict], max_tokens: int = 2048) -> AsyncGenerator[str, None]:
        if not self._active_config:
            raise ValueError("API未配置")

        cfg = self._active_config
        anthropic = self._is_anthropic(cfg["base_url"])
        headers = self._build_headers(cfg, anthropic)
        body = self._build_body(cfg, messages, max_tokens, True, anthropic)

        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), verify=False, trust_env=False) as client:
            async with client.stream("POST", cfg["base_url"], headers=headers, json=body) as resp:
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

    async def generate(self, messages: list[dict], max_tokens: int = 2048) -> str:
        if not self._active_config:
            raise ValueError("API未配置")

        cfg = self._active_config
        anthropic = self._is_anthropic(cfg["base_url"])
        headers = self._build_headers(cfg, anthropic)
        body = self._build_body(cfg, messages, max_tokens, False, anthropic)

        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), verify=False, trust_env=False) as client:
            resp = await client.post(cfg["base_url"], headers=headers, json=body)
            if resp.status_code != 200:
                raise ValueError(f"API错误 {resp.status_code}: {resp.text[:300]}")
            resp_text = resp.content.decode("utf-8", errors="replace")
            data = json.loads(resp_text)
            return self._parse_response(data, anthropic)

    async def test_connection(self, config: dict) -> bool:
        url = config["base_url"]
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
