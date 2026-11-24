from __future__ import annotations

import os
import secrets
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from starlette.middleware.sessions import SessionMiddleware

security = HTTPBasic(auto_error=False)


def session_secret() -> str:
    return os.environ.get("SESSION_SECRET") or secrets.token_hex(32)


def review_password() -> str:
    return os.environ.get("REVIEW_PASSWORD", "review")


def require_login(request: Request) -> str:
    tester = request.session.get("tester")
    if not tester:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")
    return str(tester)


def check_password(credentials: HTTPBasicCredentials | None = Depends(security)) -> None:
    """Optional Basic Auth gate in addition to session login."""
    expected = review_password().encode()
    if credentials is None:
        # Allow form login page; API still uses session.
        return
    user_ok = secrets.compare_digest(credentials.username.encode(), b"reviewer")
    pass_ok = secrets.compare_digest(credentials.password.encode(), expected)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )


def add_session_middleware(app, secret: str | None = None) -> None:
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret or session_secret(),
        session_cookie="detection_review_session",
        same_site="lax",
        https_only=False,
        max_age=60 * 60 * 12,
    )
