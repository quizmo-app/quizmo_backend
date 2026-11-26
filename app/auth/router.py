"""Authentication routes. Login itself (LDAP, CU1.1) belongs to another story."""

from fastapi import APIRouter, Response

from app.dependencies import COOKIE_NAMES, TeacherDep
from app.schemas_common import ApiModel

router = APIRouter(prefix="/api/auth", tags=["auth"])


class CurrentTeacherResponse(ApiModel):
    """Identity of the authenticated teacher."""

    id_enseignant: str


@router.get("/me", response_model=CurrentTeacherResponse)
def read_current_teacher(teacher: TeacherDep) -> CurrentTeacherResponse:
    """Return the teacher identified by the Bearer token or the session cookie."""
    return CurrentTeacherResponse(id_enseignant=teacher)


@router.post("/logout", status_code=204)
def logout() -> Response:
    """Clear the session cookies."""
    response = Response(status_code=204)
    for name in COOKIE_NAMES:
        response.delete_cookie(name, httponly=True, samesite="lax")
    return response
