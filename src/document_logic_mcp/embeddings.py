"""Semantic embeddings for truth similarity search."""

import logging
import pickle
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# Lazy import to avoid loading model if not needed
_sentence_transformer = None


def _get_model():
    """Lazy load sentence transformer model."""
    global _sentence_transformer
    if _sentence_transformer is None:
        try:
            from sentence_transformers import SentenceTransformer
            _sentence_transformer = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Loaded sentence transformer model: all-MiniLM-L6-v2")
        except ImportError:
            logger.error("sentence-transformers not installed. Embeddings disabled.")
            raise ImportError(
                "sentence-transformers required for embeddings. "
                "Install with: pip install sentence-transformers"
            )
    return _sentence_transformer


class EmbeddingService:
    """Generate and compare semantic embeddings for text."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize embedding service.

        Args:
            model_name: Sentence transformer model to use.
                       Default: all-MiniLM-L6-v2 (fast, 384-dim, good for semantic similarity)
        """
        self.model_name = model_name
        # Model loaded lazily on first use
        self._model: Optional[object] = None

    @property
    def model(self):
        """Lazy load model on first use."""
        if self._model is None:
            self._model = _get_model()
        return self._model

    def embed_text(self, text: str) -> np.ndarray:
        """
        Generate embedding vector for text.

        Args:
            text: Text to embed (typically a truth statement)

        Returns:
            Numpy array with embedding vector (384-dim for all-MiniLM-L6-v2)
        """
        if not text or not text.strip():
            # Return zero vector for empty text
            return np.zeros(384, dtype=np.float32)

        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)  # Reduce precision for storage

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        """
        Generate embeddings for multiple texts efficiently.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        embeddings = self.model.encode(texts, convert_to_numpy=True, show_progress_bar=False)
        return [emb.astype(np.float32) for emb in embeddings]

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """
        Compute cosine similarity between two vectors.

        Args:
            a: First embedding vector
            b: Second embedding vector

        Returns:
            Similarity score between 0.0 and 1.0 (1.0 = identical)
        """
        # Handle zero vectors
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)

        if norm_a == 0 or norm_b == 0:
            return 0.0

        return float(np.dot(a, b) / (norm_a * norm_b))

    @staticmethod
    def serialize_embedding(embedding: np.ndarray) -> bytes:
        """
        Serialize embedding for storage in database.

        Args:
            embedding: Numpy array to serialize

        Returns:
            Pickled bytes suitable for BLOB storage
        """
        return pickle.dumps(embedding, protocol=pickle.HIGHEST_PROTOCOL)

    @staticmethod
    def deserialize_embedding(blob: bytes) -> np.ndarray:
        """
        Deserialize embedding from database.

        Args:
            blob: Pickled bytes from database

        Returns:
            Numpy array with embedding
        """
        return pickle.loads(blob)


def compute_similarities(query_embedding: np.ndarray, truth_embeddings: list[np.ndarray]) -> list[float]:
    """
    Compute cosine similarities between query and all truths efficiently.

    Args:
        query_embedding: Query vector
        truth_embeddings: List of truth vectors

    Returns:
        List of similarity scores (same length as truth_embeddings)
    """
    if not truth_embeddings:
        return []

    # Stack embeddings into matrix for vectorized computation
    truth_matrix = np.vstack(truth_embeddings)

    # Normalize query
    query_norm = query_embedding / np.linalg.norm(query_embedding)

    # Normalize truth matrix rows
    truth_norms = np.linalg.norm(truth_matrix, axis=1, keepdims=True)
    truth_matrix_norm = truth_matrix / np.where(truth_norms == 0, 1, truth_norms)

    # Compute all similarities at once (vectorized dot product)
    similarities = np.dot(truth_matrix_norm, query_norm)

    return similarities.tolist()
