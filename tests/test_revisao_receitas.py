"""Achados da revisão cruzada sobre as receitas: regex do usuário e stdin do hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.apoio import CasoComLedger

RAIZ = Path(__file__).resolve().parent.parent
HOOK = RAIZ / "hooks" / "pretooluse-check-cmd.py"


class TesteGuardaDeRegex(CasoComLedger):
    def _add(self, regex):
        return self.cli(
            "recipe", "add", "x", "--quando", "q", "--cmd", "bin/x", "--em-vez-de", regex
        )[0]

    def test_repeticao_gigante_e_uso_errado_e_nao_excecao(self):
        self.assertEqual(self._add("a{99999999999999999999}"), 2)

    def test_alternativa_sob_quantificador_aberto_e_recusada(self):
        for ruim in (r"(a|aa)+$", r"(?:x|xy)*z", r"(a|b|ab){2,}c"):
            self.assertEqual(self._add(ruim), 2, ruim)

    def test_alternativa_sem_quantificador_aberto_continua_valendo(self):
        for boa in (r"\bgh\s+(?:pr\s+checks|run\s+watch)\b", r"x\s*(?:&&|;)?\s*y"):
            self.assertEqual(self._add(boa), 0, boa)

    def test_regex_que_estoura_na_hora_de_casar_e_ignorada(self):
        self.assertEqual(self._add(r"\bmake\s+deploy\b"), 0)
        with self.banco.transacao() as con:
            con.execute(
                "UPDATE receitas SET em_vez_de_json = ?",
                (json.dumps(["a{99999999999999999999}", r"\bmake\s+deploy\b"]),),
            )
        self.assertEqual(self.cli("check-cmd", "make deploy")[0], 1)


class TesteHookStdinGigante(unittest.TestCase):
    def test_payload_maior_que_o_teto_passa_sem_consultar(self):
        with tempfile.TemporaryDirectory() as tmp:
            ambiente = dict(os.environ)
            ambiente["ERRATUM_DB"] = str(Path(tmp) / "ledger.db")
            ambiente["PYTHONPATH"] = str(RAIZ)
            ambiente["ERRATUM_HOOK_BLOQUEIA"] = "1"
            subprocess.run(
                [
                    sys.executable, "-m", "erratum", "recipe", "add", "r", "--project", "geral",
                    "--quando", "q", "--cmd", "bin/r", "--em-vez-de", r"\bmake\s+deploy\b",
                ],
                env=ambiente, check=True, capture_output=True,
            )
            payload = json.dumps(
                {
                    "tool_name": "Bash",
                    "tool_input": {"command": "make deploy # " + "x" * (2 * 1024 * 1024)},
                }
            )
            proc = subprocess.run(
                [sys.executable, str(HOOK)], input=payload, env=ambiente,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual((proc.returncode, proc.stdout), (0, ""))
            pequeno = json.dumps({"tool_name": "Bash", "tool_input": {"command": "make deploy"}})
            proc = subprocess.run(
                [sys.executable, str(HOOK)], input=pequeno, env=ambiente,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
