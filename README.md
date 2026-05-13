# ResusBot 🏥

Bot Telegram para pesquisa de artigos científicos médicos com foco em ressuscitação e emergências.

Integra **AGNO** (workflow de 5 agentes LLM), **Crossref**, **OpenAlex**, **Unpaywall** e **OrioSearch** para encontrar artigos, validar DOIs e localizar PDFs gratuitamente — tudo com cache inteligente e painel de métricas.

## Stack

| Camada | Tecnologia |
|---|---|
| Runtime | Python 3.12 |
| Web | FastAPI + uvicorn |
| Bot | python-telegram-bot v21 |
| Agents | AGNO + Groq (Llama 3.3 70B) |
| DB | SQLite + SQLAlchemy 2.0 async + Alembic |
| Cache | Redis 7 (sliding window + TTL) |
| Dashboard | FastAPI + Jinja2 + HTMX + Chart.js |
| Auth | HTTPBasic + bcrypt |
| Busca | OrioSearch (self-hosted, SearXNG) |
| Deploy | Docker + Dokploy + Traefik v3 |
| CI/CD | GitHub Actions |

## Funcionalidades

- 🔍 **Pesquisa via Telegram** — `/search <query>` ou texto livre
- 📄 **Metadados científicos** — título, autores, DOI, journal, ano, citações
- 📥 **Links PDF gratuitos** — via Unpaywall (acesso aberto legal)
- ⚡ **Cache inteligente** — resposta em <200ms para queries repetidas (Redis + SQLite fallback)
- 📊 **Dashboard de métricas** — taxa de uso, top usuários, top 10 assuntos, artigos mais pesquisados
- 🗄️ **Dataset para ML** — artigos catalogados por categoria (ressuscitação, sepse, cardiologia, etc.)
- 🔒 **Segurança** — rate limiting, sanitização anti-prompt-injection, HTTPS via Traefik

## Setup local

### Pré-requisitos
- Python 3.12+
- Docker e Docker Compose v2
- [uv](https://docs.astral.sh/uv/) (gerenciador de pacotes)

### 1. Clone e configure

```bash
git clone https://github.com/thedocwhocode/resus_bot.git
cd resus_bot
cp .env.example .env
```

Edite `.env` com seus tokens:
- `TELEGRAM_BOT_TOKEN` — obtenha no [@BotFather](https://t.me/BotFather)
- `GROQ_API_KEY` — [console.groq.com](https://console.groq.com)
- `OPENALEX_EMAIL` e `UNPAYWALL_EMAIL` — qualquer email válido

### 2. Instale dependências

```bash
uv sync --extra dev
```

### 3. Suba Redis + OrioSearch

```bash
docker compose -f docker-compose.dev.yml up -d redis oriosearch searxng
```

### 4. Inicie o bot (modo polling)

```bash
TELEGRAM_MODE=polling uv run uvicorn resusbot.main:app --reload
```

### 5. Teste

```bash
# Health check
curl http://localhost:8000/health

# Dashboard (senha definida no .env ou gerada abaixo)
curl -u admin:SENHA http://localhost:8000/dashboard
```

## Gerar hash de senha para o Dashboard

```bash
python -c "from passlib.hash import bcrypt; print(bcrypt.hash('sua_senha'))"
```

Cole o resultado em `DASHBOARD_PASSWORD_HASH` no `.env`.

## Testes

```bash
uv run pytest -q
```

## Deploy em produção (Dokploy + Traefik)

1. Configure domínio e aponte DNS para o servidor.
2. Certifique-se que a network `traefik_public` existe no Docker.
3. Defina `TELEGRAM_MODE=webhook` e `TELEGRAM_WEBHOOK_URL=https://seudominio.com/telegram/webhook` no `.env`.
4. Configure o Traefik com `certresolver=letsencrypt`.
5. Suba os serviços:
```bash
docker compose up -d
```
6. Registre o webhook no Telegram:
```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://seudominio.com/telegram/webhook/${TELEGRAM_WEBHOOK_SECRET}" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

## Backup do banco de dados

```bash
# Executa manualmente
docker compose exec bot bash /app/scripts/backup_sqlite.sh

# Ou via cron (adicione ao crontab do host):
# 0 2 * * * docker compose -f /caminho/docker-compose.yml exec -T bot bash /app/scripts/backup_sqlite.sh
```

## Estrutura do projeto

```
src/resusbot/
├── main.py              # FastAPI + lifespan
├── config.py            # Configurações (pydantic-settings)
├── telegram/            # Bot, handlers, middleware, formatters
├── workflows/           # Workflow AGNO (5 agentes)
├── tools/               # OrioSearch, Crossref, OpenAlex, Unpaywall
├── db/                  # Models, session, repository (SQLAlchemy)
├── cache/               # Redis + fallback SQLite
├── services/            # research_service, dedup, category_classifier
├── dashboard/           # Rotas, auth, templates HTMX
├── security/            # Rate limit, sanitize
└── scripts/             # Seed de categorias
```

## Categorias de artigos (ML-ready)

| ID | Slug | Categoria |
|---|---|---|
| 1 | resuscitation | Ressuscitação |
| 2 | sepsis | Sepse / Choque Séptico |
| 3 | cardiology | Cardiologia |
| 4 | trauma | Trauma |
| 5 | neuro | Neurologia / Neurointensivismo |
| 6 | pediatrics | Pediatria / Neonatologia |
| 7 | airway | Via Aérea / Ventilação |
| 8 | toxicology | Toxicologia |
| 9 | other | Outros |

## Licença

MIT
