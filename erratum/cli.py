from __future__ import annotations

import argparse
import json
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path

from erratum.banco import Banco
from erratum.ledger import ErroNaoEncontrado, Ledger


class _UsoErrado(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _UsoErrado(message)

    def exit(self, status=0, message=None):
        raise _UsoErrado(message or "")


class ProjetoAtual:
    def __call__(self):
        try:
            saida = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
            if saida.returncode == 0:
                topo = saida.stdout.strip()
                if topo:
                    return Path(topo).name
        except OSError:
            pass
        return Path.cwd().name


class Comando(ABC):
    nome = ""

    def __init__(self, entrada, saida):
        self._entrada = entrada
        self._saida = saida

    @abstractmethod
    def configurar(self, parser):
        raise NotImplementedError

    @abstractmethod
    def executar(self, args, ledger):
        raise NotImplementedError

    def _ler_texto(self, bruto):
        if bruto == "-":
            return self._entrada.read().rstrip("\r\n")
        return bruto

    def _escrever_json(self, dado):
        self._saida.write(json.dumps(dado, ensure_ascii=False) + "\n")


class ComandoErr(Comando):
    nome = "err"

    def configurar(self, parser):
        parser.add_argument("texto", nargs="?", default="-")
        parser.add_argument("--stage", default="")
        parser.add_argument("--tool", default="")
        parser.add_argument("--kind", default="error")
        parser.add_argument("--task", default="")

    def executar(self, args, ledger):
        texto = self._ler_texto(args.texto)
        contexto = {}
        if args.task:
            contexto["task"] = args.task
        erro, pistas = ledger.registrar_erro(
            texto,
            args.project,
            tipo=args.kind,
            etapa=args.stage,
            ferramenta=args.tool,
            contexto=contexto,
        )
        if args.json:
            self._escrever_json(
                {"erro": asdict(erro), "pistas": [asdict(p) for p in pistas]}
            )
            return 0
        self._saida.write(
            "erro #%d registrado [%s] assinatura: %s\n"
            % (erro.id, erro.projeto, erro.assinatura)
        )
        for pista in pistas:
            for correcao in pista.correcoes:
                self._saida.write(_linha_pista(correcao))
        return 0


class ComandoFix(Comando):
    nome = "fix"

    def configurar(self, parser):
        parser.add_argument("alvo")
        parser.add_argument("nota")
        parser.add_argument("--ref", default="")
        parser.add_argument("--test", default="")

    def executar(self, args, ledger):
        alvo = args.alvo
        if alvo == "-":
            alvo = self._entrada.read().rstrip("\r\n")
        elif alvo.isdigit():
            alvo = int(alvo)
        try:
            correcao = ledger.registrar_correcao(
                alvo,
                args.nota,
                args.project,
                ref=args.ref,
                teste=args.test,
            )
        except ErroNaoEncontrado:
            return 2
        if args.json:
            self._escrever_json({"correcao": asdict(correcao)})
            return 0
        self._saida.write(
            "correção #%d registrada [%s] para: %s\n"
            % (correcao.id, correcao.projeto, correcao.assinatura)
        )
        return 0


def _sufixo_de_correcao(correcao):
    extra = []
    if correcao.ref:
        extra.append("ref: %s" % correcao.ref)
    if correcao.teste:
        extra.append("teste: %s" % correcao.teste)
    return " [%s]" % ", ".join(extra) if extra else ""


def _linha_pista(correcao):
    return "  correção conhecida: %s%s\n" % (
        correcao.nota,
        _sufixo_de_correcao(correcao),
    )


class ComandoTop(Comando):
    nome = "top"

    def configurar(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--all-projects", action="store_true")
        parser.add_argument("--resolved", action="store_true")

    def executar(self, args, ledger):
        projeto = None if args.all_projects else args.project
        padroes = ledger.o_que_repete(
            projeto, dias=args.days, resolvidos=args.resolved
        )
        if args.json:
            self._escrever_json({"padroes": [asdict(p) for p in padroes]})
            return 0
        if not padroes:
            self._saida.write("nada se repetindo\n")
            return 0
        for p in padroes:
            estado = "resolvido" if p.resolvido else "sem correção"
            self._saida.write(
                "%3dx  %d tasks  %-13s %s\n"
                % (p.ocorrencias, p.tasks, estado, p.assinatura)
            )
        return 0


class ComandoWin(Comando):
    nome = "win"

    def configurar(self, parser):
        parser.add_argument("texto")
        parser.add_argument("--task", default="")
        parser.add_argument("--cost", type=float, default=None)

    def executar(self, args, ledger):
        o_que = self._ler_texto(args.texto)
        acerto, streak = ledger.registrar_acerto(
            o_que,
            args.project,
            task=args.task,
            custo_usd=args.cost,
        )
        if args.json:
            self._escrever_json({"acerto": asdict(acerto), "streak": streak})
            return 0
        self._saida.write(
            "acerto #%d registrado [%s] streak: %d\n"
            % (acerto.id, acerto.projeto, streak)
        )
        return 0


class ComandoFind(Comando):
    nome = "find"

    def configurar(self, parser):
        parser.add_argument("texto")
        parser.add_argument("-n", type=int, default=5)

    def executar(self, args, ledger):
        texto = self._ler_texto(args.texto)
        achados = ledger.buscar(texto, n=args.n)
        if args.json:
            self._escrever_json({"achados": [asdict(a) for a in achados]})
            return 0
        if not achados:
            self._saida.write("nada parecido no ledger\n")
            return 0
        for i, achado in enumerate(achados, 1):
            self._saida.write(
                "%d. [%s] %s\n" % (i, achado.origem, achado.assinatura)
            )
            for correcao in achado.correcoes:
                self._saida.write(
                    "   correção: %s%s\n"
                    % (correcao.nota, _sufixo_de_correcao(correcao))
                )
        return 0


class Cli:
    def __init__(
        self,
        fabrica_de_ledger,
        entrada=None,
        saida=None,
        projeto_padrao=None,
        comandos=None,
    ):
        self._fabrica_de_ledger = fabrica_de_ledger
        self._entrada = sys.stdin if entrada is None else entrada
        self._saida = sys.stdout if saida is None else saida
        if projeto_padrao is None:
            projeto_padrao = ProjetoAtual()
        self._projeto_padrao = projeto_padrao
        if comandos is None:
            comandos = [
                ComandoErr(self._entrada, self._saida),
                ComandoFix(self._entrada, self._saida),
                ComandoFind(self._entrada, self._saida),
                ComandoTop(self._entrada, self._saida),
                ComandoWin(self._entrada, self._saida),
            ]
        self._comandos = list(comandos)

    def executar(self, argv):
        parser = self._montar_parser()
        try:
            args = parser.parse_args(list(argv) if argv is not None else [])
        except (SystemExit, argparse.ArgumentError, _UsoErrado):
            return 2
        comando = getattr(args, "comando_obj", None)
        if comando is None:
            return 2
        if not args.project:
            args.project = self._projeto_padrao()
        ledger = self._fabrica_de_ledger()
        return comando.executar(args, ledger)

    def _montar_parser(self):
        parser = _Parser(prog="erratum")
        sub = parser.add_subparsers(dest="comando")
        for cmd in self._comandos:
            p = sub.add_parser(cmd.nome)
            p.add_argument("--json", action="store_true")
            p.add_argument("--project", default=None)
            cmd.configurar(p)
            p.set_defaults(comando_obj=cmd)
        return parser


def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
    with Banco() as banco:
        cli = Cli(lambda: Ledger.sobre(banco))
        codigo = cli.executar(argv)
    sys.exit(codigo)
