import os
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ErreurMetier


@dataclass(frozen=True)
class Enseignant:
    login: str


ENSEIGNANTS = {login: Enseignant(login) for login in ("enseignantA", "enseignantB")}


def get_current_user(
    request: Request,
    jeton: Annotated[HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))],
) -> Enseignant:
    """Authentification bouchonnée, à remplacer par le vrai LDAP/JWT."""
    if "authorization" in request.headers:
        login = jeton.credentials if jeton else None
    else:
        login = os.environ.get("QUIZMO_UTILISATEUR_DEV")

    enseignant = ENSEIGNANTS.get(login)
    if enseignant is None:
        raise ErreurMetier(
            401, "NON_AUTHENTIFIE", "Vous devez être connecté pour effectuer cette action."
        )
    return enseignant
