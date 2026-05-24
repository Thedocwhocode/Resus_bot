"""Pydantic schemas for the pedagogical response of the Study Pipeline."""

from enum import Enum

from pydantic import BaseModel, Field


class StudyMode(str, Enum):
    STUDY_20_80 = "20_80"
    DEEP_DIVE = "deep_dive"
    CLINICAL_CASE = "clinical_case"


class Citation(BaseModel):
    source: str = Field(description="Book or article name")
    section: str = Field(description="Chapter or section title")
    page: str = Field(description="Page number or range (e.g. '342-345')")
    snippet: str = Field(description="Relevant excerpt, max 150 chars")


class ClinicalFramework(BaseModel):
    recognition: str = Field(description="How to identify this condition at the bedside")
    pathophysiology: str = Field(description="Key mechanism in 2-3 sentences")
    initial_management: str = Field(description="First-hour interventions in order of priority")
    decision_points: list[str] = Field(
        description="Critical branch decisions with consequence of each path"
    )


class PedagogicalResponse(BaseModel):
    """Structured output from the Study Workflow — one full teaching session."""

    topic: str = Field(description="The main medical topic addressed")
    mode_used: StudyMode = Field(description="Which study mode was applied")

    study_focus_20_80: list[str] = Field(
        description="Top 3-5 highest-yield points that cover 80 percent of clinical scenarios"
    )
    why_it_matters: str = Field(
        description="Clinical relevance hook in 1-2 sentences — why an EM physician must master this"
    )
    feynman_explanation: str = Field(
        description=(
            "Simple but precise explanation as if teaching a smart but insecure intern. "
            "No jargon without definition."
        )
    )
    clinical_framework: ClinicalFramework = Field(
        description="Structured recognition-to-management framework"
    )
    first_hour_actions: list[str] = Field(
        description="Time-critical ordered interventions for the first hour"
    )
    common_errors: list[str] = Field(
        description="Pitfalls, red flags, contraindications, and dangerous mistakes"
    )
    socratic_questions: list[str] = Field(
        description="2-5 questions that force active recall and clinical reasoning"
    )
    high_yield_takeaways: list[str] = Field(
        description="Board-style key points — what you must not forget"
    )
    citations: list[Citation] = Field(
        description="Source references with specific section and page"
    )
    external_update_notes: list[str] = Field(
        default_factory=list,
        description="Recent guideline updates from external search (deep mode only)",
    )
    uncertainties: str = Field(
        default="",
        description="Areas of clinical controversy or weak evidence",
    )
    next_study_step: str = Field(
        description="Recommended next topic to study for logical progression"
    )
