from __future__ import annotations
import re


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[一-鿿　-〿＀-￯]', text))
    remaining = len(text) - chinese_chars
    return int(chinese_chars * 1.5 + remaining * 0.25)


def estimate_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for m in messages:
        total += 4  # message overhead
        content = m.get("content", "")
        if isinstance(content, list):
            for item in content:
                if item.get("type") == "text":
                    total += estimate_tokens(item.get("text", ""))
                elif item.get("type") == "image_url":
                    total += 500  # estimate per image
        else:
            total += estimate_tokens(content)
    return total
