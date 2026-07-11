"""Provider-independent embedding abstraction (Phase 11, Prompt 2).

Importing this package stays lightweight: it exposes the contracts,
the dependency-free deterministic provider, and the factory. The
optional sentence-transformers provider lives in
``experienceos.embeddings.local`` and is imported only when explicitly
requested. See ``docs/embedding_providers.md``.
"""

from experienceos.embeddings.base import (
    EmbeddingAvailability,
    EmbeddingDimensionError,
    EmbeddingInputError,
    EmbeddingProvider,
    EmbeddingProviderError,
    EmbeddingResult,
    EmbeddingUnavailableError,
    EmbeddingUnavailableReason,
    EmbeddingVector,
    cosine_similarity,
    require_text,
    validate_vector,
)
from experienceos.embeddings.deterministic import (
    DEFAULT_DIMENSIONS,
    DeterministicEmbeddingProvider,
)
from experienceos.embeddings.factory import (
    EMBEDDING_MODES,
    EmbeddingConfigError,
    create_embedding_provider,
)

__all__ = [
    "DEFAULT_DIMENSIONS",
    "DeterministicEmbeddingProvider",
    "EMBEDDING_MODES",
    "EmbeddingAvailability",
    "EmbeddingConfigError",
    "EmbeddingDimensionError",
    "EmbeddingInputError",
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingResult",
    "EmbeddingUnavailableError",
    "EmbeddingUnavailableReason",
    "EmbeddingVector",
    "cosine_similarity",
    "create_embedding_provider",
    "require_text",
    "validate_vector",
]
