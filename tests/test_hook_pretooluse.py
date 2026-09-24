"""Hook PreToolUse (hooks/pretooluse-check-cmd.py): lê o JSON do hook no stdin, passa o comando Bash
pelo `erratum check-cmd` e, por padrão, AVISA e deixa passar. Falha do erratum nunca trava o Bash.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HOOK = RAIZ / "hooks" / "pretooluse-check-cmd.py"


class TesteHookPreToolUse(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = str(Path(self._tmp.name) / "ledger.db")
        self.ambiente = dict(os.environ)
        self.ambiente.pop("ERRATUM_HOOK_BLOQUEIA", None)
        self.ambiente.pop("ERRATUM_JUDGE_CMD", None)
        self.ambiente["ERRATUM_DB"] = self.db
        self.ambiente["PYTHONPATH"] = str(RAIZ)
        self.ambiente["PYTHONDONTWRITEBYTECODE"] = "1"
        subprocess.run(
            [
                sys.executable, "-m", "erratum", "recipe", "add", "esperar-ci",
                "--project", "geral", "--quando", "esperar o CI",
                "--cmd", "bin/ci-espera <pr>", "--perigo", "rode em background",
                "--em-vez-de", r"\bgh\s+(pr\s+checks|run\s+watch)\b",
            ],
            env=self.ambiente, check=True, capture_output=True,
        )

    def _rodar(self, payload, **env):
        ambiente = dict(self.ambiente)
        ambiente.update(env)
        entrada = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            [sys.executable, str(HOOK)], input=entrada, env=ambiente,
            capture_output=True, text=True, timeout=30,
        )

    def _payload(self, comando, ferramenta="Bash"):
        return {
            "session_id": "sessao-1",
            "cwd": self._tmp.name,
            "hook_event_name": "PreToolUse",
            "tool_name": ferramenta,
            "tool_input": {"command": comando},
        }

    def _usos(self):
        import sqlite3

        con = sqlite3.connect(self.db)
        try:
            return con.execute("SELECT tipo, task FROM usos_de_receita").fetchall()
        finally:
            con.close()

    def test_padrao_avisa_no_contexto_do_modelo_e_deixa_passar(self):
        proc = self._rodar(self._payload("gh pr checks 12 --watch"))
        self.assertEqual(proc.returncode, 0)
        saida = json.loads(proc.stdout)["hookSpecificOutput"]
        self.assertEqual(saida["hookEventName"], "PreToolUse")
        self.assertIn("use a receita esperar-ci: bin/ci-espera <pr>", saida["additionalContext"])
        self.assertIn("rode em background", saida["additionalContext"])
        self.assertNotIn("permissionDecision", saida)
        self.assertEqual(self._usos(), [("desvio", "sessao-1")])

    def test_bloqueante_so_com_a_variavel(self):
        proc = self._rodar(self._payload("gh run watch 3"), ERRATUM_HOOK_BLOQUEIA="1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("use a receita esperar-ci", proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_comando_sem_receita_e_silencio(self):
        for bloqueia in ("", "1"):
            proc = self._rodar(self._payload("ls -la"), ERRATUM_HOOK_BLOQUEIA=bloqueia)
            self.assertEqual((proc.returncode, proc.stdout, proc.stderr), (0, "", ""))

    def test_outra_ferramenta_passa_sem_consultar(self):
        proc = self._rodar(self._payload("gh pr checks 12", ferramenta="Read"))
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        self.assertEqual(self._usos(), [])

    def test_stdin_torto_nunca_trava(self):
        tortos = [
            "", "nao e json", "[]", "null", '{"tool_name": "Bash"}',
            '{"tool_name": "Bash", "tool_input": null}',
            '{"tool_name": "Bash", "tool_input": {"command": 7}}',
            '{"tool_name": "Bash", "tool_input": {"command": ""}}',
        ]
        for torto in tortos:
            proc = self._rodar(torto, ERRATUM_HOOK_BLOQUEIA="1")
            self.assertEqual((proc.returncode, proc.stdout), (0, ""), torto)

    def test_erratum_quebrado_nunca_trava(self):
        payload = self._payload("gh pr checks 12 --watch")
        for env in (
            {"ERRATUM_PYTHON": "/nao/existe/python"},
            {"ERRATUM_DB": "/proc/nao-da-pra-criar/ledger.db"},
        ):
            proc = self._rodar(payload, ERRATUM_HOOK_BLOQUEIA="1", **env)
            self.assertEqual((proc.returncode, proc.stdout), (0, ""), env)

    def test_comando_que_comeca_com_traco_nao_vira_flag(self):
        proc = self._rodar(self._payload("--json; gh run watch 3"))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("esperar-ci", proc.stdout)

    def test_cwd_inexistente_nao_trava(self):
        payload = self._payload("gh run watch 3")
        payload["cwd"] = "/nao/existe"
        proc = self._rodar(payload)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("esperar-ci", proc.stdout)

    def test_commit_no_verify_e_barrado_sempre(self):
        for comando in ("git commit --no-verify -m x", "git commit -n -m x", "git commit -nm x",
                        "git add a && git commit -am x -n", "git -C repo commit --no-verify"):
            proc = self._rodar(self._payload(comando))  # sem ERRATUM_HOOK_BLOQUEIA
            self.assertEqual(proc.returncode, 2, comando)
            self.assertIn("--no-verify", proc.stderr, comando)
            self.assertIn("portão", proc.stderr, comando)

    def test_commit_no_verify_barrado_em_ingles_por_padrao(self):
        proc = self._rodar(self._payload("git commit --no-verify -m x"), ERRATUM_LANG="")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("fix the gate that failed", proc.stderr)

    def test_commit_sem_no_verify_passa(self):
        for comando in ('git commit -m "x"', 'git commit -m "usa -n aqui"',
                        "git commit -m 'pula --no-verify nunca'", "git log -n 3",
                        "git commit --amend --no-edit"):
            proc = self._rodar(self._payload(comando), ERRATUM_HOOK_BLOQUEIA="1")
            self.assertEqual((proc.returncode, proc.stderr), (0, ""), comando)


if __name__ == "__main__":
    unittest.main()
