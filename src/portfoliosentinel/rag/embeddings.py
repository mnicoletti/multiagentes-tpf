"""Embeddings locales deterministas — cero red (DoD MARKET_FIXTURE / demo offline).

Hashing de tokens a vector fijo + L2. Suficiente para retrieval de corpus chico
con términos distintivos; no depende de descargar modelos ONNX.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Any


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑ0-9]+", text.lower())


class LocalHashEmbeddingFunction:
    """EmbeddingFunction compatible con Chroma (callable sobre list[str])."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def is_legacy(self) -> bool:
        return True

    def name(self) -> str:
        return f"local_hash_{self.dim}"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002 — API Chroma
        return [self._embed_one(t) for t in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self(input)

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _tokenize(text)
        if not tokens:
            tokens = ["empty"]
        for tok in tokens:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            # Dos buckets por token (positivo / negativo) estilo feature hashing.
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
            # bigrams ligeros
        for a, b in zip(tokens, tokens[1:], strict=False):
            digest = hashlib.sha256(f"{a}_{b}".encode()).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += 0.5 * sign
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    # Chroma a veces inspecciona estos attrs
    def get_config(self) -> dict[str, Any]:
        return {"dim": self.dim}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> LocalHashEmbeddingFunction:
        return LocalHashEmbeddingFunction(dim=int(config.get("dim", 384)))
