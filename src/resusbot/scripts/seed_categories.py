"""Popula tabela categories com as categorias médicas padrão."""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CATEGORIES = [
    (1, "resuscitation", "Ressuscitação", "Resuscitation"),
    (2, "sepsis", "Sepse / Choque Séptico", "Sepsis / Septic Shock"),
    (3, "cardiology", "Cardiologia", "Cardiology"),
    (4, "trauma", "Trauma", "Trauma"),
    (5, "neuro", "Neurologia / Neurointensivismo", "Neurology / Neurocritical Care"),
    (6, "pediatrics", "Pediatria / Neonatologia", "Pediatrics / Neonatology"),
    (7, "airway", "Via Aérea / Ventilação", "Airway / Mechanical Ventilation"),
    (8, "toxicology", "Toxicologia", "Toxicology"),
    (9, "other", "Outros", "Other"),
]


async def seed_categories() -> None:
    from resusbot.db.models import Category
    from resusbot.db.session import get_session_context

    async with get_session_context() as session:
        for cat_id, slug, name_pt, name_en in CATEGORIES:
            result = await session.execute(select(Category).where(Category.slug == slug))
            if result.scalar_one_or_none() is None:
                session.add(Category(id=cat_id, slug=slug, name_pt=name_pt, name_en=name_en))
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed_categories())
