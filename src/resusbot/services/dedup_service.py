from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from resusbot.db.repository import upsert_article

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


def normalize_doi(doi: str) -> str:
    return doi.lower().strip().removeprefix("https://doi.org/").removeprefix("http://doi.org/")


async def upsert_article_safe(session: AsyncSession, data: dict[str, Any]) -> int | None:
    """
    Insere ou atualiza artigo com deduplicação por DOI.
    Retorna o id do artigo ou None se não há DOI válido.
    """
    doi = data.get("doi", "")
    if not doi or doi.strip() == "":
        log.debug("dedup_no_doi_skipped")
        return None

    data["doi"] = normalize_doi(doi)
    try:
        article = await upsert_article(session, data)
        return article.id
    except Exception as e:
        log.warning("dedup_upsert_error", doi=doi, error=str(e))
        return None
