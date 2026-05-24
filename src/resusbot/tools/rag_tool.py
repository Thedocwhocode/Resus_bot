"""
Agno Toolkit wrapper for the LlamaIndex MedicalRAGRetriever.

Registered as a tool so Agno agents can call retrieve_medical_context()
and receive the full citation-aware context block as a string.
"""

from __future__ import annotations

from agno.tools import Toolkit

from resusbot.rag.retrieval import MedicalRAGRetriever, RetrievalResult

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


class RAGRetrievalTool(Toolkit):
    """Agno toolkit that wraps MedicalRAGRetriever for use inside agents."""

    name: str = "rag_retrieval"

    def __init__(self, retriever: MedicalRAGRetriever) -> None:
        super().__init__(name=self.name)
        self._retriever = retriever
        self.register(self.retrieve_medical_context)

    def retrieve_medical_context(self, query: str, top_k: int = 6) -> str:
        """
        Search the emergency medicine corpus and return relevant passages with citations.

        Args:
            query: Clinical question or topic to search for.
            top_k: Number of source chunks to retrieve (default 6).

        Returns:
            Formatted string with retrieved text and inline citation metadata.
        """
        log.info("rag_tool_called", query=query[:80])
        result: RetrievalResult = self._retriever.retrieve(query)
        return result.full_context_for_prompt()
