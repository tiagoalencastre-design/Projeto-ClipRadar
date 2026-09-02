"""
Estrutura de MCP — Fase 9.

DESLIGADO POR PADRÃO e de propósito. `flags.mcp_enabled` é sempre False no
app_config, em todos os modos.

O que existe aqui é só o esqueleto: uma descrição de quais ferramentas o
ClipRadar exporia se algum dia virasse um servidor MCP. Nada é executado,
nada é servido, nenhuma dependência nova foi adicionada.

Por que criar isso agora, se está desligado: pra que a decisão de quais
ferramentas expor seja tomada com calma, escrita e revisável, em vez de
improvisada no dia em que precisar.
"""
from core.mcp.tools import MCP_TOOLS, describe_tools, is_mcp_enabled

__all__ = ["MCP_TOOLS", "describe_tools", "is_mcp_enabled"]
