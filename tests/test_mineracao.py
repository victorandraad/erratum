"""`scan` (stream-json de agente) e `import` (JSONL generico): alimentam o ledger em lote e sao
idempotentes, porque a mesma fonte e relida a cada varredura."""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

from erratum.ledger import Ledger
from erratum.mineracao import ImportadorJsonl, MineradorDeStream
from tests.apoio import CasoComLedger


def _uso(id_, nome):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": id_, "name": nome, "input": {}}]}}


def _retorno(id_, conteudo, erro=True):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": id_, "is_error": erro, "content": conteudo}]}}


STREAM = [
    {"type": "system", "subtype": "init"},
    _uso("t1", "Bash"),
    _retorno("t1", "Exit 127 /tmp/x-47062/vendor/bin/runner: No such file"),
    _uso("t2", "Edit"),
    _retorno("t2", [{"type": "text", "text": "String to replace not found"}]),
    _uso("t3", "Bash"),
    _retorno("t3", "tudo certo", erro=False),
    _uso("t4", "Bash"),
    _retorno("t4", "Exit 127 /tmp/y-99/vendor/bin/runner: No such file"),
    _retorno("orfao", "erro sem tool_use antes"),
    {"type": "assistant", "message": "texto solto"},
]


class ComArquivos(CasoComLedger):
    def setUp(self):
        super().setUp()
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)

    def _arquivo(self, nome, linhas):
        caminho = Path(self._dir.name) / nome
        caminho.write_text("".join(
            (l if isinstance(l, str) else json.dumps(l)) + "\n" for l in linhas))
        return caminho

    def _erros(self):
        return self.banco.consultar("SELECT * FROM errors ORDER BY id")


class TestMinerador(ComArquivos):
    def test_extrai_so_tool_result_com_erro_e_acha_a_ferramenta(self):
        erros = MineradorDeStream().extrair(STREAM)
        self.assertEqual([(e.ferramenta, e.texto) for e in erros], [
            ("Bash", "Exit 127 /tmp/x-47062/vendor/bin/runner: No such file"),
            ("Edit", "String to replace not found"),
            ("Bash", "Exit 127 /tmp/y-99/vendor/bin/runner: No such file"),
            ("?", "erro sem tool_use antes"),
        ])

    def test_agrega_por_assinatura_contando_execucoes_distintas(self):
        outra = [_uso("a", "Edit"), _retorno("a", "String to replace not found")]
        grupos = MineradorDeStream().agregar([("run1", STREAM), ("run2", outra)])
        self.assertEqual(grupos[0].assinatura, "string to replace not found")
        self.assertEqual((grupos[0].execucoes, grupos[0].ocorrencias, grupos[0].ferramenta),
                         (2, 2, "Edit"))
        self.assertEqual((grupos[1].execucoes, grupos[1].ocorrencias), (1, 2))

    def test_scan_grava_no_ledger_e_e_idempotente(self):
        caminho = self._arquivo("T-run.jsonl", STREAM + ["linha que nao e json", ""])
        codigo, saida = self.cli("scan", str(caminho), "--json")
        self.assertEqual(codigo, 0, saida)
        dado = json.loads(saida)
        self.assertEqual((dado["lidos"], dado["novos"]), (4, 4))
        linhas = self._erros()
        self.assertEqual(len(linhas), 4)
        self.assertEqual({l["project"] for l in linhas}, {"acme"})
        self.assertEqual({l["kind"] for l in linhas}, {"exec_error"})
        self.assertEqual(linhas[1]["tool"], "Edit")
        # a execucao (nome do arquivo sem extensao) e a task: e o que o top conta como distinto
        self.assertEqual(json.loads(linhas[0]["context_json"])["task"], "T-run")
        codigo, saida = self.cli("scan", str(caminho), "--json")
        self.assertEqual(json.loads(saida)["novos"], 0)
        self.assertEqual(len(self._erros()), 4)
        self.assertEqual(self.ledger.o_que_repete("acme")[0].ocorrencias, 2)

    def test_dois_erros_iguais_sem_id_na_mesma_execucao_sao_duas_ocorrencias(self):
        repetido = [_retorno(None, "falha identica"), _retorno(None, "falha identica")]
        caminho = self._arquivo("run.jsonl", repetido)
        self.cli("scan", str(caminho))
        self.assertEqual(len(self._erros()), 2)
        # stream so cresce no fim: reler com mais eventos nao duplica os antigos
        caminho = self._arquivo("run.jsonl", repetido + [_retorno(None, "falha identica")])
        self.cli("scan", str(caminho))
        self.assertEqual(len(self._erros()), 3)

    def test_scan_de_arquivo_inexistente_e_uso_errado(self):
        self.assertEqual(self.cli("scan", str(Path(self._dir.name) / "nao-existe.jsonl"))[0], 2)


class TestImport(ComArquivos):
    LINHAS = [
        {"ts": "2025-03-01T10:00:00+00:00", "project": "loja", "text": "push rejeitado 1",
         "kind": "falhou", "stage": "dev", "tool": "git", "task": "c1"},
        {"ts": "2025-03-02T10:00:00+00:00", "project": "loja", "text": "push rejeitado 2"},
        {"text": "sem projeto nem ts"},
        {"ts": "2025-03-03T10:00:00+00:00", "project": "loja"},
        "nao e json",
        [1, 2],
    ]

    def test_importar_duas_vezes_da_a_mesma_contagem(self):
        caminho = self._arquivo("dados.jsonl", self.LINHAS)
        codigo, saida = self.cli("import", str(caminho), "--json")
        self.assertEqual(codigo, 0, saida)
        self.assertEqual(json.loads(saida), {"lidos": 3, "novos": 3, "ignorados": 3})
        codigo, saida = self.cli("import", str(caminho), "--json")
        self.assertEqual(json.loads(saida), {"lidos": 3, "novos": 0, "ignorados": 3})
        self.assertEqual(len(self._erros()), 3)

    def test_preserva_campos_da_linha_e_cai_no_padrao_quando_falta(self):
        self.cli("import", str(self._arquivo("dados.jsonl", self.LINHAS)))
        a, b, c = self._erros()
        self.assertEqual((a["ts"], a["project"], a["kind"], a["stage"], a["tool"]),
                         ("2025-03-01T10:00:00+00:00", "loja", "falhou", "dev", "git"))
        self.assertEqual(json.loads(a["context_json"])["task"], "c1")
        self.assertEqual(a["signature"], b["signature"])
        self.assertEqual((b["kind"], b["stage"], b["tool"]), ("error", "", ""))
        # sem project na linha vale o --project; sem ts vale o relogio do ledger
        self.assertEqual(c["project"], "acme")
        self.assertTrue(c["ts"].startswith("2026-01-01"))

    def test_mesma_linha_em_arquivos_diferentes_nao_duplica(self):
        self.cli("import", str(self._arquivo("a.jsonl", self.LINHAS[:2])))
        self.cli("import", str(self._arquivo("b.jsonl", self.LINHAS[:3])))
        self.assertEqual(len(self._erros()), 3)

    def test_mesma_linha_sem_project_em_projetos_diferentes_sao_dois_registros(self):
        caminho = self._arquivo("dados.jsonl", [{"text": "sem projeto nem ts"}])
        self.cli("import", str(caminho), "--project", "loja")
        self.cli("import", str(caminho), "--project", "blog")
        self.cli("import", str(caminho), "--project", "blog")
        self.assertEqual(sorted(l["project"] for l in self._erros()), ["blog", "loja"])

    def test_importador_direto_devolve_a_contagem(self):
        relatorio = ImportadorJsonl(self.ledger).importar(
            [json.dumps(l) for l in self.LINHAS[:2]], "acme")
        self.assertEqual((relatorio.lidos, relatorio.novos, relatorio.ignorados), (2, 2, 0))

    def test_import_de_arquivo_inexistente_e_uso_errado(self):
        self.assertEqual(self.cli("import", str(Path(self._dir.name) / "nao-existe.jsonl"))[0], 2)

    def test_carga_em_lote_nao_dispara_a_busca_externa(self):
        marca = Path(self._dir.name) / "marca"
        script = Path(self._dir.name) / "busca.py"
        script.write_text("import sys, pathlib\npathlib.Path(sys.argv[1]).write_text('x')\n")
        self.ledger = Ledger.sobre(
            self.banco, relogio=self.relogio, aviso=io.StringIO(),
            ambiente={"ERRATUM_SEARCH_CMD": "%s %s %s" % (sys.executable, script, marca)})
        self.cli("import", str(self._arquivo("dados.jsonl", self.LINHAS)))
        self.cli("scan", str(self._arquivo("run.jsonl", STREAM)))
        self.assertFalse(marca.exists())
        self.assertEqual(len(self._erros()), 7)
