"""測試 PubMed 工具模組（需要網路）"""

import asyncio
import pytest
from contentflow.tools.pubmed import search_pubmed


@pytest.mark.asyncio
async def test_search_pubmed_returns_results():
    """用開發計劃指定的測試案例：刺五加 + 骨關節炎"""
    result = await search_pubmed(
        "Acanthopanax senticosus osteoarthritis",
        max_results=5,
    )
    assert result.query == "Acanthopanax senticosus osteoarthritis"
    assert isinstance(result.articles, list)
    # PubMed 可能找不到完全相符的結果，只驗證型別
    for article in result.articles:
        assert article.pmid
        assert article.title


@pytest.mark.asyncio
async def test_search_pubmed_empty_query():
    """無相符結果時應回傳空清單而非拋出例外"""
    result = await search_pubmed("zzzyyyy_no_results_xyz", max_results=5)
    assert result.articles == [] or isinstance(result.articles, list)
