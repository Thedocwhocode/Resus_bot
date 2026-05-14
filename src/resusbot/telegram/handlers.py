import time

import structlog
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

from resusbot.security.sanitize import clean
from resusbot.telegram.formatters import (
    format_error,
    format_research_response,
    format_typing_message,
)

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# Import lazy para evitar circular (services dependem de db que é iniciado no lifespan)
_research_service = None


def get_research_service():  # type: ignore[return]
    global _research_service
    if _research_service is None:
        from resusbot.services.research_service import research_service

        _research_service = research_service
    return _research_service


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "👋 Olá! Sou o *ResusBot*, especializado em artigos científicos de emergência e ressuscitação\\.\n\n"
        "📚 *Como usar:*\n"
        "• `/search <query>` — pesquisa artigo por título, autores ou DOI\n"
        "• Envie uma mensagem de texto diretamente\n\n"
        "💡 *Exemplos:*\n"
        "`/search ROX index sepse`\n"
        "`/search 10.1164/rccm.201803-0561OC`\n"
        "`ROSC after cardiac arrest guidelines 2021`\n\n"
        "_ℹ️ Conteúdo informativo\\. Não substitui julgamento clínico\\._",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "🆘 *Ajuda — ResusBot*\n\n"
        "*Comandos disponíveis:*\n"
        "• `/start` — Apresentação\n"
        "• `/search <query>` — Pesquisa artigo científico\n"
        "• `/help` — Esta mensagem\n"
        "• `/stats` — Suas estatísticas de uso\n\n"
        "*Dicas:*\n"
        "• Use o título completo para melhor resultado\n"
        "• Informe DOI para busca direta: `10\\.xxxx/xxxxx`\n"
        "• Inclua autores ou ano para refinar",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.effective_user:
        return
    try:
        from resusbot.db.repository import get_user_stats
        from resusbot.db.session import get_session_context

        async with get_session_context() as session:
            stats = await get_user_stats(session, update.effective_user.id)
        await update.message.reply_text(
            f"📊 *Suas estatísticas*\n\n"
            f"🔍 Pesquisas realizadas: `{stats['total']}`\n"
            f"⚡ Respostas do cache: `{stats['cache_hits']}`\n"
            f"🗓️ Primeira pesquisa: `{stats['first_seen']}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    except Exception as e:
        log.warning("stats_handler error", error=str(e))
        await update.message.reply_text(
            "Estatísticas indisponíveis no momento\\.", parse_mode=ParseMode.MARKDOWN_V2
        )


async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para /search <query>."""
    if not update.message or not update.effective_user:
        return

    args = context.args or []
    query = " ".join(args).strip()

    if not query:
        await update.message.reply_text(
            "Por favor, informe o que deseja pesquisar\\.\n*Exemplo:* `/search ROX index sepse`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    await _process_query(update, query)


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler para mensagens de texto livres (sem comando)."""
    if not update.message or not update.message.text or not update.effective_user:
        return
    await _process_query(update, update.message.text)


async def _process_query(update: Update, raw_query: str) -> None:
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    query = clean(raw_query)

    if not query:
        await update.message.reply_text(
            "Mensagem inválida ou muito curta\\.", parse_mode=ParseMode.MARKDOWN_V2
        )
        return

    log.info("search_request", telegram_id=user_id, query_length=len(query))

    # Envia "digitando..."
    await update.message.chat.send_action(ChatAction.TYPING)
    typing_msg = await update.message.reply_text(
        format_typing_message(), parse_mode=ParseMode.MARKDOWN_V2
    )

    start = time.monotonic()
    try:
        service = get_research_service()
        result = await service.handle(query=query, telegram_id=user_id)
        latency = int((time.monotonic() - start) * 1000)
        log.info(
            "search_done",
            telegram_id=user_id,
            latency_ms=latency,
            cache_hit=result.get("cache_hit"),
            error=result.get("error"),
        )

        # Saldo insuficiente — oferece botão "Ver planos"
        if result.get("error") == "insufficient_credits":
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            kb = InlineKeyboardMarkup(
                [[InlineKeyboardButton("💳 Ver planos", callback_data="plan:list")]]
            )
            await typing_msg.edit_text(
                format_error(result["response"]),
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb,
            )
            return

        formatted, keyboard = format_research_response(result["response"])
        await typing_msg.edit_text(
            formatted, parse_mode=ParseMode.MARKDOWN_V2, reply_markup=keyboard
        )

    except Exception as e:
        log.exception("search_error", telegram_id=user_id, error=str(e))
        await typing_msg.edit_text(
            format_error("Ocorreu um erro ao processar sua pesquisa. Tente novamente."),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
