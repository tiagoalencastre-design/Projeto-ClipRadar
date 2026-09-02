"""
Armazenamento de jobs com persistência automática — Fase 2b.

O PROBLEMA que isto resolve:
    O api_server.py guarda o estado dos processamentos em três dicionários
    na memória RAM. Se o servidor reinicia (ou cai), todo o histórico some.
    As tabelas do banco existiam desde a Fase 2, mas ninguém escrevia nelas.

A SOLUÇÃO:
    Um dicionário que se comporta EXATAMENTE como um dicionário comum, mas
    que, além de guardar na memória, espelha as mudanças no banco.

    No api_server.py, muda só a linha de criação:

        jobs: dict[str, dict] = {}                  # antes
        jobs = PersistentJobStore("generate")       # depois

    Todo o resto do código continua igual, sem exceção:

        jobs[job_id] = {"status": "running", "user_id": 1, ...}
        jobs[job_id].update({"status": "done"})
        jobs[job_id]["step"] = "transcrevendo"
        del jobs[job_id]

    Cada uma dessas linhas continua funcionando como sempre — e agora
    também grava no banco, sem ninguém precisar lembrar de fazer isso.

POR QUE assim, em vez de espalhar chamadas de banco pelo api_server.py:
    Menos lugares pra errar. Uma chamada esquecida num dos ~10 pontos de
    atualização viraria um job com status errado no histórico. Aqui é
    impossível esquecer, porque quem grava é a própria estrutura.

GARANTIA DE SEGURANÇA:
    A memória continua sendo a fonte da verdade pro que está acontecendo
    AGORA. O banco é só o histórico. Se o banco falhar, o repositório
    devolve None, o aviso aparece no console, e o processamento segue
    normalmente. Nenhum clipe se perde por causa disso.
"""
from __future__ import annotations

from core.repositories import JobRepository

# Campos que fazem sentido espelhar no banco. Qualquer outra chave do
# dicionário (created_at, video_name, result...) fica só na memória.
_PERSISTED_FIELDS = ("status", "step", "error")


class _TrackedJob(dict):
    """
    Um job individual. É um dicionário normal, mas quando 'status', 'step'
    ou 'error' mudam, a alteração também vai pro banco.
    """

    def __init__(self, data: dict, job_id: str):
        super().__init__(data)
        self._job_id = job_id

    def _sync(self) -> None:
        status = self.get("status")
        if not status:
            return
        JobRepository.update_status(
            self._job_id,
            status=status,
            step=self.get("step"),
            error=self.get("error"),
        )

    def __setitem__(self, key, value) -> None:
        super().__setitem__(key, value)
        if key in _PERSISTED_FIELDS:
            self._sync()

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)
        changed = set()
        for arg in args:
            changed.update(arg.keys() if hasattr(arg, "keys") else dict(arg).keys())
        changed.update(kwargs.keys())
        if changed & set(_PERSISTED_FIELDS):
            self._sync()


class PersistentJobStore(dict):
    """
    Substitui `dict[str, dict]` no api_server.py.

    job_type identifica de onde vem o job ("generate", "analyze",
    "youtube_download") e é gravado na coluna job_type da tabela jobs.
    """

    def __init__(self, job_type: str):
        super().__init__()
        self._job_type = job_type

    def __setitem__(self, job_id: str, value: dict) -> None:
        tracked = _TrackedJob(value, job_id)
        super().__setitem__(job_id, tracked)

        # Só registra no banco se soubermos de quem é o job. Sem user_id não
        # dá pra gravar (a coluna é obrigatória) — nesse caso o job continua
        # funcionando normalmente, só não entra no histórico.
        user_id = value.get("user_id")
        if user_id is None:
            return

        JobRepository.create(
            job_id=job_id,
            user_id=user_id,
            job_type=self._job_type,
            video_id=value.get("video_id"),
        )

        # Grava o status inicial (create() sempre insere como 'queued').
        if value.get("status") and value["status"] != "queued":
            tracked._sync()

    def setdefault(self, job_id, default=None):
        if job_id not in self:
            self[job_id] = default if default is not None else {}
        return self[job_id]

    def update(self, *args, **kwargs):
        """Atualizar o STORE inteiro (raro) — cada item entra pelo caminho
        normal, então cada um é registrado corretamente."""
        for arg in args:
            for k, v in (arg.items() if hasattr(arg, "items") else arg):
                self[k] = v
        for k, v in kwargs.items():
            self[k] = v

    # Nota sobre `del jobs[job_id]`: a limpeza periódica remove jobs velhos
    # da MEMÓRIA. O registro no banco continua lá de propósito — é
    # justamente o histórico que a Fase 2 quer preservar.
