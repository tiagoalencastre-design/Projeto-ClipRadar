"""
Abstração de fila de jobs — Fase 7.

HOJE: continua sendo threading.Thread dentro do próprio processo, exatamente
como antes. Nada ficou mais lento, nada mudou de comportamento.

POR QUE existe: quando o ClipRadar precisar de worker separado (Redis, Celery,
RQ), a troca acontece AQUI dentro. Quem chama não muda nenhuma linha.

    from core.queue import get_queue
    get_queue().submit(minha_funcao, arg1, arg2)

O backend vem de app_config.queue.backend. Hoje só "thread" existe; se
alguém configurar outro valor, cai no thread com um aviso — nunca quebra.
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Callable

from core.app_config import get_app_config


class JobQueue(ABC):
    """Interface de fila. Toda implementação precisa destes três métodos."""

    name: str = "base"

    @abstractmethod
    def submit(self, func: Callable, *args, **kwargs) -> bool:
        """Coloca o trabalho pra rodar. True se aceitou."""
        raise NotImplementedError

    @abstractmethod
    def active_count(self) -> int:
        """Quantos jobs estão rodando agora."""
        raise NotImplementedError

    @abstractmethod
    def has_capacity(self) -> bool:
        """Se ainda cabe mais um job."""
        raise NotImplementedError


class ThreadQueue(JobQueue):
    """
    Implementação atual: uma thread por job, com limite de simultâneos.

    É o mesmo comportamento que o api_server.py já tinha — só que agora
    encapsulado num lugar só, contável e testável.
    """

    name = "thread"

    def __init__(self, max_workers: int = 2):
        self._max_workers = max_workers
        self._lock = threading.Lock()
        self._active = 0

    def active_count(self) -> int:
        with self._lock:
            return self._active

    def has_capacity(self) -> bool:
        with self._lock:
            return self._active < self._max_workers

    def _acquire(self) -> bool:
        with self._lock:
            if self._active >= self._max_workers:
                return False
            self._active += 1
            return True

    def _release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)

    def submit(self, func: Callable, *args, **kwargs) -> bool:
        if not self._acquire():
            return False

        def _wrapped():
            try:
                func(*args, **kwargs)
            finally:
                # O release SEMPRE acontece, mesmo se o job explodir —
                # senão a fila entope e o usuário não consegue mais gerar nada.
                self._release()

        threading.Thread(target=_wrapped, daemon=True).start()
        return True


_queue_instance: JobQueue | None = None
_instance_lock = threading.Lock()


def get_queue() -> JobQueue:
    """Fila compartilhada do processo (criada uma vez só)."""
    global _queue_instance
    with _instance_lock:
        if _queue_instance is None:
            config = get_app_config()
            if config.queue.backend != "thread":
                print(
                    f"[ClipRadar] Fila '{config.queue.backend}' ainda não existe. "
                    f"Usando 'thread'."
                )
            _queue_instance = ThreadQueue(max_workers=config.queue.max_workers)
        return _queue_instance


def reset_queue() -> None:
    """Só pros testes — descarta a instância compartilhada."""
    global _queue_instance
    with _instance_lock:
        _queue_instance = None
