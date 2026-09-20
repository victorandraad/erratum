from __future__ import annotations

import json

from tests.apoio import CasoComLedger


class TestCliErr(CasoComLedger):
    def test_err_registra_e_mostra_assinatura(self):
        codigo, saida = self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file",
                                 "--stage", "dev", "--tool", "Bash")
        self.assertEqual(codigo, 0)
        self.assertIn("erro #1 registrado [acme]", saida)
        self.assertIn("exit code N /PATH: no such file", saida)
        self.assertEqual(self.ledger.erro(1).etapa, "dev")

    def test_err_le_stdin_e_devolve_json(self):
        codigo, saida = self.cli("err", "-", "--json", "--project", "outro", entrada="falha via pipe\n")
        dado = json.loads(saida)
        self.assertEqual(codigo, 0)
        self.assertEqual(dado["erro"]["texto"], "falha via pipe")
        self.assertEqual(dado["erro"]["projeto"], "outro")
        self.assertEqual(dado["pistas"], [])

    def test_uso_errado_sai_com_2(self):
        self.assertEqual(self.cli("err", "--flag-que-nao-existe")[0], 2)
        self.assertEqual(self.cli("comando-que-nao-existe")[0], 2)
        self.assertEqual(self.cli()[0], 2)


class TestCliFix(CasoComLedger):
    def test_fix_por_id_e_err_seguinte_traz_a_correcao(self):
        self.cli("err", "Exit code 127 /tmp/w-1/bin/runner: No such file")
        codigo, saida = self.cli("fix", "1", "prep do worktree", "--ref", "abc123", "--test", "test_prep")
        self.assertEqual(codigo, 0)
        self.assertIn("correção #1 registrada", saida)
        _, saida = self.cli("err", "Exit code 1 /tmp/w-2/bin/runner: No such file")
        self.assertIn("prep do worktree", saida)
        self.assertIn("abc123", saida)

    def test_fix_por_texto_cru_em_json(self):
        codigo, saida = self.cli("fix", "Timeout 30s em /srv/fila", "aumentar o teto", "--json")
        self.assertEqual(codigo, 0)
        self.assertEqual(json.loads(saida)["correcao"]["assinatura"], "timeout Ns em /PATH")

    def test_fix_de_id_inexistente_e_uso_errado(self):
        self.assertEqual(self.cli("fix", "42", "nota")[0], 2)
