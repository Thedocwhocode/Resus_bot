"""
Hybrid RAG retrieval with inline citations via LlamaIndex CitationQueryEngine.

Returns a RetrievalResult with the answer text and structured citation list
that the study workflow can pass directly into the pedagogical prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

try:
    from llama_index.core import VectorStoreIndex
    from llama_index.core.query_engine import CitationQueryEngine

    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False


@dataclass
class SourceNode:
    source: str
    section: str
    page: str
    snippet: str
    score: float


@dataclass
class RetrievalResult:
    answer: str
    source_nodes: list[SourceNode] = field(default_factory=list)

    def citations_as_text(self) -> str:
        """Format citations as a compact block for prompt injection."""
        if not self.source_nodes:
            return "No citations available."
        lines = []
        for i, node in enumerate(self.source_nodes, 1):
            lines.append(
                f"[{i}] {node.source} | {node.section} | p.{node.page} | "
                f"score={node.score:.2f}\n    \"{node.snippet}\""
            )
        return "\n".join(lines)

    def full_context_for_prompt(self) -> str:
        """Merge answer text + citation block into a single context string."""
        return f"{self.answer}\n\nCITATIONS:\n{self.citations_as_text()}"


class MedicalRAGRetriever:
    """
    Wraps LlamaIndex CitationQueryEngine for the study pipeline.

    Args:
        index: A loaded/built VectorStoreIndex from MedicalIndexer.
        similarity_top_k: How many chunks to retrieve per query.
        citation_chunk_size: Token window for each cited chunk.
    """

    def __init__(
        self,
        index: "VectorStoreIndex",
        similarity_top_k: int = 6,
        citation_chunk_size: int = 512,
    ) -> None:
        if not _DEPS_AVAILABLE:
            raise RuntimeError("llama-index-core is required for retrieval.")
        self._index = index
        self._query_engine = CitationQueryEngine.from_args(
            index,
            similarity_top_k=similarity_top_k,
            citation_chunk_size=citation_chunk_size,
        )

    def retrieve(self, query: str) -> RetrievalResult:
        """Run a semantic query and return answer + citations."""
        log.info("rag_retrieve", query_length=len(query))
        try:
            response = self._query_engine.query(query)
        except Exception:
            log.exception("rag_query_failed")
            return RetrievalResult(answer="Retrieval failed — no context available.")

        source_nodes: list[SourceNode] = []
        for node_with_score in response.source_nodes:
            meta = node_with_score.node.metadata
            source_nodes.append(
                SourceNode(
                    source=meta.get("source", "Unknown"),
                    section=meta.get("section", ""),
                    page=meta.get("page", "?"),
                    snippet=node_with_score.node.text[:200].replace("\n", " "),
                    score=node_with_score.score or 0.0,
                )
            )

        log.info("rag_retrieved", nodes=len(source_nodes))
        return RetrievalResult(
            answer=str(response),
            source_nodes=source_nodes,
        )
