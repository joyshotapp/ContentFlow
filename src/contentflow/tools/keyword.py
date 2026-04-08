"""關鍵字分析工具：從競品內容提取高頻詞與語意相關詞"""

from __future__ import annotations
import re
from collections import Counter
from loguru import logger
from ..models import SerpAnalysis


# 常見停用詞（中文）
_STOPWORDS_ZH = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一個", "上", "也", "很", "到", "說", "要", "去", "你", "會",
    "著", "沒有", "看", "好", "自己", "這", "那", "什麼", "對", "中",
    "以", "時", "可以", "可", "但", "如果", "因為", "所以", "而且",
}


def extract_keywords_from_serp(
    serp: SerpAnalysis,
    top_n: int = 30,
) -> list[str]:
    """
    從 SERP 結果（標題 + snippet）提取高頻關鍵詞。

    Returns:
        依頻率排序的關鍵詞清單（前 top_n 個）
    """
    text_corpus = " ".join(
        f"{r.title} {r.snippet}" for r in serp.top_results
    )
    paa_text = " ".join(p.question for p in serp.people_also_ask)
    full_text = f"{text_corpus} {paa_text}"

    # 簡易中文詞頻（以 2-6 字詞為單位）
    words = _tokenize_zh(full_text)
    filtered = [w for w in words if w not in _STOPWORDS_ZH and len(w) >= 2]
    counter = Counter(filtered)

    top_keywords = [word for word, _ in counter.most_common(top_n)]
    logger.info(f"提取到 {len(top_keywords)} 個關鍵詞")
    return top_keywords


def _tokenize_zh(text: str) -> list[str]:
    """
    簡易中文斷詞（bigram + trigram）。
    正式使用建議換成 jieba 或 ckiptagger。
    """
    # 去除 HTML 標籤與特殊符號
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\u4e00-\u9fff\w\s]", " ", text)

    tokens: list[str] = []
    # bigram
    for i in range(len(text) - 1):
        chunk = text[i:i+2].strip()
        if len(chunk) == 2:
            tokens.append(chunk)
    # trigram
    for i in range(len(text) - 2):
        chunk = text[i:i+3].strip()
        if len(chunk) == 3:
            tokens.append(chunk)
    return tokens
