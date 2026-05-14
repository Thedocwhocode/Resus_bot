from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from resusbot.security.sanitize import escape_markdown_v2

DISCLAIMER = "\n\n_ℹ️ Conteúdo informativo\\. Não substitui julgamento clínico\\._"

MAX_MESSAGE_LENGTH = 4000


def format_research_response(text: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Formata a resposta do workflow para MarkdownV2 do Telegram.
    Retorna (texto_formatado, teclado_inline_ou_None).
    """
    escaped = escape_markdown_v2(text)
    full = escaped + DISCLAIMER

    if len(full) > MAX_MESSAGE_LENGTH:
        full = full[: MAX_MESSAGE_LENGTH - 3] + "\\.\\.\\."

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Nova pesquisa", switch_inline_query_current_chat="")]]
    )
    return full, keyboard


def format_error(message: str) -> str:
    return escape_markdown_v2(f"⚠️ {message}")


def format_typing_message() -> str:
    return escape_markdown_v2("🔍 Pesquisando artigos, aguarde...")
