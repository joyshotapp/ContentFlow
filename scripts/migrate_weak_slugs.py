#!/usr/bin/env python3
"""P1：批次將弱 slug 遷移為語意化 slug，並登記 old_slugs 供 301。

用法：
  PYTHONPATH=src python scripts/migrate_weak_slugs.py [--dry-run] [--project-id N]
"""

from __future__ import annotations

import argparse
import sys

from contentflow.db import SessionLocal, init_db
from contentflow.models.database import Article
from contentflow.utils.slug_governance import (
    is_weak_slug,
    propose_article_slug,
    register_slug_change,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-id", type=int, default=None)
    args = parser.parse_args()

    init_db()
    updated = 0

    with SessionLocal() as session:
        query = session.query(Article).filter(Article.slug != "")
        if args.project_id:
            query = query.filter(Article.project_id == args.project_id)
        articles = query.all()

        for article in articles:
            if not is_weak_slug(article.slug or ""):
                continue
            new_slug = propose_article_slug(
                primary_keyword=article.primary_keyword or article.title or "",
                title=article.title or "",
                existing_slug=article.slug or "",
            )
            if new_slug == article.slug:
                continue
            print(f"#{article.id} {article.slug!r} -> {new_slug!r}")
            if not args.dry_run:
                register_slug_change(article, new_slug)
                updated += 1

        if not args.dry_run:
            session.commit()

    print(f"完成：{'預覽' if args.dry_run else '更新'} {updated} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
