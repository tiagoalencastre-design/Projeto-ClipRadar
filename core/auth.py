"""
Autenticação simples: hash de senha (PBKDF2-HMAC-SHA256, já embutido no
Python — sem precisar de biblioteca externa tipo bcrypt) + sessões por
cookie, guardadas no SQLite.

Cada usuário recebe um "storage_key" — um código aleatório difícil de
adivinhar, usado como nome da pasta onde os vídeos/clipes dele ficam. Isso
NÃO é controle de acesso de verdade (qualquer um com o link exato ainda
consegue acessar), mas é uma proteção razoável pra um beta fechado com
poucas pessoas de confiança.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from core.database import get_db

SESSION_DURATION_DAYS = 14
PBKDF2_ITERATIONS = 260_000


class AuthError(Exception):
    """Erro amigável — a mensagem já vem pronta pra mostrar pro usuário final."""
    pass


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    check_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(check_hash, password_hash)


def create_user(email: str, username: str, password: str) -> dict:
    email = email.lower().strip()
    username = username.strip()

    if len(password) < 8:
        raise AuthError("A senha precisa ter pelo menos 8 caracteres.")

    with get_db() as conn:
        if conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("Já existe uma conta com esse e-mail.")
        if conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
            raise AuthError("Esse nome de usuário já está em uso.")

        password_hash, salt = hash_password(password)
        storage_key = secrets.token_hex(16)
        verification_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).isoformat()

        cur = conn.execute(
            "INSERT INTO users (email, username, password_hash, password_salt, storage_key, "
            "verification_token, verification_sent_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (email, username, password_hash, salt, storage_key, verification_token, now, now),
        )
        conn.commit()
        return {
            "id": cur.lastrowid, "email": email, "username": username,
            "storage_key": storage_key, "verification_token": verification_token,
        }


def get_user_by_email(email: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
        return dict(row) if row else None


def verify_email_token(token: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM users WHERE verification_token = ?", (token,)).fetchone()
        if not row:
            return False
        conn.execute("UPDATE users SET email_verified = 1, verification_token = NULL WHERE id = ?", (row["id"],))
        conn.commit()
        return True


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DURATION_DAYS)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
        conn.commit()
    return token


def get_user_from_session(token: str | None) -> dict | None:
    if not token:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT sessions.expires_at AS session_expires_at, users.* "
            "FROM sessions JOIN users ON users.id = sessions.user_id WHERE sessions.token = ?",
            (token,),
        ).fetchone()
        if not row:
            return None
        expires_at = datetime.fromisoformat(row["session_expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None
        return dict(row)


def delete_session(token: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def regenerate_verification_token(email: str) -> str:
    """Gera um novo link de confirmação (ex: usuário perdeu o e-mail antigo
    ou o link expirou)."""
    email = email.lower().strip()
    with get_db() as conn:
        row = conn.execute("SELECT id, email_verified FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            raise AuthError("Não existe conta com esse e-mail.")
        if row["email_verified"]:
            raise AuthError("Esse e-mail já está confirmado.")
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE users SET verification_token = ?, verification_sent_at = ? WHERE id = ?",
            (token, now, row["id"]),
        )
        conn.commit()
        return token
