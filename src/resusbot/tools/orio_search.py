"""Tool AGNO para OrioSearch (Tavily-compatible, self-hosted)."""
from agno.tools import Toolkit

from resusbot.config import settings
from resusbot.tools.base import get_http_client


class OrioSearchTool(Toolkit):
    name: str = "orio_search"

    def __init__(self) -> None:
        super().__init__(name=self.name)
        self.register(self.search_web)

    def search_web(self, query: str, max_results: int = 5) -> str:
        """
        Busca no OrioSearch e retorna snippets + URLs.

        Args:
            query: Título do artigo, autores, tema clínico ou DOI.
            max_results: Número de resultados (padrão 5).
        """
        import asyncio
        return asyncio.get_event_loop().run_until_complete(
            self._search_web_async(query, max_results)
        )

    async def _search_web_async(self, query: str, max_results: int) -> str:
        try:
            client = get_http_client()
            resp = await client.post(
                f"{settings.orio_base_url}/search",
                json={
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                    "search_depth": "advanced",
                },
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                return "Nenhum resultado encontrado."
            lines = []
            for i, r in enumerate(results, 1):
                lines.append(
                    f"{i}. {r.get('title', 'Sem título')}\n"
                    f"   URL: {r.get('url', '')}\n"
                    f"   {r.get('content', '')[:300]}"
                )
            return "\n\n".join(lines)
        except Exception as e:
            return f"Erro OrioSearch: {e}"
