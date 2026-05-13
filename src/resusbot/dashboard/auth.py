import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from passlib.hash import bcrypt

from resusbot.config import settings

security = HTTPBasic()


def verify_dashboard_credentials(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    correct_user = secrets.compare_digest(
        credentials.username.encode("utf8"),
        settings.dashboard_user.encode("utf8"),
    )
    try:
        correct_pass = bcrypt.verify(credentials.password, settings.dashboard_password_hash)
    except Exception:
        correct_pass = False

    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciais inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username
