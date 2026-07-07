"""Human-in-the-loop corrections."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.operations import UserCorrection


CORRECTION_TYPES = frozenset({
    "wrong_category",
    "incorrect_merge",
    "poor_summary",
    "missing_source",
})


async def submit_correction(
    db: AsyncSession,
    user_id: uuid.UUID,
    correction_type: str,
    details: dict,
    event_id: uuid.UUID | None = None,
    article_id: uuid.UUID | None = None,
) -> UserCorrection:
    if correction_type not in CORRECTION_TYPES:
        raise ValueError(f"Invalid correction type: {correction_type}")

    correction = UserCorrection(
        user_id=user_id,
        event_id=event_id,
        article_id=article_id,
        correction_type=correction_type,
        details=details,
    )
    db.add(correction)
    await db.flush()

    # Apply immediate ranking adjustments where possible
    if correction_type == "wrong_category" and event_id:
        await _apply_category_correction(db, user_id, event_id, details)

    return correction


async def _apply_category_correction(
    db: AsyncSession,
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    details: dict,
) -> None:
    from app.models.article import CanonicalEvent

    result = await db.execute(
        select(CanonicalEvent).where(
            CanonicalEvent.id == event_id, CanonicalEvent.user_id == user_id
        )
    )
    event = result.scalar_one_or_none()
    if not event:
        return

    correct_categories = details.get("correct_categories")
    if correct_categories:
        event.categories = correct_categories
        correction = details.get("note", "user correction")
        alts = list(event.alternative_explanations or [])
        alts.append(f"[correction] {correction}")
        event.alternative_explanations = alts


async def list_corrections(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 50,
) -> list[UserCorrection]:
    result = await db.execute(
        select(UserCorrection)
        .where(UserCorrection.user_id == user_id)
        .order_by(UserCorrection.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
