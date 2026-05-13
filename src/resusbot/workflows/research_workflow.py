"""
Workflow AGNO completo para pesquisa de artigos científicos.
5 agentes: Planner → Search → DOIResolver → PDFLink → Formatter
LLM: Groq (Llama 3.3 70B Versatile)
"""
from typing import Iterator

import structlog
from agno.agent import Agent
from agno.models.groq import Groq
from agno.tools.reasoning import ReasoningTools
from agno.workflow import RunResponse, Workflow

from resusbot.config import settings
from resusbot.tools.crossref import CrossrefTool
from resusbot.tools.openalex import OpenAlexTool
from resusbot.tools.orio_search import OrioSearchTool
from resusbot.tools.unpaywall import UnpaywallTool

log: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

_MODEL_ID = "llama-3.3-70b-versatile"


def _groq() -> Groq:
    return Groq(id=_MODEL_ID, api_key=settings.groq_api_key)


planner_agent = Agent(
    name="PlannerAgent",
    model=_groq(),
    tools=[ReasoningTools(add_instructions=True)],
    role="Analisar a mensagem do usuário e extrair: título do artigo, autores, DOI (se informado) e intenção.",
    instructions=[
        "Retorne um JSON com os campos: doi (string ou null), title (string ou null), authors (string ou null), intent (search | download | unknown).",
        "Se o usuário pediu apenas tema clínico sem artigo específico, marque intent como 'search'.",
        "Seja objetivo, retorne apenas o JSON.",
    ],
)

search_agent = Agent(
    name="SearchAgent",
    model=_groq(),
    tools=[OrioSearchTool()],
    role="Usar OrioSearch para descobrir o artigo mais relevante na web.",
    instructions=[
        "Busque pelo título completo + autores quando disponível.",
        "Priorize resultados de PubMed, SciELO, journals oficiais e repositórios confiáveis.",
        "Retorne os 3 melhores candidatos com título, URL e DOI se visível.",
    ],
)

doi_agent = Agent(
    name="DOIResolverAgent",
    model=_groq(),
    tools=[CrossrefTool(), OpenAlexTool()],
    role="Resolver e validar o DOI correto do artigo, enriquecendo com metadados científicos.",
    instructions=[
        "Se já existe um DOI, valide com Crossref lookup_doi.",
        "Se não há DOI, use Crossref search_by_title para encontrar candidatos.",
        "Após confirmar o DOI, busque metadados enriquecidos no OpenAlex.",
        "Retorne: doi confirmado, título oficial, autores, journal, ano, citações, se é open access.",
    ],
)

pdf_agent = Agent(
    name="PDFLinkAgent",
    model=_groq(),
    tools=[UnpaywallTool()],
    role="Encontrar o melhor link de download gratuito e legal para o artigo.",
    instructions=[
        "Use o DOI confirmado para consultar o Unpaywall.",
        "Se houver PDF direto, retorne o link.",
        "Se não houver acesso aberto, informe claramente e forneça o link doi.org.",
        "Nunca invente links.",
    ],
)

formatter_agent = Agent(
    name="FormatterAgent",
    model=_groq(),
    tools=[ReasoningTools()],
    role="Formatar a resposta final para envio como mensagem no Telegram. Máximo 3500 caracteres.",
    instructions=[
        "Seja direto e claro. Use emojis com moderação.",
        "Estrutura obrigatória:\n"
        "📄 TÍTULO\n"
        "👥 Autores\n"
        "📅 Ano | Journal\n"
        "🔗 DOI: doi.org/...\n"
        "📥 PDF: <link ou 'Não disponível gratuitamente'>\n"
        "📊 Citações: <número>",
        "Se não achou o artigo, informe que não foi possível localizar e sugira buscar no PubMed.",
        "Nunca ultrapasse 3500 caracteres.",
        "Não use caracteres especiais de Markdown como *, _, [ ] no texto corrido.",
    ],
)


class ResearchWorkflow(Workflow):
    """
    Workflow de pesquisa de artigos científicos para o Resus_bot.
    Orquestra: OrioSearch → Crossref → OpenAlex → Unpaywall → Formatação.
    """

    planner: Agent = planner_agent
    searcher: Agent = search_agent
    doi_resolver: Agent = doi_agent
    pdf_finder: Agent = pdf_agent
    formatter: Agent = formatter_agent

    def run(self, user_message: str) -> Iterator[RunResponse]:  # type: ignore[override]
        log.info("workflow_start", message_length=len(user_message))

        # Step 1: Planejar
        yield RunResponse(content="🔍 Analisando sua pesquisa...")
        plan = self.planner.run(user_message)
        plan_text = plan.content or ""

        has_doi = "doi" in plan_text.lower() and "null" not in plan_text.lower()

        # Step 2: Busca web (se não tiver DOI direto)
        if not has_doi:
            yield RunResponse(content="🌐 Buscando artigo na web...")
            search_result = self.searcher.run(
                f"Encontre o artigo científico: {user_message}"
            )
            search_context = search_result.content or ""
        else:
            search_context = ""

        # Step 3: Resolver DOI e metadados
        yield RunResponse(content="📋 Buscando metadados científicos...")
        doi_context = f"Pergunta original: {user_message}\n"
        if search_context:
            doi_context += f"Resultados da busca web:\n{search_context}\n"
        doi_context += f"Plano extraído:\n{plan_text}"
        doi_result = self.doi_resolver.run(doi_context)

        # Step 4: Buscar PDF
        yield RunResponse(content="📥 Verificando disponibilidade de PDF...")
        pdf_result = self.pdf_finder.run(
            f"Metadados do artigo:\n{doi_result.content or ''}"
        )

        # Step 5: Formatar
        yield RunResponse(content="✍️ Formatando resposta...")
        final_context = (
            f"Pergunta do usuário: {user_message}\n\n"
            f"Metadados encontrados:\n{doi_result.content or ''}\n\n"
            f"Link de PDF:\n{pdf_result.content or ''}"
        )
        final = self.formatter.run(final_context)
        content = final.content or "Não foi possível encontrar o artigo solicitado."
        log.info("workflow_done", response_length=len(content))
        yield RunResponse(content=content)
