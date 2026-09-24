"""Portões determinísticos sobre o diff de uma branch, como objetos.

Um portão é uma peça com **entrada** (o diff sobre uma base, o worktree, a config do repo) e
**saída enumerada** (`APROVOU`, `REPROVOU` com motivo, `PULOU` com motivo). Zero modelo em todos.

O preâmbulo de diff (listar o que mudou, separar teste de produção, rodar o comando de teste) é uma
peça só (`DiffDoDev`), e a única divergência real entre os portões vira parâmetro nomeado
(`novos_ou_modificados`).

**Fronteira honesta.** Nada aqui lê estado global nem config: `sh`, `log`, as `settings` do repo e o
callback `ao_decidir` são INJETADOS pelo construtor. O que **vaza** de propósito: dois portões
escrevem no worktree (o fix-noop reverte e restaura arquivos; o em-dash corrige, testa e COMMITA),
então não são funções puras: o worktree é entrada e saída, e por isso chega pelo `DiffDoDev`.

Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

# Saída enumerada. Str simples (e não Enum) pra atravessar JSON/log sem conversão.
APROVOU = "aprovou"
REPROVOU = "reprovou"
PULOU = "pulou"
NAO_SE_APLICA = PULOU   # nome antigo do mesmo veredito

# Onde o comando de teste recebe os arquivos de teste do escopo (os que o diff tocou).
MARCADOR_TESTES = "{testes}"

# Montado por código: o próprio arquivo obedece a regra que o `PortaoEmDash` aplica.
TRAVESSAO = chr(0x2014)


def executar(cmd, cwd=None, timeout=120):
    """`sh` padrão: o mesmo contrato que os portões esperam de um `sh` injetado
    (`sh(cmd, cwd=..., timeout=...)` devolvendo algo com `returncode` e `stdout`)."""
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


class Resultado:
    """Veredito de um portão. `motivo` só tem conteúdo quando reprovou (é o texto que volta pra
    quem escreveu o código); `detalhe` é o que aconteceu, em qualquer veredito."""

    __slots__ = ("veredito", "motivo", "detalhe", "extra")

    def __init__(self, veredito, motivo="", detalhe="", **extra):
        self.veredito = veredito
        self.motivo = motivo
        self.detalhe = detalhe or motivo
        self.extra = extra

    @property
    def rodou(self):
        return self.veredito != PULOU

    @property
    def reprovou(self):
        return self.veredito == REPROVOU

    @property
    def pulou(self):
        return self.veredito == PULOU


def _pulou(detalhe=""):
    return Resultado(PULOU, detalhe=detalhe)


# ponytail: heurística de arquivo de teste: dir tests/, *Test.php (phpunit), .test./.spec. (js/ts),
# test_*.py e *_test.py (python). Convenção fora disso: o arquivo conta como produção.
_TEST_FILE_RX = re.compile(
    r"(^|/)tests/|Test\.php$|\.test\.|\.spec\.|(^|/)test_[^/]*\.py$|_test\.py$", re.I)


class DiffDoDev:
    """O preâmbulo comum aos portões: o que a branch mudou sobre a base, separado em teste e
    produção, mais a rodada do comando de teste. Uma pergunta ao git por variante, memoizada."""

    def __init__(self, worktree, diff_ref, sh=None, staged=False):
        self.worktree = Path(worktree)
        self.diff_ref = diff_ref
        self.sh = sh or executar
        self.staged = bool(staged)
        self._cache = {}

    def arquivos(self, novos_ou_modificados=False):
        """Caminhos que a branch mudou sobre a base.

        `novos_ou_modificados` acrescenta `--diff-filter=AM -M`: serve ao portão anti-stub (rename
        sem `-M` faria um stub ANTIGO parecer arquivo novo)."""
        if novos_ou_modificados not in self._cache:
            if self.staged:
                cmd = ["git", "diff", "--cached", "--name-only"]
            else:
                cmd = ["git", "diff", f"{self.diff_ref}...HEAD", "--name-only"]
            if novos_ou_modificados:
                cmd += ["--diff-filter=AM", "-M"]
            out = self.sh(cmd, cwd=str(self.worktree)).stdout or ""
            self._cache[novos_ou_modificados] = [l.strip() for l in out.splitlines() if l.strip()]
        return self._cache[novos_ou_modificados]

    def testes(self):
        return [f for f in self.arquivos() if _TEST_FILE_RX.search(f)]

    def producao(self):
        return [f for f in self.arquivos() if not _TEST_FILE_RX.search(f)]

    def pendentes(self):
        """Linhas de `git status --porcelain --untracked-files=no`: alteração rastreada no
        worktree ou no índice. Arquivo não rastreado não conta."""
        out = self.sh(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=str(self.worktree),
        ).stdout or ""
        return [linha for linha in out.splitlines() if linha.strip()]

    def existe_na_base(self, rel):
        ref = "HEAD" if self.staged else self.diff_ref
        return self.sh(["git", "cat-file", "-e", f"{ref}:{rel}"],
                       cwd=str(self.worktree)).returncode == 0

    def ler(self, rel):
        if self.staged:
            r = self.sh(["git", "show", ":%s" % rel], cwd=str(self.worktree))
            if getattr(r, "returncode", 0) != 0:
                return None
            return r.stdout
        try:
            return (self.worktree / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def rodar_testes(self, comandos, testes=(), timeout=1800):
        """Roda os comandos de teste, em ordem, e para no primeiro que falha (devolve o resultado
        dele; todos verdes = o do último).

        Cada comando é uma string (partida com `shlex`) ou uma lista de argumentos. O marcador
        `{testes}` é trocado pelos arquivos de teste do escopo; comando sem marcador roda como veio
        (a suíte inteira). Sem shell: `a && b` vira dois comandos na lista, não um."""
        res = None
        for comando in comandos:
            partes = shlex.split(comando) if isinstance(comando, str) else list(comando)
            cmd = []
            for p in partes:
                cmd += list(testes) if p == MARCADOR_TESTES else [p]
            res = self.sh(cmd, cwd=str(self.worktree), timeout=timeout)
            if res.returncode != 0:
                return res
        return res


class Portao:
    """Entrada injetada, saída enumerada. Nenhum portão levanta pro chamador: portão é opcional e
    não derruba quem o chama.

    `settings`: dict do repo. Chaves lidas: a `flag` de cada portão (liga/desliga, default ligado)
    e `test_cmds` (lista de comandos de teste, ver `DiffDoDev.rodar_testes`).
    `comandos_de_teste`: o mesmo que `settings["test_cmds"]`, e ganha dele quando vem preenchido.
    `ao_decidir(nome_do_portao, veredito, detalhe)`: chamado em TODO veredito (aprovou, reprovou,
    pulou). É por onde se conta disparo; exceção nele é logada e engolida."""

    flag = None            # chave em `settings` que liga/desliga (None = sempre ligado)
    nome = "portao"

    def __init__(self, diff, settings=None, log=None, ao_decidir=None, comandos_de_teste=None):
        self.diff = diff
        self.settings = settings or {}
        self.log = log or (lambda msg: None)
        self.ao_decidir = ao_decidir
        cmds = comandos_de_teste or self.settings.get("test_cmds") or []
        self.comandos_de_teste = [cmds] if isinstance(cmds, str) else list(cmds)

    def rodar(self):
        try:
            if self.flag and not self.settings.get(self.flag, True):
                resultado = _pulou("flag desligada no repo")
            else:
                resultado = self._julgar()
        except Exception as exc:  # noqa: BLE001: portão não pode derrubar o chamador
            self.log(f"{self.nome}: {exc}")
            resultado = _pulou(f"exceção: {exc}")
        self._avisar(resultado)
        return resultado

    def _avisar(self, resultado):
        if self.ao_decidir is None:
            return
        try:
            self.ao_decidir(self.nome, resultado.veredito, resultado.detalhe)
        except Exception as exc:  # noqa: BLE001: telemetria quebrada não muda o veredito
            self.log(f"{self.nome}: ao_decidir falhou: {exc}")

    def _julgar(self):
        raise NotImplementedError


class PortaoFixNoop(Portao):
    """Anti-fix-no-op (git puro + comando de teste, ZERO modelo): reverte SÓ o código de produção da
    branch (os de teste ficam intactos) e roda o comando de teste. Se continua verde, o "fix" não
    prova nada (no-op, ou teste que sempre passa): REPROVOU. Se falha, há regressão real que o teste
    captura: APROVOU. Restaura a produção no finally em sucesso, no-op E exceção.

    Antes de reverter, roda os mesmos testes COM o patch: se já falham, REPROVOU `instrumento-morto`.
    Sem comando de teste configurado: PULOU com motivo (não há como provar nada).
    Alteração rastreada pendente no worktree ou no índice: PULOU sem tocar em arquivo nem rodar teste.
    # ponytail: em projeto Python, use `python -B ...` no comando: o portão troca o fonte e destroca
    # em menos de um segundo, e um `.pyc` gravado no meio pode sobreviver com o mesmo mtime+tamanho."""

    flag = "fix_noop_gate"
    nome = "fix-noop"

    def _julgar(self):
        if not self.comandos_de_teste:
            self.log(f"{self.nome}: sem comando de teste configurado, pulando")
            return _pulou("sem comando de teste configurado (test_cmds / --test-cmd)")
        testes, prod = self.diff.testes(), self.diff.producao()
        # Nada a provar: sem teste (não há o que falhar) OU sem produção (nada pra reverter).
        if not testes or not prod:
            return _pulou("diff sem par produção+teste")
        pendentes = self.diff.pendentes()
        if pendentes:
            return _pulou(
                "alteracao rastreada pendente no worktree "
                f"({len(pendentes)} arquivo(s)): commite ou guarde antes")
        # Baseline: teste que já falha COM o patch não prova nada (quebrado de nascença).
        base = self.diff.rodar_testes(self.comandos_de_teste, testes)
        if base.returncode != 0:
            saida = f"{base.stdout or ''}\n{base.stderr or ''}"
            cauda = " | ".join([l for l in saida.splitlines() if l.strip()][-5:])
            return Resultado(REPROVOU, motivo="instrumento-morto: os testes do escopo já falham "
                             f"com a correção aplicada (teste quebrado não prova nada): {cauda}")
        sh, wt = self.diff.sh, str(self.diff.worktree)
        orig_sha = (sh(["git", "rev-parse", "HEAD"], cwd=wt).stdout or "").strip()
        resultado = _pulou("exceção")
        try:
            for f in prod:
                # produção NOVA (ausente em diff_ref): reverter = remover do working tree.
                if self.diff.existe_na_base(f):
                    sh(["git", "checkout", self.diff.diff_ref, "--", f], cwd=wt)
                else:
                    sh(["git", "rm", "-f", "--quiet", f], cwd=wt)
            passou = self.diff.rodar_testes(self.comandos_de_teste, testes).returncode == 0
            if passou:
                resultado = Resultado(REPROVOU, motivo="Testes do escopo continuam verdes sem a "
                                      "correção (no-op ou teste que sempre passa)")
            else:
                resultado = Resultado(APROVOU, detalhe="Testes do escopo falham sem a correção "
                                      "(regressão real capturada)")
        except Exception as exc:  # noqa: BLE001: portão não pode derrubar o chamador
            self.log(f"{self.nome}: {exc}")
            resultado = _pulou(f"exceção: {exc}")
        finally:
            # restaura o commit original (recria o que foi removido: orig_sha tem o arquivo).
            for f in prod:
                sh(["git", "checkout", orig_sha, "--", f], cwd=wt)
        return resultado


# ── Portão determinístico anti-stub-neutro ────────────────────────────────────
# O defeito que ele pega: um contrato sem implementação concreta estoura erro em produção, e o
# "conserto" é uma classe nova cujo único método devolve `[]`. O erro para, a suíte fica verde, e
# quem consome o vazio calcula em cima dele: índice 0, saúde 100, cobertura 0, selo de "confiança
# alta". A tela vira uma AFIRMAÇÃO calculada a partir de nada. O erro não mentia: só não mostrava.
#
# O portão é calibrado pra PRECISÃO, não pra recall: dispara só no sinal forte (arquivo NOVO, classe
# que satisfaz um contrato, TODOS os métodos devolvendo constante neutra, contrato sem outra
# implementação concreta na base). Retorno vazio NÃO é proibido: lista vazia é a resposta certa em
# montes de lugar; o defeito é a implementação nova que promete consultar uma fonte e nunca consulta.
# ponytail: regex, não parser. Só arquivo NOVO inteiro (o formato de 1 classe por arquivo); classe
# nova enxertada em arquivo antigo escapa; cruzar as linhas adicionadas do `git diff -U0` é o
# upgrade quando alguém provar que isso acontece.
_STUB_CODE_EXTS = (".php", ".js", ".jsx", ".ts", ".tsx", ".py")
# Código de terceiro, gerado, e todo parente de teste (fake/stub/mock/factory/fixture). O
# `_TEST_FILE_RX` acima continua servindo o fix_noop_gate (que o usa pra ESCOLHER quais testes rodar,
# então alargá-lo lá quebraria aquele portão); aqui ele é reaproveitado em OR com este.
_STUB_SKIP_PATH_RX = re.compile(
    r"(^|/)(vendor|node_modules|dist|build|public|storage|__mocks__|__pycache__|migrations)/"
    r"|(^|/)(spec|specs|fixtures?|factories|stubs|mocks|fakes|doubles)/"
    r"|(Fake|Stub|Mock|Double|Dummy)\w*\.(php|jsx?|tsx?|py)$"
    r"|conftest\.py$|\.pyi$|\.d\.ts$|\.min\.|\.generated\.", re.I)
# Null Object deliberado: o NOME anuncia que o vazio é a resposta certa.
_NULL_OBJECT_RX = re.compile(r"Null|No[oO]p|Void|Dummy|Fake|Stub|InMemory|Fallback", re.I)
# Contratos onde vazio é a VERDADE, não "não sei": serialização, e base de framework.
_CONTRATO_NEUTRO_OK_RX = re.compile(
    r"Arrayable|JsonSerializable|Jsonable|Serializable|Stringable|Countable|IteratorAggregate"
    r"|Renderable|Responsable|Castable|Enum|Exception|Error|TypedDict|NamedTuple|Protocol|ABC"
    r"|object|BaseModel", re.I)
# Métodos de framework cujo vazio é resposta legítima ("sem regra", "sem middleware").
_METODO_NEUTRO_OK = {
    "rules", "casts", "messages", "attributes", "middleware", "broadcaston", "policies", "via",
    "up", "down", "register", "boot", "tags", "uniqueid", "failed", "authorize", "extensions",
    "toarray", "jsonserialize", "getattributes", "defaults", "share", "map", "geterrors",
}
# Feature flag / kill switch: aqui o neutro É a verdade ("desligado"), não "eu não sei".
_FLAG_METODO_RX = re.compile(r"^(is|has|can|should|must|use)[A-Z_]")
# Literal de lista/dict vazio, que é o argumento com que a coleção vazia costuma ser construída.
_VAZIO_RX = r"(?:\[\s*\]|\{\s*\}|array\s*\(\s*\))"
# Coleção vazia nas grafias que o Dev realmente escreve: `collect()`, `collect([])`,
# `new Collection` (PHP aceita sem parênteses), `new Collection([])`, `Collection::make([])`, e as
# mesmas com o nome totalmente qualificado (`new \Illuminate\Support\Collection()`).
_COLECAO_VAZIA_RX = (r"(?:collect|[\w\\]*Collection::make)\s*\(\s*" + _VAZIO_RX + r"?\s*\)"
                     r"|new\s+[\w\\]*Collection\s*(?:\(\s*" + _VAZIO_RX + r"?\s*\))?")
_NEUTRO_VALOR = (r"(?:" + _VAZIO_RX + r"|\(\s*\)|" + _COLECAO_VAZIA_RX +
                 r"|null|nil|none|undefined|0|0\.0|false|''|\"\")")
_NEUTRO_RX = re.compile(r"^return\s*" + _NEUTRO_VALOR + r"\s*;?$", re.I)
_NEUTRO_SO_VALOR_RX = re.compile(_NEUTRO_VALOR, re.I)
_RETURN_RX = re.compile(r"(?<![\w$])return\b([^;\n]*)")
_NOISE_PATS = [r"'''.*?'''", r'""".*?"""', r"/\*.*?\*/", r"//[^\n]*",
               r"'(?:\\.|[^'\\\n])*'", r"\"(?:\\.|[^\"\\\n])*\""]
_NOISE_RX = re.compile("|".join(_NOISE_PATS), re.S)
_NOISE_HASH_RX = re.compile("|".join(_NOISE_PATS[:4] + [r"#[^\n]*"] + _NOISE_PATS[4:]), re.S)
_CLASS_C_RX = re.compile(r"\b(?P<mods>(?:abstract|final|export|default|declare)\s+)*"
                         r"class\s+(?P<nome>\w+)(?P<cab>[^{;]*)\{")
_METODO_C_RX = re.compile(
    r"(?P<mods>(?:public|private|protected|static|final|abstract|async|readonly|get|set)\s+)*"
    r"(?:function\s+)?(?P<nome>\w+)\s*\((?P<args>[^()]*)\)\s*(?::[^{;=]+)?\{")
# Injeção de dependência por construtor é padrão comum: contá-lo como método
# não-neutro fazia `len(neutros) != len(metodos)` dar verdadeiro e a classe INTEIRA escapar.
# Construtor não é promessa de contrato em nenhuma das três linguagens.
_CONSTRUTORES = {"constructor", "__construct", "__init__"}
_NAO_METODO = {"if", "for", "foreach", "while", "switch", "catch", "match", "do", "else",
               "elseif", "return", "function", "fn", "try", "use", "new"} | _CONSTRUTORES
_CLASS_PY_RX = re.compile(r"^class\s+(?P<nome>\w+)\s*\((?P<cab>[^()]*)\)\s*:", re.M)
_DEF_PY_RX = re.compile(r"^(?P<ind>[ \t]+)def\s+(?P<nome>\w+)\s*\((?P<args>[^()]*)\)"
                        r"\s*(?:->[^:]+)?:", re.M)
# Critério do parâmetro ignorado: exigir que o corpo inteiro seja um return tem ruído zero,
# mas cego pro que um dev escreve naturalmente (log antes do return, vazio guardado em variável,
# guarda de config). O discriminador é o PARÂMETRO IGNORADO: o stub recebe exatamente o que descreve
# o que buscar (`listarItens(Loja $loja, array $params)`) e nunca toca em nada disso; quem
# faz trabalho de verdade usa o que recebeu. ("não chama colaborador" foi descartado: deixaria passar
# `Log::info(...); return [];` e acusaria `$this->repo->save($x); return [];`, que faz trabalho.)
_PY_NAO_PARAM = {"self", "cls"}
_PARAM_MOD_RX = re.compile(r"^\s*(?:public|private|protected|readonly|static|final)\s+")


def _stub_sem_tipos(args):
    """Tira colchete/chave/generic da assinatura, pra split por vírgula não partir `Dict[str, int]`
    nem `Row[]`. Destructuring de JS some junto (o parâmetro vira anônimo e é ignorado): falso
    NEGATIVO, direção segura."""
    for _ in range(3):
        args = re.sub(r"\[[^\[\]]*\]|\{[^{}]*\}|<[^<>]*>", "", args)
    return args


def _stub_params(args, py, php):
    """Nomes dos parâmetros COMO O CORPO OS MENCIONARIA (`$loja` em PHP, `loja` nas
    outras). `$this`/`self`/`cls` não são parâmetro: quem só usa o próprio objeto continua tendo
    ignorado o que descrevia a busca. Default, variádico e por referência contam igual."""
    args = _stub_sem_tipos(args)
    if php:
        return ["$" + n for n in re.findall(r"\$(\w+)", args)]
    out = []
    for seg in args.split(","):
        m = re.match(r"\s*(?:\.{3})?\*{0,2}(\w+)", _PARAM_MOD_RX.sub("", seg))
        if m and not (py and m.group(1) in _PY_NAO_PARAM):
            out.append(m.group(1))
    return out


def _stub_ocorrencias(corpo, nome):
    """Menções ao nome com limite de palavra, pra `$id` não casar dentro de `$identificador`."""
    return len(re.findall(r"(?<![\w$])" + re.escape(nome) + r"\b", corpo))


def _stub_alias_neutro(corpo, var):
    """`$rows = []; return $rows;` é a mesma constante neutra com um nome no meio. Só vale se a
    variável aparece exatamente 2x (atribuição + return).
    # ponytail: contagem de ocorrência, não fluxo de dados. `$rows[] = $l` dá 3 e cai fora, que é o
    # lado certo de errar; análise de fluxo quando alguém provar que o alias escapa de outro jeito."""
    if not re.fullmatch(r"\$?\w+", var):
        return None
    m = re.search(r"(?<![\w$])" + re.escape(var) + r"\s*=\s*(" + _NEUTRO_VALOR + r")", corpo)
    if not m or _stub_ocorrencias(corpo, var) != 2:
        return None
    return m.group(1).strip()


def _stub_metodo_neutro(corpo, params):
    """(é neutro?, valor devolvido, parâmetros ignorados).

    Sem parâmetro: regra estreita de sempre (o corpo INTEIRO é um return neutro), onde o vazio
    costuma ser a verdade (`getErrors(): array { return []; }`), não promessa quebrada.
    Com parâmetro: TODOS os `return` devolvem constante neutra E NENHUM parâmetro é usado. Corpo
    vazio (`{}`) não tem return e continua fora."""
    if not params:
        corpo = corpo.strip()
        return bool(_NEUTRO_RX.match(corpo)), corpo[len("return"):].strip().rstrip(";"), []
    if any(_stub_ocorrencias(corpo, p) for p in params):
        return False, "", []
    rets = _RETURN_RX.findall(corpo)
    if not rets:
        return False, "", []
    valores = []
    for r in rets:
        r = r.strip()
        if not _NEUTRO_SO_VALOR_RX.fullmatch(r):
            r = _stub_alias_neutro(corpo, r)
            if r is None:
                return False, "", []
        valores.append(r)
    return True, valores[0], list(params)


def _stub_sem_ruido(src, hash_comment):
    """Tira comentário e docblock (o corpo é julgado pelo CÓDIGO) e neutraliza string literal, pra
    código dentro de string/heredoc não passar por método. String vazia continua vazia."""
    def repl(m):
        t = m.group(0)
        if t[:1] in "'\"" and not t.startswith(("'''", '"""')):
            return t[0] * 2 if len(t) == 2 else "'S'"
        return "\n" * t.count("\n")
    return (_NOISE_HASH_RX if hash_comment else _NOISE_RX).sub(repl, src)


def _stub_fecha_chave(src, i):
    """Índice da `}` que fecha a `{` em `i` (-1 se não fecha)."""
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _stub_metodos_c(corpo, php):
    """Métodos do topo do corpo da classe (PHP/JS/TS): pula o corpo de cada um, então `if (...) {`
    aninhado nunca é lido como método. Default com parênteses (`$p = foo()`) não casa → o método
    escapa; falso NEGATIVO, direção segura."""
    out, i = [], 0
    while True:
        m = _METODO_C_RX.search(corpo, i)
        if not m:
            return out
        fim = _stub_fecha_chave(corpo, m.end() - 1)
        if fim < 0:
            return out
        if m.group("nome").lower() not in _NAO_METODO:
            out.append((m.group("nome"), (m.group("mods") or ""), corpo[m.end():fim],
                        _stub_params(m.group("args"), py=False, php=php)))
        i = fim + 1


def _stub_classes(rel, src):
    """[(classe, contratos, [(método, mods, corpo, params)])] das classes que satisfazem um
    contrato."""
    py = rel.endswith(".py")
    limpo = _stub_sem_ruido(src, hash_comment=py or rel.endswith(".php"))
    achados = []
    if py:
        if re.search(r"\babstractmethod\b|\bProtocol\b|\bABC\b", limpo):
            return []          # base abstrata: corpo neutro é declaração de contrato, não resposta
        for m in _CLASS_PY_RX.finditer(limpo):
            corpo = limpo[m.end():]
            corte = re.search(r"^\S", corpo, re.M)
            corpo = corpo[:corte.start()] if corte else corpo
            metodos = []
            for d in _DEF_PY_RX.finditer(corpo):
                if d.group("nome") in _CONSTRUTORES:
                    continue
                resto = corpo[d.end():]
                fim = re.search(rf"^(?![ \t]*$)(?![ \t]{{{len(d.group('ind')) + 1},}})", resto, re.M)
                metodos.append((d.group("nome"), "", resto[:fim.start()] if fim else resto,
                                _stub_params(d.group("args"), py=True, php=False)))
            achados.append((m.group("nome"), m.group("cab"), metodos))
        return achados
    for m in _CLASS_C_RX.finditer(limpo):
        if "abstract" in (m.group("mods") or ""):
            return []          # base pra ser sobrescrita
        fim = _stub_fecha_chave(limpo, m.end() - 1)
        if fim < 0:
            continue
        cab = m.group("cab")
        if "implements" not in cab:
            continue           # sem contrato declarado não há promessa a quebrar
        achados.append((m.group("nome"), cab.split("implements", 1)[1],
                        _stub_metodos_c(limpo[m.end():fim], php=rel.endswith(".php"))))
    return achados


def _stub_frase(nome, valor, ignorados):
    """Sem dizer QUAL parâmetro foi ignorado o Dev não entende a acusação."""
    frase = f"`{nome}()` devolve {valor or 'neutro'}"
    if ignorados:
        frase += " ignorando " + ", ".join(f"`{p}`" for p in ignorados)
    return frase


class PortaoStubNeutro(Portao):
    """Anti-stub-neutro (regex sobre o diff, ZERO modelo, ZERO comando de teste). Acusa
    implementação NOVA que satisfaz um contrato devolvendo constante neutra (`[]`, `{}`, null, 0,
    `''`, false, coleção vazia) em TODOS os seus métodos, sem consultar fonte nenhuma: neutro ali
    não significa "nada aconteceu", significa "eu não sei", e quem consome transforma isso em
    veredito na tela.

    Custa milissegundos e serve PHP, JS/TS e Python."""

    flag = "stub_neutro_gate"
    nome = "stub-neutro"

    def _julgar(self):
        achados = []
        for rel in self.diff.arquivos(novos_ou_modificados=True):
            achados += self._achados_do_arquivo(rel)
        if not achados:
            return Resultado(APROVOU, detalhe="nenhum stub neutro")
        return Resultado(REPROVOU, motivo="; ".join(achados))

    def _achados_do_arquivo(self, rel):
        if not rel.endswith(_STUB_CODE_EXTS):
            return []
        if _TEST_FILE_RX.search(rel) or _STUB_SKIP_PATH_RX.search(rel):
            return []
        # só implementação NOVA: arquivo que já existia na base não é promessa recém-feita
        # (e rename sem `-M` deixaria um stub antigo parecer novo).
        if self.diff.existe_na_base(rel):
            return []
        src = self.diff.ler(rel)
        if src is None:
            return []
        achados = []
        for classe, contratos, metodos in _stub_classes(rel, src):
            if not metodos or _NULL_OBJECT_RX.search(classe):
                continue
            if _CONTRATO_NEUTRO_OK_RX.search(contratos):
                continue
            neutros = []
            for n, mods, corpo, params in metodos:
                ok, valor, ignorados = _stub_metodo_neutro(corpo, params)
                if ok:
                    neutros.append((n, mods, valor, ignorados))
            # a classe INTEIRA é neutra. Parcial (ISP: um método que não se aplica numa classe com
            # métodos reais) passa, e é de propósito.
            if len(neutros) != len(metodos):
                continue
            # default protegido pra ser sobrescrito não é promessa ao consumidor.
            if any(re.search(r"protected|private", mods) for _, mods, _, _ in neutros):
                continue
            if all(n.lower() in _METODO_NEUTRO_OK or _FLAG_METODO_RX.match(n)
                   for n, _, _, _ in neutros):
                continue
            iface = self._contrato(contratos)
            if iface and self._ja_tem_implementacao_real(iface):
                continue
            achados.append(f"{rel}: `{classe}` implementa `{iface}` e "
                           + ", ".join(_stub_frase(n, valor, ign)
                                       for n, _, valor, ign in neutros)
                           + " sem consultar fonte nenhuma")
        return achados

    @staticmethod
    def _contrato(contratos):
        """Nome totalmente qualificado (`implements \\App\\Contracts\\X`) vira o último segmento:
        senão o contrato sairia "App" e a guarda procuraria a coisa errada."""
        raw = (re.findall(r"[\w\\.]+", contratos) or [""])[0]
        return re.split(r"[\\.]", raw)[-1]

    def _ja_tem_implementacao_real(self, iface):
        """Contrato que JÁ tem implementação concreta na base: o neutro nasce ao lado de uma real,
        então é Null Object/irmão, não o único provedor do dado.

        Vale pras três linguagens (em Python o `implements` é a herança) e só conta arquivo de
        PRODUÇÃO: interface sem implementação de produção quase sempre tem um fake em tests/, porque
        foi assim que ela chegou a ser testada, e contar esse fake calaria o portão justamente no
        caso que ele existe pra pegar."""
        g = self.diff.sh(["git", "grep", "-l", "-E",
                          rf"(implements[^;{{]*|class\s+\w+\s*\([^)]*)\b{iface}\b",
                          self.diff.diff_ref], cwd=str(self.diff.worktree))
        if g.returncode not in (0, 1):
            return True           # git grep quebrou: na dúvida, cala
        outras = [l.split(":", 1)[-1].strip() for l in (g.stdout or "").splitlines() if l.strip()]
        return any(not (_TEST_FILE_RX.search(o) or _STUB_SKIP_PATH_RX.search(o)) for o in outras)


def _voltar_ao_head(sh, wt, arquivos):
    """Índice e worktree dos arquivos voltam ao HEAD. Depois de `git add`,
    `git checkout --` restaura do índice, não do HEAD."""
    if not arquivos:
        return
    sh(["git", "reset", "-q", "HEAD", "--", *arquivos], cwd=wt)
    sh(["git", "checkout", "HEAD", "--", *arquivos], cwd=wt)


# ── Portão de travessão ───────────────────────────────────────────────────────
def corrigir_travessao(texto):
    """Troca SÓ o travessão de prosa (colado a letra/dígito ou a espaço de algum lado) por vírgula,
    nunca por hífen. Deixa intacto o placeholder isolado (entre aspas, entre `>` e `<`), que é dado
    de tela e não prosa. Pura e determinística (sem git, sem disco)."""
    def ofensor(c):
        return c == " " or c.isalnum()

    out, n = [], len(texto)
    for i, ch in enumerate(texto):
        if ch != TRAVESSAO:
            out.append(ch)
            continue
        prev = texto[i - 1] if i > 0 else ""
        nxt = texto[i + 1] if i + 1 < n else ""
        if not (ofensor(prev) or ofensor(nxt)):
            out.append(ch)  # placeholder isolado: preserva
            continue
        if out and out[-1] == " ":
            out.pop()  # some com o espaço antes pra não sobrar " , "
        out.append(",")
        if nxt and nxt != " ":
            out.append(" ")  # garante o espaço depois da vírgula
    return "".join(out)


# ponytail: .py entrou na lista no porte (o original só olhava PHP/JS/TS); markdown e config ficam
# de fora porque ali travessão não quebra teste de ninguém.
_EM_DASH_EXTS = (".php", ".js", ".jsx", ".ts", ".tsx", ".py")


class PortaoEmDash(Portao):
    """Travessão (regex + fix, ZERO modelo): corrige o travessão de prosa nos arquivos de código
    tocados pelo diff e roda o comando de teste. Verde: commita a correção (APROVOU). Vermelho: a
    troca quebrou algo de verdade, reverte e devolve (REPROVOU).

    Diff com arquivo de teste mas sem comando de teste configurado: PULOU sem tocar em nada (não dá
    pra confirmar que a troca é inofensiva). Diff sem teste nenhum: corrige e commita direto.

    É o único portão que COMMITA no repositório: `corrigiu` no extra diz se houve commit.
    Com correção a fazer e alteração rastreada pendente: PULOU sem tocar. git add ou git commit que falha: desfaz (índice e arquivo voltam ao HEAD) e PULOU."""

    nome = "em-dash"

    def _ofensores(self):
        correcoes = {}
        for rel in self.diff.arquivos():
            if not rel.endswith(_EM_DASH_EXTS):
                continue
            src = self.diff.ler(rel)
            if src is None or TRAVESSAO not in src:
                continue
            corrigido = corrigir_travessao(src)
            if corrigido != src:
                correcoes[rel] = corrigido
        return correcoes

    def _so_detectar(self):
        correcoes = self._ofensores()
        if not correcoes:
            return Resultado(APROVOU, detalhe="nenhum travessão de prosa", corrigiu=False)
        return Resultado(
            REPROVOU,
            motivo=", ".join(correcoes),
            corrigiu=False,
        )

    def _julgar(self):
        if self.diff.staged:
            return self._so_detectar()
        sh, wt = self.diff.sh, str(self.diff.worktree)
        correcoes = self._ofensores()
        if not correcoes:
            return Resultado(APROVOU, detalhe="nenhum travessão de prosa", corrigiu=False)
        pendentes = self.diff.pendentes()
        if pendentes:
            return Resultado(
                PULOU,
                detalhe=("alteracao rastreada pendente no worktree "
                         f"({len(pendentes)} arquivo(s)): commite ou guarde antes"),
                corrigiu=False)
        testes = self.diff.testes()
        if testes and not self.comandos_de_teste:
            return Resultado(PULOU, detalhe=f"travessão de prosa em {len(correcoes)} arquivo(s), "
                             "mas sem comando de teste pra confirmar a troca", corrigiu=False)
        tocados = list(correcoes)
        try:
            for rel, corrigido in correcoes.items():
                (self.diff.worktree / rel).write_text(corrigido, encoding="utf-8")
            if testes and self.diff.rodar_testes(self.comandos_de_teste, testes).returncode != 0:
                sh(["git", "checkout", "--", *tocados], cwd=wt)
                return Resultado(
                    REPROVOU,
                    motivo="Testes do escopo falham depois de trocar o travessão por vírgula",
                    corrigiu=True)
            add = sh(["git", "add", "--", *tocados], cwd=wt)
            if add.returncode != 0:
                _voltar_ao_head(sh, wt, tocados)
                return Resultado(PULOU, detalhe=f"git add falhou: {(add.stderr or '').strip()}",
                                 corrigiu=False)
            commit = sh(["git", "commit", "-q", "-m", "Troca travessao por virgula"], cwd=wt)
            if commit.returncode != 0:
                _voltar_ao_head(sh, wt, tocados)
                return Resultado(
                    PULOU, detalhe=f"git commit falhou: {(commit.stderr or '').strip()}",
                    corrigiu=False)
            return Resultado(APROVOU, detalhe=f"corrigido em {len(tocados)} arquivo(s)",
                             corrigiu=True)
        except Exception as exc:  # noqa: BLE001: portão não pode derrubar o chamador
            self.log(f"{self.nome}: {exc}")
            _voltar_ao_head(sh, wt, tocados)
            return Resultado(PULOU, detalhe=str(exc), corrigiu=False)


# Nome de CLI -> classe, na ordem em que faz sentido rodar (o em-dash commita, então vai primeiro).
PORTOES = {p.nome: p for p in (PortaoEmDash, PortaoStubNeutro, PortaoFixNoop)}
