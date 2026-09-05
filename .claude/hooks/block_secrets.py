"""
Hook PreToolUse — bloqueia commit com credencial real no staged diff.

CONTEXTO: uma chave da OpenAI já vazou neste projeto, colada num comentário
do settings.yaml. O .gitignore protege o .env, mas não protege um segredo
escrito por engano em outro arquivo.

COMO EVITA FALSO POSITIVO — três camadas:
  1. Os padrões exigem o FORMATO real da credencial (prefixo + comprimento),
     não a palavra "api_key". Documentação e código que mencionam api_key
     passam sem problema.
  2. Valores obviamente falsos (FAKE, EXEMPLO, SUA_CHAVE...) são ignorados.
  3. Arquivos onde chave falsa é esperada (tests/, .env.example, docs) são
     ignorados.

Nada é enviado para lugar nenhum: a checagem lê o diff local via git.

ENTRADA: JSON no stdin (protocolo de hooks do Claude Code).
SAÍDA: exit 2 bloqueia o commit e devolve a mensagem ao Claude.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys

# Formatos reais de credencial. Específicos de propósito.
SECRET_PATTERNS = (
    ("OpenAI",  re.compile(r"sk-proj-[A-Za-z0-9_-]{20,}")),
    ("OpenAI",  re.compile(r"sk-[A-Za-z0-9]{32,}")),
    ("Resend",  re.compile(r"re_[A-Za-z0-9]{20,}")),
    ("AWS",     re.compile(r"AKIA[0-9A-Z]{16}")),
    ("Google",  re.compile(r"AIza[0-9A-Za-z_-]{35}")),
    ("genérico", re.compile(
        r"(OPENAI|RESEND|OMNIROUTE|ANTHROPIC)_API_KEY\s*=\s*['\"]?[A-Za-z0-9_-]{20,}")),
)

FAKE_MARKERS = ("FAKE", "FALSA", "FALSO", "EXAMPLE", "EXEMPLO", "PLACEHOLDER",
                "SUA_CHAVE", "YOUR-KEY", "YOUR_KEY", "XXXX", "TEST", "DUMMY")

IGNORED_PATHS = ("tests/", ".env.example", "CLAUDE.md",
                 "DIAGNOSTICO_ARQUITETURA.md", ".claude/hooks/")


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not re.search(r"\bgit\s+commit\b", command):
        return 0

    try:
        diff = subprocess.run(
            ["git", "diff", "--cached", "-U0"],
            cwd=payload.get("cwd") or ".",
            capture_output=True, text=True, timeout=20,
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return 0   # sem git: não trava o trabalho

    current_file = ""
    offenders: list[str] = []

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:]
            continue
        if not line.startswith("+") or line.startswith("+++"):
            continue
        if any(ignored in current_file for ignored in IGNORED_PATHS):
            continue
        if any(marker in line.upper() for marker in FAKE_MARKERS):
            continue
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                shown = match.group(0)[:12] + "..."
                offenders.append(f"{current_file} — credencial {label}: {shown}")
                break

    if offenders:
        print("COMMIT BLOQUEADO: credencial detectada nas linhas adicionadas.",
              file=sys.stderr)
        for item in offenders[:5]:
            print(f"  {item}", file=sys.stderr)
        print("Mova o valor para o .env e refaça o stage.", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
