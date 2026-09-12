from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import redis
import yaml
from sqlalchemy import text

from app.config import ROOT, get_settings
from app.db import engine


def tokenize(value: str) -> set[str]:
    value = value.lower()
    tokens = set(re.findall(r"[a-z_][a-z0-9_]*|\d+(?:\.\d+)?", value))
    for block in re.findall(r"[\u4e00-\u9fff]+", value):
        tokens.add(block)
        tokens.update(block[index:index + 2] for index in range(max(1, len(block) - 1)))
    return {token for token in tokens if token.strip()}


def hash_embedding(value: str, dimension: int) -> list[float]:
    """Deterministic local embedding keeps the demo reproducible and cheap."""
    vector = [0.0] * dimension
    for token in tokenize(value):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        number = int.from_bytes(digest, "little")
        vector[number % dimension] += 1.0 if number & 1 else -1.0
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [item / norm for item in vector]


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{item:.8f}" for item in vector) + "]"


@dataclass
class KnowledgeHit:
    id: str
    kind: str
    title: str
    content: str
    score: float
    source: str = "Northwind知识库"

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class HybridRetriever:
    """PostgreSQL hybrid RAG: pg_trgm recall + pgvector recall + RRF."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.settings = get_settings()
        self.path = Path(path or ROOT / "data" / "knowledge.yaml")
        self.documents: list[dict[str, Any]] = yaml.safe_load(self.path.read_text(encoding="utf-8")) or []
        self.redis = redis.Redis.from_url(self.settings.redis_url, decode_responses=True)
        self.redis.ping()

    def ensure_index(self) -> None:
        dimension = self.settings.rag_embedding_dim
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS rag_knowledge (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
                    embedding vector({dimension}) NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_rag_knowledge_text_trgm
                ON rag_knowledge USING gin ((title || ' ' || content) gin_trgm_ops)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_rag_knowledge_embedding_hnsw
                ON rag_knowledge USING hnsw (embedding vector_cosine_ops)
            """))
            for item in self.documents:
                source = f"{item['title']} {item['content']} {' '.join(item.get('keywords', []))}"
                conn.execute(text("""
                    INSERT INTO rag_knowledge(id, kind, title, content, keywords, embedding, updated_at)
                    VALUES (:id, :kind, :title, :content, CAST(:keywords AS jsonb), CAST(:embedding AS vector), now())
                    ON CONFLICT (id) DO UPDATE SET
                        kind = EXCLUDED.kind,
                        title = EXCLUDED.title,
                        content = EXCLUDED.content,
                        keywords = EXCLUDED.keywords,
                        embedding = EXCLUDED.embedding,
                        updated_at = now()
                """), {
                    "id": item["id"],
                    "kind": item.get("kind", "knowledge"),
                    "title": item["title"],
                    "content": item["content"],
                    "keywords": json.dumps(item.get("keywords", []), ensure_ascii=False),
                    "embedding": vector_literal(hash_embedding(source, dimension)),
                })

    def retrieve(self, query: str, top_k: int | None = None, kinds: set[str] | None = None) -> list[KnowledgeHit]:
        top_k = top_k or self.settings.rag_top_k
        kind_key = ",".join(sorted(kinds or []))
        cache_key = "querymind:rag:" + hashlib.sha256(f"{query}|{top_k}|{kind_key}".encode()).hexdigest()
        cached = self.redis.get(cache_key)
        if cached:
            return [KnowledgeHit(**item) for item in json.loads(cached)]

        limit = max(20, top_k * 4)
        params: dict[str, Any] = {
            "query": query,
            "embedding": vector_literal(hash_embedding(query, self.settings.rag_embedding_dim)),
            "limit": limit,
        }
        kind_sql = ""
        if kinds:
            params["kinds"] = list(kinds)
            kind_sql = "WHERE kind = ANY(:kinds)"

        with engine.connect() as conn:
            keyword_rows = conn.execute(text(f"""
                SELECT id, similarity(title || ' ' || content, :query) AS score
                FROM rag_knowledge
                {kind_sql}
                ORDER BY score DESC, id
                LIMIT :limit
            """), params).mappings().all()
            vector_rows = conn.execute(text(f"""
                SELECT id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
                FROM rag_knowledge
                {kind_sql}
                ORDER BY embedding <=> CAST(:embedding AS vector), id
                LIMIT :limit
            """), params).mappings().all()

        rrf: dict[str, float] = {}
        for rank, row in enumerate(keyword_rows, start=1):
            rrf[row["id"]] = rrf.get(row["id"], 0.0) + 1 / (60 + rank)
        for rank, row in enumerate(vector_rows, start=1):
            rrf[row["id"]] = rrf.get(row["id"], 0.0) + 1 / (60 + rank)
        selected = [item[0] for item in sorted(rrf.items(), key=lambda item: item[1], reverse=True)[:top_k]]
        if not selected:
            return []

        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT id, kind, title, content
                FROM rag_knowledge WHERE id = ANY(:ids)
            """), {"ids": selected}).mappings().all()
        by_id = {row["id"]: row for row in rows}
        hits = [
            KnowledgeHit(
                id=doc_id,
                kind=by_id[doc_id]["kind"],
                title=by_id[doc_id]["title"],
                content=by_id[doc_id]["content"],
                score=round(rrf[doc_id], 6),
            )
            for doc_id in selected if doc_id in by_id
        ]
        self.redis.setex(cache_key, self.settings.rag_cache_seconds, json.dumps([hit.as_dict() for hit in hits], ensure_ascii=False))
        return hits
