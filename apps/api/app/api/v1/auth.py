"""Sign in, sign out, and who am I.

Deliberately outside the `get_session` dependency: these endpoints decide
*which* database a request should use, so they cannot themselves be handed one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import (
    SESSION_COOKIE,
    USERS,
    check_password,
    display_name,
    issue_cookie,
    resolve_user,
)
from app.config import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login"""

    username: str = Field(description="One of the identifiers from /auth/users.")
    password: str


class CurrentUser(BaseModel):
    """Who the caller is signed in as."""

    username: str = ""
    name: str = ""
    signed_in: bool = False
    #: Send this back as `Authorization: Bearer <token>`. It is the same signed
    #: value as the cookie, for the browsers that will not keep a cross-site one.
    token: str = ""
    #: False when this deployment does not ask anyone to sign in, so the console
    #: knows to skip the sign-in screen entirely rather than guessing.
    login_required: bool = True


class UserOption(BaseModel):
    """One person the sign-in screen offers."""

    username: str
    name: str


class UserList(BaseModel):
    users: list[UserOption]
    login_required: bool = True


@router.get("/users", response_model=UserList)
async def list_users() -> UserList:
    """The people this deployment is for. Never returns the password."""
    return UserList(
        users=[UserOption(username=u, name=n) for u, n in USERS.items()],
        login_required=settings.require_login,
    )


@router.post("/login", response_model=CurrentUser)
async def login(body: LoginRequest, response: Response) -> CurrentUser:
    """Exchange credentials for a signed session cookie."""
    username = body.username.strip().lower()
    if not check_password(username, body.password):
        # One message for both a wrong name and a wrong password: saying which
        # was wrong tells an unauthenticated caller which usernames exist.
        raise HTTPException(401, "That username and password do not match.")

    response.set_cookie(
        SESSION_COOKIE,
        issue_cookie(username),
        max_age=60 * 60 * 24 * 30,
        httponly=True,  # unreadable from JavaScript, so an XSS cannot lift it
        samesite="none",  # console and API are different origins on Cloud Run
        secure=True,
        path="/",
    )
    return CurrentUser(
        username=username,
        name=display_name(username),
        signed_in=True,
        login_required=settings.require_login,
        token=issue_cookie(username),
    )


@router.post("/logout", response_model=CurrentUser)
async def logout(response: Response) -> CurrentUser:
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="none", secure=True)
    return CurrentUser(login_required=settings.require_login)


@router.get("/me", response_model=CurrentUser)
async def me(request: Request) -> CurrentUser:
    """Who the caller is. The console asks this before rendering anything."""
    username = resolve_user(request)
    if not username:
        return CurrentUser(login_required=settings.require_login)
    return CurrentUser(
        username=username,
        name=display_name(username),
        signed_in=True,
        login_required=settings.require_login,
    )
