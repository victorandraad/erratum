"""Achados da revisão cruzada: confiança NaN do juiz e task homônima em projetos diferentes."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

from erratum.decisao import JuizExterno
from erratum.ledger import Ledger
from erratum.sementes import Semeador
from tests.apoio import CasoComLedger
from tests.test_sementes import VARIACOES

NAN = "import json, sys\np = json.load(sys.stdin)\nprint('{\"escolha\": \"1\", \"confianca\": NaN}')\n"
ALHEIO = "kernel panic - not syncing: VFS unable to mount root fs"


class TestJuizComNaN(CasoComLedger):
    def test_confianca_nan_e_falha_do_juiz(self):
        Semeador(self.ledger).semear()
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "j.py"
            script.write_text(NAN)
            aviso = io.StringIO()
            juiz = JuizExterno("%s %s" % (sys.executable, script), aviso=aviso)
            texto = "error: linker `cc` not found"
            base = Ledger.sobre(self.banco, ambiente={}).decidir(texto, so_resolvidos=True)
            d = Ledger.sobre(self.banco, ambiente={}, juiz=juiz).decidir(texto, so_resolvidos=True)
            self.assertEqual(d, base)
            self.assertIn("juiz externo falhou", aviso.getvalue())


class TestEfeitoNaoMisturaProjetos(CasoComLedger):
    def test_mesma_task_em_dois_projetos_sao_duas_tasks(self):
        Semeador(self.ledger).semear()
        self.cli("err", VARIACOES[0][0], "--task", "T-1", "--project", "loja")
        self.cli("desfecho", "T-1", "nao_resolveu", "--project", "loja")
        self.cli("err", ALHEIO, "--task", "T-1", "--project", "blog")
        self.cli("desfecho", "T-1", "resolveu", "--project", "blog")
        dado = json.loads(self.cli("efeito", "--all-projects", "--json")[1])
        g = {x["grupo"]: x for x in dado["tasks"]}
        self.assertEqual((g["match"]["n"], g["match"]["resolveu"]), (1, 0))
        self.assertEqual((g["abstain"]["n"], g["abstain"]["resolveu"]), (1, 1))
        self.assertEqual(g["geral"]["n"], 2)
