"""
Configuração central do ClipRadar — Fase 1 (expandida).

Um único lugar pra saber em que "modo" o app está rodando, quais recursos
estão ligados, e como as várias partes do sistema estão configuradas
(IA, pipeline, storage, fila, observabilidade).

REGRA DE OURO DESTE ARQUIVO:
    Configuração  -> pode aparecer em log, em print, no /api/system/config.
    Segredo       -> NUNCA. Chave de API só sai de variável de ambiente,
                     é lida na hora do uso, e nunca entra em as_dict().

Modos possíveis (variável de ambiente CLIPRADAR_MODE):

    development  — (padrão) uso normal no seu PC, dia a dia. Recursos de IA
                   opcionais continuam funcionando como antes.

    mock         — modo de teste seguro: MESMO que exista chave de API real
                   no .env, nenhuma chamada paga é feita. Os recursos de IA
                   caem no fallback gratuito.
                   ("test" é aceito como apelido de "mock".)

    production   — reservado pro futuro. Hoje se comporta igual a
                   "development" — é só o encaixe pronto.

Se CLIPRADAR_MODE não existir, ou vier com valor desconhecido, o app usa
"development" e avisa no console (nunca quebra por causa disso).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path

VALID_MODES = ("development", "mock", "production")
DEFAULT_MODE = "development"

# "test" é o nome pedido no plano arquitetural; internamente é o mesmo
# comportamento de "mock" (IA bloqueada). Aceitar os dois evita quebrar
# o .env e os testes que já usam "mock".
MODE_ALIASES = {"test": "mock", "dev": "development", "prod": "production"}


# ============================================================
# Feature flags
# ============================================================

@dataclass(frozen=True)
class FeatureFlags:
    """
    Cada flag descreve se um RECURSO pode ser usado — não necessariamente
    se ele JÁ está configurado (ex: ai_processing_enabled=True não significa
    que existe chave de API válida, só que o recurso não está bloqueado de
    propósito pelo modo atual).
    """
    ai_processing_enabled: bool       # título por IA + Edit Plan
    video_processing_enabled: bool    # pipeline local (sempre sem custo)
    auto_clipping_enabled: bool       # seleção automática dos melhores momentos
    captions_enabled: bool            # legenda queimada
    mcp_enabled: bool                 # Fase 9 — desligado
    payments_enabled: bool            # sem cobrança implementada
    analytics_enabled: bool           # "em breve"
    # Novas na Fase 1 expandida — todas desligadas, são só o encaixe:
    cloud_storage_enabled: bool = False       # futuro — hoje é só disco local
    distributed_queue_enabled: bool = False   # Fase 7 — hoje é threading.Thread
    structured_logging_enabled: bool = False  # Fase 8 — hoje ainda é print()
    credits_enabled: bool = False             # futuro — sem créditos ainda


# ============================================================
# Configuração de IA (sem segredos!)
# ============================================================

@dataclass(frozen=True)
class AITaskRouting:
    """
    Qual modelo usar pra cada tipo de tarefa. Hoje tudo aponta pro modelo
    barato — mas a estrutura já permite apontar cada tarefa pra um modelo
    diferente quando a Fase 3 (provider layer) existir de fato.
    """
    title: str = "gpt-4o-mini"              # título de thumbnail — tarefa simples
    edit_plan: str = "gpt-4o-mini"          # análise editorial
    classification: str = "gpt-4o-mini"     # reservado
    complex_reasoning: str = "gpt-4o-mini"  # reservado — vira modelo forte depois


@dataclass(frozen=True)
class AIConfig:
    """
    ATENÇÃO: nenhuma chave de API mora aqui. Só o NOME da variável de
    ambiente onde ela deve estar. Quem precisa da chave chama
    get_ai_api_key() na hora do uso.
    """
    provider: str                  # "openai" | "omniroute"
    base_url: str | None           # None = endpoint padrão do provider
    api_key_env_var: str           # nome da variável, não o valor
    timeout_seconds: int
    max_retries: int
    tasks: AITaskRouting

    @property
    def has_api_key(self) -> bool:
        """Se existe chave configurada — booleano, nunca o valor."""
        return bool(os.environ.get(self.api_key_env_var, "").strip())

    def as_dict(self) -> dict:
        """Versão segura pra log/endpoint público — sem valor de segredo."""
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "tasks": asdict(self.tasks),
            "has_api_key": self.has_api_key,
        }


# ============================================================
# Pipeline / storage / fila / observabilidade
# ============================================================

@dataclass(frozen=True)
class PipelineConfig:
    """
    Os ajustes finos do pipeline (whisper, thresholds, pesos do score)
    continuam no settings.yaml — este objeto só diz ONDE encontrá-lo e
    quais são os limites de execução.
    """
    settings_path: str = "config/settings.yaml"
    max_concurrent_jobs: int = 2
    job_expiry_seconds: int = 24 * 60 * 60


@dataclass(frozen=True)
class StorageConfig:
    """Onde os arquivos vivem. Hoje sempre disco local."""
    backend: str = "local"          # "local" | "s3" (futuro)
    vods_dir: str = "data/vods"
    clips_dir: str = "data/clips"
    cache_dir: str = "data/cache"
    database_path: str = "data/cliparadar.db"
    max_upload_size_bytes: int = 2 * 1024 * 1024 * 1024   # 2 GB

    def ensure_dirs(self) -> None:
        for d in (self.vods_dir, self.clips_dir, self.cache_dir):
            Path(d).mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class QueueConfig:
    """
    Hoje é threading.Thread dentro do próprio processo. A Fase 7 troca o
    backend sem mexer em quem usa.
    """
    backend: str = "thread"         # "thread" | "redis" (futuro)
    max_workers: int = 2


@dataclass(frozen=True)
class ObservabilityConfig:
    """
    Hoje structured=False = continua usando print(), igual a antes.
    A Fase 8 liga o logging estruturado sem mudar as chamadas.
    """
    level: str = "INFO"
    structured: bool = False
    track_cost: bool = False        # medir custo por processamento — Fase 8


# ============================================================
# AppConfig
# ============================================================

@dataclass(frozen=True)
class AppConfig:
    mode: str
    flags: FeatureFlags
    ai: AIConfig
    pipeline: PipelineConfig
    storage: StorageConfig
    queue: QueueConfig
    observability: ObservabilityConfig
    base_url: str = "http://localhost:8000"

    def as_dict(self) -> dict:
        """
        Formato seguro pra expor publicamente (/api/system/config).
        As chaves "mode" e "flags" existem desde a Fase 1 original e NÃO
        podem mudar de nome — o front-end e os testes dependem delas.
        """
        return {
            "mode": self.mode,
            "flags": asdict(self.flags),
            "ai": self.ai.as_dict(),
            "pipeline": asdict(self.pipeline),
            "storage": asdict(self.storage),
            "queue": asdict(self.queue),
            "observability": asdict(self.observability),
            "base_url": self.base_url,
        }


# ============================================================
# Construção
# ============================================================

def _resolve_mode() -> str:
    raw = os.environ.get("CLIPRADAR_MODE", DEFAULT_MODE).strip().lower()
    raw = MODE_ALIASES.get(raw, raw)
    if raw not in VALID_MODES:
        print(
            f"[ClipRadar] CLIPRADAR_MODE='{raw}' não é válido (use: {', '.join(VALID_MODES)}). "
            f"Usando '{DEFAULT_MODE}' por padrão."
        )
        return DEFAULT_MODE
    return raw


def _build_flags(mode: str) -> FeatureFlags:
    # No modo mock, IA fica DESLIGADA por decisão do modo, mesmo que exista
    # chave real no .env — é essa a garantia de "não gasta sem querer".
    ai_allowed_by_mode = mode != "mock"

    return FeatureFlags(
        ai_processing_enabled=ai_allowed_by_mode,
        video_processing_enabled=True,   # local, sem custo — nunca bloqueado
        auto_clipping_enabled=True,
        captions_enabled=True,
        mcp_enabled=False,
        payments_enabled=False,
        analytics_enabled=False,
        cloud_storage_enabled=False,
        distributed_queue_enabled=False,
        structured_logging_enabled=False,
        credits_enabled=False,
    )


def _read_int_env(name: str, default: int) -> int:
    """Lê inteiro do ambiente sem nunca quebrar o boot por causa de typo."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[ClipRadar] {name}='{raw}' não é número. Usando {default}.")
        return default


def _build_ai_config() -> AIConfig:
    provider = os.environ.get("CLIPRADAR_AI_PROVIDER", "openai").strip().lower()

    if provider == "omniroute":
        # OmniRoute expõe endpoint compatível com OpenAI, então o resto do
        # código não muda — só o base_url e a variável da chave.
        base_url = os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128/v1")
        key_var = "OMNIROUTE_API_KEY"
    else:
        provider = "openai"
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip() or None
        key_var = "OPENAI_API_KEY"

    return AIConfig(
        provider=provider,
        base_url=base_url,
        api_key_env_var=key_var,
        timeout_seconds=_read_int_env("CLIPRADAR_AI_TIMEOUT", 30),
        max_retries=_read_int_env("CLIPRADAR_AI_MAX_RETRIES", 2),
        tasks=AITaskRouting(),
    )


def get_app_config() -> AppConfig:
    """Lê o modo atual e monta toda a configuração. Chame isso sempre que
    precisar saber 'estou em que modo', 'esse recurso pode rodar agora' ou
    'onde ficam os arquivos' — nunca leia variável de ambiente direto em
    outro arquivo."""
    mode = _resolve_mode()
    return AppConfig(
        mode=mode,
        flags=_build_flags(mode),
        ai=_build_ai_config(),
        pipeline=PipelineConfig(),
        storage=StorageConfig(),
        queue=QueueConfig(),
        observability=ObservabilityConfig(),
        base_url=os.environ.get("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
    )


def get_ai_api_key() -> str | None:
    """
    ÚNICO lugar do sistema autorizado a ler uma chave de API.

    Devolve None se o modo atual bloqueia IA — assim, mesmo que alguém
    esqueça de checar a flag, o modo mock continua não gastando dinheiro.
    """
    config = get_app_config()
    if not config.flags.ai_processing_enabled:
        return None
    key = os.environ.get(config.ai.api_key_env_var, "").strip()
    return key or None
