"""
Camada de abstração de IA — Fase 3.

O resto do app NUNCA fala com a OpenAI (nem com nenhum outro provedor)
diretamente. Tudo passa por aqui.

Uso típico:

    from core.ai_providers import get_provider

    provider = get_provider("title")
    if provider is None:
        ...  # IA indisponível — usa o fallback gratuito
    else:
        texto = provider.complete(system="...", user="...")
"""
from core.ai_providers.base import TextProvider, TextResponse
from core.ai_providers.openai_provider import OpenAITextProvider
from core.ai_providers.registry import get_provider, is_ai_available

__all__ = [
    "TextProvider",
    "TextResponse",
    "OpenAITextProvider",
    "get_provider",
    "is_ai_available",
]
