"""
Telegram handlers for the Study Pipeline.

Commands:
  /study <topic>  — 20/80 focused review (default)
  /deep <topic>   — deep dive with external sources
  /case <vignette>— clinical case reasoning

Free text that starts with study keywords is also routed here by message_handler.
"""

from __future__ import annotations

import time

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from resusbot.security.sanitize import clean
from resusbot.study.models import PedagogicalResponse, StudyMode
from resusbot.telegram.study_formatters import format_pedagogical_response

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_study_service = None


def get_study_service():  # type: ignore[return]
    global _study_service
    if _study_service is None:
        from resusbot.study.service import study_service

        _study_service = study_service
    return _study_service


# ── Command handlers ──────────────────────────────────────────────────────────

async def study_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/study <topic> — 20/80 focused review."""
    await _dispatch(update, context, mode=StudyMode.STUDY_20_80)


async def deep_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/deep <topic> — comprehensive deep dive with external search."""
    await _dispatch(update, context, mode=StudyMode.DEEP_DIVE)


async def case_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/case <vignette> — clinical case with Socratic reasoning."""
    await _dispatch(update, context, mode=StudyMode.CLINICAL_CASE)


# ── Core dispatcher ───────────────────────────────────────────────────────────

async def _dispatch(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    mode: StudyMode,
) -> None:
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    raw_query = " ".join(args).strip()

    if not raw_query:
        examples = {
            StudyMode.STUDY_20_80: "`/study sepse`",
            StudyMode.DEEP_DIVE: "`/deep choque obstrutivo`",
            StudyMode.CLINICAL_CASE: "`/case paciente 45 anos, dor torácica, dispneia`",
        }
        await update.message.reply_text(
            f"Por favor, informe o tema\\.\n*Exemplo:* {examples[mode]}",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await _process_study_query(update, raw_query, mode)


async def _process_study_query(
    update: Update,
    raw_query: str,
    mode: StudyMode,
) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    query = clean(raw_query)

    if not query:
        await update.message.reply_text(
            "Mensagem inválida ou muito curta\\.", parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    mode_labels = {
        StudyMode.STUDY_20_80: "🎯 Revisão 20/80",
        StudyMode.DEEP_DIVE: "🔬 Deep dive",
        StudyMode.CLINICAL_CASE: "🏥 Caso clínico",
    }
    mode_label = mode_labels[mode]
    log.info("study_request", telegram_id=user_id, mode=mode.value, query_len=len(query))

    await update.message.chat.send_action(ChatAction.TYPING)
    typing_msg = await update.message.reply_text(
        f"📚 {mode_label} — *{query[:40]}*\\.\\.\\. Aguarde\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    start = time.monotonic()
    try:
        service = get_study_service()
        result = await service.handle(
            query=query,
            telegram_id=user_id,
            mode_override=mode.value,
        )
        latency_ms = int((time.monotonic() - start) * 1000)

        if result.get("error"):
            await typing_msg.edit_text(
                f"⚠️ {result['response']}",
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return

        response = result["response"]
        if isinstance(response, PedagogicalResponse):
            pages = format_pedagogical_response(response)
            await typing_msg.edit_text(
                pages[0],
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=_build_keyboard(pages, 0),
            )
            # Store extra pages in context for pagination callback
            if context.user_data is not None and len(pages) > 1:
                context.user_data[f"study_pages_{user_id}"] = pages
        else:
            await typing_msg.edit_text(
                str(response)[:4000],
                parse_mode=ParseMode.MARKDOWN_V2,
            )

        log.info("study_done", telegram_id=user_id, latency_ms=latency_ms, mode=mode.value)

    except Exception:
        log.exception("study_handler_error", telegram_id=user_id)
        await typing_msg.edit_text(
            "⚠️ Erro ao processar\\. Tente novamente\\.",
            parse_mode=ParseMode.MARKDOWN_V2,
        )


def _build_keyboard(pages: list[str], current: int) -> InlineKeyboardMarkup | None:
    if len(pages) <= 1:
        return InlineKeyboardMarkup(
            [[InlineKeyboardButton("🎯 Nova pesquisa", switch_inline_query_current_chat="")]]
        )
    buttons = []
    if current > 0:
        buttons.append(InlineKeyboardButton("◀ Anterior", callback_data=f"study_page:{current-1}"))
    if current < len(pages) - 1:
        buttons.append(InlineKeyboardButton("Próximo ▶", callback_data=f"study_page:{current+1}"))
    return InlineKeyboardMarkup([buttons])


async def study_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle pagination callbacks for multi-page study responses."""
    if not update.callback_query or not update.effective_user:
        return
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    page_idx = int(query.data.split(":")[1])  # type: ignore[union-attr]

    pages: list[str] | None = None
    if context.user_data:
        pages = context.user_data.get(f"study_pages_{user_id}")

    if not pages or page_idx >= len(pages):
        await query.edit_message_text("Sessão expirada\\. Use /study novamente\\.")
        return

    await query.edit_message_text(
        pages[page_idx],
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=_build_keyboard(pages, page_idx),
    )
