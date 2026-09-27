from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from app.api.auth import require_token
from app.api.schemas import HistoryItemOut
from app.api.state import ApiDeps

router = APIRouter(prefix="/history", tags=["history"])


@router.get("")
async def list_history(
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    deps: ApiDeps = Depends(require_token),
) -> dict:
    items, total = await deps.repo.history_list(deps.user_id, offset, limit)
    return {"total": total, "items": [HistoryItemOut.from_item(i) for i in items]}


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def clear_history(deps: ApiDeps = Depends(require_token)) -> None:
    await deps.repo.history_clear(deps.user_id)
