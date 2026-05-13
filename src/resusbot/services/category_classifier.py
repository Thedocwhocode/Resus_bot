"""
Classificador de categorias para artigos.
Primeira passagem: heurística por palavras-chave.
Fallback: categoria "other" (id=9).
"""
import re
from typing import Any

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "resuscitation": [
        "resuscitation", "ressuscita", "cpr", "rcp", "cardiac arrest", "parada cardíaca",
        "parada cardiaca", "rosc", "post-cardiac", "pós-pcr", "aesp", "pea",
    ],
    "sepsis": [
        "sepsis", "sepse", "septic shock", "choque séptico", "bacteremia", "sofa",
        "qsofa", "rox", "organ dysfunction", "disfunção orgânica",
    ],
    "cardiology": [
        "cardio", "cardiac", "myocardial", "infarto", "heart failure", "insuficiência cardíaca",
        "ecg", "stemi", "nstemi", "arrhythmia", "arritmia", "atrial fibrillation", "fibrilação",
        "troponin", "troponina",
    ],
    "trauma": [
        "trauma", "hemorrhage", "hemorragia", "damage control", "permissive hypotension",
        "massive transfusion", "transfusão maciça", "tbi", "traumatic brain",
    ],
    "neuro": [
        "neurolog", "neurocritical", "stroke", "avc", "seizure", "convulsão", "icu neuroprot",
        "targeted temperature", "hypothermia", "hipotermia",
    ],
    "pediatrics": [
        "pediatric", "pediátri", "neonatal", "neonato", "infant", "lactente", "child",
        "criança", "pals",
    ],
    "airway": [
        "airway", "via aérea", "intubation", "intubação", "rsi", "laryngoscopy",
        "video laryngoscopy", "mechanical ventilation", "ventilação mecânica",
        "extubation", "extubação",
    ],
    "toxicology": [
        "toxicolog", "overdose", "intoxica", "antidote", "antídoto", "poisoning",
        "envenenamento",
    ],
}

_compiled: dict[str, re.Pattern[str]] = {
    slug: re.compile("|".join(kws), re.IGNORECASE)
    for slug, kws in _CATEGORY_KEYWORDS.items()
}

_CATEGORY_SLUG_TO_ID: dict[str, int] = {
    "resuscitation": 1,
    "sepsis": 2,
    "cardiology": 3,
    "trauma": 4,
    "neuro": 5,
    "pediatrics": 6,
    "airway": 7,
    "toxicology": 8,
    "other": 9,
}


def classify_article(article_data: dict[str, Any]) -> int:
    """
    Retorna o category_id com base em título + journal do artigo.
    Padrão: "other" (id=9).
    """
    text = " ".join(filter(None, [
        article_data.get("title", ""),
        article_data.get("journal", ""),
        str(article_data.get("metadata_json", "")),
    ]))

    for slug, pattern in _compiled.items():
        if pattern.search(text):
            return _CATEGORY_SLUG_TO_ID[slug]

    return _CATEGORY_SLUG_TO_ID["other"]
