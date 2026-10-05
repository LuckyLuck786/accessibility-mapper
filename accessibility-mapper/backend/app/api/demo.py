"""Demo clock endpoints.

``GET /demo/clock`` is public (the board needs it on paint). Writes require the
admin guard, because a speed multiplier that anyone can set would make the
metrics meaningless.

Everything time-based in Ghost Space reads this clock, which is what lets a
judge watch a full campus day in about three minutes.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import AdminGuard, FreshDbSession
from app.schemas.space import ClockIn, ClockOut
from app.services import space_service

logger = logging.getLogger("abm.api.demo")

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get(
    "/clock",
    response_model=ClockOut,
    summary="Read the demo clock (public)",
    description=(
        "The controlled 'now' every Ghost Space decision uses. `mode: live` "
        "means real wall-clock time; `mode: demo` means the accelerated clock."
    ),
)
def read_clock(db: FreshDbSession) -> ClockOut:
    return ClockOut.model_validate(space_service.get_clock(db))


@router.post(
    "/clock",
    response_model=ClockOut,
    summary="Set the demo clock (admin)",
    description=(
        "Control mode (`live`/`demo`), speed multiplier (1-600x), an absolute "
        "jump, or pause. Requires `X-Admin-Token` in production."
    ),
)
def write_clock(
    payload: ClockIn, db: FreshDbSession, _user: AdminGuard
) -> ClockOut:
    try:
        state = space_service.set_clock(
            db,
            mode=payload.mode,
            speed=payload.speed,
            jump_to=payload.jump_to,
            playing=payload.playing,
            reset=payload.reset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return ClockOut.model_validate(state)


__all__ = ["router"]