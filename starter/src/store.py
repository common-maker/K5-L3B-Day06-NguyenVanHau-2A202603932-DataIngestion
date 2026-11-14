"""PostgreSQL + pgvector store with idempotent upsert and parameterized metadata filtering."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg

from .models import Chunk

_ALLOWED_FILTERS: dict[str, type] = {
    "year": int,
    "document_type": str,
    "section": str,
    "document_id": str,
}


def _to_pgvector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8f}" for v in vector) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("database_url must not be empty")
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise ValueError("dimensions must be a positive integer")
        self.database_url = database_url
        self.dimensions = dimensions

    def create_schema(self) -> None:
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS rag_chunks (
                        strategy TEXT NOT NULL,
                        chunk_id TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        source TEXT NOT NULL,
                        page INTEGER NOT NULL,
                        year INTEGER NOT NULL,
                        document_type TEXT NOT NULL,
                        section TEXT NOT NULL,
                        content TEXT NOT NULL,
                        content_hash TEXT NOT NULL,
                        metadata JSONB NOT NULL,
                        embedding vector({self.dimensions}) NOT NULL,
                        PRIMARY KEY (strategy, chunk_id)
                    );
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy_doc
                    ON rag_chunks (strategy, document_id);
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_rag_chunks_strategy_filters
                    ON rag_chunks (strategy, year, document_type, section);
                    """
                )
            conn.commit()

    def upsert(
        self,
        strategy: str,
        chunks: list[Chunk],
        vectors: list[list[float]],
        prune_missing_documents: bool = False,
    ) -> None:
        if not strategy:
            raise ValueError("strategy must not be empty")
        if len(chunks) != len(vectors):
            raise ValueError(
                f"chunks ({len(chunks)}) and vectors ({len(vectors)}) length mismatch"
            )
        for idx, vec in enumerate(vectors):
            if len(vec) != self.dimensions:
                raise ValueError(
                    f"Vector at index {idx} has {len(vec)} dims; expected {self.dimensions}"
                )

        if not chunks:
            return

        by_doc: dict[str, list[str]] = {}
        rows: list[tuple[Any, ...]] = []
        for chunk, vec in zip(chunks, vectors):
            meta = dict(chunk.metadata)
            year = int(meta["year"])
            document_type = str(meta["document_type"])
            section = str(meta["section"])
            content_hash = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
            by_doc.setdefault(chunk.document_id, []).append(chunk.chunk_id)
            rows.append(
                (
                    strategy,
                    chunk.chunk_id,
                    chunk.document_id,
                    chunk.source,
                    int(chunk.page),
                    year,
                    document_type,
                    section,
                    chunk.text,
                    content_hash,
                    json.dumps(meta, ensure_ascii=False),
                    _to_pgvector_literal(vec),
                )
            )

        with psycopg.connect(self.database_url) as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO rag_chunks (
                            strategy, chunk_id, document_id, source, page,
                            year, document_type, section, content, content_hash,
                            metadata, embedding
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::vector)
                        ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                            document_id = EXCLUDED.document_id,
                            source = EXCLUDED.source,
                            page = EXCLUDED.page,
                            year = EXCLUDED.year,
                            document_type = EXCLUDED.document_type,
                            section = EXCLUDED.section,
                            content = EXCLUDED.content,
                            content_hash = EXCLUDED.content_hash,
                            metadata = EXCLUDED.metadata,
                            embedding = EXCLUDED.embedding;
                        """,
                        rows,
                    )
                    # Remove obsolete chunks belonging to re-ingested documents.
                    for doc_id, chunk_ids in by_doc.items():
                        cur.execute(
                            """
                            DELETE FROM rag_chunks
                            WHERE strategy = %s
                              AND document_id = %s
                              AND NOT (chunk_id = ANY(%s));
                            """,
                            (strategy, doc_id, chunk_ids),
                        )
                    if prune_missing_documents:
                        cur.execute(
                            """
                            DELETE FROM rag_chunks
                            WHERE strategy = %s
                              AND NOT (document_id = ANY(%s));
                            """,
                            (strategy, list(by_doc.keys())),
                        )

    def search(
        self,
        strategy: str,
        query_vector: list[float],
        top_k: int = 3,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError(
                f"Query vector has {len(query_vector)} dims; expected {self.dimensions}"
            )
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        where_clauses = ["strategy = %s"]
        filter_params: list[Any] = [strategy]

        if filters:
            for key, raw_val in filters.items():
                if key not in _ALLOWED_FILTERS:
                    raise ValueError(
                        f"Disallowed filter field '{key}'. Allowed: {sorted(_ALLOWED_FILTERS)}"
                    )
                expected_type = _ALLOWED_FILTERS[key]
                typed_val = expected_type(raw_val)
                where_clauses.append(f"{key} = %s")
                filter_params.append(typed_val)

        vec_literal = _to_pgvector_literal(query_vector)
        sql = f"""
            SELECT
                chunk_id,
                document_id,
                source,
                page,
                content,
                metadata,
                (embedding <=> %s::vector) AS cosine_distance
            FROM rag_chunks
            WHERE {" AND ".join(where_clauses)}
            ORDER BY embedding <=> %s::vector ASC, chunk_id ASC
            LIMIT %s;
        """
        params = [vec_literal, *filter_params, vec_literal, top_k]

        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        results: list[dict[str, Any]] = []
        for chunk_id, document_id, source, page, content, metadata, dist in rows:
            dist_f = float(dist)
            results.append(
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "source": source,
                    "page": int(page),
                    "text": content,
                    "score": round(1.0 - dist_f, 6),
                    "cosine_distance": round(dist_f, 6),
                    "metadata": dict(metadata),
                }
            )
        return results

    def count_chunks(self, strategy: str, document_id: str | None = None) -> int:
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                if document_id is None:
                    cur.execute(
                        "SELECT COUNT(*) FROM rag_chunks WHERE strategy = %s;",
                        (strategy,),
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*) FROM rag_chunks WHERE strategy = %s AND document_id = %s;",
                        (strategy, document_id),
                    )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    def delete_strategy(self, strategy: str) -> None:
        with psycopg.connect(self.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM rag_chunks WHERE strategy = %s;", (strategy,))
            conn.commit()
