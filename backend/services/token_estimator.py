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
        total += estimate_tokens(m.get("content", ""))
    return total
