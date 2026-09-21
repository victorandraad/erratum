"""Sementes de receita: cada `em_vez_de` é provado contra três improvisos realistas e contra três
comandos que NÃO podem casar. Falso positivo é o que mata a confiança no `check-cmd`.
"""
from __future__ import annotations

import json

from tests.apoio import CasoComLedger

CASOS = {
    "esperar-ci-do-pr": {
        "improvisos": [
            "while true; do gh pr checks 12; sleep 30; done",
            "sleep 60 && gh pr checks 12 --json state",
            "until gh run view 991 --json conclusion | grep -q success; do\n  sleep 20\ndone",
        ],
        "inocentes": [
            "gh pr view 12 --json state,mergeable",
            "sleep 2",
            "gh pr checks 12",
        ],
        "canonico": "cd /w && gh pr checks 12 --watch --fail-fast",
    },
    "consultar-sqlite-sem-o-binario": {
        "improvisos": [
            "python3 -c \"import sqlite3; c=sqlite3.connect('app.db'); print(c.execute('select 1').fetchall())\"",
            "python -c 'import sqlite3\nfor l in sqlite3.connect(\"a.db\").execute(\"select * from t\"): print(l)'",
            "python3 - <<'EOF'\nimport sqlite3\ncon = sqlite3.connect('a.db')\nprint(con.execute('select count(*) from t').fetchone())\nEOF",
        ],
        "inocentes": [
            "sqlite3 app.db .tables",
            "python3 -c \"print(1)\"",
            "python3 tools/relatorio.py --db app.db",
        ],
        "canonico": "python3 -c \"import sqlite3,sys; [print(*l, sep='|') for l in sqlite3.connect(sys.argv[1]).execute(sys.argv[2])]\" app.db \"select id, nome from t where id > 3\"",
    },
    "suite-com-estado-isolado": {
        "improvisos": [
            "APP_STATE_DIR=/tmp/estado python3 -m unittest discover tests",
            "DATA_HOME=/tmp/t1 pytest -q",
            "export APP_STATE_DIR=/tmp/estado-teste && python -m pytest tests/",
        ],
        "inocentes": [
            "python3 -m unittest discover tests",
            "pytest -x tests/test_a.py",
            "LOG=/tmp/saida.log make build",
        ],
        "canonico": "APP_STATE_DIR=\"$(mktemp -d)\" python3 -m unittest discover tests",
    },
    "worktree-para-trabalho-isolado": {
        "improvisos": [
            "git clone . /tmp/copia-de-trabalho",
            "cp -r . /tmp/repo-copia",
            "rsync -a ./ /tmp/w/",
        ],
        "inocentes": [
            "git clone https://example.com/a/b.git",
            "cp -r src/assets dist/",
            "git worktree list",
        ],
        "canonico": "git worktree add -b tarefa-7 ../repo-tarefa-7 main",
    },
    "reiniciar-servico-com-saude": {
        "improvisos": [
            "systemctl restart api && sleep 5 && curl -s localhost:8080/health",
            "sudo systemctl restart api; sleep 10; curl -fsS http://127.0.0.1:8080/up",
            "service api restart && sleep 3 && curl -I localhost",
        ],
        "inocentes": [
            "systemctl restart api",
            "sleep 2",
            "curl -fsS http://127.0.0.1:8080/health",
        ],
        "canonico": "systemctl restart api && timeout 60 sh -c 'until curl -fsS http://127.0.0.1:8080/health >/dev/null; do sleep 2; done'",
    },
}


class TesteSementesDeReceita(CasoComLedger):
    def setUp(self):
        super().setUp()
        codigo, saida = self.cli("seed", "--json")
        self.assertEqual(codigo, 0)
        self.semeado = json.loads(saida)

    def test_seed_traz_as_cinco_e_e_idempotente(self):
        self.assertEqual(self.semeado["receitas_novas"], 5)
        self.assertEqual(self.semeado["receitas_total"], 5)
        _c, saida = self.cli("seed", "--json")
        self.assertEqual(json.loads(saida)["receitas_novas"], 0)
        linhas = self.banco.consultar("SELECT project, origem, import_key FROM receitas")
        self.assertEqual(len(linhas), 5)
        for linha in linhas:
            self.assertEqual(linha["project"], "geral")
            self.assertEqual(linha["origem"], "semente")
            self.assertTrue(linha["import_key"].startswith("semente-receita:"))

    def test_seed_nao_pisa_na_receita_manual_de_mesmo_nome(self):
        self.cli(
            "recipe", "add", "esperar-ci-do-pr", "--project", "geral",
            "--quando", "meu jeito", "--cmd", "bin/espera <pr>",
        )
        self.cli("seed")
        _c, saida = self.cli("recipe", "show", "esperar-ci-do-pr", "--json")
        self.assertEqual(json.loads(saida)["receita"]["comando"], "bin/espera <pr>")

    def test_seed_list_mostra_as_receitas(self):
        _c, saida = self.cli("seed", "--list")
        for slug in CASOS:
            self.assertIn(slug, saida)
        _c, saida = self.cli("seed", "--list", "--json")
        self.assertEqual(len(json.loads(saida)["receitas"]), 5)

    def test_seed_humano_conta_as_receitas(self):
        _c, saida = self.cli("seed")
        self.assertIn("receitas: 0 novas (total 5)", saida)

    def test_toda_regex_de_semente_passa_pela_guarda(self):
        from erratum.receitas import GuardaDeRegex
        from erratum.sementes import Semeador

        guarda = GuardaDeRegex()
        for semente in Semeador(self.ledger).receitas():
            self.assertTrue(semente["em_vez_de"], semente["slug"])
            for regex in semente["em_vez_de"]:
                guarda.validar(regex)

    def test_improvisos_sao_barrados_e_apontam_a_receita_certa(self):
        for slug, caso in CASOS.items():
            self.assertEqual(len(caso["improvisos"]), 3)
            for comando in caso["improvisos"]:
                codigo, saida = self.cli("check-cmd", comando, "--json")
                self.assertEqual(codigo, 1, comando)
                self.assertEqual(json.loads(saida)["receita"], slug, comando)

    def test_inocentes_passam_em_silencio(self):
        for caso in CASOS.values():
            self.assertEqual(len(caso["inocentes"]), 3)
            for comando in caso["inocentes"]:
                self.assertEqual(self.cli("check-cmd", comando), (0, ""), comando)

    def test_o_comando_canonico_conta_como_uso(self):
        for slug, caso in CASOS.items():
            codigo, saida = self.cli("check-cmd", caso["canonico"], "--json")
            self.assertEqual(codigo, 0, slug)
            dado = json.loads(saida)
            self.assertEqual((dado["tipo"], dado["receita"]), ("uso", slug))

    def test_inocentes_tambem_passam_com_todas_as_sementes_juntas(self):
        # um comando canonico de uma receita nao pode ser desvio de outra
        for slug, caso in CASOS.items():
            codigo, _s = self.cli("check-cmd", caso["canonico"])
            self.assertEqual(codigo, 0, slug)
