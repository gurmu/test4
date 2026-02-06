"""
ITSM Search Plugin with Multi-Vector Support

Supports multi-vector hybrid search:
- text_embedding: 384 dims (sentence-transformers)
- image_description_embedding: 512 dims (CLIP text)
- Keyword search on content field
- Optional semantic ranking

Returns STRUCTURED JSON (not string headers):
  {
    "kb_hits_count": <int>,
    "results": [
      {"title": ..., "content": ..., "source": ..., "score": ...}
    ]
  }
Score fields are included for observability/logging but are NOT used
for routing decisions.  The LLM (not a threshold) decides whether
the results are relevant enough to answer the user's question.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)


class ITSMSearchPlugin:
    """Semantic Kernel plugin for Azure AI Search with multi-vector support."""

    def __init__(
        self,
        endpoint: str,
        index_name: str,
        api_key: str,
        content_field: str = "content",
        embedding_model=None,   # sentence-transformers model for 384D text embeddings
        clip_model=None,        # CLIP model for 512D image embeddings
    ):
        self._content_field = content_field
        self._client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(api_key),
        )

        # Embedding models (loaded lazily if needed)
        self._embedding_model = embedding_model
        self._clip_model = clip_model
        self._models_loaded = False

    # ------------------------------------------------------------------
    # Multimodal embedding models (CLIP + sentence-transformers)
    # ------------------------------------------------------------------
    def _load_models(self):
        """Lazy load embedding models."""
        if self._models_loaded:
            return

        if self._embedding_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedding_model = SentenceTransformer(
                    "sentence-transformers/all-MiniLM-L6-v2"
                )
                logger.info("Loaded text embedding model (384D)")
            except Exception as e:
                logger.warning(f"Could not load text embedding model: {e}")

        if self._clip_model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._clip_model = SentenceTransformer(
                    "sentence-transformers/clip-ViT-B-32"
                )
                logger.info("Loaded CLIP model (512D)")
            except Exception as e:
                logger.warning(f"Could not load CLIP model: {e}")

        self._models_loaded = True

    def _get_text_embedding(self, text: str) -> list[float] | None:
        """Generate 384-dim text embedding for text_embedding field."""
        self._load_models()
        if not self._embedding_model:
            return None
        try:
            embedding = self._embedding_model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error generating text embedding: {e}")
            return None

    def _get_image_description_embedding(self, text: str) -> list[float] | None:
        """Generate 512-dim CLIP text embedding for image_description_embedding field."""
        self._load_models()
        if not self._clip_model:
            return None
        try:
            embedding = self._clip_model.encode(text, convert_to_tensor=False)
            return embedding.tolist()
        except Exception as e:
            logger.error(f"Error generating CLIP embedding: {e}")
            return None

    # ------------------------------------------------------------------
    # Content extraction helper
    # ------------------------------------------------------------------
    def _extract_content(self, doc: dict[str, Any]) -> str:
        """Extract content from search result."""
        value = doc.get(self._content_field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        for key in ["content", "text", "chunk", "chunk_text", "body"]:
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    # ------------------------------------------------------------------
    # Main search function (kernel_function for Semantic Kernel)
    # ------------------------------------------------------------------
    @kernel_function(
        name="search_kb",
        description="Search the ITSM knowledge base using multi-vector hybrid search.",
    )
    def search_kb(
        self,
        query: str,
        top_k: int = 5,
        semantic_config: str | None = None,
        use_text_vectors: bool = True,
        use_image_vectors: bool = True,
    ) -> str:
        """
        Search with hybrid approach (keyword + text vector + CLIP vector).

        Returns a JSON string with structured results:
        {
            "kb_hits_count": 3,
            "results": [
                {
                    "title": "file_name.pdf",
                    "content": "...",
                    "source": "file_name=x | page_num=5",
                    "score": 12.345,
                    "image_url": null
                },
                ...
            ]
        }

        If no results:  {"kb_hits_count": 0, "results": []}

        Scores are included for logging/observability only and are NOT
        used for routing decisions.
        """
        if not query.strip():
            return json.dumps({"kb_hits_count": 0, "results": [], "error": "No query provided."})

        # Base keyword search
        search_kwargs: dict[str, Any] = {
            "search_text": query,
            "top": top_k,
            "select": ["id", "file_name", "page_num", "content", "item_type", "image_url"],
        }

        # Add semantic ranking if configured
        if semantic_config:
            search_kwargs["query_type"] = "semantic"
            search_kwargs["semantic_configuration_name"] = semantic_config
            logger.info(f"Using semantic search with config: {semantic_config}")

        # Add vector queries (multimodal: text + CLIP)
        vector_queries = []

        if use_text_vectors:
            text_vector = self._get_text_embedding(query)
            if text_vector:
                vector_queries.append(
                    VectorizedQuery(
                        vector=text_vector,
                        fields="text_embedding",
                        k_nearest_neighbors=top_k,
                    )
                )
                logger.info("Added text vector query (384D)")

        if use_image_vectors:
            image_desc_vector = self._get_image_description_embedding(query)
            if image_desc_vector:
                vector_queries.append(
                    VectorizedQuery(
                        vector=image_desc_vector,
                        fields="image_description_embedding",
                        k_nearest_neighbors=top_k,
                    )
                )
                logger.info("Added image description vector query (512D)")

        if vector_queries:
            search_kwargs["vector_queries"] = vector_queries

        # Execute search
        try:
            results = self._client.search(**search_kwargs)
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return json.dumps({"kb_hits_count": 0, "results": [], "error": str(e)})

        # Collect structured results
        result_items: list[dict[str, Any]] = []

        for result in results:
            doc = dict(result)
            content = self._extract_content(doc)
            if not content:
                continue

            # Capture the search score for logging (NOT for gating)
            score = doc.get("@search.score", 0.0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0

            # Build source reference string
            source_parts = []
            if doc.get("file_name"):
                source_parts.append(f"file_name={doc['file_name']}")
            if doc.get("page_num") is not None:
                source_parts.append(f"page_num={doc['page_num']}")
            if doc.get("item_type"):
                source_parts.append(f"type={doc['item_type']}")

            result_items.append({
                "title": doc.get("file_name", "Unknown"),
                "content": content,
                "source": " | ".join(source_parts),
                "score": round(score, 4),
                "image_url": doc.get("image_url"),
            })

        kb_hits_count = len(result_items)

        # Log scores for observability (NOT used for routing)
        if result_items:
            top_score = max(r["score"] for r in result_items)
            logger.info(
                f"KB search: hits={kb_hits_count}, top_score={top_score:.4f} "
                f"(logged for observability, NOT used for routing)"
            )
        else:
            logger.info("KB search: hits=0")

        output = {"kb_hits_count": kb_hits_count, "results": result_items}
        return json.dumps(output, ensure_ascii=False)
