"""
Hook PostToolUse — verificação rápida após editar um arquivo Python.

O QUE ELE FAZ: compila o arquivo editado (checagem de sintaxe). Só isso.

O QUE ELE NÃO FAZ, E POR QUÊ: não roda testes. Rodar a suíte inteira a cada
edição custa ~12 segundos e polui a saída. E mapear "arquivo editado" para
"testes relevantes" exigiria uma heurística (procurar o nome do módulo dentro
dos arquivos de teste) que erra em silêncio quando a relação é indireta —
um teste que exercita o módulo sem citá-lo pelo nome não seria executado, e
a impressão de cobertura seria falsa.

Preferimos uma verificação 100% confiável e barata. A suíte completa roda no
fim da tarefa (hook Stop) e pode ser chamada a qualquer momento:

    python -m unittest discover -s tests

ENTRADA: JSON no stdin (protocolo de hooks do Claude Code), com
tool_input.file_path.
SAÍDA: mensagem no stdout. Sai sempre com 0 — este hook informa, não bloqueia.
"""
from __future__ import annotations

import json
import py_compile
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not file_path.endswith(".py"):
        return 0

    path = Path(file_path)
    if not path.is_file():
        return 0

    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as e:
        print(f"[hook] ERRO DE SINTAXE em {path.name}:")
        print(f"       {e.msg.strip().splitlines()[-1]}")
        return 0

    print(f"[hook] {path.name}: sintaxe OK. "
          f"Rode a suíte completa antes de concluir a tarefa.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
