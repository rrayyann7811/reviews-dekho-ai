from fastapi import APIRouter

from ..collectors.registry import ADAPTERS
from ..schemas import SupportedSite

router = APIRouter(tags=["Product links"])


@router.get("/sites", response_model=list[SupportedSite], summary="Websites whose links are recognised")
def list_sites():
    return [{"id": a.id, "name": a.name, "status": a.status, "hosts": list(a.hosts), "note": a.note,
             "example": a.example} for a in ADAPTERS]
