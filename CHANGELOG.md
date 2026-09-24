# Changelog

Formato: [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/). Versionamento:
[SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- `fix-noop` roda a baseline com o patch aplicado e reprova como `instrumento-morto` o teste que
  já falha com a correção: teste quebrado de nascença não prova nada.
- Hook PreToolUse barra `git commit --no-verify` e `-n` sempre, sem depender de variável de ambiente.
- Corpus de assinatura em `tests/corpus`: 25 logs reais anonimizados (pytest, unittest, jest, tsc,
  gcc/cc, git, gh, npm, pip, docker, node) com veredito e assinatura esperados, pares que não podem
  colidir e pares que têm que colidir. Assinatura que muda sem bump de `Assinatura.VERSAO` reprova.

### Conhecido

- A assinatura corta o log inteiro em 120 caracteres: dois erros distintos do pytest com o mesmo
  cabeçalho colidem (registrado em `colisoes_conhecidas` do corpus).

## [0.1.0] - 2026-09-21

### Adicionado

- Ledger local em SQLite (WAL + FTS5), stdlib pura, Python 3.9+: `err`, `fix`, `find`, `top`, `win`.
- Assinatura normalizada v2 (caminho, número, branch, relator, slug, sha, valor) e `reindex`
  numa transação.
- Busca em cascata (assinatura exata, FTS5, `ERRATUM_SEARCH_CMD` externo) com veredito fechado
  `match` | `talvez` | `abstain`, limiar configurável e juiz externo opcional.
- Portões determinísticos no `gate`: `fix-noop`, `stub-neutro` e `em-dash`, com `--staged`, hook
  pre-commit, passo no CI e taxa de reprovação por portão no `top`.
- Sementes genéricas (`seed`), carga em lote (`scan` do stream-json, `import` de JSONL) idempotente.
- Pistas com desfecho e efeito (`desfecho`, `efeito`) para medir se a pista ajudou.
- Receitas: `recipe add/ls/show/rm`, `how`, `check-cmd` determinístico e hook PreToolUse.
- Contador de repetição por task e `compactar` para histórico inflado.
- README em inglês e português, licença GPL-3.0-or-later.

[Não lançado]: https://github.com/victorandraad/erratum/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/victorandraad/erratum/releases/tag/v0.1.0
