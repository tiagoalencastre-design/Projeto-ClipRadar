"""
Gera um título curto e chamativo pra thumbnail, usando a API da OpenAI (não é
o ChatGPT em si — é a API paga separadamente, veja config/settings.yaml).

Se não tiver chave configurada, ou se a chamada falhar por qualquer motivo
(sem internet, chave inválida, sem crédito), retorna None — quem chama isto
deve cair de volta pro método extrativo, sem quebrar o app.
"""
from __future__ import annotations


def generate_ai_title(transcript_excerpt: str, api_key: str, model: str = "gpt-4o-mini") -> str | None:
    if not transcript_excerpt or not api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError:
        return None

    try:
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Você cria títulos curtos e chamativos para thumbnails de "
                        "vídeos de gaming, no MESMO idioma do texto recebido. "
                        "Responda APENAS com o título em si, sem aspas, sem "
                        "explicação, no máximo 6 palavras."
                    ),
                },
                {"role": "user", "content": transcript_excerpt},
            ],
            max_tokens=20,
            temperature=0.9,
        )
        title = response.choices[0].message.content
        if not title:
            return None
        return title.strip().strip('"').upper()
    except Exception:
        return None