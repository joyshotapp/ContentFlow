"""關鍵字分析工具：從競品內容提取高頻詞與語意相關詞"""

from __future__ import annotations
import re
from collections import Counter
from loguru import logger
from ..models import SerpAnalysis

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False


# 常見停用詞（中文）
_STOPWORDS_ZH = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都",
    "一", "一個", "上", "也", "很", "到", "說", "要", "去", "你", "會",
    "著", "沒有", "看", "好", "自己", "這", "那", "什麼", "對", "中",
    "以", "時", "可以", "可", "但", "如果", "因為", "所以", "而且",
    "來", "個", "為", "與", "或", "及", "等", "被", "從", "而",
    "最", "更", "讓", "把", "能", "其", "他", "她", "它",
    "這個", "那個", "如何", "怎麼", "哪些", "為什麼",
    "透過", "進行", "使用", "需要", "包括", "提供", "相關",
}


def extract_keywords_from_serp(
    serp: SerpAnalysis,
    top_n: int = 30,
) -> list[str]:
    """
    從 SERP 結果（標題 + snippet + PAA）提取高頻語意詞。

    使用 jieba 分詞（若可用），否則退回 bigram/trigram。
    過濾 2 字以上、非停用詞的有效詞組。
    """
    text_corpus = " ".join(
        f"{r.title} {r.snippet}" for r in serp.top_results
    )
    paa_text = " ".join(p.question for p in serp.people_also_ask)
    full_text = f"{text_corpus} {paa_text}"

    if _HAS_JIEBA:
        words = _tokenize_jieba(full_text)
    else:
        words = _tokenize_zh(full_text)

    filtered = [w for w in words if w not in _STOPWORDS_ZH and len(w) >= 2]
    counter = Counter(filtered)

    top_keywords = [word for word, _ in counter.most_common(top_n)]
    logger.info(f"提取到 {len(top_keywords)} 個關鍵詞（{'jieba' if _HAS_JIEBA else 'ngram'}）")
    return top_keywords


def _tokenize_jieba(text: str) -> list[str]:
    """使用 jieba 進行中文分詞。"""
    # 去除 HTML 標籤
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[^\u4e00-\u9fff\w\s]", " ", text)
    # jieba 精確模式分詞
    words = jieba.lcut(text)
    # 過濾空白與純數字
    return [w.strip() for w in words if w.strip() and not w.strip().isdigit()]


def _tokenize_zh(text: str) -> list[str]:
    """
    簡易中文斷詞（bigram + trigram）。
    退回方案：當 jieba 不可用時使用。
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
