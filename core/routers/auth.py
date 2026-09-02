"""
Router de autenticação — Fase 6.

Rotas movidas do api_server.py, SEM nenhuma alteração de comportamento:

    POST /api/auth/signup
    GET  /api/auth/verify
    POST /api/auth/resend-verification
    POST /api/auth/login
    POST /api/auth/logout
    GET  /api/auth/me

As URLs são exatamente as mesmas, então nada muda pro front-end.
"""
from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from core import auth, email_service
from core.dependencies import APP_BASE_URL, SESSION_COOKIE_NAME, get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------- Modelos de request ----------
class SignupRequest(BaseModel):
    email: str
    username: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ResendVerificationRequest(BaseModel):
    email: str


# ---------- Rotas ----------
@router.post("/signup")
def signup(req: SignupRequest) -> dict:
    try:
        user = auth.create_user(req.email, req.username, req.password)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))

    verification_url = f"{APP_BASE_URL}/api/auth/verify?token={user['verification_token']}"
    email_service.send_verification_email(user["email"], user["username"], verification_url)
    return {"message": "Conta criada! Confira seu e-mail (inclusive spam) pra confirmar antes de entrar."}


@router.get("/verify")
def verify(token: str):
    ok = auth.verify_email_token(token)
    if not ok:
        raise HTTPException(400, "Link de confirmação inválido ou expirado.")
    return RedirectResponse(url="/login?verified=1")


@router.post("/resend-verification")
def resend_verification(req: ResendVerificationRequest) -> dict:
    try:
        token = auth.regenerate_verification_token(req.email)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    user = auth.get_user_by_email(req.email)
    verification_url = f"{APP_BASE_URL}/api/auth/verify?token={token}"
    email_service.send_verification_email(user["email"], user["username"], verification_url)
    return {"message": "Novo link de confirmação enviado."}


@router.post("/login")
def login(req: LoginRequest, response: Response) -> dict:
    user = auth.get_user_by_email(req.email)
    if not user or not auth.verify_password(req.password, user["password_hash"], user["password_salt"]):
        raise HTTPException(401, "E-mail ou senha incorretos.")
    if not user["email_verified"]:
        raise HTTPException(403, "Confirme seu e-mail antes de entrar (veja sua caixa de entrada).")

    token = auth.create_session(user["id"])
    response.set_cookie(
        SESSION_COOKIE_NAME, token, httponly=True, samesite="lax",
        max_age=auth.SESSION_DURATION_DAYS * 24 * 3600,
    )
    return {"email": user["email"], "username": user["username"]}


@router.post("/logout")
def logout(response: Response, cliparadar_session: str | None = Cookie(default=None)) -> dict:
    if cliparadar_session:
        auth.delete_session(cliparadar_session)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"email": user["email"], "username": user["username"]}
