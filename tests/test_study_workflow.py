"""
Tests for the Study Pipeline.

Uses mocks for heavy dependencies (LlamaIndex, Agno, DeepSeek)
so the test suite runs without GPU or API keys.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resusbot.rag.enrichment import ClinicalEnricher
from resusbot.rag.retrieval import RetrievalResult, SourceNode
from resusbot.study.models import (
    Citation,
    ClinicalFramework,
    PedagogicalResponse,
    StudyMode,
)
from resusbot.study.prompts import (
    QUERY_CLASSIFIER_PROMPT,
    SYSTEM_PROMPTS,
)
from resusbot.telegram.study_formatters import format_pedagogical_response


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def sample_pedagogical_response() -> PedagogicalResponse:
    return PedagogicalResponse(
        topic="Sepsis",
        mode_used=StudyMode.STUDY_20_80,
        study_focus_20_80=[
            "Early recognition via qSOFA ≥2",
            "1-hour bundle: cultures + antibiotics + lactate + fluids",
            "Vasopressor target: MAP ≥65 mmHg",
        ],
        why_it_matters="Sepsis kills 1 in 5 patients. One-hour delays worsen mortality.",
        feynman_explanation=(
            "Think of sepsis as the body overreacting to infection. "
            "The immune system goes haywire, vessels dilate, organs lose perfusion. "
            "Your job: find the infection, kill it fast, and support the failing circulation."
        ),
        clinical_framework=ClinicalFramework(
            recognition="Suspected infection + qSOFA ≥2 or SOFA change ≥2",
            pathophysiology=(
                "Pathogen triggers systemic immune activation → vasodilation → "
                "distributive shock → mitochondrial dysfunction → multi-organ failure."
            ),
            initial_management="Cultures → antibiotics (within 1h) → 30 mL/kg crystalloid → vasopressors if MAP <65",
            decision_points=[
                "Fluid responsive? → continue resuscitation",
                "MAP still <65 after 2L? → start norepinephrine",
                "Source identified? → source control within 6-12h",
            ],
        ),
        first_hour_actions=[
            "Blood cultures ×2 before antibiotics",
            "Broad-spectrum antibiotics ASAP",
            "Lactate measurement",
            "30 mL/kg IV crystalloid if hypoperfusion",
            "Vasopressors if MAP <65 despite fluids",
        ],
        common_errors=[
            "Delaying antibiotics to wait for cultures",
            "Over-resuscitating with fluids after initial bolus",
            "Missing occult sepsis in elderly or immunocompromised",
        ],
        socratic_questions=[
            "A 70yo with pneumonia, BP 85/50, RR 24, confused. What do you do in the first 10 minutes?",
            "Why is norepinephrine preferred over dopamine in septic shock?",
            "When should you stop fluid resuscitation?",
        ],
        high_yield_takeaways=[
            "qSOFA ≥2 = red flag for sepsis outside ICU",
            "Antibiotics within 1h reduces mortality",
            "Norepinephrine is first-line vasopressor",
            "Source control is as important as antibiotics",
        ],
        citations=[
            Citation(
                source="Rosen's Emergency Medicine",
                section="Chapter 130: Sepsis",
                page="1680-1695",
                snippet="Early recognition and the 1-hour bundle are the cornerstones of sepsis management.",
            )
        ],
        external_update_notes=[],
        uncertainties="Optimal fluid resuscitation volume remains debated (SMART trial, FEAST).",
        next_study_step="Septic shock vasopressors and steroid use",
    )


@pytest.fixture()
def sample_retrieval_result() -> RetrievalResult:
    return RetrievalResult(
        answer="Sepsis is defined by life-threatening organ dysfunction caused by dysregulated host response to infection.",
        source_nodes=[
            SourceNode(
                source="Rosen's Emergency Medicine",
                section="Chapter 130",
                page="1680",
                snippet="Sepsis is characterized by organ dysfunction...",
                score=0.92,
            ),
            SourceNode(
                source="Surviving Sepsis Campaign 2021",
                section="Definitions",
                page="3",
                snippet="Septic shock is a subset of sepsis...",
                score=0.87,
            ),
        ],
    )


# ── ClinicalEnricher tests ────────────────────────────────────────────────────

class TestClinicalEnricher:
    def test_keyword_fallback_sepsis(self) -> None:
        enricher = ClinicalEnricher()
        result = enricher._enrich_keywords(
            "Patient with suspected sepsis, bacteremia, give antibiotics immediately"
        )
        assert "sepsis" in result["clinical_categories"]
        assert result["source"] == "keyword_fallback"

    def test_keyword_fallback_airway(self) -> None:
        enricher = ClinicalEnricher()
        result = enricher._enrich_keywords("RSI with videolaryngoscopy for rapid sequence intubation")
        assert "airway" in result["clinical_categories"]

    def test_keyword_fallback_multiple_categories(self) -> None:
        enricher = ClinicalEnricher()
        result = enricher._enrich_keywords(
            "septic shock requiring vasopressor and urgent airway management"
        )
        cats = result["clinical_categories"]
        assert "sepsis" in cats
        assert "shock" in cats
        assert "airway" in cats

    def test_format_for_prompt_empty(self) -> None:
        enricher = ClinicalEnricher()
        result = enricher.format_for_prompt({"clinical_categories": [], "diseases": [], "drugs": [], "procedures": []})
        assert "No specific entities" in result

    def test_format_for_prompt_with_categories(self) -> None:
        enricher = ClinicalEnricher()
        result = enricher.format_for_prompt(
            {"clinical_categories": ["sepsis", "shock"], "diseases": [], "drugs": [], "procedures": []}
        )
        assert "sepsis" in result
        assert "shock" in result


# ── RetrievalResult tests ─────────────────────────────────────────────────────

class TestRetrievalResult:
    def test_citations_as_text(self, sample_retrieval_result: RetrievalResult) -> None:
        text = sample_retrieval_result.citations_as_text()
        assert "[1]" in text
        assert "Rosen" in text
        assert "score=0.92" in text

    def test_full_context_for_prompt(self, sample_retrieval_result: RetrievalResult) -> None:
        ctx = sample_retrieval_result.full_context_for_prompt()
        assert "CITATIONS:" in ctx
        assert "Surviving Sepsis" in ctx

    def test_empty_citations(self) -> None:
        result = RetrievalResult(answer="test", source_nodes=[])
        assert "No citations available" in result.citations_as_text()


# ── PedagogicalResponse schema tests ─────────────────────────────────────────

class TestPedagogicalResponseSchema:
    def test_valid_response(self, sample_pedagogical_response: PedagogicalResponse) -> None:
        assert sample_pedagogical_response.topic == "Sepsis"
        assert sample_pedagogical_response.mode_used == StudyMode.STUDY_20_80
        assert len(sample_pedagogical_response.study_focus_20_80) == 3
        assert len(sample_pedagogical_response.citations) == 1

    def test_external_update_notes_default_empty(
        self, sample_pedagogical_response: PedagogicalResponse
    ) -> None:
        assert sample_pedagogical_response.external_update_notes == []

    def test_uncertainties_default_empty(self) -> None:
        resp = PedagogicalResponse(
            topic="Test",
            mode_used=StudyMode.DEEP_DIVE,
            study_focus_20_80=["point 1"],
            why_it_matters="important",
            feynman_explanation="simple",
            clinical_framework=ClinicalFramework(
                recognition="X",
                pathophysiology="Y",
                initial_management="Z",
                decision_points=[],
            ),
            first_hour_actions=[],
            common_errors=[],
            socratic_questions=["Q?"],
            high_yield_takeaways=[],
            citations=[],
            next_study_step="next",
        )
        assert resp.uncertainties == ""
        assert resp.external_update_notes == []

    def test_study_mode_enum_values(self) -> None:
        assert StudyMode.STUDY_20_80.value == "20_80"
        assert StudyMode.DEEP_DIVE.value == "deep_dive"
        assert StudyMode.CLINICAL_CASE.value == "clinical_case"


# ── Prompts tests ─────────────────────────────────────────────────────────────

class TestPrompts:
    def test_all_modes_have_system_prompts(self) -> None:
        assert "20_80" in SYSTEM_PROMPTS
        assert "deep_dive" in SYSTEM_PROMPTS
        assert "clinical_case" in SYSTEM_PROMPTS

    def test_system_prompts_contain_core_principles(self) -> None:
        for mode, prompt in SYSTEM_PROMPTS.items():
            assert "20/80" in prompt, f"Mode {mode} missing 20/80"
            assert "Feynman" in prompt, f"Mode {mode} missing Feynman"

    def test_classifier_prompt_format(self) -> None:
        formatted = QUERY_CLASSIFIER_PROMPT.format(query="sepsis management")
        assert "sepsis management" in formatted
        assert "20_80" in formatted
        assert "deep_dive" in formatted


# ── Telegram formatters tests ─────────────────────────────────────────────────

class TestStudyFormatters:
    def test_format_returns_list_of_pages(
        self, sample_pedagogical_response: PedagogicalResponse
    ) -> None:
        pages = format_pedagogical_response(sample_pedagogical_response)
        assert isinstance(pages, list)
        assert len(pages) >= 3

    def test_pages_within_telegram_limit(
        self, sample_pedagogical_response: PedagogicalResponse
    ) -> None:
        pages = format_pedagogical_response(sample_pedagogical_response)
        for page in pages:
            assert len(page) <= 4000, f"Page too long: {len(page)}"

    def test_topic_appears_in_first_page(
        self, sample_pedagogical_response: PedagogicalResponse
    ) -> None:
        pages = format_pedagogical_response(sample_pedagogical_response)
        assert "Sepsis" in pages[0]

    def test_disclaimer_on_every_page(
        self, sample_pedagogical_response: PedagogicalResponse
    ) -> None:
        pages = format_pedagogical_response(sample_pedagogical_response)
        for page in pages:
            assert "julgamento clínico" in page

    def test_extra_page_for_updates(
        self, sample_pedagogical_response: PedagogicalResponse
    ) -> None:
        resp = sample_pedagogical_response.model_copy(
            update={"external_update_notes": ["SSC 2024: bundle updated"]}
        )
        pages = format_pedagogical_response(resp)
        assert len(pages) == 4
        assert "Atualizações Externas" in pages[3]

    def test_no_extra_page_without_updates(self) -> None:
        resp = PedagogicalResponse(
            topic="Test",
            mode_used=StudyMode.STUDY_20_80,
            study_focus_20_80=["A"],
            why_it_matters="B",
            feynman_explanation="C",
            clinical_framework=ClinicalFramework(
                recognition="D", pathophysiology="E", initial_management="F", decision_points=[]
            ),
            first_hour_actions=[],
            common_errors=[],
            socratic_questions=["G?"],
            high_yield_takeaways=[],
            citations=[],
            next_study_step="",
            uncertainties="",
            external_update_notes=[],
        )
        pages = format_pedagogical_response(resp)
        assert len(pages) == 3


# ── StudyService graceful degradation ─────────────────────────────────────────

class TestStudyServiceDegradation:
    @pytest.mark.asyncio
    async def test_missing_deepseek_key(self) -> None:
        from resusbot.study.service import StudyService

        svc = StudyService()
        with patch("resusbot.study.service.settings") as mock_settings:
            mock_settings.deepseek_api_key = ""
            result = await svc.handle(query="sepsis", telegram_id=12345)
        assert result["error"] == "missing_config"

    @pytest.mark.asyncio
    async def test_missing_rag_config(self) -> None:
        from resusbot.study.service import StudyService

        svc = StudyService()
        with patch("resusbot.study.service.settings") as mock_settings:
            mock_settings.deepseek_api_key = "fake-key"
            mock_settings.rag_corpus_dir = ""
            mock_settings.rag_persist_dir = ""
            result = await svc.handle(query="sepsis", telegram_id=12345)
        assert result["error"] == "rag_not_ready"
