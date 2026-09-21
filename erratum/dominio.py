from __future__ import annotations

import re
from dataclasses import dataclass


class Assinatura:
    VERSAO = 2
    _RELATOR = re.compile(
        r"^\w+\s+(?:reportou(?:\s+falhou)?|reported(?:\s+failed)?):\s*"
        r"(?:(?:falhou|failed):\s*)*"
    )
    _RODADA = re.compile(r"\(rodada \d+(?:/\d+)?\)")
    _VALOR = re.compile(
        r"(?:us\$|r\$|\$|\u20ac|\u00a3|\b(?:euro|libra)\b)\s*"
        r"[0-9]+(?:[.,][0-9]+)*"
    )
    _SHA = re.compile(r"\b[0-9a-f]{7,40}\b")
    _SLUG = re.compile(r"['\"]([a-z0-9]+(?:-[a-z0-9]+){2,})['\"]")
    _TOKEN_BRANCH = r"(?!(?:o|a|em|no|na)\b)[\w./-]+"
    _PREFIXO_BRANCH = re.compile(
        r"\b(?:origin/(?:(?:feature|hotfix|bugfix|release|chore|feat|fix)/)?"
        r"|(?:feature|hotfix|bugfix|release|chore|feat|fix)/)[\w./-]+"
    )
    _BRANCH_ASPAS = re.compile(
        r"\b((?:branch|merge|base|rebase|checkout|origin)\s+)['\"]([\w./-]+)['\"]"
    )
    _BRANCH_DIVERGIU = re.compile(
        r"['\"][\w./-]+['\"](\s+(?:divergiu|diverged)\b)"
        r"|(\b(?:conflita com|conflicts with)\s+)['\"][\w./-]+['\"]"
    )
    _BRANCH_LIGADO = re.compile(
        r"(<branch>\s+(?:em|no|na|into|onto|to|and)\s+(?:[oa]\s+)?)"
        + _TOKEN_BRANCH
    )
    _BETWEEN_BRANCH = re.compile(
        r"(\bbetween\s+)" + _TOKEN_BRANCH + r"(\s+and\s+<branch>)"
    )
    _VERBO_BRANCH = re.compile(
        r"\b((?:mergear|integrar|rebasear)(?:\s+(?:o|a|em|no|na))?)\s+"
        + _TOKEN_BRANCH
    )
    _FRENTE_BRANCH = re.compile(
        r"(\u00e0 frente )d[oa]\s+" + _TOKEN_BRANCH
    )
    _SOBRE_BRANCH = re.compile(
        r"(commits novos sobre )[oa]\s+" + _TOKEN_BRANCH
    )
    _MERGE_COM_BRANCH = re.compile(
        r"(merge com )[oa]\s+" + _TOKEN_BRANCH
    )
    # o ':' depois do caminho precisa permanecer (mensagens "arquivo: motivo")
    _CAMINHO = re.compile(r"/[^\s\"':]+")
    _DIGITOS = re.compile(r"\d+")

    def __init__(self, texto):
        self._valor = self._normalizar(texto)

    @classmethod
    def ja_normalizada(cls, valor):
        obj = cls.__new__(cls)
        obj._valor = valor
        return obj

    @property
    def valor(self):
        return self._valor

    def __str__(self):
        return self._valor

    def __eq__(self, other):
        if not isinstance(other, Assinatura):
            return NotImplemented
        return self._valor == other._valor

    def __hash__(self):
        return hash(self._valor)

    @classmethod
    def _trocar_sha(cls, m):
        s = m.group(0)
        if any(c.isdigit() for c in s) and any(c.isalpha() for c in s):
            return "<sha>"
        return s

    @classmethod
    def _enquanto_mudar(cls, padrao, reposicao, texto):
        for _ in range(8):
            novo = padrao.sub(reposicao, texto)
            if novo == texto:
                return texto
            texto = novo
        return texto

    @classmethod
    def _trocar_branch(cls, texto):
        texto = cls._PREFIXO_BRANCH.sub("<branch>", texto)
        texto = cls._BRANCH_ASPAS.sub(r"\1'<branch>'", texto)
        texto = cls._BRANCH_DIVERGIU.sub(
            lambda m: "'<branch>'" + m.group(1) if m.group(1) else m.group(2) + "'<branch>'",
            texto,
        )
        texto = cls._enquanto_mudar(cls._BRANCH_LIGADO, r"\1<branch>", texto)
        texto = cls._BETWEEN_BRANCH.sub(r"\1<branch>\2", texto)
        texto = cls._VERBO_BRANCH.sub(r"\1 <branch>", texto)
        texto = cls._FRENTE_BRANCH.sub(r"\1do <branch>", texto)
        texto = cls._SOBRE_BRANCH.sub(r"\1o <branch>", texto)
        texto = cls._MERGE_COM_BRANCH.sub(r"\1o <branch>", texto)
        return texto

    @classmethod
    def _normalizar(cls, texto):
        if texto is None:
            texto = ""
        texto = texto.strip().lower()
        texto = texto.replace("\n", " ")
        texto = cls._RELATOR.sub("", texto)
        texto = cls._RODADA.sub("", texto)
        texto = cls._VALOR.sub("<valor>", texto)
        texto = cls._SHA.sub(cls._trocar_sha, texto)
        texto = cls._SLUG.sub("'<slug>'", texto)
        texto = cls._trocar_branch(texto)
        texto = cls._CAMINHO.sub("/PATH", texto)
        texto = cls._DIGITOS.sub("N", texto)
        texto = " ".join(texto.split())
        texto = texto[:120]
        if not texto:
            return "(sem texto)"
        return texto


@dataclass(frozen=True)
class Erro:
    id: int
    ts: str
    projeto: str
    tipo: str
    etapa: str
    ferramenta: str
    assinatura: str
    texto: str
    contexto: dict


@dataclass(frozen=True)
class Correcao:
    id: int
    ts: str
    projeto: str
    assinatura: str
    nota: str
    ref: str
    teste: str
    fonte: str
    receita: str = ""


@dataclass(frozen=True)
class Acerto:
    id: int
    ts: str
    projeto: str
    task: str
    o_que: str
    custo_usd: float
    contexto: dict


@dataclass(frozen=True)
class VereditoDePortao:
    id: int
    ts: str
    projeto: str
    portao: str
    veredito: str
    detalhe: str


@dataclass(frozen=True)
class Padrao:
    assinatura: str
    ocorrencias: int
    tasks: int
    projetos: tuple
    ultimo_ts: str
    exemplo: str
    resolvido: bool


@dataclass(frozen=True)
class TaxaDePortao:
    portao: str
    rodadas: int
    reprovou: int
    pulou: int
    taxa: float
    nunca_decidiu: bool = False


@dataclass(frozen=True)
class Achado:
    origem: str
    assinatura: str
    texto: str
    correcoes: tuple
    pontuacao: float
    veredito: str = "talvez"
    confianca: float = 0.0
    cobertura: float = 0.0
    decidido_por: str = "limiar"
    receita: object = None
