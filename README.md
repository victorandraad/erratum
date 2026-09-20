# erratum

Agente de código erra, alguém conserta, e na semana seguinte o mesmo erro volta porque a correção
ficou num log que ninguém lê. `erratum` é um ledger local: registra o erro, guarda a correção pela
**assinatura** do erro e a devolve na hora em que ele reaparece. Python puro (stdlib), um SQLite.

## Em 30 segundos

```sh
python -m erratum err "Exit code 127 /tmp/w-1/bin/runner: No such file"
# erro #1 registrado [acme] assinatura: exit code N /PATH: no such file

python -m erratum fix 1 "rodar o prep do worktree antes do runner" --ref abc123 --test test_prep
# correção #1 registrada [acme] para: exit code N /PATH: no such file

python -m erratum err "Exit code 1 /tmp/w-99/bin/runner: No such file"
# erro #2 registrado [acme] assinatura: exit code N /PATH: no such file
#   correção conhecida: rodar o prep do worktree antes do runner [ref: abc123, teste: test_prep]

python -m erratum find "bin/runner no such file"
# 1. [fts] exit code N /PATH: no such file
#    correção: rodar o prep do worktree antes do runner [ref: abc123, teste: test_prep]
```

A assinatura normaliza o que é volátil (caminhos viram `/PATH`, números viram `N`, contador de
rodada some), então uma correção cobre as ocorrências passadas e as futuras.

## Comandos

| Comando | Faz |
|---|---|
| `err "<texto>" [--stage --tool --kind --task]` | registra o erro e já devolve a correção conhecida |
| `fix <id\|texto> "<nota>" [--ref --test]` | registra a correção pela assinatura do erro |
| `find "<texto>" [-n N]` | busca no ledger (assinatura, depois FTS); não registra |

Todos aceitam `--json` e `--project` (padrão: nome da raiz do git). Texto `-` lê do stdin.
Saída 0 sempre; uso errado sai com 2.

## Para colar no SKILL.md / CLAUDE.md do seu agente

```
Deu erro de ferramenta? Rode `erratum err "<texto do erro>"` antes de tentar de novo: se vier
"correção conhecida", aplique. Consertou algo novo? `erratum fix <id> "<o que resolveu>"`.
```

## Onde ficam os dados

`$ERRATUM_DB` (padrão `~/.local/state/erratum/ledger.db`), SQLite em WAL: várias CLIs podem
escrever ao mesmo tempo. Um ledger serve vários projetos (coluna `project`).

```
errors(id, ts, project, kind, stage, tool, signature, text, context_json, import_key)
fixes(id, ts, project, signature, note, ref, test, source, import_key)
wins(id, ts, project, task, what, cost_usd, context_json)
gate_runs(id, ts, project, gate, verdict, detail)
ledger_fts = fts5(signature, text, note, src)
```

## Não-objetivos

Não é daemon, não é pipeline, não usa embeddings. É uma lib e uma CLI que o seu fluxo chama.

## Testes

```sh
python -m unittest -v
```
