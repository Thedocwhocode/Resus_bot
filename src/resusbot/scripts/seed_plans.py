"""Popula tabela `plans` com os 5 planos do SaaS (free + 4 pagos)."""
import asyncio

from sqlalchemy import select

PLANS = [
    # (slug, name, monthly_credits, price_brl_cents, validity_days, is_free)
    ("free",         "Gratuito",     10,    0,    30, True),
    ("plantao",      "Plantão",      50,    1490, 60, False),
    ("residente",    "Residente",    150,   3490, 60, False),
    ("especialista", "Especialista", 400,   7990, 60, False),
    ("pesquisador",  "Pesquisador",  1200,  19900, 60, False),
]


async def seed_plans() -> None:
    from resusbot.db.models import Plan
    from resusbot.db.session import get_session_context

    async with get_session_context() as session:
        for slug, name, credits, price, validity, is_free in PLANS:
            result = await session.execute(select(Plan).where(Plan.slug == slug))
            existing = result.scalar_one_or_none()
            if existing is None:
                session.add(Plan(
                    slug=slug,
                    name=name,
                    monthly_credits=credits,
                    price_brl_cents=price,
                    validity_days=validity,
                    is_free=is_free,
                    is_active=True,
                ))
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_plans())
