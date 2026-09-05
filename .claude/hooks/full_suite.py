"""
Suíte completa de testes.

Executa exatamente:
    python -m unittest discover -s tests

Serve para duas coisas:
  - hook Stop (fim de tarefa), com o contexto vindo pelo stdin;
  - execução manual: `python .claude/hooks/full_suite.py`

Sai com 0 quando usado como hook (informar, não travar o encerramento) e
com o código real do unittest quando chamado direto no terminal, para
funcionar em script.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    as_hook = not sys.stdin.isatty()
    project = Path.cwd()

    if as_hook:
        try:
            payload = json.load(sys.stdin)
            project = Path(payload.get("cwd") or ".")
        except (json.JSONDecodeError, ValueError):
            pass

    if not (project / "tests").is_dir():
        print("[hook] pasta tests/ não encontrada.")
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=project, capture_output=True, text=True,
    )
    output = (result.stderr or result.stdout).strip()
    for line in output.splitlines()[-4:]:
        print(f"       {line}")
    print(f"[suíte] {'OK' if result.returncode == 0 else 'FALHOU'}")

    return 0 if as_hook else result.returncode


if __name__ == "__main__":
    sys.exit(main())
