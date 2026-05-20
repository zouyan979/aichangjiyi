from __future__ import annotations
import re
import math
from collections import Counter
from ..services.token_estimator import estimate_tokens


# Simple Chinese/English tokenizer without external deps
def _tokenize(text: str) -> list[str]:
    tokens = []
    # Chinese: bigram approach
    chinese = re.findall(r'[一-鿿]+', text)
    for seg in chinese:
        if len(seg) <= 2:
            tokens.append(seg)
        else:
            for i in range(len(seg) - 1):
                tokens.append(seg[i:i+2])
            tokens.append(seg)
    # English words
    english = re.findall(r'[a-zA-Z]+', text.lower())
    tokens.extend(english)
    return tokens


# Common Chinese stopwords
_STOPWORDS = set("的了是在我你他她它们这那个有不人大来上中下会可能要就"
                 "和与及把被让给对从到过着地得而而且但是如果因为所以"
                 "什么怎么哪里谁多少一天这个那个还是只也又再已经")


def _filter_tokens(tokens: list[str]) -> list[str]:
    return [t for t in tokens if len(t) > 1 and t not in _STOPWORDS]


def bm25_score(query_tokens: list[str], doc_tokens: list[str],
               avg_dl: float, num_docs: int, doc_freqs: dict[str, int],
               k1: float = 1.5, b: float = 0.75) -> float:
    score = 0.0
    dl = len(doc_tokens)
    doc_counter = Counter(doc_tokens)

    for qt in set(query_tokens):
        if qt not in doc_freqs:
            continue
        df = doc_freqs[qt]
        idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1)
        tf = doc_counter.get(qt, 0)
        tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
        score += idf * tf_norm

    return score


class RelevanceEngine:
    def __init__(self):
        self._idf_cache = {}

    def score_summaries(self, query: str, summaries: list[dict],
                        recency_weight: float = 0.3) -> list[tuple[dict, float]]:
        if not summaries:
            return []

        query_tokens = _filter_tokens(_tokenize(query))
        if not query_tokens:
            # Fallback: return by recency
            return [(s, 1.0 - i * 0.01) for i, s in enumerate(reversed(summaries))]

        # Tokenize all summaries
        doc_tokens_list = []
        for s in summaries:
            text = s.get("summary", "") + " " + " ".join(s.get("topics", []))
            doc_tokens_list.append(_filter_tokens(_tokenize(text)))

        num_docs = len(doc_tokens_list)
        avg_dl = sum(len(dt) for dt in doc_tokens_list) / max(num_docs, 1)

        # Build document frequency
        doc_freqs = Counter()
        for dt in doc_tokens_list:
            for token in set(dt):
                doc_freqs[token] += 1

        # Score each summary
        scores = []
        for i, (summary, doc_tokens) in enumerate(zip(summaries, doc_tokens_list)):
            relevance = bm25_score(query_tokens, doc_tokens, avg_dl, num_docs, doc_freqs)
            recency = 1.0 - (num_docs - 1 - i) / max(num_docs, 1)  # newer = higher
            combined = relevance * (1 - recency_weight) + recency * recency_weight
            scores.append((summary, combined))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores

    def select_within_budget(self, query: str, summaries: list[dict],
                             token_budget: int, recency_weight: float = 0.3) -> list[dict]:
        scored = self.score_summaries(query, summaries, recency_weight)
        selected = []
        used_tokens = 0

        # Always include the most recent summary if available
        if summaries:
            most_recent = summaries[-1]
            recent_tokens = estimate_tokens(most_recent.get("summary", ""))
            if recent_tokens <= token_budget:
                selected.append(most_recent)
                used_tokens += recent_tokens

        for summary, score in scored:
            if score <= 0:
                continue
            if summary in selected:
                continue
            tokens = estimate_tokens(summary.get("summary", ""))
            if used_tokens + tokens > token_budget:
                continue
            selected.append(summary)
            used_tokens += tokens

        # Sort by time for consistent ordering
        selected.sort(key=lambda s: s.get("created_at", ""))
        return selected


relevance_engine = RelevanceEngine()
