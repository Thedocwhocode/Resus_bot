"""
WhatsApp message formatters — plain text with WhatsApp markdown.

WhatsApp markup differs from Telegram MarkdownV2:
  *text*   → bold
  _text_   → italic
  ~text~   → strikethrough
  ```text``` → monospace

No inline keyboards. Use emojis and numbered lists for navigation cues.
"""

from __future__ import annotations

from resusbot.study.models import PedagogicalResponse, StudyMode

_DISCLAIMER = (
    "\n\n_ℹ️ Conteúdo educacional. Não substitui julgamento clínico._"
)

_MODE_EMOJI: dict[StudyMode, str] = {
    StudyMode.STUDY_20_80: "🎯",
    StudyMode.DEEP_DIVE: "🔬",
    StudyMode.CLINICAL_CASE: "🏥",
}
_MODE_LABEL: dict[StudyMode, str] = {
    StudyMode.STUDY_20_80: "Revisão 20/80",
    StudyMode.DEEP_DIVE: "Deep Dive",
    StudyMode.CLINICAL_CASE: "Caso Clínico",
}


def _bold(text: str) -> str:
    return f"*{text}*"


def _italic(text: str) -> str:
    return f"_{text}_"


def _bullets(items: list[str], prefix: str = "•") -> str:
    return "\n".join(f"{prefix} {item}" for item in items if item)


def _section(title: str, body: str, emoji: str = "") -> str:
    header = _bold(f"{emoji} {title}" if emoji else title)
    return f"{header}\n{body}\n"


def format_research_response(text: str) -> str:
    """Format the research pipeline response for WhatsApp."""
    return f"{text}\n{_DISCLAIMER}"


def format_typing() -> str:
    return "🔍 Buscando, aguarde..."


def format_error(message: str) -> str:
    return f"⚠️ {message}"


def format_study_typing(topic: str, mode_label: str) -> str:
    return f"📚 {mode_label} — *{topic}*... Aguarde."


def format_pedagogical_response(resp: PedagogicalResponse) -> list[str]:
    """
    Format a PedagogicalResponse into 1-4 WhatsApp messages.

    Messages are split logically (not by char count) to keep each
    block coherent. Each message < 4096 chars.
    """
    emoji = _MODE_EMOJI.get(resp.mode_used, "📚")
    label = _MODE_LABEL.get(resp.mode_used, resp.mode_used.value)

    # ── Message 1: Hook + 20/80 + Feynman ────────────────────────────────────
    m1 = (
        f"{emoji} {_bold(resp.topic)} | {label}\n"
        f"{_italic(resp.why_it_matters)}\n\n"
    )
    m1 += _section("Foco 20/80 — o que mais importa", _bullets(resp.study_focus_20_80, "⚡"), "🎯")
    m1 += "\n" + _section("Explicação Feynman", resp.feynman_explanation, "🧠")
    m1 += _DISCLAIMER

    # ── Message 2: Clinical framework ─────────────────────────────────────────
    cf = resp.clinical_framework
    m2 = f"{emoji} {_bold(resp.topic)} — Estrutura Clínica\n\n"
    m2 += _section("Reconhecimento", cf.recognition, "🔍")
    m2 += "\n" + _section("Fisiopatologia", cf.pathophysiology, "⚙️")
    m2 += "\n" + _section("Conduta Inicial", cf.initial_management, "🏥")
    if cf.decision_points:
        m2 += "\n" + _section("Pontos de Decisão", _bullets(cf.decision_points, "↳"), "🔀")
    if resp.first_hour_actions:
        numbered = "\n".join(f"{i}. {a}" for i, a in enumerate(resp.first_hour_actions, 1))
        m2 += "\n" + _section("Primeira Hora — ações críticas", numbered, "⏱️")
    if resp.common_errors:
        m2 += "\n" + _section("Erros Comuns e Red Flags", _bullets(resp.common_errors, "❌"), "⚠️")
    m2 += _DISCLAIMER

    # ── Message 3: Socratic + Takeaways + Citations ───────────────────────────
    m3 = f"{emoji} {_bold(resp.topic)} — Estudo Ativo\n\n"
    if resp.socratic_questions:
        qs = "\n".join(f"{i}. {q}" for i, q in enumerate(resp.socratic_questions, 1))
        m3 += _section("Perguntas Socráticas", qs, "❓")
    if resp.high_yield_takeaways:
        m3 += "\n" + _section("High-Yield — não esqueça", _bullets(resp.high_yield_takeaways, "⭐"), "📌")
    if resp.citations:
        lines = []
        for i, c in enumerate(resp.citations[:5], 1):
            line = f"[{i}] {c.source} | {c.section} | p.{c.page}"
            if c.snippet:
                lines.append(f"{line}\n    {_italic(c.snippet[:100])}")
            else:
                lines.append(line)
        m3 += "\n" + _section("Fontes", "\n".join(lines), "📚")
    if resp.next_study_step:
        m3 += "\n" + _section("Próximo Passo", resp.next_study_step, "➡️")
    m3 += _DISCLAIMER

    messages = [m1, m2, m3]

    # ── Message 4 (optional): External + uncertainties ────────────────────────
    has_extra = resp.external_update_notes or resp.uncertainties
    if has_extra:
        m4 = f"{emoji} {_bold(resp.topic)} — Atualizações\n\n"
        if resp.external_update_notes:
            m4 += _section("Atualizações Externas", _bullets(resp.external_update_notes, "🔗"), "🌐")
        if resp.uncertainties:
            m4 += "\n" + _section("Incertezas / Controvérsias", resp.uncertainties, "🔬")
        m4 += _DISCLAIMER
        messages.append(m4)

    return [m[:4096] for m in messages]
