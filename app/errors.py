from fastapi import Request
from fastapi.responses import JSONResponse


class ErreurMetier(Exception):
    """Erreur destinée à l'enseignant, renvoyée au client en JSON {code, message}."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


async def gerer_erreur(_request: Request, erreur: ErreurMetier) -> JSONResponse:
    return JSONResponse(
        {"code": erreur.code, "message": erreur.message}, status_code=erreur.status
    )
