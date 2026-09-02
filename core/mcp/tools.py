"""
Catálogo das ferramentas MCP planejadas — Fase 9.

NADA AQUI EXECUTA. É uma descrição, não uma implementação. Cada ferramenta
tem nome, descrição e se é somente-leitura.

A separação read_only importa: se um dia isso for ligado, uma IA externa
poderia chamar essas ferramentas. Ferramenta que só lê é segura; ferramenta
que gasta processamento ou apaga arquivo precisa de confirmação humana.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.app_config import get_app_config


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    read_only: bool


MCP_TOOLS: tuple[MCPTool, ...] = (
    MCPTool("list_videos", "Lista os vídeos enviados pelo usuário", read_only=True),
    MCPTool("list_clips", "Lista os clipes já gerados", read_only=True),
    MCPTool("get_job_status", "Consulta o andamento de um processamento", read_only=True),
    MCPTool("get_analysis", "Lê os momentos candidatos e seus scores", read_only=True),
    MCPTool("explain_score", "Explica quais sinais pesaram num momento", read_only=True),
    # As de escrita ficam declaradas, mas exigiriam confirmação explícita:
    MCPTool("generate_clips", "Inicia a geração de clipes de um vídeo", read_only=False),
    MCPTool("render_clip", "Renderiza um clipe específico com ajustes", read_only=False),
)


def is_mcp_enabled() -> bool:
    """Sempre False nesta fase. É o portão que mantém tudo desligado."""
    return get_app_config().flags.mcp_enabled


def describe_tools() -> list[dict]:
    """Catálogo em formato simples — útil pra documentação e pra interface."""
    return [
        {"name": t.name, "description": t.description, "read_only": t.read_only}
        for t in MCP_TOOLS
    ]
