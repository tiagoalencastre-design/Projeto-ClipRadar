"""
Registry — decide qual provedor usar para cada tarefa. Fase 3.

É o único lugar que junta as três informações necessárias:
  1. o modo do app (mock bloqueia IA de propósito)
  2. a chave de API (vem do ambiente, nunca de arquivo versionado)
  3. qual modelo cada tarefa deve usar

Assim o objetivo do plano fica possível sem mexer no resto do código:

    title              -> modelo barato
    edit_plan          -> modelo mais forte
    classification     -> modelo barato
    complex_reasoning  -> Claude, no futuro

Basta editar AITaskRouting no core/app_config.py.
"""
from __future__ import annotations

from core.ai_providers.base import TextProvider
from core.ai_providers.openai_provider import OpenAITextProvider
from core.app_config import get_ai_api_key, get_app_config

VALID_TASKS = ("title", "edit_plan", "classification", "complex_reasoning")


def is_ai_available() -> bool:
    """True se existe chave E o modo atual permite chamadas pagas."""
    return get_ai_api_key() is not None


def get_provider(task: str = "title") -> TextProvider | None:
    """
    Devolve o provedor configurado para a tarefa, ou None se a IA não
    estiver disponível (sem chave, ou modo mock).

    None NÃO é erro — é o sinal de "use o caminho gratuito".
    """
    api_key = get_ai_api_key()
    if api_key is None:
        return None

    config = get_app_config()
    return OpenAITextProvider(
        api_key=api_key,
        base_url=config.ai.base_url,
        timeout_seconds=config.ai.timeout_seconds,
        max_retries=config.ai.max_retries,
        provider_name=config.ai.provider,
    )


def get_model_for_task(task: str) -> str:
    """Qual modelo usar nessa tarefa. Tarefa desconhecida cai no de título."""
    tasks = get_app_config().ai.tasks
    return getattr(tasks, task, tasks.title)
