"""快速驗證資料庫匯入結果"""
from contentflow.db import get_db
from contentflow.models.database import (
    Keyword, Article, ContentCalendar, Category,
    Competitor, WritingRule, ContentStrategy, LegalTerm,
)

s = get_db()
print("=== 資料庫驗證 ===")
print(f"關鍵字: {s.query(Keyword).count()}")
print(f"文章: {s.query(Article).count()}")
print(f"日曆: {s.query(ContentCalendar).count()}")
print(f"分類: {s.query(Category).count()}")
print(f"競品: {s.query(Competitor).count()}")
print(f"規範: {s.query(WritingRule).count()}")
print(f"策略: {s.query(ContentStrategy).count()}")
print(f"法規: {s.query(LegalTerm).count()}")

print("\n--- Top 5 關鍵字 (by volume) ---")
for kw in s.query(Keyword).order_by(Keyword.search_volume.desc()).limit(5):
    print(f"  {kw.keyword}: vol={int(kw.search_volume)}, diff={int(kw.seo_difficulty)}")

print("\n--- 日曆 1月份 ---")
for c in s.query(ContentCalendar).filter(ContentCalendar.month == 1).all():
    print(f"  M{c.month}W{c.week} [{c.article_type}] {c.title[:50]}")

print("\n--- 文章規劃 (前5) ---")
for a in s.query(Article).order_by(Article.seqno).limit(5):
    print(f"  #{a.seqno} {a.primary_keyword} (vol={int(a.primary_keyword_volume)})")

s.close()
