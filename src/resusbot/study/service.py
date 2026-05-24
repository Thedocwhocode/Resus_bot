"""
Study Service — orchestrates the educational RAG pipeline end-to-end.

Responsible for:
  - Lazy initialization of the RAG index (MedicalIndexer)
  - Ingesting corpus PDFs on first run (MedicalCorpusIngester)
  - Running the StudyWorkflow
  - Formatting the PedagogicalResponse for Telegram

The service is designed to degrade gracefully:
  - If RAG dependencies are missing → returns an explanatory error message
  - If the corpus dir is empty → returns a warning with setup instructions
  - If the synthesizer fails → returns the fallback minimal response
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog

from resusbot.config import settings
from resusbot.study.models import PedagogicalResponse, StudyMode

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_SETUP_MSG = (
    "O pipeline de estudo ainda não está configurado.\n\n"
    "Para ativar:\n"
    "1. Defina RAG_CORPUS_DIR com o caminho para seus PDFs médicos\n"
    "2. Defina RAG_PERSIST_DIR para armazenar os embeddings\n"
    "3. Defina DEEPSEEK_API_KEY\n"
    "4. Instale: pip install 'resusbot[rag]'\n"
    "5. Reinicie o bot"
)


class StudyService:
    """High-level facade for the Study Pipeline used by Telegram handlers."""

    def __init__(self) -> None:
        self._retriever: object | None = None
        self._ready = False
        self._init_error: str | None = None

    def _initialize_rag(self) -> bool:
        """Attempt one-time RAG initialization. Returns True if successful."""
        if self._ready:
            return True
        if self._init_error:
            return False

        corpus_dir = settings.rag_corpus_dir
        persist_dir = settings.rag_persist_dir

        if not corpus_dir or not persist_dir:
            self._init_error = _SETUP_MSG
            log.warning("study_rag_not_configured")
            return False

        try:
            from resusbot.rag.indexing import MedicalIndexer
            from resusbot.rag.retrieval import MedicalRAGRetriever

            indexer = MedicalIndexer(persist_dir=persist_dir)

            if indexer.collection_count == 0:
                # First run: ingest PDFs
                from resusbot.rag.ingestion import MedicalCorpusIngester

                log.info("study_rag_first_run_ingesting", corpus_dir=corpus_dir)
                ingester = MedicalCorpusIngester(corpus_dir=corpus_dir)
                docs = ingester.ingest_corpus()

                if not docs:
                    self._init_error = (
                        f"Nenhum PDF encontrado em {corpus_dir}. "
                        "Adicione os livros ao diretório e reinicie."
                    )
                    return False

                indexer.build_index(docs)

            index = indexer.load_index()
            self._retriever = MedicalRAGRetriever(index=index)
            self._ready = True
            log.info("study_rag_ready", chunks=indexer.collection_count)
            return True

        except ImportError as exc:
            self._init_error = (
                f"Dependências RAG ausentes: {exc}. "
                "Instale com: pip install 'resusbot[rag]'"
            )
            log.error("study_rag_import_error", error=str(exc))
            return False
        except Exception:
            self._init_error = "Erro ao inicializar o pipeline de estudo. Verifique os logs."
            log.exception("study_rag_init_error")
            return False

    async def handle(
        self,
        query: str,
        telegram_id: int,
        mode_override: str | None = None,
    ) -> dict:
        """
        Process a study request and return a dict with:
          - response: str or PedagogicalResponse
          - error: str | None
          - mode: str
        """
        if not settings.deepseek_api_key:
            return {
                "response": "DEEPSEEK_API_KEY não configurada. Configure e reinicie.",
                "error": "missing_config",
                "mode": "unknown",
            }

        loop = asyncio.get_event_loop()

        # RAG init is CPU-bound (model loading) — run in executor
        ready = await loop.run_in_executor(None, self._initialize_rag)
        if not ready:
            return {
                "response": self._init_error or _SETUP_MSG,
                "error": "rag_not_ready",
                "mode": "unknown",
            }

        from resusbot.rag.retrieval import MedicalRAGRetriever
        from resusbot.study.workflow import get_study_workflow

        retriever: MedicalRAGRetriever = self._retriever  # type: ignore[assignment]
        workflow = get_study_workflow(retriever)

        def _run_sync() -> PedagogicalResponse | str:
            last: object = None
            for resp in workflow.run(user_message=query, mode_override=mode_override):
                last = resp.content
            return last  # type: ignore[return-value]

        log.info("study_request", telegram_id=telegram_id, query_len=len(query))
        try:
            result = await loop.run_in_executor(None, _run_sync)
        except Exception:
            log.exception("study_workflow_error", telegram_id=telegram_id)
            return {
                "response": "Erro ao processar sua pergunta. Tente novamente.",
                "error": "workflow_error",
                "mode": mode_override or "20_80",
            }

        mode = "unknown"
        if isinstance(result, PedagogicalResponse):
            mode = result.mode_used.value

        return {
            "response": result,
            "error": None,
            "mode": mode,
        }


study_service = StudyService()
