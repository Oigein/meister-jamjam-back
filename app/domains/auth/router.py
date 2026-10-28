from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse

from app.common.ratelimit import check_ip_limit
from app.core.config import settings
from app.core.dependencies import DB
from app.core.security import clear_session_cookie, destroy_session, set_session_cookie
from app.domains.auth import service
from app.domains.auth.oauth import GoogleClient, get_google_client

router = APIRouter(prefix="/auth", tags=["auth"])


def _limit(request: Request) -> None:
    check_ip_limit(request, "login", settings.rate_login_per_min)


@router.get("/google", dependencies=[Depends(_limit)])
async def google_login(
    redirect: str | None = Query(None),
    client: GoogleClient = Depends(get_google_client),
):
    url = await service.start_login(client, redirect)
    return RedirectResponse(url, status_code=302)


@router.get("/google/callback", dependencies=[Depends(_limit)])
async def google_callback(
    db: DB,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    client: GoogleClient = Depends(get_google_client),
):
    result = await service.finish_login(db, client, code, state, error)
    response = RedirectResponse(result.location, status_code=302)
    if result.session_id:
        set_session_cookie(response, result.session_id)
    return response


@router.post("/logout", status_code=204)
async def logout(request: Request):
    """세션이 없어도 같은 응답을 돌려준다."""
    await destroy_session(request.cookies.get(settings.cookie_name))
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response
