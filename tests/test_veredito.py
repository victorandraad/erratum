"""Busca que sabe dizer "não sei": todo achado sai com veredito fechado (match | talvez) e
confiança HEURÍSTICA; abaixo do piso é descartado e, sem nada, a decisão é abstain."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

from erratum.decisao import Decisao, JuizExterno, Limiar
from erratum.dominio import Achado
from erratum.ledger import Ledger
from erratum.sementes import Semeador
from tests.apoio import CasoComLedger
from tests.test_sementes import VARIACOES

ALHEIOS = [
    "TypeError: Cannot read properties of undefined (reading 'map')",
    "kernel panic - not syncing: VFS unable to mount root fs",
    "a janela de login ficou azul e o botao sumiu",
    "segmentation fault (core dumped) in libfoo.so",
]


class TestContratoDoAchado(CasoComLedger):
    def test_achado_antigo_continua_construindo(self):
        a = Achado(origem="fts", assinatura="x", texto="", correcoes=(), pontuacao=0.0)
        self.assertEqual((a.veredito, a.confianca), ("talvez", 0.0))

    def test_assinatura_exata_e_match_com_confianca_um(self):
        self.ledger.registrar_erro("Timeout 30s em /srv/fila", "acme", com_pistas=False)
        self.ledger.registrar_correcao(1, "aumentar o teto", "acme")
        d = self.ledger.decidir("Timeout 99s em /srv/outra")
        self.assertIsInstance(d, Decisao)
        self.assertEqual((d.veredito, d.confianca), ("match", 1.0))
        self.assertEqual(d.achados[0].origem, "assinatura")
        self.assertEqual(d.achados[0].veredito, "match")

    def test_ledger_vazio_abstem(self):
        d = self.ledger.decidir("qualquer coisa que nunca vi")
        self.assertEqual((d.veredito, d.confianca, d.achados), ("abstain", 0.0, ()))


class TestLimiarNasSementes(CasoComLedger):
    def setUp(self):
        super().setUp()
        Semeador(self.ledger).semear()

    def test_as_dez_variacoes_casam_como_match(self):
        for texto, slug in VARIACOES:
            d = self.ledger.decidir(texto, so_resolvidos=True)
            self.assertEqual(d.veredito, "match", texto[:50])
            self.assertEqual(d.achados[0].correcoes[0].ref, "semente:%s" % slug)
            self.assertTrue(0.0 < d.confianca <= 1.0)

    def test_erro_alheio_abstem(self):
        for texto in ALHEIOS:
            d = self.ledger.decidir(texto, so_resolvidos=True)
            self.assertEqual(d.veredito, "abstain", texto)
            self.assertEqual(self.ledger.buscar(texto, so_resolvidos=True), [])

    def test_parecido_sem_folga_sobre_o_segundo_e_talvez(self):
        # acha duas sementes quase empatadas: nao finge certeza
        d = self.ledger.decidir("error: linker `cc` not found", so_resolvidos=True)
        self.assertEqual(d.veredito, "talvez")
        self.assertTrue(all(a.veredito == "talvez" for a in d.achados))
        self.assertLess(d.confianca, 0.5)

    def test_n_igual_a_um_nao_muda_o_veredito(self):
        d = self.ledger.decidir(VARIACOES[0][0], n=1, so_resolvidos=True)
        self.assertEqual((d.veredito, len(d.achados)), ("match", 1))

    def test_limiar_pelo_construtor(self):
        rigido = Ledger.sobre(self.banco, ambiente={}, limiar=Limiar(match=50.0, talvez=0.15))
        self.assertEqual(rigido.decidir(VARIACOES[0][0], so_resolvidos=True).veredito, "talvez")
        mudo = Ledger.sobre(self.banco, ambiente={}, limiar=Limiar(match=1.6, talvez=1.1))
        self.assertEqual(mudo.decidir(VARIACOES[0][0], so_resolvidos=True).veredito, "abstain")

    def test_limiar_pelo_ambiente(self):
        amb = {"ERRATUM_LIMIAR_MATCH": "50", "ERRATUM_LIMIAR_TALVEZ": "0.15"}
        self.assertEqual(Ledger.sobre(self.banco, ambiente=amb)
                         .decidir(VARIACOES[0][0], so_resolvidos=True).veredito, "talvez")

    def test_limiar_invalido_no_ambiente_avisa_e_usa_o_padrao(self):
        aviso = io.StringIO()
        ledger = Ledger.sobre(self.banco, ambiente={"ERRATUM_LIMIAR_MATCH": "banana"}, aviso=aviso)
        self.assertEqual(ledger.decidir(VARIACOES[0][0], so_resolvidos=True).veredito, "match")
        self.assertIn("ERRATUM_LIMIAR_MATCH", aviso.getvalue())

    def test_padroes_documentados(self):
        self.assertEqual((Limiar().match, Limiar().talvez), (Limiar.MATCH_PADRAO, Limiar.TALVEZ_PADRAO))


class TestCliDizNaoSei(CasoComLedger):
    def setUp(self):
        super().setUp()
        Semeador(self.ledger).semear()

    def test_find_abstem_em_texto_e_json(self):
        codigo, saida = self.cli("find", ALHEIOS[0], "--resolved")
        self.assertEqual(codigo, 0)
        self.assertIn("nada parecido com confiança", saida)
        codigo, saida = self.cli("find", ALHEIOS[0], "--resolved", "--json")
        dado = json.loads(saida)
        self.assertEqual(codigo, 0)
        self.assertEqual((dado["veredito"], dado["achados"]), ("abstain", []))

    def test_find_mostra_veredito_e_confianca(self):
        _, saida = self.cli("find", VARIACOES[0][0], "--resolved")
        self.assertIn("match", saida.splitlines()[0])
        dado = json.loads(self.cli("find", VARIACOES[0][0], "--resolved", "--json")[1])
        self.assertEqual(dado["veredito"], "match")
        self.assertEqual(dado["achados"][0]["veredito"], "match")
        self.assertIn("confianca", dado["achados"][0])

    def test_err_abstem_explicitamente(self):
        codigo, saida = self.cli("err", ALHEIOS[1])
        self.assertEqual(codigo, 0)
        self.assertIn("nada parecido com confiança", saida)
        dado = json.loads(self.cli("err", ALHEIOS[2], "--json")[1])
        self.assertEqual((dado["veredito"], dado["pistas"]), ("abstain", []))

    def test_err_com_pista_traz_o_veredito_no_json(self):
        dado = json.loads(self.cli("err", VARIACOES[1][0], "--json")[1])
        self.assertEqual(dado["veredito"], "match")
        self.assertEqual(dado["pistas"][0]["veredito"], "match")


ESCOLHE = """import json, sys
p = json.load(sys.stdin)
open(sys.argv[1], 'w').write(json.dumps(p))
ids = [c['id'] for c in p['candidatos']]
print(json.dumps({'escolha': ids[-1], 'confianca': 0.93, 'mesmo_erro': {i: i == ids[-1] for i in ids}}))
"""
ABSTEM = "import json, sys\njson.load(sys.stdin)\nprint(json.dumps({'escolha': 'abstain', 'confianca': 0.9, 'mesmo_erro': {}}))\n"
DORME = "import time\ntime.sleep(30)\n"
NETO_DORME = "import subprocess, sys\nsubprocess.run([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
LIXO = "print('isto nao e json')\n"
SAI_TRES = "import sys\nsys.exit(3)\n"
ID_FALSO = "import json\nprint(json.dumps({'escolha': 'zzz', 'confianca': 1, 'mesmo_erro': {}}))\n"
CONFIANCA_TORTA = "import json, sys\np = json.load(sys.stdin)\nprint(json.dumps({'escolha': p['candidatos'][0]['id'], 'confianca': 'alta'}))\n"
MARCA = "import sys, pathlib\npathlib.Path(sys.argv[1]).write_text('rodou')\nprint('{}')\n"

QUASE_EMPATE = "error: linker `cc` not found"


class TestJuizExterno(CasoComLedger):
    def setUp(self):
        super().setUp()
        Semeador(self.ledger).semear()
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.aviso = io.StringIO()
        self.marca = Path(self._dir.name) / "marca.json"

    def _ledger(self, corpo, timeout=None):
        script = Path(self._dir.name) / "juiz_falso.py"
        script.write_text(corpo)
        cmd = " ".join([sys.executable, str(script), str(self.marca)])
        juiz = JuizExterno(cmd, aviso=self.aviso) if timeout is None else JuizExterno(
            cmd, aviso=self.aviso, timeout=timeout)
        return Ledger.sobre(self.banco, ambiente={}, aviso=self.aviso, juiz=juiz)

    def test_timeout_padrao_e_cinco_segundos(self):
        self.assertEqual(JuizExterno("x").timeout, 5)

    def test_juiz_escolhe_e_o_escolhido_vira_match(self):
        base = Ledger.sobre(self.banco, ambiente={}).decidir(QUASE_EMPATE, so_resolvidos=True)
        d = self._ledger(ESCOLHE).decidir(QUASE_EMPATE, so_resolvidos=True)
        self.assertEqual((d.veredito, d.confianca), ("match", 0.93))
        self.assertEqual(len(d.achados), 1)  # mesmo_erro false derruba os outros
        self.assertEqual(d.achados[0].assinatura, base.achados[-1].assinatura)
        self.assertEqual(d.achados[0].decidido_por, "juiz")
        pedido = json.loads(self.marca.read_text())
        self.assertEqual(pedido["erro"], QUASE_EMPATE)
        self.assertEqual(pedido["perguntas"], ["serve", "mesmo_erro"])
        self.assertEqual(sorted(pedido["candidatos"][0]), ["assinatura", "id", "nota", "score"])
        self.assertTrue(pedido["assinatura"])

    def test_juiz_abstem_e_a_decisao_vira_abstain(self):
        d = self._ledger(ABSTEM).decidir(QUASE_EMPATE, so_resolvidos=True)
        self.assertEqual((d.veredito, d.achados), ("abstain", ()))
        self.assertEqual(self.aviso.getvalue(), "")

    def test_falhas_do_juiz_viram_aviso_e_vale_o_limiar(self):
        base = Ledger.sobre(self.banco, ambiente={}).decidir(QUASE_EMPATE, so_resolvidos=True)
        for corpo in (LIXO, SAI_TRES, ID_FALSO, CONFIANCA_TORTA):
            self.aviso.seek(0)
            self.aviso.truncate()
            d = self._ledger(corpo).decidir(QUASE_EMPATE, so_resolvidos=True)
            self.assertEqual(d, base, corpo)
            self.assertIn("juiz externo falhou", self.aviso.getvalue(), corpo)

    def test_timeout_mata_o_juiz_e_os_netos_sem_travar(self):
        import time
        for corpo in (DORME, NETO_DORME):
            inicio = time.monotonic()
            d = self._ledger(corpo, timeout=0.5).decidir(QUASE_EMPATE, so_resolvidos=True)
            self.assertLess(time.monotonic() - inicio, 5)
            self.assertEqual(d.veredito, "talvez")
            self.assertIn("juiz externo falhou", self.aviso.getvalue())

    def test_assinatura_exata_nunca_chama_o_juiz(self):
        ledger = self._ledger(MARCA)
        ledger.registrar_erro("Timeout 30s em /srv/fila", "acme", com_pistas=False)
        ledger.registrar_correcao("Timeout 30s em /srv/fila", "aumentar o teto", "acme")
        self.assertEqual(ledger.decidir("Timeout 31s em /srv/fila").veredito, "match")
        self.assertFalse(self.marca.exists())

    def test_sem_candidato_nao_chama_o_juiz(self):
        self.assertEqual(self._ledger(MARCA).decidir(ALHEIOS[3]).veredito, "abstain")
        self.assertFalse(self.marca.exists())

    def test_env_pluga_o_juiz_e_sem_env_nada_roda(self):
        script = Path(self._dir.name) / "j.py"
        script.write_text(MARCA)
        cmd = " ".join([sys.executable, str(script), str(self.marca)])
        Ledger.sobre(self.banco, ambiente={}, aviso=self.aviso).decidir(QUASE_EMPATE)
        self.assertFalse(self.marca.exists())
        Ledger.sobre(self.banco, ambiente={"ERRATUM_JUDGE_CMD": cmd}, aviso=self.aviso).decidir(QUASE_EMPATE)
        self.assertTrue(self.marca.exists())
