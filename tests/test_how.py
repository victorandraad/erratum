"""`erratum how`: busca de receita por intenção, no MESMO contrato match|talvez|abstain da busca de
erros (mesma BuscaFTS, mesmo Limiar, mesmo juiz externo). E `fix --recipe`: a pista do `err` passa a
mostrar o comando da receita.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from tests.apoio import CasoComLedger


class TesteHow(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.cli(
            "recipe", "add", "esperar-ci", "--project", "geral",
            "--quando", "esperar o CI de um pull request terminar",
            "--cmd", "gh pr checks <pr> --watch --fail-fast",
            "--notas", "bloqueia até os checks fecharem",
            "--perigo", "rode em background",
        )
        self.cli(
            "recipe", "add", "reiniciar-servico",
            "--quando", "reiniciar um serviço e confirmar a saúde",
            "--cmd", "systemctl restart <servico>",
        )
        self.cli(
            "recipe", "add", "segredo-do-vizinho", "--project", "vizinho",
            "--quando", "publicar o pacote no índice", "--cmd", "bin/publica",
        )

    def _consultas(self):
        return self.banco.consultar(
            "SELECT * FROM usos_de_receita WHERE tipo = 'consulta' ORDER BY id"
        )

    def test_acha_a_receita_e_mostra_o_comando(self):
        codigo, saida = self.cli("how", "como esperar o CI do pull request")
        self.assertEqual(codigo, 0)
        self.assertIn("esperar-ci", saida)
        self.assertIn("gh pr checks <pr> --watch --fail-fast", saida)
        self.assertIn("rode em background", saida)

    def test_json_segue_o_contrato_da_busca(self):
        _c, saida = self.cli("how", "esperar CI pull request terminar", "--json")
        dado = json.loads(saida)
        self.assertIn(dado["veredito"], ("match", "talvez"))
        self.assertIsInstance(dado["confianca"], float)
        primeiro = dado["achados"][0]
        self.assertEqual(primeiro["receita"]["nome"], "esperar-ci")
        self.assertIn(primeiro["veredito"], ("match", "talvez"))

    def test_sem_achado_confiante_diz_que_nao_tem_e_sai_0(self):
        codigo, saida = self.cli("how", "pintar a tela de azul")
        self.assertEqual(codigo, 0)
        self.assertIn("sem receita pra isso", saida)
        _c, saida = self.cli("how", "pintar a tela de azul", "--json")
        dado = json.loads(saida)
        self.assertEqual((dado["veredito"], dado["achados"]), ("abstain", []))

    def test_limiar_de_cobertura_e_o_mesmo_da_busca_de_erros(self):
        # uma palavra comum em doze não passa do piso de cobertura
        codigo, saida = self.cli(
            "how",
            "terminar montar planilha enviar relatorio cliente segunda feira cedo antes almoco",
        )
        self.assertIn("sem receita pra isso", saida)

    def test_receita_de_outro_projeto_nao_aparece(self):
        _c, saida = self.cli("how", "publicar o pacote no índice")
        self.assertIn("sem receita pra isso", saida)

    def test_grava_consulta_com_e_sem_achado(self):
        self.cli("how", "esperar o CI do pull request", "--task", "t-1")
        self.cli("how", "pintar a tela de azul")
        linhas = self._consultas()
        self.assertEqual(len(linhas), 2)
        self.assertIsNotNone(linhas[0]["receita_id"])
        self.assertEqual(linhas[0]["task"], "t-1")
        self.assertEqual(linhas[0]["comando"], "esperar o CI do pull request")
        self.assertIsNone(linhas[1]["receita_id"])

    def test_n_limita(self):
        _c, saida = self.cli("how", "esperar reiniciar serviço CI", "-n", "1", "--json")
        self.assertLessEqual(len(json.loads(saida)["achados"]), 1)

    def test_how_nao_mistura_com_o_indice_de_erros(self):
        self.cli("err", "esperar o CI do pull request estourou o tempo")
        _c, saida = self.cli("find", "esperar o CI do pull request", "--json")
        for achado in json.loads(saida)["achados"]:
            self.assertNotEqual(achado["assinatura"], "esperar-ci")
        _c, saida = self.cli("how", "estourou o tempo", "--json")
        self.assertEqual(json.loads(saida)["veredito"], "abstain")

    def test_rm_tira_do_indice(self):
        self.cli("recipe", "rm", "esperar-ci", "--project", "geral")
        _c, saida = self.cli("how", "esperar o CI do pull request")
        self.assertIn("sem receita pra isso", saida)


class TesteHowComJuiz(CasoComLedger):
    def _ledger_com_juiz(self, resposta):
        from erratum.ledger import Ledger

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        script = Path(tmp.name) / "juiz.sh"
        pedido = Path(tmp.name) / "pedido.json"
        script.write_text(
            "#!/bin/sh\ncat > %s\necho '%s'\n" % (pedido, json.dumps(resposta)),
            encoding="utf-8",
        )
        os.chmod(script, stat.S_IRWXU)
        self.ledger = Ledger.sobre(
            self.banco, relogio=self.relogio, ambiente={"ERRATUM_JUDGE_CMD": str(script)}
        )
        return pedido

    def setUp(self):
        super().setUp()
        self.cli(
            "recipe", "add", "esperar-ci", "--quando", "esperar o CI de um pull request",
            "--cmd", "gh pr checks <pr> --watch",
        )
        self.cli(
            "recipe", "add", "esperar-deploy", "--quando", "esperar o deploy de um pull request",
            "--cmd", "bin/espera-deploy <pr>",
        )

    def test_juiz_escolhe_e_vira_match(self):
        pedido = self._ledger_com_juiz({"escolha": "2", "confianca": 0.9})
        _c, saida = self.cli("how", "esperar pull request", "--json")
        dado = json.loads(saida)
        self.assertEqual(dado["veredito"], "match")
        escolhidos = [a for a in dado["achados"] if a["decidido_por"] == "juiz"]
        self.assertEqual(len(escolhidos), 1)
        enviado = json.loads(pedido.read_text(encoding="utf-8"))
        self.assertEqual(len(enviado["candidatos"]), 2)
        # o juiz precisa ver o que a receita faz, não só o nome
        self.assertTrue(all(c["nota"] for c in enviado["candidatos"]))

    def test_juiz_abstem(self):
        self._ledger_com_juiz({"escolha": "abstain"})
        _c, saida = self.cli("how", "esperar pull request")
        self.assertIn("sem receita pra isso", saida)


class TesteFixComReceita(CasoComLedger):
    def setUp(self):
        super().setUp()
        self.cli(
            "recipe", "add", "prep-do-worktree", "--project", "geral",
            "--quando", "preparar o worktree antes do runner",
            "--cmd", "bin/prep <worktree>", "--perigo", "apaga o vendor",
        )

    def test_pista_do_err_mostra_o_comando_da_receita(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        codigo, _s = self.cli("fix", "1", "rodar o prep antes", "--recipe", "prep-do-worktree")
        self.assertEqual(codigo, 0)
        _c, saida = self.cli("err", "Exit code 1 /tmp/w-9/bin/runner: No such file", "--task", "t-2")
        self.assertIn("rodar o prep antes", saida)
        self.assertIn("receita prep-do-worktree: bin/prep <worktree>", saida)
        self.assertIn("apaga o vendor", saida)
        origens = [
            l["origem"]
            for l in self.banco.consultar("SELECT origem FROM pistas WHERE task = 't-2'")
        ]
        self.assertEqual(origens, ["receita"])

    def test_json_traz_a_receita_na_correcao(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        self.cli("fix", "1", "rodar o prep antes", "--recipe", "prep-do-worktree")
        _c, saida = self.cli("find", "Exit code 3 /tmp/w-2/bin/runner: No such file", "--json")
        correcao = json.loads(saida)["achados"][0]["correcoes"][0]
        self.assertEqual(correcao["receita"], "prep-do-worktree")

    def test_receita_inexistente_e_uso_errado_e_nao_grava(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        codigo, _s = self.cli("fix", "1", "nota", "--recipe", "nao-existe")
        self.assertEqual(codigo, 2)
        n = self.banco.consultar("SELECT COUNT(*) AS n FROM fixes")[0]["n"]
        self.assertEqual(n, 0)

    def test_receita_removida_depois_nao_quebra_o_err(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        self.cli("fix", "1", "rodar o prep antes", "--recipe", "prep-do-worktree")
        self.cli("recipe", "rm", "prep-do-worktree", "--project", "geral")
        codigo, saida = self.cli("err", "Exit code 1 /tmp/w-9/bin/runner: No such file")
        self.assertEqual(codigo, 0)
        self.assertIn("rodar o prep antes", saida)

    def test_fix_sem_recipe_continua_igual(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        self.cli("fix", "1", "rodar o prep antes")
        _c, saida = self.cli("err", "Exit code 1 /tmp/w-9/bin/runner: No such file")
        self.assertIn("correção conhecida: rodar o prep antes", saida)
        self.assertNotIn("receita", saida)
