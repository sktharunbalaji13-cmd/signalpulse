import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.services.rate_limit import enforce_rate_limit
from app.sources.base import SourceError, SourceResult
from app.sources.registry import registry

router = APIRouter(
    tags=["sources"],
    dependencies=[Depends(enforce_rate_limit)],  # M19.1: same per-IP budget as search creation
)


class SourceSearchResponse(BaseModel):
    query: str
    source: str
    results: list[SourceResult]


@router.get("/{source_name}/search", response_model=SourceSearchResponse)
async def source_search(
    source_name: str,
    q: str = Query(..., min_length=1, max_length=200),
) -> SourceSearchResponse:
    adapter = registry.get(source_name)
    if adapter is None:
        raise HTTPException(status_code=404, detail=f"Unknown source: {source_name}")
    try:
        results = await adapter.search(q)
    except SourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"{source_name} request failed") from exc
    return SourceSearchResponse(query=q, source=adapter.source_name, results=results)