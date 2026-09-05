"""
Limite de tentativas por IP.

O QUE PROTEGE:
    /api/auth/login                força bruta de senha
    /api/auth/signup               criação de contas em massa
    /api/auth/resend-verification  uso do servidor para enviar spam

COMO FUNCIONA: janela deslizante em memória. Guardamos os horários das
tentativas recentes de cada chave e contamos quantas cabem na janela.

LIMITAÇÃO HONESTA: o estado vive na memória do processo. Reiniciar o
servidor zera os contadores, e com vários processos cada um teria a sua
contagem. Para o uso atual (um processo, uvicorn local ou atrás de um
túnel) isso resolve o problema real, que é alguém tentando mil senhas em
sequência. Se um dia houver mais de um processo, isto vira Redis — a
interface não muda.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, max_attempts: int, window_seconds: int, label: str):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.label = label
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._hits[key]
        limite = now - self.window_seconds
        while hits and hits[0] < limite:
            hits.popleft()
        return hits

    def check(self, key: str) -> None:
        """Registra a tentativa. Levanta 429 quando passa do limite."""
        now = time.time()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.max_attempts:
                espera = int(self.window_seconds - (now - hits[0])) + 1
                raise HTTPException(
                    429,
                    f"Muitas tentativas. Aguarde {max(espera // 60, 1)} minuto(s) "
                    f"e tente de novo.",
                    headers={"Retry-After": str(espera)},
                )
            hits.append(now)

    def reset(self, key: str) -> None:
        """Zera a contagem — chamado quando o login dá certo, para que
        alguém que errou a senha duas vezes e acertou não fique penalizado."""
        with self._lock:
            self._hits.pop(key, None)


def client_key(request: Request, suffix: str = "") -> str:
    """
    Identidade do cliente para fins de limite.

    Usa o IP da conexão. Atrás de um proxy (cloudflared, nginx) todos os
    pedidos chegariam com o mesmo IP, então respeitamos X-Forwarded-For
    quando presente — com a ressalva de que esse cabeçalho é falsificável
    se o proxy não o sobrescrever.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (
        request.client.host if request.client else "desconhecido"
    )
    return f"{ip}:{suffix}" if suffix else ip


# Limites por rota. Números escolhidos para não atrapalhar uso legítimo:
# ninguém erra a senha 8 vezes em 5 minutos sem estar tentando adivinhar.
login_limiter = RateLimiter(max_attempts=8, window_seconds=300, label="login")
signup_limiter = RateLimiter(max_attempts=5, window_seconds=3600, label="signup")
resend_limiter = RateLimiter(max_attempts=3, window_seconds=3600, label="resend")
