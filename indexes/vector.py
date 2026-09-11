"""Rebuildable vector index and deterministic lexical-hash fallback embeddings."""

import hashlib
from typing import Dict, List, Tuple

import numpy as np


class VectorIndex:
    """Small rebuildable cosine index used by the prototype runtime.

    The built-in embedding function is deliberately a deterministic lexical
    hashing baseline, *not* a semantic embedding model. Production/research
    runs that claim semantic retrieval should inject a real pinned embedding
    provider and record its model/version in experiment metadata.
    """

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension
        self._memory_ids: List[str] = []
        self._embeddings: List[np.ndarray] = []
        self._id_to_idx: Dict[str, int] = {}

    def add_vector(self, memory_id: str, vector: List[float] | np.ndarray) -> None:
        vec = np.asarray(vector, dtype=np.float32)
        if vec.shape != (self.dimension,):
            raise ValueError(
                f"embedding dimension mismatch: expected {self.dimension}, got {vec.shape}"
            )
        norm = np.linalg.norm(vec)
        vec = vec / norm if norm > 0 else np.zeros(self.dimension, dtype=np.float32)

        if memory_id in self._id_to_idx:
            idx = self._id_to_idx[memory_id]
            self._embeddings[idx] = vec
        else:
            idx = len(self._memory_ids)
            self._memory_ids.append(memory_id)
            self._embeddings.append(vec)
            self._id_to_idx[memory_id] = idx

    def search(
        self,
        query_vector: List[float] | np.ndarray,
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        if not self._memory_ids:
            return []

        q_vec = np.asarray(query_vector, dtype=np.float32)
        if q_vec.shape != (self.dimension,):
            raise ValueError(
                f"query dimension mismatch: expected {self.dimension}, got {q_vec.shape}"
            )
        norm = np.linalg.norm(q_vec)
        if norm > 0:
            q_vec = q_vec / norm

        matrix = np.vstack(self._embeddings)
        scores = np.dot(matrix, q_vec)
        top_indices = np.argsort(scores)[::-1][:top_k]
        return [(self._memory_ids[idx], float(scores[idx])) for idx in top_indices]

    def remove(self, memory_id: str) -> None:
        if memory_id not in self._id_to_idx:
            return
        idx = self._id_to_idx[memory_id]
        self._memory_ids.pop(idx)
        self._embeddings.pop(idx)
        self._id_to_idx = {mid: i for i, mid in enumerate(self._memory_ids)}

    def clear(self) -> None:
        self._memory_ids.clear()
        self._embeddings.clear()
        self._id_to_idx.clear()

    @staticmethod
    def deterministic_hash_embed(text: str, dimension: int = 256) -> np.ndarray:
        """Stable signed feature hashing for deterministic baseline retrieval.

        Unlike Python's process-randomized ``hash()``, SHA-256 makes replay
        stable across processes and machines. This remains a lexical baseline;
        it does not make semantic similarity claims.
        """
        vec = np.zeros(dimension, dtype=np.float32)
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % dimension
            sign = 1.0 if (digest[8] & 1) == 0 else -1.0
            vec[bucket] += sign
        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec

    @staticmethod
    def mock_embed_text(text: str, dimension: int = 256) -> np.ndarray:
        """Backward-compatible alias for the deterministic lexical baseline."""
        return VectorIndex.deterministic_hash_embed(text, dimension=dimension)
