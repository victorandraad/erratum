"""Sementes: o ledger já nasce com as correções mais comuns e mais caras.

Contrato:
- `erratum/sementes.json` é empacotado; `Semeador(ledger, caminho=None)` lê (caminho None = o
  embarcado), `sementes()` devolve a lista de dicts e `semear()` devolve quantas entraram AGORA.
- Cada semente vira uma CORREÇÃO (fonte `semente`, projeto `geral`, ref e import_key
  `semente:<slug>`) mais o texto do erro no índice de busca. Semente NÃO é ocorrência: nada entra
  em `errors`, então `top` e streak não mudam.
- `erratum seed` é idempotente; `erratum seed --list` só lista, não grava.
"""
from __future__ import annotations

import json
import unittest

from erratum.dominio import Assinatura
from tests.apoio import CasoComLedger

CAMPOS = ("slug", "erro", "causa", "correcao", "prevencao", "etapa", "tags")

# (variação realista que alguém colaria, slug esperado como PRIMEIRA pista)
VARIACOES = [
    ("CONFLICT (content): Merge conflict in src/app.py\nAutomatic merge failed; fix conflicts and "
     "then commit the result.", "conflito-de-merge-na-branch-do-agente"),
    ("dev não gerou commits à frente da base, nada pra revisar", "agente-terminou-sem-commit"),
    ("error: cannot lock ref 'refs/remotes/origin/feat/x': is at 1a2b3c but expected 4d5e6f",
     "git-cannot-lock-ref"),
    (" ! [rejected]        feat/y -> feat/y (non-fast-forward)\nerror: failed to push some refs to "
     "'github.com:acme/loja.git'", "push-rejeitado-non-fast-forward"),
    ("Error: Cannot find module 'vite'\nRequire stack: /tmp/w-7/node_modules/.bin/vite",
     "dependencias-ausentes-no-worktree"),
    ("GraphQL: A pull request already exists for acme:feat/z", "pr-ja-existe-para-a-branch"),
    ("You've hit your session limit · resets 3am (UTC)", "limite-de-uso-do-provedor"),
    ("The process \"vendor/bin/runner --parallel\" exceeded the timeout of 300 seconds.",
     "timeout-do-gerenciador-de-pacotes"),
    ("fatal: detected dubious ownership in repository at '/srv/loja'", "git-dubious-ownership"),
    ("/bin/sh: 1: gh: not found (exit code 127)", "comando-nao-encontrado-no-cron"),
]


class TestArquivoDeSementes(CasoComLedger):
    def setUp(self):
        super().setUp()
        from erratum.sementes import Semeador
        self.semeador = Semeador(self.ledger)
        self.sementes = self.semeador.sementes()

    def test_de_20_a_30_sementes_completas(self):
        self.assertGreaterEqual(len(self.sementes), 20)
        self.assertLessEqual(len(self.sementes), 30)
        for s in self.sementes:
            for campo in CAMPOS:
                self.assertTrue(s.get(campo), "%s sem %s" % (s.get("slug"), campo))
            self.assertIsInstance(s["tags"], list)

    def test_slug_e_assinatura_sao_unicos(self):
        slugs = [s["slug"] for s in self.sementes]
        self.assertEqual(len(slugs), len(set(slugs)))
        assinaturas = [Assinatura(s["erro"]).valor for s in self.sementes]
        self.assertEqual(len(assinaturas), len(set(assinaturas)))

    def test_caminho_alternativo_pelo_construtor(self):
        from erratum.sementes import Semeador
        outro = self.caminho.parent / "minhas.json"
        outro.write_text(json.dumps([{
            "slug": "x", "erro": "falha xpto no deploy", "causa": "c", "correcao": "faça y",
            "prevencao": "p", "etapa": "e", "tags": ["t"]}]), encoding="utf-8")
        semeador = Semeador(self.ledger, caminho=outro)
        self.assertEqual(semeador.semear(), 1)
        self.assertEqual(semeador.semear(), 0)


class TestSeed(CasoComLedger):
    def _contar(self, tabela):
        return self.banco.consultar("SELECT COUNT(*) AS n FROM %s" % tabela)[0]["n"]

    def _total(self):
        from erratum.sementes import Semeador
        return len(Semeador(self.ledger).sementes())

    def test_seed_grava_correcoes_e_e_idempotente(self):
        codigo, saida = self.cli("seed", "--json")
        self.assertEqual(codigo, 0)
        dado = json.loads(saida)
        self.assertEqual(dado["novas"], self._total())
        self.assertEqual(dado["total"], self._total())
        self.assertEqual(self._contar("fixes"), self._total())
        codigo, saida = self.cli("seed", "--json")
        self.assertEqual(json.loads(saida)["novas"], 0)
        self.assertEqual(self._contar("fixes"), self._total())

    def test_saida_humana_diz_quantas_entraram(self):
        _codigo, saida = self.cli("seed")
        self.assertIn(str(self._total()), saida)

    def test_correcao_da_semente_tem_origem_projeto_e_ref(self):
        self.cli("seed")
        linhas = self.banco.consultar("SELECT project, source, ref, import_key, note FROM fixes")
        for l in linhas:
            self.assertEqual(l["project"], "geral")
            self.assertEqual(l["source"], "semente")
            self.assertTrue(l["ref"].startswith("semente:"))
            self.assertEqual(l["ref"], l["import_key"])
        from erratum.sementes import Semeador
        uma = Semeador(self.ledger).sementes()[0]
        nota = [l["note"] for l in linhas if l["ref"] == "semente:" + uma["slug"]][0]
        for campo in ("correcao", "causa", "prevencao"):
            self.assertIn(uma[campo], nota)

    def test_list_nao_grava(self):
        codigo, saida = self.cli("seed", "--list")
        self.assertEqual(codigo, 0)
        self.assertEqual(self._contar("fixes"), 0)
        self.assertIn("agente-terminou-sem-commit", saida)
        _codigo, saida = self.cli("seed", "--list", "--json")
        self.assertEqual(len(json.loads(saida)["sementes"]), self._total())
        self.assertEqual(self._contar("fixes"), 0)

    def test_semente_nao_e_ocorrencia(self):
        self.cli("seed")
        self.assertEqual(self._contar("errors"), 0)
        _codigo, saida = self.cli("top", "--all-projects", "--resolved", "--days", "3650", "--json")
        self.assertEqual(json.loads(saida)["padroes"], [])
        # acerto no projeto geral continua contando: semente não zera streak
        _codigo, saida = self.cli("win", "entrega limpa", "--project", "geral", "--json")
        self.assertEqual(json.loads(saida)["streak"], 1)

    def test_ocorrencia_real_de_erro_semeado_conta_uma_vez(self):
        self.cli("seed")
        self.cli("err", VARIACOES[0][0], "--project", "loja")
        _codigo, saida = self.cli("top", "--all-projects", "--resolved", "--json")
        padroes = json.loads(saida)["padroes"]
        self.assertEqual(sum(p["ocorrencias"] for p in padroes), 1)


class TestErrAchaASemente(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.cli("seed")

    def test_variacoes_realistas_em_qualquer_projeto(self):
        for i, (texto, slug) in enumerate(VARIACOES):
            _codigo, saida = self.cli("err", texto, "--project", "projeto%d" % i, "--json")
            pistas = json.loads(saida)["pistas"]
            self.assertTrue(pistas, "sem pista para: %s" % texto[:50])
            refs = [c["ref"] for c in pistas[0]["correcoes"]]
            self.assertIn("semente:" + slug, refs, "primeira pista errada para: %s" % texto[:50])

    def test_saida_humana_mostra_a_correcao(self):
        _codigo, saida = self.cli("err", VARIACOES[2][0], "--project", "loja")
        self.assertIn("semente:git-cannot-lock-ref", saida)

    def test_ruido_sem_correcao_nao_esconde_a_semente(self):
        # muitos erros parecidos e SEM correção não podem empurrar a semente pra fora das pistas
        for i in range(12):
            self.ledger.registrar_erro(
                "error: cannot lock ref refs remotes origin ramo%s falhou de novo" % ("x" * (i + 1)),
                "ruido", com_pistas=False)
        _codigo, saida = self.cli("err", VARIACOES[2][0], "--project", "loja", "--json")
        refs = [c["ref"] for p in json.loads(saida)["pistas"] for c in p["correcoes"]]
        self.assertIn("semente:git-cannot-lock-ref", refs)


if __name__ == "__main__":
    unittest.main()
