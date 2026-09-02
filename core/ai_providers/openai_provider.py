"""
Implementação concreta para a OpenAI — Fase 3.

Serve também para o OmniRoute: como ele expõe um endpoint compatível com o
protocolo da OpenAI, basta apontar o base_url pra ele. Por isso não existe
um arquivo omni_route_provider.py separado — seria código duplicado.
"""
from __future__ import annotations

from core.ai_providers.base import TextProvider, TextResponse


class OpenAITextProvider(TextProvider):
    name = "openai"

    def __init__(
        self,
        api_key: str,
        base_url: str | None = None,
        timeout_seconds: int = 30,
        max_retries: int = 2,
        provider_name: str | None = None,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        if provider_name:
            self.name = provider_name

    def _client(self):
        """Cria o cliente na hora do uso. O import fica aqui dentro de
        propósito: se a biblioteca openai não estiver instalada, o app
        continua funcionando sem IA em vez de falhar ao iniciar."""
        from openai import OpenAI

        kwargs = {
            "api_key": self._api_key,
            "timeout": self._timeout,
            "max_retries": self._max_retries,
        }
        if self._base_url:
            kwargs["base_url"] = self._base_url
        return OpenAI(**kwargs)

    def complete(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 300,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> TextResponse | None:
        if not self._api_key or not user:
            return None

        # Nota: não checamos o import aqui de propósito. O _client() já faz
        # o import, e um ImportError (biblioteca openai não instalada) cai
        # no except abaixo, junto com as demais falhas — devolvendo None e
        # deixando o pipeline seguir pelo caminho gratuito.
        try:
            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = self._client().chat.completions.create(**kwargs)
            text = response.choices[0].message.content
            if not text:
                return None

            usage = getattr(response, "usage", None)
            return TextResponse(
                text=text,
                provider=self.name,
                model=model,
                prompt_tokens=getattr(usage, "prompt_tokens", None),
                completion_tokens=getattr(usage, "completion_tokens", None),
            )
        except Exception:
            # Sem crédito, sem internet, chave inválida, timeout... o
            # pipeline de vídeo continua normalmente com o fallback.
            return None
