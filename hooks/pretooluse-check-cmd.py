#!/usr/bin/env python3
"""Hook PreToolUse: avisa (ou bloqueia) quando o Bash improvisa no lugar de uma receita."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

LIMITE_DO_STDIN = 1048576


def _sair(codigo=0):
    sys.exit(codigo)


def _payload():
    try:
        bruto = sys.stdin.read(LIMITE_DO_STDIN + 1)
    except OSError:
        return None
    if len(bruto) > LIMITE_DO_STDIN:
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
    # o projeto sai da raiz do git do cwd da sessao, como em qualquer chamada do erratum
    cwd = dado.get("cwd")
    if not (isinstance(cwd, str) and Path(cwd).is_dir()):
        cwd = None
    try:
        return subprocess.run(
            argv,
            input=comando,
            capture_output=True,
            text=True,
            env=os.environ,
            cwd=cwd,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


_SEPARADORES = {";", "&&", "||", "|", "&"}
# flags curtas do git commit que consomem valor: o resto do grupo (ou o próximo token) é valor
_COM_VALOR = set("mFCct")
_COM_VALOR_LONGO = {"--message", "--file", "--reuse-message", "--reedit-message", "--template",
                    "--author", "--date", "--fixup", "--squash", "--cleanup", "--trailer"}


def _pula_verificacao(comando):
    """True se algum `git ... commit` do comando leva --no-verify ou -n (inclusive agrupado)."""
    try:
        lexer = shlex.shlex(comando, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return False
    subs, atual = [], []
    for t in tokens:
        if t in _SEPARADORES:
            subs.append(atual)
            atual = []
        else:
            atual.append(t)
    subs.append(atual)
    for sub in subs:
        if not sub or os.path.basename(sub[0]) != "git":
            continue
        i = 1
        while i < len(sub) and sub[i].startswith("-"):
            i += 2 if sub[i] in ("-C", "-c") else 1  # opções globais do git
        if i >= len(sub) or sub[i] != "commit":
            continue
        args = sub[i + 1:]
        pula_valor = False
        for a in args:
            if pula_valor:
                pula_valor = False
            elif a == "--no-verify":
                return True
            elif a.startswith("--"):
                pula_valor = a in _COM_VALOR_LONGO
            elif a.startswith("-") and len(a) > 1:
                for i, letra in enumerate(a[1:]):
                    if letra == "n":
                        return True
                    if letra in _COM_VALOR:
                        pula_valor = i == len(a) - 2  # valor no próximo token
                        break
    return False


def _aviso_de(dado):
    nome = dado.get("receita") or ""
    comando = dado.get("comando") or ""
    # mesmo contrato de erratum.idioma, sem importar o pacote
    pt = os.environ.get("ERRATUM_LANG", "").lower().startswith("pt")
    aviso = ("use a receita %s: %s\n" if pt else "use recipe %s: %s\n") % (nome, comando)
    if dado.get("perigo"):
        aviso += ("perigo: %s\n" if pt else "danger: %s\n") % dado["perigo"]
    return aviso


def main():
    dado = _payload()
    if dado is None:
        _sair(0)
    comando = _comando(dado)
    if comando is None:
        _sair(0)
    if _pula_verificacao(comando):
        pt = os.environ.get("ERRATUM_LANG", "").lower().startswith("pt")
        sys.stderr.write(
            "git commit --no-verify (ou -n) barrado: rode o commit sem --no-verify "
            "e conserte o portão que reprovou.\n" if pt else
            "git commit --no-verify (or -n) blocked: commit without --no-verify "
            "and fix the gate that failed.\n")
        _sair(2)
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
