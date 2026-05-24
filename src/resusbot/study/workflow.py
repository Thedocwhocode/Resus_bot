"""
Agno Level-3 Study Workflow for emergency medicine pedagogy.

Pipeline:
  IntentClassifierAgent (Groq — fast)
      ↓ mode + topic + rewritten query
  RAGRetrieverAgent (Groq — uses RAGRetrievalTool)
      ↓ retrieved context with citations
  ExternalSearchAgent (Groq — only in deep_dive mode, uses OrioSearch)
      ↓ recent guideline updates
  PedagogicalSynthesizerAgent (DeepSeek — structured PedagogicalResponse)

The workflow is driven by the StudyWorkflow.run() method and yields
RunResponse objects so the caller can show intermediate progress.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import structlog
from agno.agent import Agent
from agno.models.deepseek import DeepSeek
from agno.models.groq import Groq
from agno.tools.reasoning import ReasoningTools
from agno.workflow import RunResponse, Workflow

from resusbot.config import settings
from resusbot.rag.enrichment import ClinicalEnricher
from resusbot.rag.retrieval import MedicalRAGRetriever
from resusbot.study.models import PedagogicalResponse, StudyMode
from resusbot.study.prompts import (
    QUERY_CLASSIFIER_PROMPT,
    QUERY_REWRITER_PROMPT,
    SYSTEM_PROMPTS,
    USER_PROMPT_TEMPLATE,
    EXTERNAL_SECTION_TEMPLATE,
)
from resusbot.tools.orio_search import OrioSearchTool
from resusbot.tools.rag_tool import RAGRetrievalTool

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_GROQ_FAST = "llama-3.3-70b-versatile"
_DEEPSEEK_MODEL = "deepseek-chat"  # deepseek-chat has reliable JSON structured output


def _groq(temperature: float = 0.1) -> Groq:
    return Groq(id=_GROQ_FAST, api_key=settings.groq_api_key, temperature=temperature)


def _deepseek() -> DeepSeek:
    return DeepSeek(id=_DEEPSEEK_MODEL, api_key=settings.deepseek_api_key)


class StudyWorkflow(Workflow):
    """
    Agno Level-3 workflow orchestrating the full educational RAG pipeline.

    Level-3 characteristics:
    - Multi-agent specialization (4 agents with distinct roles)
    - Stateful context passing between steps
    - Structured Pydantic output (PedagogicalResponse)
    - Tool integration (RAGRetrievalTool + OrioSearchTool)
    - Mode-conditional branching (20_80 / deep_dive / clinical_case)
    """

    intent_classifier: Agent
    rag_retriever: Agent
    external_searcher: Agent
    synthesizer: Agent
    _enricher: ClinicalEnricher

    def __init__(self, retriever: MedicalRAGRetriever) -> None:
        rag_tool = RAGRetrievalTool(retriever)

        intent_classifier = Agent(
            name="IntentClassifierAgent",
            model=_groq(temperature=0.0),
            tools=[ReasoningTools(add_instructions=True)],
            role="Classify the student's intent and select the optimal study mode.",
            instructions=[
                "You receive a medical study request. Identify the topic and select the mode.",
                "Return ONLY valid JSON with keys: mode, topic, reasoning.",
                "Never add prose before or after the JSON block.",
            ],
        )

        rag_retriever = Agent(
            name="RAGRetrieverAgent",
            model=_groq(temperature=0.1),
            tools=[rag_tool],
            role="Retrieve relevant clinical passages from the emergency medicine corpus.",
            instructions=[
                "Use retrieve_medical_context with the rewritten query.",
                "Return the full retrieval result unchanged — do not summarize or rephrase.",
                "Always include the citation metadata in your response.",
            ],
        )

        external_searcher = Agent(
            name="ExternalSearchAgent",
            model=_groq(temperature=0.1),
            tools=[OrioSearchTool()],
            role="Find recent guideline updates or new evidence from the web (deep mode only).",
            instructions=[
                "Search for the latest guidelines, systematic reviews, or RCTs on the topic.",
                "Focus on PubMed, UpToDate, ACEP, EMRA, LITFL, and major journals.",
                "Return a concise list of key updates: what changed and when.",
                "Limit to 3-5 external findings. Label each with its source URL.",
            ],
        )

        synthesizer = Agent(
            name="PedagogicalSynthesizerAgent",
            model=_deepseek(),
            response_model=PedagogicalResponse,
            role="Synthesize a complete pedagogical teaching session from retrieved context.",
            instructions=[
                "You are given: retrieved corpus context, clinical enrichment, and optional external notes.",
                "Apply the assigned study mode's pedagogical strategy.",
                "Every clinical claim must cite a source from the retrieved context.",
                "Produce a complete PedagogicalResponse following the Pydantic schema exactly.",
                "Do NOT hallucinate information not present in the provided context.",
            ],
        )

        super().__init__(
            intent_classifier=intent_classifier,
            rag_retriever=rag_retriever,
            external_searcher=external_searcher,
            synthesizer=synthesizer,
        )
        self._enricher = ClinicalEnricher()

    def run(  # type: ignore[override]
        self,
        user_message: str,
        mode_override: str | None = None,
    ) -> Iterator[RunResponse]:
        log.info("study_workflow_start", message_length=len(user_message))

        # ── Step 1: Classify intent ──────────────────────────────────────────
        yield RunResponse(content="Classificando sua pergunta...")

        classifier_prompt = QUERY_CLASSIFIER_PROMPT.format(query=user_message)
        classification_raw = self.intent_classifier.run(classifier_prompt)
        classification = _parse_json_safe(
            classification_raw.content or "{}",
            defaults={"mode": "20_80", "topic": user_message, "reasoning": ""},
        )

        mode_str = mode_override or classification.get("mode", "20_80")
        topic = classification.get("topic", user_message)

        try:
            mode = StudyMode(mode_str)
        except ValueError:
            mode = StudyMode.STUDY_20_80

        log.info("study_mode_selected", mode=mode.value, topic=topic)

        # ── Step 2: Rewrite query for optimal retrieval ──────────────────────
        rewriter_prompt = QUERY_REWRITER_PROMPT.format(query=user_message, topic=topic)
        rewritten_raw = self.intent_classifier.run(rewriter_prompt)
        rewritten_query = (rewritten_raw.content or user_message).strip()

        yield RunResponse(content=f"Buscando no corpus: *{topic}*...")

        # ── Step 3: RAG retrieval ────────────────────────────────────────────
        rag_context_raw = self.rag_retriever.run(
            f"Retrieve clinical knowledge about: {rewritten_query}"
        )
        rag_context = rag_context_raw.content or "No context retrieved."

        # ── Step 4: Clinical enrichment ─────────────────────────────────────
        enrichment = self._enricher.enrich(rag_context[:2000])
        enrichment_text = self._enricher.format_for_prompt(enrichment)

        # ── Step 5: External search (deep mode only) ─────────────────────────
        external_section = ""
        if mode == StudyMode.DEEP_DIVE:
            yield RunResponse(content="Buscando atualizações externas (modo profundo)...")
            ext_raw = self.external_searcher.run(
                f"Find latest guidelines and evidence for: {topic} in emergency medicine"
            )
            ext_content = ext_raw.content or ""
            if ext_content.strip():
                external_section = EXTERNAL_SECTION_TEMPLATE.format(
                    external_results=ext_content
                )

        # ── Step 6: Pedagogical synthesis ────────────────────────────────────
        yield RunResponse(content="Preparando resposta pedagógica...")

        system_prompt = SYSTEM_PROMPTS[mode.value]
        user_prompt = USER_PROMPT_TEMPLATE.format(
            context=rag_context,
            query=user_message,
            enrichment=enrichment_text,
            external_section=external_section,
        )

        self.synthesizer.system_prompt = system_prompt
        synthesis_result = self.synthesizer.run(user_prompt)

        if isinstance(synthesis_result.content, PedagogicalResponse):
            response = synthesis_result.content
        elif isinstance(synthesis_result.content, dict):
            response = PedagogicalResponse(**synthesis_result.content)
        else:
            response = _fallback_response(user_message, mode, rag_context)

        log.info(
            "study_workflow_done",
            topic=response.topic,
            mode=response.mode_used,
            citations=len(response.citations),
        )
        yield RunResponse(content=response)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json_safe(text: str, defaults: dict) -> dict:
    """Extract the first JSON object from text; return defaults on failure."""
    text = text.strip()
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return defaults
    try:
        return json.loads(text[start:end])
    except json.JSONDecodeError:
        log.warning("json_parse_failed", snippet=text[:100])
        return defaults


def _fallback_response(query: str, mode: StudyMode, context: str) -> PedagogicalResponse:
    """Minimal valid response when the synthesizer returns unexpected output."""
    from resusbot.study.models import Citation, ClinicalFramework

    return PedagogicalResponse(
        topic=query,
        mode_used=mode,
        study_focus_20_80=["Resposta estruturada indisponível — revise o contexto recuperado."],
        why_it_matters="Tema relevante em medicina de emergência.",
        feynman_explanation=context[:500] if context else "Contexto não disponível.",
        clinical_framework=ClinicalFramework(
            recognition="Ver contexto recuperado.",
            pathophysiology="Ver contexto recuperado.",
            initial_management="Ver contexto recuperado.",
            decision_points=[],
        ),
        first_hour_actions=[],
        common_errors=[],
        socratic_questions=["O que você faria primeiro neste cenário clínico?"],
        high_yield_takeaways=[],
        citations=[],
        next_study_step="Reformule sua pergunta para uma nova busca.",
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

_workflow: StudyWorkflow | None = None


def get_study_workflow(retriever: MedicalRAGRetriever) -> StudyWorkflow:
    global _workflow
    if _workflow is None:
        _workflow = StudyWorkflow(retriever=retriever)
    return _workflow
