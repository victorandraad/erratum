"""O contador nao perde incremento com varias CLIs ao mesmo tempo.

A esteira roda agentes em paralelo e cada um abre o proprio Banco. Se o incremento
fosse ler-somar-gravar em Python, dois processos leriam o mesmo valor e uma das
repeticoes sumiria. A cobertura anterior de concorrencia passou a usar assinaturas
distintas (o contador colapsa iguais), entao este caso ficou sem teste.
"""
from __future__ import annotations

import multiprocessing
import tempfile
import unittest
from pathlib import Path


def _martelar(args):
    caminho, quantos = args
    from erratum.banco import Banco
    from erratum.ledger import Ledger
    with Banco(caminho) as banco:
        ledger = Ledger.sobre(banco)
        for _ in range(quantos):
            ledger.registrar_erro(
                "quarentena sem pronto", "acme",
                contexto={"task": "t1"}, com_pistas=False)
    return quantos


class TestIncrementoConcorrente(unittest.TestCase):
    """O que o contador garante sob concorrencia, e o que nao garante.

    Garante: nenhum incremento perdido, porque o UPDATE soma no proprio SQL dentro
    da transacao, sem ler-somar-gravar em Python.
    Nao garante linha unica: a consulta do ultimo erro do escopo acontece fora da
    transacao do insert, entao N processos que comecam juntos podem abrir ate N
    linhas antes de convergirem. O teto e o numero de escritores simultaneos, nao
    o numero de ticks, que era o problema original. Se um dia incomodar, o conserto
    e indice unico por (projeto, task, assinatura) com upsert.
    """

    def test_nenhum_incremento_se_perde(self):
        processos, por_processo = 4, 25
        with tempfile.TemporaryDirectory() as tmp:
            caminho = str(Path(tmp) / "ledger.db")
            from erratum.banco import Banco
            with Banco(caminho) as banco:
                banco.consultar("SELECT 1", ())
            with multiprocessing.Pool(processos) as pool:
                pool.map(_martelar, [(caminho, por_processo)] * processos)
            with Banco(caminho) as banco:
                linhas = banco.consultar(
                    "SELECT repetitions AS r FROM errors WHERE signature LIKE 'quarentena%'", ())
        total = sum(l["r"] for l in linhas)
        self.assertEqual(total, processos * por_processo, "incremento perdido na corrida")
        self.assertLessEqual(len(linhas), processos, "linha por escritor simultaneo e o teto")
        self.assertLess(len(linhas), processos * por_processo / 2, "nao pode voltar a inflar")
