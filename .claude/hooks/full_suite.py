"""
Hook Stop — suíte completa ao FIM da tarefa.

Complementa o after_edit.py: durante o trabalho rodam testes direcionados
(rápidos); ao encerrar, roda tudo. Assim nenhuma regressão passa, sem
pagar 13 segundos a cada edição.

Sai sempre com 0: informar é o objetivo, não travar o encerramento.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    project = Path(payload.get("cwd") or ".")
    if not (project / "tests").is_dir():
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=project, capture_output=True, text=True,
    )
    tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
    print(f"[hook] suíte completa: {'OK' if result.returncode == 0 else 'FALHOU'}")
    for line in tail:
        print(f"       {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
