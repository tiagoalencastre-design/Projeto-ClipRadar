"""
Hook PreToolUse — bloqueia commit com chave de API real.

CONTEXTO: uma chave da OpenAI já vazou neste projeto, num comentário do
settings.yaml. O .gitignore protege o .env, mas não protege um segredo
colado por engano em outro arquivo.

ENTRADA: JSON no stdin (protocolo de hooks do Claude Code).
SAÍDA: exit 2 bloqueia a ferramenta e devolve a mensagem ao Claude.

CUIDADO COM FALSO POSITIVO: a checagem roda só sobre as linhas ADICIONADAS
no diff em stage, e ignora exemplos e testes. Chaves falsas usadas em teste
("sk-proj-CHAVE_FALSA_DE_TESTE") não podem bloquear o trabalho.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# Padrões de segredo REAL. Deliberadamente específicos: um regex largo
# demais bloquearia documentação legítima.
SECRET_PATTERNS = (
    re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
    re.compile(r"re_[A-Za-z0-9]{20,}"),                    # Resend
    re.compile(r"(OPENAI|RESEND|OMNIROUTE)_API_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{20,}"),
)

# Marcas de valor obviamente falso, usado em teste ou exemplo.
FAKE_MARKERS = ("FALSA", "FAKE", "EXAMPLE", "EXEMPLO", "XXXX", "your-key",
                "SUA_CHAVE", "PLACEHOLDER", "TEST")

# Arquivos onde chave falsa é esperada.
ALLOWED_PATHS = ("tests/", ".env.example", "CLAUDE.md", "DIAGNOSTICO")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\bgit\s+(commit|push)\b", command):
        return 0

    try:
        diff = subprocess.run(
            ["git", "diff", "--cached", "-U0"],
            cwd=payload.get("cwd") or ".",
            capture_output=True, text=True, timeout=20,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return 0   # sem git disponível: não bloqueia o trabalho

    current_file = ""
    offenders = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if any(allowed in current_file for allowed in ALLOWED_PATHS):
            continue
        if any(marker in line.upper() for marker in FAKE_MARKERS):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(line):
                offenders.append(f"{current_file}: {line[:60]}...")
                break

    if offenders:
        print("BLOQUEADO: possível chave de API nas linhas adicionadas.",
              file=sys.stderr)
        for item in offenders[:5]:
            print(f"  {item}", file=sys.stderr)
        print("Mova o segredo para o .env e refaça o stage.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
