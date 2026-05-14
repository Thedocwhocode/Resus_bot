"""Tool AGNO para OpenAlex API (gratuito, email para polite pool)."""

import asyncio

from agno.tools import Toolkit

from resusbot.config import settings
from resusbot.tools.base import get_http_client

BASE = "https://api.openalex.org"


class OpenAlexTool(Toolkit):
    name: str = "openalex"

    def __init__(self) -> None:
        super().__init__(name=self.name)
        self.register(self.get_work_by_doi)

    def get_work_by_doi(self, doi: str) -> str:
        """
        Busca metadados enriquecidos de um artigo no OpenAlex pelo DOI.
        Inclui número de citações, acesso aberto, tópicos e link de full-text.

        Args:
            doi: DOI do artigo.
        """
        return asyncio.get_event_loop().run_until_complete(self._get_work_by_doi(doi))

    async def _get_work_by_doi(self, doi: str) -> str:
        try:
            client = get_http_client()
            r = await client.get(
                f"{BASE}/works",
                params={"filter": f"doi:{doi}", "mailto": settings.openalex_email},
            )
            r.raise_for_status()
            results = r.json().get("results", [])
            if not results:
                return "Artigo não encontrado no OpenAlex."
            w = results[0]
            oa = w.get("open_access", {})
            oa_url = oa.get("oa_url") or "Não disponível em acesso aberto"
            citations = w.get("cited_by_count", 0)
            topics = ", ".join(t.get("display_name", "") for t in w.get("topics", [])[:3])
            return (
                f"OpenAlex ID: {w.get('id', '')}\n"
                f"Citações: {citations}\n"
                f"Acesso aberto: {'Sim' if oa.get('is_oa') else 'Não'}\n"
                f"Link OA: {oa_url}\n"
                f"Tópicos: {topics}"
            )
        except Exception as e:
            return f"OpenAlex erro: {e}"
