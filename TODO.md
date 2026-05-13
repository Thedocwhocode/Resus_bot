# TODO — ResusBot

Checklist de implementação por fases.

## Fase 0 — Bootstrap ✅
- [x] `pyproject.toml` com todas as dependências
- [x] Configuração ruff / mypy / pytest
- [x] `.env.example`
- [x] `.gitignore` / `.dockerignore`
- [x] Estrutura de diretórios `src/resusbot/`
- [x] README inicial

## Fase 1 — Telegram MVP ✅
- [x] `config.py` com pydantic-settings
- [x] `logging_setup.py` com structlog + redação de PII
- [x] `telegram/bot.py` com Application builder
- [x] `telegram/handlers.py` — /start /help /search /stats + texto livre
- [x] `telegram/middleware.py` — rate limit por telegram_id (Redis)
- [x] `telegram/formatters.py` — MarkdownV2 + inline buttons
- [x] `main.py` — FastAPI + lifespan + polling/webhook

## Fase 2 — Workflow AGNO ✅
- [x] `tools/base.py` — httpx.AsyncClient compartilhado
- [x] `tools/orio_search.py`
- [x] `tools/crossref.py`
- [x] `tools/openalex.py`
- [x] `tools/unpaywall.py`
- [x] `workflows/research_workflow.py` — 5 agentes com Groq

## Fase 3 — Persistência ✅
- [x] `db/models.py` — User, Category, Article, SearchLog, SearchArticle, CacheEntry
- [x] `db/session.py` — AsyncEngine + sessionmaker
- [x] `db/repository.py` — CRUD completo
- [x] `services/dedup_service.py` — dedup por DOI normalizado
- [x] `services/category_classifier.py` — classificação por keywords
- [x] `scripts/seed_categories.py` — 9 categorias médicas

## Fase 4 — Cache ✅
- [x] `cache/redis_client.py` — pool async
- [x] `cache/query_cache.py` — hash(query) → Redis TTL + fallback SQLite
- [x] `services/research_service.py` — orquestra cache → workflow → persist

## Fase 5 — Dashboard ✅
- [x] `dashboard/routes.py` — partials HTMX + JSON
- [x] `dashboard/auth.py` — HTTPBasic + bcrypt
- [x] `dashboard/templates/base.html`
- [x] `dashboard/templates/dashboard.html` — HTMX + Chart.js
- [x] `dashboard/templates/partials/kpis.html`
- [x] `dashboard/templates/partials/top_subjects.html`
- [x] `dashboard/templates/partials/top_users.html`
- [x] `dashboard/templates/partials/top_queries.html`
- [x] `dashboard/templates/partials/top_articles.html`

## Fase 6 — Segurança ✅
- [x] `security/sanitize.py` — anti-prompt-injection + escape MarkdownV2
- [x] `security/rate_limit.py` — slowapi limiter global
- [x] HTTPBasic + bcrypt no dashboard
- [x] Validação `secret_token` no webhook (dupla: path + header)
- [x] Headers de segurança (X-Content-Type-Options, X-Frame-Options)
- [x] CORS restrito ao domínio do dashboard
- [x] structlog com redação de telegram_id (PII)

## Fase 7 — DevOps ✅
- [x] `Dockerfile` multistage (builder + runtime slim)
- [x] `docker-compose.yml` — bot + redis + oriosearch + searxng + Traefik labels
- [x] `docker-compose.dev.yml` — override dev (polling, sem TLS)
- [x] `.github/workflows/ci.yml` — lint + typecheck + tests
- [x] `.github/workflows/docker-build.yml` — build multi-arch + GHCR
- [x] `scripts/backup_sqlite.sh` — snapshot diário com rotação 14d
- [x] `searxng/settings.yml` — configuração SearXNG

## Fase 8 — Testes ✅
- [x] `tests/conftest.py` — fixtures DB efêmero + fakeredis
- [x] `tests/test_sanitize.py`
- [x] `tests/test_cache.py`
- [x] `tests/test_dedup.py`
- [x] `tests/test_category_classifier.py`
- [x] `tests/test_repository.py`

## Fase 9 — SaaS de créditos ✅
- [x] **9.1** Schema (Plan, Subscription, CreditBalance, CreditTransaction, Payment) + seed 5 planos
- [x] **9.2** `credits_service.py` + integração no `research_service.handle()` (gate + consume)
- [x] **9.3** Comandos Telegram `/saldo`, `/planos`, `/historico`, `/cancelar` + `CallbackQueryHandler`
- [x] **9.4** `payments_service.py` + `MercadoPagoProvider` + webhook idempotente + landing
- [x] **9.5** Dashboard `/dashboard/billing` (MRR, ARPU, churn, conversão, custo Groq, subscribers)
- [x] **9.6** APScheduler (reset mensal, expiração de créditos, expiração de assinaturas)
- [x] **9.7** Testes `test_credits.py`, `test_payments.py` + README billing

## Pendente / Melhorias futuras
- [ ] Migrar para Alembic migrations (atualmente usa create_all)
- [ ] Adicionar testes de integração para o workflow AGNO (com mocks LLM)
- [ ] Botão "Mais como este" no Telegram (artigos relacionados por categoria)
- [ ] Export do dataset de artigos em CSV/JSONL para treinamento ML
- [ ] Alertas de degradação de serviço (Redis down, OrioSearch offline)
- [ ] Suporte a múltiplos idiomas na resposta do bot
- [ ] Migrar SQLite → PostgreSQL quando search_logs > 1M
- [ ] Stripe como segundo provider (manter ABC PaymentProvider)
- [ ] Integração eNotas/Bling para emissão de NFS-e (Fase 10)
- [ ] Comando admin `/admin_refund` para reembolso manual
- [ ] Dashboard: gráfico de cohort de retenção e LTV
