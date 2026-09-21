from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path

from erratum.banco import Banco
from erratum.decisao import Decisao
from erratum.ledger import ErroNaoEncontrado, Ledger
from erratum.receitas import Receita

_MSG_ABSTAIN = "nada parecido com confiança no ledger"


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


class WorktreeDoGate:
    def __call__(self, worktree, base, staged=False):
        try:
            topo = self._git(worktree, "rev-parse", "--show-toplevel")
            if topo.returncode != 0:
                return "worktree não é um repositório git"
            if staged:
                return None
            commit = self._git(
                worktree,
                "rev-parse",
                "--verify",
                "--quiet",
                "--end-of-options",
                "%s^{commit}" % base,
            )
            if commit.returncode != 0:
                return "base não resolve para um commit"
            status = self._git(
                worktree, "status", "--porcelain", "--untracked-files=no"
            )
            if status.stdout.strip():
                return "há alteração rastreada não commitada"
        except OSError:
            return "worktree não é um repositório git"
        return None

    def _git(self, worktree, *args):
        return subprocess.run(
            ["git", *args],
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )


class Comando(ABC):
    nome = ""

    def __init__(self, entrada, saida, aviso=None):
        self._entrada = entrada
        self._saida = saida
        self._aviso = sys.stderr if aviso is None else aviso

    def _avisar_regra_antiga(self, ledger):
        if ledger.regra_desatualizada():
            self._aviso.write(
                "assinaturas com regra antiga: rode erratum reindex\n"
            )

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
        self._avisar_regra_antiga(ledger)
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
            task=args.task,
        )
        decisao = Decisao.de(pistas)
        if args.json:
            self._escrever_json(
                {
                    "erro": asdict(erro),
                    "pistas": [asdict(p) for p in pistas],
                    "veredito": decisao.veredito,
                    "confianca": decisao.confianca,
                }
            )
            return 0
        self._saida.write(
            "erro #%d registrado [%s] assinatura: %s\n"
            % (erro.id, erro.projeto, erro.assinatura)
        )
        if decisao.veredito == "abstain":
            self._saida.write("%s\n" % _MSG_ABSTAIN)
            return 0
        for i, pista in enumerate(pistas):
            for correcao in pista.correcoes:
                receita = None
                if correcao.receita:
                    receita = ledger.receita_por_nome(
                        correcao.receita, args.project
                    )
                if i == 0:
                    self._saida.write(_linha_pista(correcao, receita))
                else:
                    self._saida.write(_linha_pista_curta(correcao))
        return 0


class ComandoFix(Comando):
    nome = "fix"

    def configurar(self, parser):
        parser.add_argument("alvo")
        parser.add_argument("nota")
        parser.add_argument("--ref", default="")
        parser.add_argument("--test", default="")
        parser.add_argument("--task", default="")
        parser.add_argument("--recipe", default=None)

    def executar(self, args, ledger):
        alvo = args.alvo
        if alvo == "-":
            alvo = self._entrada.read().rstrip("\r\n")
        elif alvo.isdigit():
            alvo = int(alvo)
        receita_nome = args.recipe or ""
        if args.recipe:
            if ledger.receita_por_nome(args.recipe, args.project) is None:
                return 2
        try:
            correcao = ledger.registrar_correcao(
                alvo,
                args.nota,
                args.project,
                ref=args.ref,
                teste=args.test,
                task=args.task,
                receita=receita_nome,
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


def _linha_pista_curta(correcao):
    # só a primeira pista vem inteira; o resto é candidato fraco da busca por texto
    return "  talvez: %s%s\n" % (
        correcao.nota.split("\n", 1)[0],
        _sufixo_de_correcao(correcao),
    )


def _linha_pista(correcao, receita=None):
    texto = "  correção conhecida: %s%s\n" % (
        correcao.nota,
        _sufixo_de_correcao(correcao),
    )
    if receita is not None:
        texto += "  receita %s: %s\n" % (
            receita.nome,
            receita.comando_obrigatorio(),
        )
        if receita.perigo:
            texto += "  perigo: %s\n" % receita.perigo
    return texto


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
        taxas = ledger.taxa_de_portoes(projeto, dias=args.days)
        improvisos = ledger.improvisos(projeto, dias=args.days)
        if args.json:
            self._escrever_json(
                {
                    "padroes": [asdict(p) for p in padroes],
                    "portoes": [asdict(t) for t in taxas],
                    "improvisos": improvisos,
                }
            )
            return 0
        if not padroes:
            self._saida.write("nada se repetindo\n")
        else:
            for p in padroes:
                estado = "resolvido" if p.resolvido else "sem correção"
                self._saida.write(
                    "%3dx  %d tasks  %-13s %s\n"
                    % (p.ocorrencias, p.tasks, estado, p.assinatura)
                )
        if improvisos:
            self._saida.write("improvisos\n")
            for item in improvisos:
                self._saida.write(
                    "%3dx  %s\n" % (item["desvios"], item["receita"])
                )
        for t in taxas:
            julgados = t.rodadas - t.pulou
            linha = "portão %s: %d/%d reprovou (%d%%), %d pulou" % (
                t.portao,
                t.reprovou,
                julgados,
                int(round(t.taxa * 100)),
                t.pulou,
            )
            if t.nunca_decidiu:
                linha += "  [!] nunca decidiu: portão quebrado?"
            self._saida.write(linha + "\n")
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


class ComandoGate(Comando):
    nome = "gate"

    def __init__(self, entrada, saida, worktree_do_gate=None, aviso=None):
        super().__init__(entrada, saida, aviso=aviso)
        self._worktree_do_gate = worktree_do_gate or WorktreeDoGate()

    def configurar(self, parser):
        parser.add_argument("lista")
        parser.add_argument("--base", default=None)
        parser.add_argument("--worktree", default=".")
        parser.add_argument("--test-cmd", action="append", default=None)
        parser.add_argument("--staged", action="store_true")

    def executar(self, args, ledger):
        from erratum.portoes import PORTOES, DiffDoDev

        nomes = [n.strip() for n in args.lista.split(",") if n.strip()]
        if not nomes or any(n not in PORTOES for n in nomes):
            return 2
        staged = bool(args.staged)
        if staged and "fix-noop" in nomes:
            return 2
        if not staged and not args.base:
            return 2
        base = args.base or "HEAD"
        recusa = self._worktree_do_gate(args.worktree, base, staged=staged)
        if recusa:
            if args.json:
                self._escrever_json({"erro": recusa})
            else:
                self._saida.write("%s\n" % recusa)
            return 2

        def ao_decidir(nome, veredito, detalhe):
            ledger.registrar_portao(nome, veredito, detalhe, args.project)

        resultados = []
        for nome in nomes:
            resultado = PORTOES[nome](
                DiffDoDev(Path(args.worktree), base, staged=staged),
                comandos_de_teste=args.test_cmd,
                ao_decidir=ao_decidir,
            ).rodar()
            resultados.append((nome, resultado))
        if args.json:
            self._escrever_json(
                {
                    "portoes": [
                        {
                            "portao": nome,
                            "veredito": r.veredito,
                            "motivo": r.motivo,
                            "detalhe": r.detalhe,
                        }
                        for nome, r in resultados
                    ],
                    "reprovou": any(r.reprovou for _, r in resultados),
                }
            )
        else:
            for nome, r in resultados:
                self._saida.write(
                    "%s: %s %s\n" % (nome, r.veredito, r.motivo or r.detalhe)
                )
        return 1 if any(r.reprovou for _, r in resultados) else 0


class ComandoHow(Comando):
    nome = "how"

    def configurar(self, parser):
        parser.add_argument("texto")
        parser.add_argument("-n", type=int, default=5)
        parser.add_argument("--task", default="")

    def executar(self, args, ledger):
        texto = self._ler_texto(args.texto)
        decisao = ledger.consultar_receita(
            texto, args.project, task=args.task, n=args.n
        )
        achados = list(decisao.achados)
        if args.json:
            self._escrever_json(
                {
                    "veredito": decisao.veredito,
                    "confianca": decisao.confianca,
                    "achados": [asdict(a) for a in achados],
                }
            )
            return 0
        if decisao.veredito == "abstain":
            self._saida.write("sem receita pra isso\n")
            return 0
        for i, achado in enumerate(achados, 1):
            rec = achado.receita
            if rec is None:
                continue
            self._saida.write(
                "%d. [%s] %s (%.2f) %s\n"
                % (
                    i,
                    achado.origem,
                    achado.veredito,
                    achado.confianca,
                    rec.nome,
                )
            )
            if rec.quando:
                self._saida.write("   quando: %s\n" % rec.quando)
            if rec.comando:
                self._saida.write("   rode: %s\n" % rec.comando)
            if rec.notas:
                self._saida.write("   notas: %s\n" % rec.notas)
            if rec.perigo:
                self._saida.write("   perigo: %s\n" % rec.perigo)
        return 0


class ComandoFind(Comando):
    nome = "find"

    def configurar(self, parser):
        parser.add_argument("texto")
        parser.add_argument("-n", type=int, default=5)
        parser.add_argument("--resolved", action="store_true")
        parser.add_argument("--registrar", action="store_true")
        parser.add_argument("--task", default="")

    def executar(self, args, ledger):
        self._avisar_regra_antiga(ledger)
        texto = self._ler_texto(args.texto)
        if args.registrar:
            decisao = ledger.registrar_pistas_de_consulta(
                texto,
                args.project,
                task=args.task,
                n=args.n,
                so_resolvidos=args.resolved,
            )
        else:
            decisao = ledger.decidir(
                texto, n=args.n, so_resolvidos=args.resolved
            )
        achados = list(decisao.achados)
        if args.json:
            self._escrever_json(
                {
                    "veredito": decisao.veredito,
                    "confianca": decisao.confianca,
                    "achados": [asdict(a) for a in achados],
                }
            )
            return 0
        if decisao.veredito == "abstain":
            self._saida.write("%s\n" % _MSG_ABSTAIN)
            return 0
        for i, achado in enumerate(achados, 1):
            self._saida.write(
                "%d. [%s] %s (%.2f) %s\n"
                % (
                    i,
                    achado.origem,
                    achado.veredito,
                    achado.confianca,
                    achado.assinatura,
                )
            )
            for correcao in achado.correcoes:
                self._saida.write(
                    "   correção: %s%s\n"
                    % (correcao.nota, _sufixo_de_correcao(correcao))
                )
        return 0


def _sha256(texto):
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _ler_dicts_jsonl(caminho):
    eventos = []
    with open(caminho, encoding="utf-8") as fh:
        for linha in fh:
            bruto = linha.strip()
            if not bruto:
                continue
            try:
                dado = json.loads(bruto)
            except json.JSONDecodeError:
                continue
            if isinstance(dado, dict):
                eventos.append(dado)
    return eventos


class ComandoScan(Comando):
    nome = "scan"

    def __init__(self, entrada, saida, minerador=None, aviso=None):
        super().__init__(entrada, saida, aviso=aviso)
        self._minerador = minerador

    def configurar(self, parser):
        parser.add_argument("caminho")

    def executar(self, args, ledger):
        if self._minerador is None:
            from erratum.mineracao import MineradorDeStream

            self._minerador = MineradorDeStream()
        caminho = Path(args.caminho)
        try:
            eventos = _ler_dicts_jsonl(caminho)
        except (OSError, UnicodeError):
            return 2
        erros = self._minerador.extrair(eventos)
        tarefa = caminho.stem
        novos = 0
        for indice, erro in enumerate(erros):
            chave = "scan:" + _sha256(
                tarefa + erro.id_da_chamada + erro.texto + str(indice)
            )
            _gravado, inserido = ledger.registrar_erro_importado(
                erro.texto,
                args.project,
                tipo="exec_error",
                ferramenta=erro.ferramenta,
                contexto={"task": tarefa},
                chave_importacao=chave,
            )
            if inserido:
                novos += 1
        grupos = self._minerador.agregar([(tarefa, eventos)])
        desvios = 0
        usos = 0
        for id_uso, comando in self._minerador.comandos_bash(eventos):
            chave = "scan-receita:" + _sha256(
                tarefa + str(id_uso) + comando
            )
            resultado = ledger.verificar_comando(
                comando,
                args.project,
                task=tarefa,
                chave_importacao=chave,
            )
            if resultado.tipo == "desvio":
                desvios += 1
            elif resultado.tipo == "uso":
                usos += 1
        if args.json:
            self._escrever_json(
                {
                    "lidos": len(erros),
                    "novos": novos,
                    "grupos": [asdict(g) for g in grupos],
                    "receitas": {"desvios": desvios, "usos": usos},
                }
            )
            return 0
        self._saida.write(
            "scan: %d lidos, %d novos\n" % (len(erros), novos)
        )
        self._saida.write(
            "receitas: %d desvios, %d usos\n" % (desvios, usos)
        )
        for grupo in grupos:
            self._saida.write(
                "%3dx  %d exec  %-13s %s\n"
                % (
                    grupo.ocorrencias,
                    grupo.execucoes,
                    grupo.ferramenta,
                    grupo.assinatura,
                )
            )
        return 0


class ComandoSeed(Comando):
    nome = "seed"

    def configurar(self, parser):
        parser.add_argument("--list", action="store_true")

    def executar(self, args, ledger):
        from erratum.sementes import Semeador

        semeador = Semeador(ledger)
        sementes = semeador.sementes()
        receitas = semeador.receitas()
        if args.list:
            if args.json:
                self._escrever_json(
                    {"sementes": sementes, "receitas": receitas}
                )
                return 0
            for semente in sementes:
                frase = semente["erro"].split(".")[0].strip()
                self._saida.write("%s  %s\n" % (semente["slug"], frase))
            for receita in receitas:
                self._saida.write(
                    "%s  %s\n" % (receita["slug"], receita["quando"])
                )
            return 0
        novas = semeador.semear()
        receitas_novas = semeador.semear_receitas()
        total = len(sementes)
        receitas_total = len(receitas)
        if args.json:
            self._escrever_json(
                {
                    "novas": novas,
                    "total": total,
                    "receitas_novas": receitas_novas,
                    "receitas_total": receitas_total,
                }
            )
            return 0
        self._saida.write("semeou %d novas (total %d)\n" % (novas, total))
        self._saida.write(
            "receitas: %d novas (total %d)\n"
            % (receitas_novas, receitas_total)
        )
        return 0


class ComandoDesfecho(Comando):
    nome = "desfecho"

    def configurar(self, parser):
        parser.add_argument("task")
        parser.add_argument("desfecho")

    def executar(self, args, ledger):
        try:
            n = ledger.registrar_desfecho(
                args.task, args.desfecho, projeto=args.project
            )
        except ValueError:
            return 2
        if args.json:
            self._escrever_json({"fechou": n})
            return 0
        self._saida.write("%d\n" % n)
        return 0


class ComandoEfeito(Comando):
    nome = "efeito"

    def configurar(self, parser):
        parser.add_argument("--days", type=int, default=None)
        parser.add_argument("--all-projects", action="store_true")

    def executar(self, args, ledger):
        projeto = None if args.all_projects else args.project
        dado = ledger.efeito(projeto, dias=args.days)
        if args.json:
            self._escrever_json(dado)
            return 0
        for g in dado["tasks"]:
            linha = "%s N=%d" % (g["grupo"], g["n"])
            if g["amostra_pequena"]:
                linha += " amostra pequena, não conclua"
            self._saida.write(linha + "\n")
        for r in dado.get("receitas") or []:
            pct = int(round((r["taxa_de_uso"] or 0) * 100))
            self._saida.write(
                "receita %s: %d uso, %d desvios (%d%% pela receita)\n"
                % (r["receita"], r["usos"], r["desvios"], pct)
            )
        return 0


class ComandoRecipe(Comando):
    nome = "recipe"

    def configurar(self, parser):
        parser.add_argument("acao", choices=["add", "ls", "show", "rm"])
        parser.add_argument("nome", nargs="?")
        parser.add_argument("--quando", default=None)
        parser.add_argument("--cmd", default=None)
        parser.add_argument("--em-vez-de", action="append", default=None)
        parser.add_argument("--notas", default="")
        parser.add_argument("--perigo", default=None)

    def executar(self, args, ledger):
        if args.acao == "add":
            return self._add(args, ledger)
        if args.acao == "ls":
            return self._ls(args, ledger)
        if args.acao == "show":
            return self._show(args, ledger)
        if args.acao == "rm":
            return self._rm(args, ledger)
        return 2

    def _add(self, args, ledger):
        if not args.nome or not args.quando or not args.cmd:
            return 2
        receita = Receita(
            id=0,
            ts="",
            projeto=args.project,
            nome=args.nome,
            quando=args.quando,
            comando=args.cmd,
            notas=args.notas or "",
            perigo=args.perigo,
            em_vez_de=tuple(args.em_vez_de or ()),
            origem="manual",
        )
        try:
            gravada = ledger.salvar_receita(receita)
        except ValueError:
            return 2
        if args.json:
            self._escrever_json({"receita": asdict(gravada)})
            return 0
        self._saida.write(
            "receita %s registrada [%s]\n" % (gravada.nome, gravada.projeto)
        )
        return 0

    def _ls(self, args, ledger):
        receitas = ledger.receitas_visiveis(args.project)
        if args.json:
            self._escrever_json({"receitas": [asdict(r) for r in receitas]})
            return 0
        for r in receitas:
            self._saida.write("%s  %s\n" % (r.nome, r.comando))
        return 0

    def _show(self, args, ledger):
        if not args.nome:
            return 2
        receita = ledger.receita_por_nome(args.nome, args.project)
        if receita is None:
            return 2
        if args.json:
            self._escrever_json({"receita": asdict(receita)})
            return 0
        self._saida.write("%s  %s\n" % (receita.nome, receita.comando))
        return 0

    def _rm(self, args, ledger):
        if not args.nome:
            return 2
        n = ledger.remover_receita(args.nome, args.project)
        if not n:
            return 2
        if args.json:
            self._escrever_json({"removeu": n})
            return 0
        self._saida.write("receita %s removida\n" % args.nome)
        return 0


class ComandoCheckCmd(Comando):
    nome = "check-cmd"

    def configurar(self, parser):
        parser.add_argument("comando")
        parser.add_argument("--task", default="")

    def executar(self, args, ledger):
        comando = self._ler_texto(args.comando)
        resultado = ledger.verificar_comando(
            comando, args.project, task=args.task
        )
        receita = resultado.receita
        if args.json:
            self._escrever_json(
                {
                    "tipo": resultado.tipo,
                    "receita": None if receita is None else receita.nome,
                    "comando": None if receita is None else receita.comando,
                    "perigo": None if receita is None else receita.perigo,
                }
            )
        elif resultado.tipo == "desvio" and receita is not None:
            self._saida.write(
                "use a receita %s: %s\n"
                % (receita.nome, receita.comando_obrigatorio())
            )
            if receita.perigo:
                self._saida.write("perigo: %s\n" % receita.perigo)
        return 1 if resultado.tipo == "desvio" else 0


class ComandoReindex(Comando):
    nome = "reindex"

    def configurar(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def executar(self, args, ledger):
        r = ledger.reindexar(simular=args.dry_run)
        if args.json:
            self._escrever_json(asdict(r))
            return 0
        extra = " (simulado)" if r.simulado else ""
        self._saida.write(
            "reindex%s: %d -> %d assinaturas\n" % (extra, r.antes, r.depois)
        )
        return 0


class ComandoImport(Comando):
    nome = "import"

    def configurar(self, parser):
        parser.add_argument("caminho")

    def executar(self, args, ledger):
        caminho = Path(args.caminho)
        try:
            texto = caminho.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return 2
        from erratum.mineracao import ImportadorJsonl

        relatorio = ImportadorJsonl(ledger).importar(
            texto.splitlines(), args.project
        )
        if args.json:
            self._escrever_json(
                {
                    "lidos": relatorio.lidos,
                    "novos": relatorio.novos,
                    "ignorados": relatorio.ignorados,
                }
            )
            return 0
        self._saida.write(
            "import: %d lidos, %d novos, %d ignorados\n"
            % (relatorio.lidos, relatorio.novos, relatorio.ignorados)
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
        aviso=None,
    ):
        self._fabrica_de_ledger = fabrica_de_ledger
        self._entrada = sys.stdin if entrada is None else entrada
        self._saida = sys.stdout if saida is None else saida
        self._aviso = sys.stderr if aviso is None else aviso
        if projeto_padrao is None:
            projeto_padrao = ProjetoAtual()
        self._projeto_padrao = projeto_padrao
        if comandos is None:
            comandos = [
                ComandoErr(self._entrada, self._saida, aviso=self._aviso),
                ComandoFix(self._entrada, self._saida, aviso=self._aviso),
                ComandoFind(self._entrada, self._saida, aviso=self._aviso),
                ComandoHow(self._entrada, self._saida, aviso=self._aviso),
                ComandoTop(self._entrada, self._saida, aviso=self._aviso),
                ComandoWin(self._entrada, self._saida, aviso=self._aviso),
                ComandoGate(self._entrada, self._saida, aviso=self._aviso),
                ComandoScan(self._entrada, self._saida, aviso=self._aviso),
                ComandoImport(self._entrada, self._saida, aviso=self._aviso),
                ComandoSeed(self._entrada, self._saida, aviso=self._aviso),
                ComandoReindex(self._entrada, self._saida, aviso=self._aviso),
                ComandoDesfecho(self._entrada, self._saida, aviso=self._aviso),
                ComandoEfeito(self._entrada, self._saida, aviso=self._aviso),
                ComandoRecipe(self._entrada, self._saida, aviso=self._aviso),
                ComandoCheckCmd(self._entrada, self._saida, aviso=self._aviso),
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
    try:
        with Banco() as banco:
            cli = Cli(lambda: Ledger.sobre(banco, aviso=sys.stderr))
            codigo = cli.executar(argv)
    except BrokenPipeError:
        # flush do interpretador na saida; o resto vai pra /dev/null
        # pra nao estourar de novo no shutdown
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(0)
    sys.exit(codigo)


def __getattr__(name):
    if name in ("PORTOES", "DiffDoDev"):
        from erratum.portoes import PORTOES, DiffDoDev

        globals()["PORTOES"] = PORTOES
        globals()["DiffDoDev"] = DiffDoDev
        return globals()[name]
    if name in ("MineradorDeStream", "ImportadorJsonl"):
        from erratum.mineracao import ImportadorJsonl, MineradorDeStream

        globals()["ImportadorJsonl"] = ImportadorJsonl
        globals()["MineradorDeStream"] = MineradorDeStream
        return globals()[name]
    if name == "Semeador":
        from erratum.sementes import Semeador

        globals()["Semeador"] = Semeador
        return Semeador
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
