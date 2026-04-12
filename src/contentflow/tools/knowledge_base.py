"""知識庫 (KB) 向量搜尋工具

CF-05-03: ChromaDB collection 建置與 embedding pipeline
CF-05-04: KB query adapter（供 Strategy Agent 呼叫）

架構：
  每個 project 有獨立的 ChromaDB collection（名稱：kb_project_{id}）
  universal 知識共用一個全域 collection（名稱：kb_universal）
  
  embedding model：text-embedding-3-small（已有 OpenAI key）

  主要 API：
    sync_project_knowledge(session, project_id)  → 將 DB 中的 KnowledgeEntry 同步到 ChromaDB
    query_kb(project_id, query_text, top_k=5)    → 查詢並回傳格式化知識摘要
    
  使用 ChromaDB ephemeral client（in-memory）當 CHROMA_PERSIST_DIR 未設定時，
  否則使用 PersistentClient（本地磁碟儲存）。
"""
from __future__ import annotations

import json
import os
from typing import Optional

from loguru import logger

from ..config import settings
from ..models.database import KnowledgeEntry

# ─────────────────────────────────────────────────────────────────────────────
# ChromaDB client 初始化（lazy，避免每次 import 就連線）
# ─────────────────────────────────────────────────────────────────────────────

_chroma_client = None

def _get_chroma_client():
    """回傳 ChromaDB client（singleton，lazy init）"""
    global _chroma_client
    if _chroma_client is not None:
        return _chroma_client

    try:
        import chromadb

        persist_dir = getattr(settings, "chroma_persist_dir", None) or os.environ.get("CHROMA_PERSIST_DIR", "")
        if persist_dir:
            _chroma_client = chromadb.PersistentClient(path=persist_dir)
            logger.info(f"[KB] ChromaDB PersistentClient 初始化：{persist_dir}")
        else:
            _chroma_client = chromadb.EphemeralClient()
            logger.debug("[KB] ChromaDB EphemeralClient 初始化（in-memory）")
    except ImportError:
        logger.warning("[KB] chromadb 未安裝，KB 功能降級為純文字搜尋")
        _chroma_client = None

    return _chroma_client


def _collection_name(project_id: Optional[int]) -> str:
    if project_id is None:
        return "kb_universal"
    return f"kb_project_{project_id}"


def _get_or_create_collection(project_id: Optional[int]):
    """取得或建立 ChromaDB collection，若 client 不可用則回傳 None"""
    client = _get_chroma_client()
    if client is None:
        return None

    name = _collection_name(project_id)
    try:
        return client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        logger.warning(f"[KB] 無法取得 collection {name}：{e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Embedding 工具
# ─────────────────────────────────────────────────────────────────────────────

_EMBED_MODEL = "text-embedding-3-small"


def _get_embedding(text: str) -> list[float]:
    """呼叫 OpenAI embedding API，若 API key 未設定則回傳全零向量"""
    api_key = getattr(settings, "openai_api_key", None) or os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-placeholder"):
        # fallback：回傳 1536 維全零向量（只在測試環境使用）
        return [0.0] * 1536

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.embeddings.create(model=_EMBED_MODEL, input=text[:8000])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning(f"[KB] embedding 失敗：{e}，使用零向量 fallback")
        return [0.0] * 1536


def _entry_to_document(entry: KnowledgeEntry) -> str:
    """將 KnowledgeEntry 轉換為供 embedding 的文字"""
    meta = {}
    try:
        meta = json.loads(entry.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        pass

    parts = [
        f"類別：{entry.category}",
        f"模式：{entry.pattern}",
        f"信心等級：{entry.confidence_level}",
        f"支持數據：{entry.evidence_count} 篇",
    ]
    if meta:
        for k, v in list(meta.items())[:3]:
            if isinstance(v, float):
                parts.append(f"{k}：{v:.2f}")
            elif v is not None:
                parts.append(f"{k}：{v}")
    return "\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# CF-05-03: 同步 KnowledgeEntry → ChromaDB
# ─────────────────────────────────────────────────────────────────────────────

def sync_project_knowledge(session, project_id: int) -> int:
    """
    將 project 的 active KnowledgeEntry 同步到 ChromaDB。
    universal 條目同步到 kb_universal collection。
    
    回傳已同步的條目數。
    """
    entries: list[KnowledgeEntry] = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.is_active.is_(True),
        )
        .all()
    )

    # 同步 universal 條目（跨專案共用）
    universal_entries: list[KnowledgeEntry] = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.confidence_level == "universal",
            KnowledgeEntry.is_active.is_(True),
        )
        .all()
    )

    synced = 0
    for entry_list, pid in [(entries, project_id), (universal_entries, None)]:
        collection = _get_or_create_collection(pid)
        if collection is None:
            continue   # chromadb 不可用

        for entry in entry_list:
            doc = _entry_to_document(entry)
            embedding = _get_embedding(doc)
            entry_id = f"entry_{entry.id}"
            try:
                collection.upsert(
                    ids=[entry_id],
                    embeddings=[embedding],
                    documents=[doc],
                    metadatas=[{
                        "entry_id": entry.id,
                        "category": entry.category,
                        "confidence_level": entry.confidence_level,
                        "evidence_count": entry.evidence_count,
                    }],
                )
                synced += 1
            except Exception as e:
                logger.warning(f"[KB] upsert entry_{entry.id} 失敗：{e}")

    logger.info(f"[KB] project={project_id} 同步 {synced} 條知識到 ChromaDB")
    return synced


# ─────────────────────────────────────────────────────────────────────────────
# CF-05-04: KB Query Adapter
# ─────────────────────────────────────────────────────────────────────────────

def query_kb(
    project_id: int,
    query_text: str,
    top_k: int = 5,
    session=None,
) -> list[str]:
    """
    查詢知識庫，回傳最相關的知識條目文字列表。

    若 ChromaDB 不可用，fallback 為從 DB 直接依 category 過濾相關條目。

    Args:
        project_id: 專案 ID
        query_text: 查詢文字（通常是關鍵字 + 文章類型）
        top_k: 回傳最多筆數
        session: SQLAlchemy session（fallback 用）
    
    Returns:
        list[str]，每個元素為格式化的知識摘要
    """
    # 嘗試從 ChromaDB 查詢
    client = _get_chroma_client()
    if client is not None:
        results = []
        for pid in [project_id, None]:   # 先查 project-specific，再查 universal
            collection = _get_or_create_collection(pid)
            if collection is None:
                continue
            try:
                count = collection.count()
                if count == 0:
                    continue
                embedding = _get_embedding(query_text)
                resp = collection.query(
                    query_embeddings=[embedding],
                    n_results=min(top_k, count),
                    include=["documents", "metadatas"],
                )
                for doc in (resp.get("documents") or [[]])[0]:
                    if doc and doc not in results:
                        results.append(doc)
            except Exception as e:
                logger.warning(f"[KB] query collection pid={pid} 失敗：{e}")
                continue
        if results:
            return results[:top_k]

    # Fallback：直接從 DB 查詢（不做 embedding）
    if session is None:
        logger.warning("[KB] ChromaDB 不可用且無 session，無法 fallback")
        return []

    entries = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.project_id == project_id,
            KnowledgeEntry.is_active.is_(True),
        )
        .order_by(KnowledgeEntry.evidence_count.desc())
        .limit(top_k)
        .all()
    )

    # 補充 universal 條目
    universal = (
        session.query(KnowledgeEntry)
        .filter(
            KnowledgeEntry.confidence_level == "universal",
            KnowledgeEntry.is_active.is_(True),
        )
        .order_by(KnowledgeEntry.evidence_count.desc())
        .limit(top_k)
        .all()
    )

    all_entries = entries + [e for e in universal if e not in entries]
    return [_entry_to_document(e) for e in all_entries[:top_k]]


def format_kb_context(kb_results: list[str], keyword: str) -> str:
    """
    將 KB 查詢結果格式化為注入 prompt 的文字區塊。
    
    輸出格式：
    === 知識庫：過去文章學習成果（適用「{keyword}」類型文章）===
    1. ...
    2. ...
    ===
    """
    if not kb_results:
        return ""

    lines = [
        f"=== 知識庫：過去文章學習成果（適用「{keyword}」類型文章）===",
    ]
    for i, result in enumerate(kb_results, 1):
        # 只取核心行（避免 prompt 過長）
        core_lines = [ln for ln in result.split("\n") if ln.strip()][:3]
        lines.append(f"{i}. {' | '.join(core_lines)}")
    lines.append("===")
    return "\n".join(lines)
