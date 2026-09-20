"""Busca externa (`ERRATUM_SEARCH_CMD`): comando do usuario plugado no fim da cascata. Falha dele
nunca derruba a busca: vira aviso no stderr."""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

from erratum.busca import BuscaExterna
from erratum.ledger import Ledger
from tests.apoio import CasoComLedger

OK = "import sys\nprint('nota externa sobre ' + sys.argv[-1])\nprint()\nprint('segunda linha')\n"
SAI_TRES = "import sys\nprint('lixo')\nsys.stderr.write('quebrei')\nsys.exit(3)\n"
DORME = "import time\ntime.sleep(5)\nprint('tarde demais')\n"
MARCA = "import sys, pathlib\npathlib.Path(sys.argv[1]).write_text('rodou')\nprint('achei')\n"


class TestBuscaExterna(CasoComLedger):
    def setUp(self):
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.aviso = io.StringIO()

    def _cmd(self, corpo, *extra):
        script = Path(self._dir.name) / "busca_falsa.py"
        script.write_text(corpo)
        return " ".join([sys.executable, str(script)] + list(extra))

    def test_cada_linha_vira_achado_external(self):
        achados = BuscaExterna(self._cmd(OK), aviso=self.aviso).buscar("disco cheio", 5)
        self.assertEqual([a.origem for a in achados], ["external", "external"])
        # a query vai como UM argumento no fim, e linha vazia nao vira achado
        self.assertEqual([a.texto for a in achados],
                         ["nota externa sobre disco cheio", "segunda linha"])
        self.assertEqual(self.aviso.getvalue(), "")

    def test_respeita_n(self):
        self.assertEqual(len(BuscaExterna(self._cmd(OK), aviso=self.aviso).buscar("x", 1)), 1)

    def test_query_nao_passa_por_shell(self):
        achados = BuscaExterna(self._cmd(OK), aviso=self.aviso).buscar("a; echo $(id) 'b", 5)
        self.assertEqual(achados[0].texto, "nota externa sobre a; echo $(id) 'b")

    def test_exit_diferente_de_zero_vira_aviso(self):
        achados = BuscaExterna(self._cmd(SAI_TRES), aviso=self.aviso).buscar("x", 5)
        self.assertEqual(achados, [])
        self.assertIn("3", self.aviso.getvalue())

    def test_timeout_vira_aviso(self):
        busca = BuscaExterna(self._cmd(DORME), aviso=self.aviso, timeout=0.3)
        self.assertEqual(busca.buscar("x", 5), [])
        self.assertTrue(self.aviso.getvalue().strip())

    def test_comando_inexistente_vira_aviso(self):
        busca = BuscaExterna("comando-que-nao-existe-acme --json", aviso=self.aviso)
        self.assertEqual(busca.buscar("x", 5), [])
        self.assertTrue(self.aviso.getvalue().strip())

    def test_comando_malformado_vira_aviso(self):
        busca = BuscaExterna("aspas 'abertas", aviso=self.aviso)
        self.assertEqual(busca.buscar("x", 5), [])
        self.assertTrue(self.aviso.getvalue().strip())

    def test_timeout_padrao_e_dez_segundos(self):
        self.assertEqual(BuscaExterna("true").timeout, 10)

    def test_ledger_pluga_no_fim_da_cascata(self):
        self.ledger.registrar_erro("disco cheio em /var/dados 1", "acme")
        ledger = Ledger.sobre(self.banco, relogio=self.relogio,
                              ambiente={"ERRATUM_SEARCH_CMD": self._cmd(OK)}, aviso=self.aviso)
        origens = [a.origem for a in ledger.buscar("disco cheio em /var/dados 2")]
        self.assertEqual(origens[0], "assinatura")
        self.assertEqual(origens[-2:], ["external", "external"])

    def test_env_ausente_nao_roda_nada(self):
        marca = Path(self._dir.name) / "marca"
        cmd = self._cmd(MARCA, str(marca))
        for ambiente in ({}, {"ERRATUM_SEARCH_CMD": "  "}):
            ledger = Ledger.sobre(self.banco, relogio=self.relogio, ambiente=ambiente,
                                  aviso=self.aviso)
            self.assertEqual(ledger.buscar("qualquer coisa"), [])
        self.assertFalse(marca.exists())
        ligado = Ledger.sobre(self.banco, relogio=self.relogio,
                              ambiente={"ERRATUM_SEARCH_CMD": cmd}, aviso=self.aviso)
        self.assertEqual(len(ligado.buscar("qualquer coisa")), 1)
        self.assertTrue(marca.exists())


class TestCascataDeduplicaAntesDeCortar(CasoComLedger):
    def test_match_exato_que_tambem_esta_no_fts_nao_come_uma_vaga(self):
        for nome in ("alfa", "beta", "gama", "delta"):
            self.ledger.registrar_erro("falha de rede ao baixar pacote %s" % nome, "acme")
        achados = self.ledger.buscar("falha de rede ao baixar pacote alfa", n=3)
        self.assertEqual(len(achados), 3)
        self.assertEqual(achados[0].origem, "assinatura")
        self.assertEqual(len({a.assinatura for a in achados}), 3)
