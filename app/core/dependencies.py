from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.enums import Role
from app.common.exceptions import forbidden, unauthorized
from app.core.config import settings
from app.core.database import get_db
from app.core.security import resolve_session
from app.domains.user.models import User

DB = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(request: Request, db: DB) -> User:
    user_id = await resolve_session(request.cookies.get(settings.cookie_name))
    if user_id is None:
        raise unauthorized()
    user = await db.get(User, user_id)
    if user is None:
        raise unauthorized()
    return user


def require_roles(*roles: Role):
    async def _dep(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in roles:
            raise forbidden()
        return user

    return _dep


CurrentUser = Annotated[User, Depends(get_current_user)]
StudentUser = Annotated[User, Depends(require_roles(Role.STUDENT))]
# 관리자는 교사 권한을 포함한다
TeacherUser = Annotated[User, Depends(require_roles(Role.TEACHER, Role.ADMIN))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
