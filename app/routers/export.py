from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from app.services.exporter import export_result
from app.routers.testcases import get_result
from app.security import current_user

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/{result_id}.{fmt}")
def export(result_id: str, fmt: str, user: dict[str, str] = Depends(current_user)) -> Response:
    try:
        content, media_type, filename = export_result(get_result(result_id, user), fmt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})
