from __future__ import annotations

import json
import math
import os
import shlex
import signal
import subprocess
import sys
from dataclasses import dataclass, replace

from erratum.idioma import t


def _escrever(aviso, texto):
    destino = sys.stderr if aviso is None else aviso
    destino.write(texto)


@dataclass(frozen=True)
class Decisao:
    """Veredito fechado de uma busca.

    `confianca` e HEURISTICA, nao calibrada: serve para ordenar e filtrar,
    nao para conta de probabilidade.
    """

    veredito: str
    confianca: float
    achados: tuple

    @classmethod
    def de(cls, achados):
        achados = tuple(achados)
        if not achados:
            return cls("abstain", 0.0, ())
        matches = [a for a in achados if a.veredito == "match"]
        if matches:
            return cls("match", matches[0].confianca, achados)
        return cls("talvez", achados[0].confianca, achados)


class Limiar:
    MATCH_PADRAO = 1.6
    TALVEZ_PADRAO = 0.15

    def __init__(self, match=MATCH_PADRAO, talvez=TALVEZ_PADRAO):
        self.match = match
        self.talvez = talvez

    @classmethod
    def do_ambiente(cls, ambiente, aviso):
        match = cls._ler(
            ambiente, aviso, "ERRATUM_LIMIAR_MATCH", cls.MATCH_PADRAO
        )
        talvez = cls._ler(
            ambiente, aviso, "ERRATUM_LIMIAR_TALVEZ", cls.TALVEZ_PADRAO
        )
        return cls(match=match, talvez=talvez)

    @classmethod
    def _ler(cls, ambiente, aviso, nome, padrao):
        if not ambiente:
            return padrao
        bruto = ambiente.get(nome)
        if bruto is None:
            return padrao
        try:
            return float(bruto)
        except (TypeError, ValueError):
            _escrever(aviso, t("%s invalid value, using the default\n",
                               "%s valor invalido, usando o padrao\n") % nome)
            return padrao

    def classificar(self, achados):
        achados = list(achados)
        fts = [a for a in achados if a.origem == "fts"]
        folga = None
        if len(fts) >= 2:
            segundo = abs(float(fts[1].pontuacao))
            if segundo:
                folga = abs(float(fts[0].pontuacao)) / segundo
            else:
                folga = 0.0
        primeiro_fts = fts[0] if fts else None
        saida = []
        for a in achados:
            if a.origem == "assinatura":
                saida.append(
                    replace(
                        a,
                        veredito="match",
                        confianca=1.0,
                        decidido_por="assinatura",
                    )
                )
                continue
            if a.origem == "external":
                saida.append(
                    replace(
                        a,
                        veredito="talvez",
                        confianca=0.2,
                        decidido_por="limiar",
                    )
                )
                continue
            if a.origem == "fts":
                if a.cobertura < self.talvez:
                    continue
                if (
                    a is primeiro_fts
                    and folga is not None
                    and folga >= self.match
                ):
                    saida.append(
                        replace(
                            a,
                            veredito="match",
                            confianca=0.8,
                            decidido_por="limiar",
                        )
                    )
                else:
                    saida.append(
                        replace(
                            a,
                            veredito="talvez",
                            confianca=0.3,
                            decidido_por="limiar",
                        )
                    )
                continue
            saida.append(
                replace(
                    a, veredito="talvez", confianca=0.3, decidido_por="limiar"
                )
            )
        return saida


class JuizExterno:
    def __init__(self, comando, aviso=None, timeout=5):
        self._comando = comando
        self._aviso = aviso
        self.timeout = timeout

    def julgar(self, texto, assinatura, achados):
        achados = list(achados)
        if not achados:
            return achados
        if any(a.origem == "assinatura" for a in achados):
            return achados
        comando = self._comando or ""
        if not str(comando).strip():
            self._falhou(t("empty command", "comando vazio"))
            return achados
        pedido = {
            "erro": texto,
            "assinatura": assinatura,
            "candidatos": [
                {
                    "id": str(i),
                    "nota": a.correcoes[0].nota if a.correcoes else "",
                    "assinatura": a.assinatura,
                    "score": a.pontuacao,
                }
                for i, a in enumerate(achados, 1)
            ],
            "perguntas": ["serve", "mesmo_erro"],
        }
        try:
            argv = shlex.split(comando)
        except ValueError as exc:
            self._falhou(exc)
            return achados
        if not argv:
            self._falhou(t("empty command", "comando vazio"))
            return achados
        bruto = self._rodar(json.dumps(pedido, ensure_ascii=False), argv)
        if bruto is None:
            return achados
        return self._aplicar(bruto, achados)

    def _rodar(self, payload, argv):
        proc = None
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                start_new_session=True,
            )
            saida, _err = proc.communicate(input=payload, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            self._matar(proc)
            self._falhou("timeout")
            return None
        except OSError as exc:
            self._falhou(exc)
            return None
        if proc.returncode != 0:
            self._falhou(t("exit code %s", "codigo %s") % proc.returncode)
            return None
        try:
            dado = json.loads(saida or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            self._falhou(t("invalid json", "json invalido"))
            return None
        if not isinstance(dado, dict):
            self._falhou(t("invalid json", "json invalido"))
            return None
        return dado

    def _matar(self, proc):
        if proc is None:
            return
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            proc.communicate(timeout=0.5)
        except Exception:
            pass

    def _aplicar(self, dado, achados):
        if "escolha" not in dado:
            self._falhou(t("no choice", "sem escolha"))
            return achados
        escolha = dado["escolha"]
        if escolha == "abstain":
            return []
        por_id = {str(i): a for i, a in enumerate(achados, 1)}
        chave = str(escolha)
        if chave not in por_id:
            self._falhou(t("unknown id", "id desconhecido"))
            return achados
        confianca = dado.get("confianca")
        if isinstance(confianca, bool) or not isinstance(confianca, (int, float)):
            self._falhou(t("invalid confidence", "confianca invalida"))
            return achados
        confianca = float(confianca)
        if not math.isfinite(confianca) or confianca < 0.0 or confianca > 1.0:
            self._falhou(t("invalid confidence", "confianca invalida"))
            return achados
        mesmo = dado.get("mesmo_erro")
        if not isinstance(mesmo, dict):
            mesmo = {}
        escolhido = por_id[chave]
        saida = []
        for i, a in enumerate(achados, 1):
            sid = str(i)
            marca = mesmo.get(sid, mesmo.get(i))
            if marca is False:
                continue
            if a is escolhido:
                saida.append(
                    replace(
                        a,
                        veredito="match",
                        confianca=confianca,
                        decidido_por="juiz",
                    )
                )
            else:
                saida.append(a)
        return saida

    def _falhou(self, motivo):
        texto = str(motivo).replace("\n", " ")
        _escrever(self._aviso, t("external judge failed: %s\n", "juiz externo falhou: %s\n") % texto)
