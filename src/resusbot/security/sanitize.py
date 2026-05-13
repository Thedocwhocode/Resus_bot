import re

_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+previous|system\s*prompt|</?\s*system\s*>|<\s*/?instruction|forget\s+all)",
    re.IGNORECASE,
)

_MAX_QUERY_LENGTH = 500

_TELEGRAM_ESCAPE = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def clean(text: str) -> str:
    """Remove padrões de prompt-injection e limita comprimento."""
    text = text.strip()
    if len(text) > _MAX_QUERY_LENGTH:
        text = text[:_MAX_QUERY_LENGTH]
    text = _INJECTION_PATTERNS.sub("", text).strip()
    return text


def escape_markdown_v2(text: str) -> str:
    """Escapa caracteres reservados do MarkdownV2 do Telegram."""
    return _TELEGRAM_ESCAPE.sub(r"\\\1", text)
