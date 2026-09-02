"""
A interface que todo provedor de texto precisa implementar — Fase 3.

Por que isto existe: hoje só há a OpenAI. Amanhã pode haver OmniRoute,
Claude, ou um modelo local. Se o app inteiro chamasse a OpenAI direto,
trocar significaria mexer em todo lugar. Com esta interface, trocar de
provedor é trocar uma linha no .env.

REGRA QUE NUNCA MUDA:
    Falha de IA nunca derruba o pipeline de vídeo. Toda implementação
    devolve None quando algo dá errado — sem internet, sem crédito, chave
    inválida, resposta malformada. Quem chama SEMPRE precisa ter um
    caminho alternativo gratuito.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TextResponse:
    """
    Resposta de um provedor.

    Além do texto, carrega de qual provedor/modelo veio e quantos tokens
    custou — a base pro cálculo de custo real da Fase 8. Hoje ninguém usa
    esses campos ainda; eles só ficam disponíveis.
    """
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None or self.completion_tokens is None:
            return None
        return self.prompt_tokens + self.completion_tokens


class TextProvider(ABC):
    """
    Interface de um provedor de texto.

    Implementações concretas: OpenAITextProvider (e, no futuro,
    OmniRouteTextProvider — que na prática reusa a mesma, já que o
    OmniRoute fala o protocolo da OpenAI).
    """

    name: str = "base"

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 300,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> TextResponse | None:
        """
        Envia um prompt e devolve a resposta.

        json_mode=True pede ao modelo que responda com JSON válido — usado
        pelo Edit Plan.

        NUNCA levanta exceção: devolve None em qualquer falha.
        """
        raise NotImplementedError

    def complete_text(self, *args, **kwargs) -> str | None:
        """Atalho pra quem só quer o texto, sem os metadados."""
        response = self.complete(*args, **kwargs)
        return response.text if response else None
