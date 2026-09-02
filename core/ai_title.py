"""
Gera um título curto e chamativo pra thumbnail.

FASE 4: não fala mais com a OpenAI diretamente — usa a camada
core/ai_providers. O comportamento é idêntico ao de antes.

Se não tiver chave configurada, se o modo do app bloquear IA, ou se a
chamada falhar por qualquer motivo (sem internet, chave inválida, sem
crédito), retorna None — quem chama isto cai de volta pro método extrativo,
sem quebrar o app.
"""
from __future__ import annotations

from core.ai_providers import get_provider
from core.ai_providers.registry import get_model_for_task

_SYSTEM_PROMPT = (
    "Você cria títulos curtos e chamativos para thumbnails de "
    "vídeos de gaming, no MESMO idioma do texto recebido. "
    "Responda APENAS com o título em si, sem aspas, sem "
    "explicação, no máximo 6 palavras."
)


def generate_ai_title(
    transcript_excerpt: str,
    api_key: str | None = None,
    model: str | None = None,
) -> str | None:
    """
    api_key e model continuam na assinatura por compatibilidade — quem já
    chamava esta função (thumbnail.py) não precisa mudar nada. Mas os dois
    são opcionais agora: sem eles, a configuração central decide.
    """
    if not transcript_excerpt:
        return None

    provider = get_provider("title")
    if provider is None:
        return None

    title = provider.complete_text(
        system=_SYSTEM_PROMPT,
        user=transcript_excerpt,
        model=model or get_model_for_task("title"),
        max_tokens=20,
        temperature=0.9,
    )
    if not title:
        return None
    return title.strip().strip('"').upper()
