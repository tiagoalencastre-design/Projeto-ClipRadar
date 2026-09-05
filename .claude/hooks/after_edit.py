"""
Hook PostToolUse — verificação DIRECIONADA após editar um arquivo.

POR QUE NÃO RODA A SUÍTE INTEIRA: os 459 testes levam ~13s. Rodar tudo a
cada edição desperdiça tempo e polui a saída. Aqui rodamos apenas os
arquivos de teste que realmente exercitam o módulo alterado.

A suíte completa continua rodando no fim da tarefa (hook Stop) e pode ser
chamada a qualquer momento com:
    python -m unittest discover -s tests

ENTRADA: JSON no stdin, conforme o protocolo de hooks do Claude Code.
    {"tool_name": "...", "tool_input": {"file_path": "..."}, ...}

SAÍDA: mensagem no stdout. Sai sempre com 0 — este hook informa, não bloqueia.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0   # sem payload utilizável: não atrapalha

    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not file_path:
        return 0

    path = Path(file_path)
    project = Path(payload.get("cwd") or ".")

    # Só nos interessam fontes Python do projeto.
    if path.suffix != ".py":
        return 0
    parts = path.as_posix()
    if "/core/" not in parts and "/tests/" not in parts:
        return 0

    tests_dir = project / "tests"
    if not tests_dir.is_dir():
        return 0

    # Editou um teste? roda só ele.
    if "/tests/" in parts:
        targets = [path.stem]
    else:
        # Editou um módulo do core: roda os testes que o importam.
        module = path.stem
        pattern = re.compile(rf"\b(core\.{module}|from core import .*\b{module}\b)")
        targets = [
            test.stem for test in sorted(tests_dir.glob("test_*.py"))
            if pattern.search(test.read_text(encoding="utf-8", errors="ignore"))
        ]

    if not targets:
        print(f"[hook] {path.name}: nenhum teste direcionado encontrado. "
              f"Rode a suíte completa antes de concluir.")
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "unittest", *[f"tests.{t}" for t in targets]],
        cwd=project, capture_output=True, text=True,
    )
    tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
    status = "OK" if result.returncode == 0 else "FALHOU"
    print(f"[hook] testes direcionados ({len(targets)}): {status}")
    for line in tail:
        print(f"       {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
