"""
Docling-based PDF ingestion for the emergency medicine corpus.

Converts PDFs (textbooks, guidelines) into structured LlamaIndex Documents
preserving page numbers, section headings, and table/figure metadata.
"""

from pathlib import Path

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Lazy imports so startup is not blocked when RAG is not configured
try:
    from docling.chunking import HybridChunker
    from docling.document_converter import DocumentConverter
    from llama_index.core.schema import Document

    _DOCLING_AVAILABLE = True
except ImportError:
    _DOCLING_AVAILABLE = False
    log.warning("docling_not_installed", hint="pip install docling llama-index-core")


def _require_docling() -> None:
    if not _DOCLING_AVAILABLE:
        raise RuntimeError(
            "docling and llama-index-core are required. "
            "Install with: pip install 'resusbot[rag]'"
        )


class MedicalCorpusIngester:
    """
    Ingest one or many PDFs from a corpus directory.

    Each PDF is converted by Docling (preserving tables, formulas, headings)
    and split into chunks ready for embedding.
    """

    # PubMedBERT tokenizer for chunk size estimation
    _TOKENIZER = "pritamdeka/PubMedBERT-mnli-snli-scinli-scitail-mednli-stsb"
    _MAX_TOKENS = 512

    def __init__(self, corpus_dir: str | Path) -> None:
        _require_docling()
        self.corpus_dir = Path(corpus_dir)
        self._converter: "DocumentConverter | None" = None
        self._chunker: "HybridChunker | None" = None

    def _get_converter(self) -> "DocumentConverter":
        if self._converter is None:
            self._converter = DocumentConverter()
        return self._converter

    def _get_chunker(self) -> "HybridChunker":
        if self._chunker is None:
            self._chunker = HybridChunker(
                tokenizer=self._TOKENIZER,
                max_tokens=self._MAX_TOKENS,
                merge_peers=True,
            )
        return self._chunker

    def ingest_pdf(self, pdf_path: Path) -> list["Document"]:
        """Convert a single PDF into a list of LlamaIndex Documents."""
        log.info("ingesting_pdf", path=str(pdf_path))
        try:
            result = self._get_converter().convert(str(pdf_path))
        except Exception:
            log.exception("pdf_conversion_failed", path=str(pdf_path))
            return []

        chunks = list(self._get_chunker().chunk(dl_doc=result.document))
        documents: list["Document"] = []

        for chunk in chunks:
            meta = chunk.meta
            page_no: int | str = "?"
            section_title = ""

            if hasattr(meta, "doc_items") and meta.doc_items:
                first_item = meta.doc_items[0]
                if hasattr(first_item, "prov") and first_item.prov:
                    page_no = first_item.prov[0].page_no

            if hasattr(meta, "headings") and meta.headings:
                section_title = meta.headings[0]

            documents.append(
                Document(
                    text=chunk.text,
                    metadata={
                        "source": pdf_path.name,
                        "source_path": str(pdf_path),
                        "page": str(page_no),
                        "section": section_title,
                        "chunk_type": getattr(chunk, "label", "text"),
                    },
                )
            )

        log.info(
            "pdf_ingested",
            path=pdf_path.name,
            chunks=len(documents),
        )
        return documents

    def ingest_corpus(self) -> list["Document"]:
        """Ingest all PDFs found recursively in corpus_dir."""
        pdfs = list(self.corpus_dir.glob("**/*.pdf"))
        if not pdfs:
            log.warning("no_pdfs_found", corpus_dir=str(self.corpus_dir))
            return []

        all_docs: list["Document"] = []
        for pdf in pdfs:
            all_docs.extend(self.ingest_pdf(pdf))

        log.info("corpus_ingested", total_chunks=len(all_docs), pdfs=len(pdfs))
        return all_docs
