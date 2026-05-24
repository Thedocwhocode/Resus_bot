"""
LlamaIndex vector store with PubMedBERT embeddings over ChromaDB.

Provides build_index() for first-time indexing and load_index() for
subsequent sessions. The index persists in RAG_PERSIST_DIR.
"""

from __future__ import annotations

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# PubMedBERT fine-tuned on NLI/STS pairs — best semantic similarity for biomedical text
PUBMED_BERT_MODEL = "pritamdeka/PubMedBERT-mnli-snli-scinli-scitail-mednli-stsb"
_COLLECTION_NAME = "emergency_medicine"

try:
    import chromadb
    from llama_index.core import StorageContext, VectorStoreIndex
    from llama_index.core.schema import Document
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    from llama_index.vector_stores.chroma import ChromaVectorStore

    _DEPS_AVAILABLE = True
except ImportError:
    _DEPS_AVAILABLE = False
    log.warning(
        "rag_deps_not_installed",
        hint="pip install chromadb llama-index-core llama-index-embeddings-huggingface "
        "llama-index-vector-stores-chroma",
    )


def _require_deps() -> None:
    if not _DEPS_AVAILABLE:
        raise RuntimeError("RAG dependencies missing. Install with: pip install 'resusbot[rag]'")


class MedicalIndexer:
    """
    Manages the ChromaDB-backed LlamaIndex vector store.

    Usage:
        indexer = MedicalIndexer(persist_dir="/data/rag")
        index = indexer.build_index(documents)   # first time
        index = indexer.load_index()              # subsequent runs
    """

    def __init__(
        self,
        persist_dir: str,
        collection_name: str = _COLLECTION_NAME,
    ) -> None:
        _require_deps()
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._embed_model: "HuggingFaceEmbedding | None" = None
        self._chroma_client: "chromadb.PersistentClient | None" = None

    def _get_embed_model(self) -> "HuggingFaceEmbedding":
        if self._embed_model is None:
            log.info("loading_pubmedbert_embeddings", model=PUBMED_BERT_MODEL)
            self._embed_model = HuggingFaceEmbedding(
                model_name=PUBMED_BERT_MODEL,
                embed_batch_size=32,
            )
        return self._embed_model

    def _get_chroma_client(self) -> "chromadb.PersistentClient":
        if self._chroma_client is None:
            self._chroma_client = chromadb.PersistentClient(path=self.persist_dir)
        return self._chroma_client

    def _make_vector_store(self) -> "ChromaVectorStore":
        collection = self._get_chroma_client().get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        return ChromaVectorStore(chroma_collection=collection)

    def build_index(self, documents: list["Document"]) -> "VectorStoreIndex":
        """Embed and store documents. Overwrites existing data in the collection."""
        vector_store = self._make_vector_store()
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        log.info("building_index", num_docs=len(documents))
        index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            embed_model=self._get_embed_model(),
            show_progress=True,
        )
        log.info("index_built", persist_dir=self.persist_dir)
        return index

    def load_index(self) -> "VectorStoreIndex":
        """Load an existing persisted index without re-embedding."""
        vector_store = self._make_vector_store()
        log.info("loading_index", persist_dir=self.persist_dir, collection=self.collection_name)
        return VectorStoreIndex.from_vector_store(
            vector_store=vector_store,
            embed_model=self._get_embed_model(),
        )

    @property
    def collection_count(self) -> int:
        """Number of chunks currently indexed."""
        try:
            col = self._get_chroma_client().get_collection(self.collection_name)
            return col.count()
        except Exception:
            return 0
