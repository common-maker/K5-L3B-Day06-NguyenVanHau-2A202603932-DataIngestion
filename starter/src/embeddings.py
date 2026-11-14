"""Real OpenAI embedding adapter with explicit error propagation and usage tracking."""
from __future__ import annotations

import os
import time
from typing import Protocol

from openai import OpenAI

_KNOWN_MODEL_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

# Published OpenAI Embeddings pricing (USD per 1M input tokens).
_PRICE_PER_1M_TOKENS = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
    "text-embedding-ada-002": 0.10,
}


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """OpenAI Embeddings API adapter; fails loudly without silent mock fallback."""

    def __init__(
        self,
        model_name: str = "text-embedding-3-small",
        batch_size: int = 64,
    ) -> None:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is missing or empty; real embeddings cannot run without it."
            )
        if model_name not in _KNOWN_MODEL_DIMENSIONS:
            raise ValueError(
                f"Unsupported or unknown embedding model '{model_name}'. "
                f"Supported: {sorted(_KNOWN_MODEL_DIMENSIONS)}"
            )

        self.model_name = model_name
        self.dimensions = _KNOWN_MODEL_DIMENSIONS[model_name]
        self.batch_size = batch_size
        self.client = OpenAI(api_key=api_key)

        self.total_prompt_tokens = 0
        self.total_requests = 0
        self.total_elapsed_seconds = 0.0

    @property
    def estimated_cost_usd(self) -> float:
        rate = _PRICE_PER_1M_TOKENS.get(self.model_name, 0.0)
        return (self.total_prompt_tokens / 1_000_000.0) * rate

    def _embed_batch(self, batch: list[str]) -> list[list[float]]:
        t0 = time.perf_counter()
        response = self.client.embeddings.create(model=self.model_name, input=batch)
        self.total_elapsed_seconds += time.perf_counter() - t0
        self.total_requests += 1
        if response.usage and response.usage.prompt_tokens is not None:
            self.total_prompt_tokens += int(response.usage.prompt_tokens)

        ordered = sorted(response.data, key=lambda item: item.index)
        vectors = [list(item.embedding) for item in ordered]
        for vec in vectors:
            if len(vec) != self.dimensions:
                raise RuntimeError(
                    f"Model {self.model_name} returned {len(vec)} dims, expected {self.dimensions}"
                )
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        all_vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            all_vectors.extend(self._embed_batch(batch))
        return all_vectors

    def embed_query(self, question: str) -> list[float]:
        if not question.strip():
            raise ValueError("Query string must not be empty")
        return self._embed_batch([question])[0]
