"""Portao anti-stub-neutro: classe NOVA que satisfaz um contrato devolvendo constante neutra
([], null, 0, '', false) em TODOS os metodos, sem consultar fonte nenhuma. O erro que ela "conserta"
nao mentia; o vazio que ela devolve vira numero na tela de quem consome.
Rodar: python3 -m unittest tests.test_portoes_stub_neutro
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from erratum import portoes


class FakeRes:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


# ── o caso canonico: provider novo cujo unico metodo devolve [] ───────────────
STUB_CANONICO = """<?php

namespace App\\Services\\Relatorio;

use App\\Models\\Dashboard;

// ponytail: a coleta diaria do Acme ainda nao existe; devolve vazio ate existir.
class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider
{
    public function dailyRows(Dashboard $dashboard, array $params): array
    {
        return [];
    }
}
"""

# Null Object deliberado: o nome ANUNCIA que o vazio e a resposta certa.
NULL_OBJECT = STUB_CANONICO.replace("AcmeRelatorioDiarioProvider", "NullRelatorioDiarioProvider")

# Fake de teste: mesmo corpo, mora em tests/.
FAKE_DE_TESTE = STUB_CANONICO.replace("AcmeRelatorioDiarioProvider", "FakeRelatorioDiarioProvider")

# Implementacao de verdade: consulta a fonte, com early return de guarda.
REAL = """<?php

class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider
{
    public function dailyRows(Dashboard $dashboard, array $params): array
    {
        if (! $dashboard->account_id) {
            return [];
        }

        return $this->insights->daily($dashboard->account_id, $params);
    }
}
"""

# Classe PARCIAL (ISP): um metodo que nao se aplica, os outros reais.
PARCIAL = """<?php

class SmsChannel implements Channel
{
    public function getAttachments(): array
    {
        return [];
    }

    public function send(Message $m): bool
    {
        return $this->client->post('/messages', $m->toArray())->ok();
    }
}
"""

ABSTRATA = """<?php

abstract class BaseFilter implements Filter
{
    protected function defaultFilters(): array
    {
        return [];
    }
}
"""

SERIALIZACAO = """<?php

class EmptyReport implements Arrayable
{
    public function toArray(): array
    {
        return [];
    }
}
"""

FEATURE_FLAG = """<?php

class RelatorioFeature implements Feature
{
    public function isEnabled(): bool
    {
        return false;
    }
}
"""

PY_STUB = '''from .contracts import RelatorioDiarioProvider


class AcmeRelatorioDiarioProvider(RelatorioDiarioProvider):
    """Serie diaria do Acme."""

    def daily_rows(self, dashboard, params):
        # a coleta ainda nao existe
        return []
'''

PY_PROTOCOL = '''from typing import Protocol


class RelatorioDiarioProvider(Protocol):
    def daily_rows(self, dashboard, params) -> list:
        return []
'''

TS_STUB = """export class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider {
  dailyRows(dashboard: Dashboard, params: Params): Row[] {
    return [];
  }
}
"""

JS_NOOP_HANDLER = """export class Painel {
  constructor(props) {
    this.props = props;
  }
}

const onChange = () => {};
export default onChange;
"""


# ── ALTA 1: o contrato so tem "implementacao" em TESTE (fake/mock) ────────────
# Interface sem impl de producao quase sempre tem um fake em tests/, porque foi assim que ela
# chegou a ser testada. Contar esse fake como "ja tem impl concreta" silencia o portao no caso real.

# ── ALTA 2: injecao de dependencia por construtor (padrao comum) ───
STUB_COM_CONSTRUTOR = """<?php

namespace App\\Services\\Relatorio;

class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider
{
    public function __construct(private readonly InsightsClient $insights)
    {
        $this->insights = $insights;
    }

    public function dailyRows(Dashboard $dashboard, array $params): array
    {
        return [];
    }
}
"""

PY_STUB_COM_INIT = '''class AcmeRelatorioDiarioProvider(RelatorioDiarioProvider):
    def __init__(self, insights):
        self.insights = insights

    def daily_rows(self, dashboard, params):
        return []
'''

TS_STUB_COM_CONSTRUCTOR = """export class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider {
  constructor(private readonly insights: InsightsClient) {
    this.insights = insights;
  }

  dailyRows(dashboard: Dashboard, params: Params): Row[] {
    return [];
  }
}
"""

# ── MEDIA 3: as grafias idiomaticas de colecao vazia ──────────────────────────
def _com_corpo(corpo):
    return STUB_CANONICO.replace("        return [];", f"        return {corpo};")


# ── BAIXA 4: contrato totalmente qualificado ─────────────────────────────────
STUB_FQN = STUB_CANONICO.replace("implements RelatorioDiarioProvider",
                                 "implements \\App\\Contracts\\RelatorioDiarioProvider")


def monta(files, *, novos=None, outra_impl=False, impl_paths=None):
    """Escreve os arquivos num worktree de verdade em tmp e devolve (path, dispatcher do `sh`).
    Só o git e mockado: o portao le o arquivo do disco."""
    wt = Path(tempfile.mkdtemp())
    for rel, src in files.items():
        p = wt / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(src, encoding="utf-8")
    novos = set(files) if novos is None else set(novos)

    def fake(cmd, **kw):
        if cmd[:2] == ["git", "diff"]:
            return FakeRes(out="".join(f"{f}\n" for f in files))
        if cmd[:2] == ["git", "cat-file"]:
            # rc 0 = o arquivo JA existia na base (nao e novo)
            rel = cmd[-1].split(":", 1)[-1]
            return FakeRes(rc=1 if rel in novos else 0)
        if cmd[:2] == ["git", "grep"]:
            # o grep devolve os CAMINHOS que citam o contrato na base; rc 1 = nenhum
            achou = (["app/Relatorio/OutroProvider.php"] if outra_impl else []) + list(impl_paths or [])
            if not achou:
                return FakeRes(rc=1)
            return FakeRes(rc=0, out="".join(f"{cmd[-1]}:{f}\n" for f in achou))
        return FakeRes(rc=0)
    return str(wt), fake


def roda(files, settings=None, **kw):
    wt, fake = monta(files, **kw)
    diff = portoes.DiffDoDev(wt, "origin/main", sh=fake)
    return portoes.PortaoStubNeutro(diff, settings or {}).rodar()


class AcusaOCasoReal(unittest.TestCase):
    def test_provider_que_so_devolve_vazio(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_CANONICO})
        self.assertTrue(g.rodou)
        self.assertTrue(g.reprovou, "o caso canonico tem que ser acusado")
        # mensagem util: arquivo, classe, metodo e a pergunta
        self.assertIn("AcmeRelatorioDiarioProvider.php", g.detalhe)
        self.assertIn("dailyRows", g.detalhe)
        self.assertIn("RelatorioDiarioProvider", g.detalhe)

    def test_python(self):
        g = roda({"src/relatorio/acme.py": PY_STUB})
        self.assertTrue(g.reprovou)
        self.assertIn("daily_rows", g.detalhe)

    def test_typescript(self):
        g = roda({"resources/js/relatorio/provider.ts": TS_STUB})
        self.assertTrue(g.reprovou)
        self.assertIn("dailyRows", g.detalhe)


class NaoAcusaOsFalsosPositivos(unittest.TestCase):
    def test_null_object_pelo_nome(self):
        self.assertFalse(roda({"app/Relatorio/NullRelatorioDiarioProvider.php": NULL_OBJECT}).reprovou)

    def test_contrato_que_ja_tem_implementacao_concreta(self):
        g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_CANONICO}, outra_impl=True)
        self.assertFalse(g.reprovou, "se o neutro nasce ao lado de uma impl real, e Null Object")

    def test_fake_dentro_de_tests(self):
        self.assertFalse(roda({"tests/Fakes/FakeRelatorioDiarioProvider.php": FAKE_DE_TESTE}).reprovou)

    def test_factory_e_vendor(self):
        g = roda({"database/factories/RelatorioFactory.php": STUB_CANONICO,
                  "vendor/acme/src/Provider.php": STUB_CANONICO})
        self.assertFalse(g.reprovou)

    def test_implementacao_real_com_early_return_de_guarda(self):
        self.assertFalse(roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": REAL}).reprovou)

    def test_classe_parcial_isp(self):
        self.assertFalse(roda({"app/Channels/SmsChannel.php": PARCIAL}).reprovou)

    def test_classe_abstrata_com_default_sobrescrivel(self):
        self.assertFalse(roda({"app/Filters/BaseFilter.php": ABSTRATA}).reprovou)

    def test_contrato_de_serializacao(self):
        self.assertFalse(roda({"app/Reports/EmptyReport.php": SERIALIZACAO}).reprovou)

    def test_feature_flag_desligada(self):
        self.assertFalse(roda({"app/Features/RelatorioFeature.php": FEATURE_FLAG}).reprovou)

    def test_arquivo_que_ja_existia_nao_e_implementacao_nova(self):
        g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_CANONICO}, novos=[])
        self.assertFalse(g.reprovou)

    def test_python_protocol_e_abstract(self):
        self.assertFalse(roda({"src/relatorio/contracts.py": PY_PROTOCOL}).reprovou)

    def test_js_noop_handler_solto(self):
        self.assertFalse(roda({"resources/js/Painel.js": JS_NOOP_HANDLER}).reprovou)


class GuardaDoContratoIgnoraTeste(unittest.TestCase):
    """ALTA 1: fake/mock em tests/ NAO conta como implementacao concreta na base. Foi o que
    silenciaria o portao quando o unico `implements RelatorioDiarioProvider` da base mora em tests/."""

    def test_so_fake_em_tests_ainda_acusa(self):
        g = roda({"app/Services/Score/AcmeRelatorioDiarioProvider.php": STUB_CANONICO},
                 impl_paths=["tests/Feature/Score/RelatorioEndpointTest.php",
                             "tests/Browser/RelatorioTelaTest.php"])
        self.assertTrue(g.reprovou, "impl so em teste nao e impl: o portao tem que acusar")

    def test_stub_fora_de_tests_mas_com_nome_de_double_tambem_nao_conta(self):
        g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_CANONICO},
                 impl_paths=["app/Support/FakeRelatorioDiarioProvider.php"])
        self.assertTrue(g.reprovou)

    def test_impl_de_producao_de_verdade_continua_calando(self):
        g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_CANONICO},
                 impl_paths=["tests/Feature/X.php", "app/Relatorio/OutroRelatorioDiarioProvider.php"])
        self.assertFalse(g.reprovou)

    def test_python_tambem_tem_a_guarda(self):
        """BAIXA 5: a guarda vale pras tres linguagens (em Python a heranca e o `implements`)."""
        g = roda({"src/relatorio/acme.py": PY_STUB},
                 impl_paths=["src/relatorio/outro.py"])
        self.assertFalse(g.reprovou, "irmao concreto na base = Null Object legitimo, tambem em .py")
        self.assertTrue(roda({"src/relatorio/acme.py": PY_STUB},
                             impl_paths=["tests/fakes/relatorio.py"]).reprovou)


class ConstrutorNaoEMetodoDeContrato(unittest.TestCase):
    """ALTA 2: injecao por construtor e padrao comum; contar `__construct`/`__init__` como
    metodo nao-neutro deixava a classe inteira escapar."""

    def test_php_com_construct(self):
        g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_COM_CONSTRUTOR})
        self.assertTrue(g.reprovou)
        self.assertIn("dailyRows", g.detalhe)
        self.assertNotIn("__construct", g.detalhe)

    def test_python_com_init(self):
        g = roda({"src/relatorio/acme.py": PY_STUB_COM_INIT})
        self.assertTrue(g.reprovou)
        self.assertNotIn("__init__", g.detalhe)

    def test_typescript_com_constructor(self):
        self.assertTrue(roda({"resources/js/relatorio/p.ts": TS_STUB_COM_CONSTRUCTOR}).reprovou)

    def test_classe_que_so_tem_construtor_nao_e_acusada(self):
        src = """<?php

class Painel implements Renderizavel
{
    public function __construct(private array $props)
    {
        $this->props = $props;
    }
}
"""
        self.assertFalse(roda({"app/Painel.php": src}).reprovou)


class GrafiasDeColecaoVazia(unittest.TestCase):
    """MEDIA 3: `collect([])` e grafia idiomatica de colecao vazia em PHP."""

    def test_grafias_reconhecidas(self):
        for corpo in ["collect([])", "collect()", "collect( [] )", "new Collection()",
                      "new Collection", "new Collection([])", "Collection::make([])",
                      "Collection::make()", "new \\Illuminate\\Support\\Collection()",
                      "[]", "array()", "null", "0", "false", "''"]:
            with self.subTest(corpo=corpo):
                g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": _com_corpo(corpo)})
                self.assertTrue(g.reprovou, f"{corpo} e constante neutra")

    def test_nao_confunde_colecao_com_dado(self):
        for corpo in ["collect($this->insights->daily($dashboard))", "$this->rows",
                      "Collection::make($rows)", "new Collection($rows)"]:
            with self.subTest(corpo=corpo):
                self.assertFalse(roda({"app/Relatorio/P.php": _com_corpo(corpo)}).reprovou)


class NomeDoContratoQualificado(unittest.TestCase):
    """BAIXA 4: `implements \\App\\Contracts\\X` nomeava o contrato como "App"."""

    def test_usa_o_ultimo_segmento(self):
        g = roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_FQN})
        self.assertTrue(g.reprovou)
        self.assertIn("`RelatorioDiarioProvider`", g.detalhe)
        self.assertNotIn("`App`", g.detalhe)



# ── criterio do parametro ignorado: TODOS os returns neutros + NENHUM parametro usado ───────────
# O criterio estreito ("corpo inteiro == um return neutro") tem ruido zero,
# mas cego pro que um dev escreve naturalmente (log antes do return, vazio guardado em variavel,
# guarda de config). O discriminador novo e o PARAMETRO IGNORADO: o stub recebe exatamente o que
# descreve o que buscar e nunca toca em nada disso; quem faz trabalho de verdade usa o que recebeu.
def _php(corpo, assinatura="dailyRows(Dashboard $dashboard, array $params): array"):
    return ("""<?php

namespace App\\Services\\Relatorio;

class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider
{
    public function %s
    {
%s
    }
}
""" % (assinatura, corpo))


class CriterioParametroIgnorado(unittest.TestCase):
    """Acusa quando TODOS os `return` do metodo devolvem constante neutra E o metodo nao usa
    nenhum dos seus parametros."""

    def test_log_antes_do_return(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        Log::info('sem coletor para o Acme');\n\n        return [];")})
        self.assertTrue(g.reprovou)
        self.assertIn("dailyRows", g.detalhe)

    def test_vazio_guardado_em_variavel(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        $rows = [];\n\n        return $rows;")})
        self.assertTrue(g.reprovou)

    def test_guarda_de_config_com_dois_returns_neutros(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        if (! config('relatorio.acme')) {\n"
                       "            return [];\n        }\n\n        return [];")})
        self.assertTrue(g.reprovou)

    def test_caso_real_com_e_sem_construtor(self):
        self.assertTrue(roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": STUB_CANONICO}).reprovou)
        self.assertTrue(roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php":
                              STUB_COM_CONSTRUTOR}).reprovou)

    def test_mensagem_diz_qual_parametro_foi_ignorado(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        Log::info('sem coletor');\n\n        return [];")})
        self.assertIn("$dashboard", g.detalhe)
        self.assertIn("$params", g.detalhe)

    def test_this_nao_e_parametro(self):
        """Metodo que so usa `$this` e ignora os argumentos continua acusado: ele ignorou o que
        descrevia a busca."""
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        $this->logger->warning('sem coletor');\n\n        return [];")})
        self.assertTrue(g.reprovou)

    def test_self_nao_conta_como_parametro_em_python(self):
        src = '''class AcmeRelatorioDiarioProvider(RelatorioDiarioProvider):
    def daily_rows(self, dashboard, params):
        self.logger.warning("sem coletor")
        return []
'''
        g = roda({"src/relatorio/acme.py": src})
        self.assertTrue(g.reprovou)
        self.assertIn("dashboard", g.detalhe)

    def test_typescript(self):
        src = """export class AcmeRelatorioDiarioProvider implements RelatorioDiarioProvider {
  dailyRows(dashboard: Dashboard, params: Params): Row[] {
    console.warn('sem coletor');
    return [];
  }
}
"""
        g = roda({"resources/js/relatorio/provider.ts": src})
        self.assertTrue(g.reprovou)
        self.assertIn("dashboard", g.detalhe)

    def test_default_variadico_e_por_referencia_contam_igual(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        Log::info('sem coletor');\n\n        return [];",
                       "dailyRows(array &$out, array $params = [], int ...$ids): array")})
        self.assertTrue(g.reprovou)
        self.assertIn("$out", g.detalhe)
        self.assertIn("$ids", g.detalhe)

    def test_nome_curto_nao_casa_dentro_de_outra_palavra(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        $identificador = $this->ids[0];\n\n        return [];",
                       "dailyRows(int $id): array")})
        self.assertTrue(g.reprovou, "`$identificador` e `$this->ids` nao sao uso de `$id`")


class ContinuaLimpoNoCriterioNovo(unittest.TestCase):
    """Vazio honesto, nao promessa quebrada."""

    def test_getter_sem_parametro(self):
        src = """<?php

class ValidadorDeConta implements Validavel
{
    public function getErrors(): array
    {
        return [];
    }
}
"""
        self.assertFalse(roda({"app/Contas/ValidadorDeConta.php": src}).reprovou)

    def test_null_object(self):
        src = """<?php

class NullLogger implements Logger
{
    public function log($m): void
    {
    }
}
"""
        self.assertFalse(roda({"app/Log/NullLogger.php": src}).reprovou)

    def test_usa_o_parametro(self):
        src = """<?php

class ContaRepositorio implements Persistivel
{
    public function salvar($x): array
    {
        $this->repo->save($x);

        return [];
    }
}
"""
        self.assertFalse(roda({"app/Contas/ContaRepositorio.php": src}).reprovou)

    def test_usa_so_um_dos_parametros(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        $this->cache->put($dashboard->id, []);\n\n        return [];")})
        self.assertFalse(g.reprovou, "usou um parametro: nao ignorou o que descreve a busca")

    def test_corpo_vazio_com_parametro_continua_fora(self):
        src = """<?php

class ContaObserver implements Observador
{
    public function notificar(Evento $e): void
    {
    }
}
"""
        self.assertFalse(roda({"app/Contas/ContaObserver.php": src}).reprovou)

    def test_variavel_que_e_preenchida_nao_e_constante_neutra(self):
        g = roda({"app/Services/Relatorio/AcmeRelatorioDiarioProvider.php":
                  _php("        $rows = [];\n        foreach ($this->cliente->linhas() as $l) {\n"
                       "            $rows[] = $l;\n        }\n\n        return $rows;")})
        self.assertFalse(g.reprovou)

    def test_implementacao_real_e_classe_parcial_seguem_limpas(self):
        self.assertFalse(roda({"app/Relatorio/AcmeRelatorioDiarioProvider.php": REAL}).reprovou)
        self.assertFalse(roda({"app/Channels/SmsChannel.php": PARCIAL}).reprovou)


class Configuracao(unittest.TestCase):
    def test_flag_desligada_por_repo(self):
        chamadas = []
        diff = portoes.DiffDoDev("/tmp/nada", "origin/main",
                                 sh=lambda cmd, **kw: chamadas.append(cmd) or FakeRes())
        r = portoes.PortaoStubNeutro(diff, {"stub_neutro_gate": False}).rodar()
        self.assertTrue(r.pulou)
        self.assertEqual([], chamadas)

    def test_nao_levanta_pro_chamador(self):
        def boom(cmd, **kw):
            raise RuntimeError("boom")
        logs = []
        r = portoes.PortaoStubNeutro(portoes.DiffDoDev("/tmp/nada", "origin/main", sh=boom),
                                     {}, log=logs.append).rodar()
        self.assertTrue(r.pulou)
        self.assertFalse(r.reprovou)
        self.assertIn("boom", logs[0])


if __name__ == "__main__":
    unittest.main()
