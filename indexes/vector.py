"""Vector embedding index for semantic memory expansion."""

from typing import Dict, List, Optional, Tuple
import numpy as np


class VectorIndex:
    """Rebuildable vector index supporting semantic candidate retrieval via cosine similarity."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension
        self._memory_ids: List[str] = []
        self._embeddings: List[np.ndarray] = []
        self._id_to_idx: Dict[str, int] = {}

    def add_vector(self, memory_id: str, vector: List[float] | np.ndarray) -> None:
        vec = np.asarray(vector, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec = np.zeros(self.dimension, dtype=np.float32)

        if memory_id in self._id_to_idx:
            idx = self._id_to_idx[memory_id]
            self._embeddings[idx] = vec
        else:
            idx = len(self._memory_ids)
            self._memory_ids.append(memory_id)
            self._embeddings.append(vec)
            self._id_to_idx[memory_id] = idx

    def search(self, query_vector: List[float] | np.ndarray, top_k: int = 5) -> List[Tuple[str, float]]:
        """Compute cosine similarity and return top_k (memory_id, score)."""
        if not self._memory_ids:
            return []

        q_vec = np.asarray(query_vector, dtype=np.float32)
        norm = np.linalg.norm(q_vec)
        if norm > 0:
            q_vec = q_vec / norm

        matrix = np.vstack(self._embeddings)
        scores = np.dot(matrix, q_vec)

        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            score = float(scores[idx])
            results.append((self._memory_ids[idx], score))
        return results

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
    def mock_embed_text(text: str, dimension: int = 64) -> np.ndarray:
        """Deterministic pseudo-embedding for text based on character hashing."""
        vec = np.zeros(dimension, dtype=np.float32)
        for i, word in enumerate(text.lower().split()):
            h = hash(word) % dimension
            vec[h] += 1.0 / (i + 1)
        norm = np.linalg.norm(vec)
        return (vec / norm) if norm > 0 else vec
