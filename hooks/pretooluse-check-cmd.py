#!/usr/bin/env python3
"""Hook PreToolUse: avisa (ou bloqueia) quando o Bash improvisa no lugar de uma receita."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _sair(codigo=0):
    sys.exit(codigo)


def _payload():
    try:
        bruto = sys.stdin.read()
    except OSError:
        return None
    if not (bruto or "").strip():
        return None
    try:
        dado = json.loads(bruto)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(dado, dict):
        return None
    return dado


def _comando(dado):
    if dado.get("tool_name") != "Bash":
        return None
    inp = dado.get("tool_input")
    if not isinstance(inp, dict):
        return None
    comando = inp.get("command")
    if not isinstance(comando, str) or not comando:
        return None
    return comando


def _checar(comando, dado):
    python = os.environ.get("ERRATUM_PYTHON") or sys.executable
    argv = [python, "-m", "erratum", "check-cmd", "-", "--json"]
    task = dado.get("session_id")
    if isinstance(task, str) and task:
        argv.extend(["--task", task])
    cwd = dado.get("cwd")
    if isinstance(cwd, str) and cwd:
        argv.extend(["--project", Path(cwd).name])
    try:
        return subprocess.run(
            argv,
            input=comando,
            capture_output=True,
            text=True,
            env=os.environ,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _aviso_de(dado):
    nome = dado.get("receita") or ""
    comando = (dado.get("comando") or "").split(" [", 1)[0]
    aviso = "use a receita %s: %s\n" % (nome, comando)
    if dado.get("perigo"):
        aviso += "perigo: %s\n" % dado["perigo"]
    return aviso


def main():
    dado = _payload()
    if dado is None:
        _sair(0)
    comando = _comando(dado)
    if comando is None:
        _sair(0)
    proc = _checar(comando, dado)
    if proc is None:
        _sair(0)
    try:
        resultado = json.loads(proc.stdout or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        _sair(0)
    if not isinstance(resultado, dict) or resultado.get("tipo") != "desvio":
        _sair(0)
    aviso = _aviso_de(resultado)
    bloqueia = os.environ.get("ERRATUM_HOOK_BLOQUEIA", "").strip() in (
        "1",
        "true",
        "yes",
    )
    if bloqueia:
        sys.stderr.write(aviso)
        _sair(2)
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": aviso,
            }
        },
        sys.stdout,
    )
    _sair(0)


if __name__ == "__main__":
    main()
