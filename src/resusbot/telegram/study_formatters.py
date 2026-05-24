"""
Telegram MarkdownV2 formatters for PedagogicalResponse.

Splits the response across multiple pages (4000 chars max each)
to handle Telegram's message size limit gracefully.
"""

from __future__ import annotations

from resusbot.security.sanitize import escape_markdown_v2
from resusbot.study.models import PedagogicalResponse, StudyMode

_MAX_PAGE = 3800
_DISCLAIMER = "\n\n_ℹ️ Conteúdo educacional\\. Não substitui julgamento clínico\\._"

_MODE_EMOJI = {
    StudyMode.STUDY_20_80: "🎯",
    StudyMode.DEEP_DIVE: "🔬",
    StudyMode.CLINICAL_CASE: "🏥",
}

_MODE_LABEL = {
    StudyMode.STUDY_20_80: "Revisão 20/80",
    StudyMode.DEEP_DIVE: "Deep Dive",
    StudyMode.CLINICAL_CASE: "Caso Clínico",
}


def _e(text: str) -> str:
    return escape_markdown_v2(text)


def _bullet_list(items: list[str], emoji: str = "•") -> str:
    return "\n".join(f"{emoji} {_e(item)}" for item in items if item)


def _section(title: str, content: str, emoji: str = "") -> str:
    prefix = f"{emoji} " if emoji else ""
    return f"*{prefix}{_e(title)}*\n{content}\n"


def format_pedagogical_response(resp: PedagogicalResponse) -> list[str]:
    """
    Build a list of MarkdownV2 pages from a PedagogicalResponse.

    Page 1: Header + 20/80 focus + Feynman explanation
    Page 2: Clinical framework + first-hour actions + errors
    Page 3: Socratic questions + takeaways + citations
    Page 4 (optional): External updates + uncertainties + next step
    """
    mode_emoji = _MODE_EMOJI.get(resp.mode_used, "📚")
    mode_label = _MODE_LABEL.get(resp.mode_used, resp.mode_used.value)

    # ── Page 1: Hook + 20/80 + Feynman ───────────────────────────────────────
    p1 = (
        f"{mode_emoji} *{_e(resp.topic)}* \\| {_e(mode_label)}\n"
        f"_{_e(resp.why_it_matters)}_\n\n"
    )
    p1 += _section(
        "Foco 20/80 — o que mais importa",
        _bullet_list(resp.study_focus_20_80, "⚡"),
        "🎯",
    )
    p1 += _section("Explicação Feynman", _e(resp.feynman_explanation), "🧠")
    p1 += _DISCLAIMER

    # ── Page 2: Clinical framework ────────────────────────────────────────────
    cf = resp.clinical_framework
    p2 = f"{mode_emoji} *{_e(resp.topic)}* — Estrutura Clínica\n\n"
    p2 += _section("Reconhecimento", _e(cf.recognition), "🔍")
    p2 += _section("Fisiopatologia", _e(cf.pathophysiology), "⚙️")
    p2 += _section("Conduta Inicial", _e(cf.initial_management), "🏥")
    if cf.decision_points:
        p2 += _section(
            "Pontos de Decisão",
            _bullet_list(cf.decision_points, "↳"),
            "🔀",
        )
    if resp.first_hour_actions:
        numbered = "\n".join(
            f"{i}\\. {_e(a)}" for i, a in enumerate(resp.first_hour_actions, 1)
        )
        p2 += _section("Primeira Hora — ações críticas", numbered, "⏱️")
    if resp.common_errors:
        p2 += _section("Erros Comuns e Red Flags", _bullet_list(resp.common_errors, "❌"), "⚠️")
    p2 += _DISCLAIMER

    # ── Page 3: Socratic + Takeaways + Citations ──────────────────────────────
    p3 = f"{mode_emoji} *{_e(resp.topic)}* — Estudo Ativo\n\n"
    if resp.socratic_questions:
        questions = "\n".join(
            f"{i}\\. {_e(q)}" for i, q in enumerate(resp.socratic_questions, 1)
        )
        p3 += _section("Perguntas Socráticas", questions, "❓")
    if resp.high_yield_takeaways:
        p3 += _section(
            "High-Yield — não esqueça",
            _bullet_list(resp.high_yield_takeaways, "⭐"),
            "📌",
        )
    if resp.citations:
        cit_lines = []
        for i, c in enumerate(resp.citations[:5], 1):
            line = f"\\[{i}\\] {_e(c.source)} | {_e(c.section)} | p\\.{_e(c.page)}"
            if c.snippet:
                line += f"\n    _{_e(c.snippet[:100])}_"
            cit_lines.append(line)
        p3 += _section("Fontes", "\n".join(cit_lines), "📚")
    p3 += _DISCLAIMER

    pages = [p1, p2, p3]

    # ── Page 4 (optional): Updates + uncertainties + next step ───────────────
    has_extra = resp.external_update_notes or resp.uncertainties or resp.next_study_step
    if has_extra:
        p4 = f"{mode_emoji} *{_e(resp.topic)}* — Atualizações e Próximos Passos\n\n"
        if resp.external_update_notes:
            p4 += _section(
                "Atualizações Externas",
                _bullet_list(resp.external_update_notes, "🔗"),
                "🌐",
            )
        if resp.uncertainties:
            p4 += _section("Incertezas / Controvérsias", _e(resp.uncertainties), "🔬")
        if resp.next_study_step:
            p4 += _section("Próximo Passo de Estudo", _e(resp.next_study_step), "➡️")
        p4 += _DISCLAIMER
        pages.append(p4)

    # Enforce page size limit
    return [p[:_MAX_PAGE] for p in pages]
