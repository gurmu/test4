"""
ITSM Search Plugin (Azure AI Search)
"""

from __future__ import annotations

import logging
from typing import Any

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from semantic_kernel.functions import kernel_function

logger = logging.getLogger(__name__)


class ITSMSearchPlugin:
    """Semantic Kernel plugin for Azure AI Search (ITSM KB)."""

    def __init__(self, endpoint: str, index_name: str, api_key: str, content_field: str = "content"):
        self._content_field = content_field
        self._client = SearchClient(
            endpoint=endpoint,
            index_name=index_name,
            credential=AzureKeyCredential(api_key),
        )

    def _extract_content(self, doc: dict[str, Any]) -> str:
        value = doc.get(self._content_field)
        if isinstance(value, str) and value.strip():
            return value.strip()
        for key in ["content", "text", "chunk", "chunk_text", "body"]:
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @kernel_function(name="search_kb", description="Search the ITSM knowledge base for relevant guidance.")
    def search_kb(
        self,
        query: str,
        top_k: int = 5,
        semantic_config: str | None = None,
        use_vectors: bool = False,
        vector_field: str = "text_embedding",
    ) -> str:
        if not query.strip():
            return "No query provided."

        search_kwargs: dict[str, Any] = {"search_text": query, "top": top_k}
        if semantic_config:
            search_kwargs["query_type"] = "semantic"
            search_kwargs["semantic_configuration_name"] = semantic_config

        if use_vectors:
            search_kwargs["vector_queries"] = [
                VectorizedQuery(vector=[0.0], fields=vector_field, k_nearest_neighbors=top_k)
            ]
            logger.warning("Vector search enabled but embedding generation is not wired.")

        results = self._client.search(**search_kwargs)
        snippets: list[str] = []
        for result in results:
            doc = dict(result)
            content = self._extract_content(doc)
            if content:
                file_name = doc.get("file_name")
                page_num = doc.get("page_num")
                ref = []
                if file_name:
                    ref.append(f"file_name={file_name}")
                if page_num is not None:
                    ref.append(f"page_num={page_num}")
                ref_text = " | ".join(ref)
                snippets.append(f"{ref_text}\n{content}" if ref_text else content)

        if not snippets:
            return "NO_KB_MATCH: No relevant ITSM guidance found."

        return "\n\n".join(snippets)
