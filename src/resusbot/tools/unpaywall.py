"""Tool AGNO para Unpaywall — encontra PDFs legais e gratuitos por DOI."""
import asyncio

from agno.tools import Toolkit

from resusbot.config import settings
from resusbot.tools.base import get_http_client


class UnpaywallTool(Toolkit):
    name: str = "unpaywall"

    def __init__(self) -> None:
        super().__init__(name=self.name)
        self.register(self.find_pdf_link)

    def find_pdf_link(self, doi: str) -> str:
        """
        Busca o melhor link de PDF gratuito e legal para um DOI via Unpaywall.

        Args:
            doi: DOI do artigo (ex: 10.1056/NEJMoa2001017).
        """
        return asyncio.get_event_loop().run_until_complete(self._find_pdf_link(doi))

    async def _find_pdf_link(self, doi: str) -> str:
        try:
            client = get_http_client()
            r = await client.get(
                f"https://api.unpaywall.org/v2/{doi}",
                params={"email": settings.unpaywall_email},
            )
            if r.status_code == 404:
                return "DOI não encontrado no Unpaywall."
            r.raise_for_status()
            data = r.json()
            if not data.get("is_oa"):
                return (
                    "Este artigo NÃO está disponível em acesso aberto.\n"
                    f"Link da editora: https://doi.org/{doi}"
                )
            best = data.get("best_oa_location") or {}
            pdf_url = best.get("url_for_pdf") or best.get("url") or ""
            host_type = best.get("host_type", "")
            version = best.get("version", "")
            if pdf_url:
                return (
                    f"✅ PDF disponível gratuitamente!\n"
                    f"Link: {pdf_url}\n"
                    f"Fonte: {host_type} ({version})"
                )
            return f"Artigo é open access mas sem PDF direto.\nTente: https://doi.org/{doi}"
        except Exception as e:
            return f"Unpaywall erro: {e}"
