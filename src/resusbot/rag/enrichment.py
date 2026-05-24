"""
Clinical entity enrichment for retrieved chunks.

Uses OpenMed NER when available; falls back to a keyword-map approach
so the pipeline degrades gracefully without the optional dependency.
"""

from __future__ import annotations

from typing import Any

import structlog

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Emergency medicine keyword taxonomy for the fallback enricher
_CLINICAL_KEYWORD_MAP: dict[str, list[str]] = {
    "airway": [
        "airway", "intubation", "rsi", "rapid sequence", "cricothyrotomy",
        "laryngoscopy", "videolaryngoscopy", "ventilation", "hypoxia", "apnea",
    ],
    "shock": [
        "shock", "hypotension", "vasopressor", "norepinephrine", "epinephrine",
        "dopamine", "fluid resuscitation", "crystalloid", "colloid", "map",
    ],
    "sepsis": [
        "sepsis", "septic", "bacteremia", "infection", "antibiotic", "qsofa",
        "sofa", "bundle", "procalcitonin", "blood culture",
    ],
    "cardiac": [
        "cardiac arrest", "cpr", "defibrillation", "arrhythmia", "amiodarone",
        "tachycardia", "bradycardia", "pulseless", "rosc", "acls", "aed",
    ],
    "trauma": [
        "trauma", "hemorrhage", "massive transfusion", "damage control",
        "penetrating", "blunt", "pneumothorax", "hemothorax", "tension",
    ],
    "neuro": [
        "stroke", "seizure", "coma", "gcs", "intracranial", "tpa",
        "hemorrhagic", "ischemic", "status epilepticus", "herniation",
    ],
    "toxicology": [
        "poisoning", "overdose", "antidote", "naloxone", "activated charcoal",
        "toxidrome", "acetaminophen", "n-acetylcysteine", "opioid",
    ],
    "obstetric": [
        "pregnancy", "eclampsia", "preeclampsia", "magnesium", "obstetric",
        "perimortem", "cesarean", "placenta", "abruption",
    ],
    "pediatric": [
        "pediatric", "neonatal", "child", "infant", "weight-based", "broselow",
        "febrile seizure", "bronchiolitis", "croup",
    ],
}


class ClinicalEnricher:
    """
    Enrich text with clinical metadata.

    Tries to use OpenMed biomedical NER first; if the library is absent or
    the model fails, falls back to a deterministic keyword-matching approach.
    """

    def __init__(self) -> None:
        self._openmed_model: Any = None
        self._openmed_tried = False

    def _try_load_openmed(self) -> bool:
        if self._openmed_tried:
            return self._openmed_model is not None
        self._openmed_tried = True
        try:
            from openmed.ner import BiomedNER  # type: ignore[import]

            self._openmed_model = BiomedNER()
            log.info("openmed_ner_loaded")
            return True
        except ImportError:
            log.info("openmed_not_available", using="keyword_fallback")
            return False
        except Exception:
            log.warning("openmed_load_error", using="keyword_fallback")
            return False

    def enrich(self, text: str) -> dict[str, Any]:
        """Return a dict of clinical entities found in text."""
        if self._try_load_openmed():
            return self._enrich_openmed(text)
        return self._enrich_keywords(text)

    def enrich_chunks(self, chunks: list[str]) -> list[dict[str, Any]]:
        return [self.enrich(c) for c in chunks]

    def _enrich_openmed(self, text: str) -> dict[str, Any]:
        try:
            entities = self._openmed_model.extract(text)
            return {
                "diseases": [e["text"] for e in entities if e.get("label") == "DISEASE"],
                "drugs": [e["text"] for e in entities if e.get("label") == "DRUG"],
                "procedures": [e["text"] for e in entities if e.get("label") == "PROCEDURE"],
                "clinical_categories": list(
                    {e.get("category", "") for e in entities if e.get("category")}
                ),
                "source": "openmed",
            }
        except Exception:
            log.warning("openmed_extract_error", fallback="keywords")
            return self._enrich_keywords(text)

    def _enrich_keywords(self, text: str) -> dict[str, Any]:
        lower = text.lower()
        categories = [
            cat for cat, kws in _CLINICAL_KEYWORD_MAP.items() if any(kw in lower for kw in kws)
        ]
        return {
            "diseases": [],
            "drugs": [],
            "procedures": [],
            "clinical_categories": categories,
            "source": "keyword_fallback",
        }

    def format_for_prompt(self, enrichment: dict[str, Any]) -> str:
        """Serialize enrichment metadata as a compact string for prompt injection."""
        parts: list[str] = []
        if enrichment.get("clinical_categories"):
            parts.append(f"Categories: {', '.join(enrichment['clinical_categories'])}")
        if enrichment.get("diseases"):
            parts.append(f"Diseases: {', '.join(enrichment['diseases'][:5])}")
        if enrichment.get("drugs"):
            parts.append(f"Drugs: {', '.join(enrichment['drugs'][:5])}")
        if enrichment.get("procedures"):
            parts.append(f"Procedures: {', '.join(enrichment['procedures'][:5])}")
        return "; ".join(parts) if parts else "No specific entities detected."
