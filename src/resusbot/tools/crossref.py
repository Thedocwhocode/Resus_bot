"""Tool AGNO para Crossref REST API (gratuito, sem chave)."""
import asyncio

from agno.tools import Toolkit

from resusbot.tools.base import get_http_client

BASE = "https://api.crossref.org"


class CrossrefTool(Toolkit):
    name: str = "crossref"

    def __init__(self) -> None:
        super().__init__(name=self.name)
        self.register(self.lookup_doi)
        self.register(self.search_by_title)

    def lookup_doi(self, doi: str) -> str:
        """
        Busca metadados completos de um artigo pelo DOI.

        Args:
            doi: DOI do artigo (ex: 10.1016/j.resuscitation.2020.01.001).
        """
        return asyncio.get_event_loop().run_until_complete(self._lookup_doi(doi))

    def search_by_title(self, title: str, rows: int = 3) -> str:
        """
        Busca artigos pelo título na Crossref.

        Args:
            title: Título (ou trecho) do artigo.
            rows: Número de resultados (padrão 3).
        """
        return asyncio.get_event_loop().run_until_complete(self._search_by_title(title, rows))

    async def _lookup_doi(self, doi: str) -> str:
        try:
            client = get_http_client()
            r = await client.get(f"{BASE}/works/{doi}")
            r.raise_for_status()
            w = r.json()["message"]
            authors = ", ".join(
                f"{a.get('given', '')} {a.get('family', '')}".strip()
                for a in w.get("author", [])[:3]
            )
            journal = (w.get("container-title") or [""])[0]
            year = (w.get("published", {}).get("date-parts") or [[""]])[0][0]
            title = (w.get("title") or ["Sem título"])[0]
            return (
                f"Título: {title}\n"
                f"Autores: {authors}\n"
                f"Journal: {journal}\n"
                f"Ano: {year}\n"
                f"DOI: {doi}\n"
                f"URL: https://doi.org/{doi}"
            )
        except Exception as e:
            return f"Crossref lookup_doi erro: {e}"

    async def _search_by_title(self, title: str, rows: int) -> str:
        try:
            client = get_http_client()
            r = await client.get(
                f"{BASE}/works",
                params={
                    "query.title": title,
                    "rows": rows,
                    "select": "DOI,title,author,published,container-title",
                },
            )
            r.raise_for_status()
            items = r.json()["message"]["items"]
            if not items:
                return "Nenhum artigo encontrado no Crossref."
            lines = []
            for it in items:
                t = (it.get("title") or ["?"])[0]
                doi = it.get("DOI", "?")
                year = (it.get("published", {}).get("date-parts") or [[""]])[0][0]
                lines.append(f"- {t} ({year}) | DOI: {doi}")
            return "\n".join(lines)
        except Exception as e:
            return f"Crossref search_by_title erro: {e}"
