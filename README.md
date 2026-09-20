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
| `top [--days N] [--all-projects] [--resolved]` | lista o que se repete, agrupado por assinatura, e a taxa de reprovação de cada portão |
| `win "<o que>" [--task --cost]` | registra um acerto |
| `gate <portões> --base <ref> [--worktree DIR] [--test-cmd "..."]` | roda portões determinísticos no diff e grava o veredito |
| `scan <stream.jsonl>` | minera os `tool_result` com `is_error` de um stream-json de agente |
| `import <arquivo.jsonl>` | carrega erros de um JSONL genérico |

O streak de `win` conta os acertos do projeto com timestamp depois do último erro do mesmo projeto; um erro zera a sequência.

Todos aceitam `--json` e `--project` (padrão: nome da raiz do git). Texto `-` lê do stdin.
Saída 0 sempre, com duas exceções: `gate` com algum portão reprovado sai com 1, e uso errado sai com 2.

## Portões (`gate`)

Checagens sem modelo sobre o diff entre `--base` e o `HEAD` do `--worktree` (padrão: diretório atual).
Cada veredito (`aprovou`, `reprovou`, `pulou`) vai pra `gate_runs`, e o `top` mostra quanto cada
portão reprova: portão que nunca dispara é portão que não está servindo.

```sh
erratum gate em-dash,stub-neutro,fix-noop --base main --test-cmd "python -B -m unittest {testes}"
```

| Portão | Reprova quando |
|---|---|
| `fix-noop` | os testes do diff passam mesmo com o código de produção revertido: a correção não corrige, ou o teste passa sempre |
| `stub-neutro` | uma classe nova cumpre o contrato devolvendo constante neutra (`[]`, `None`, `0`) em todos os métodos |
| `em-dash` | trocar o travessão de prosa por vírgula quebra os testes (no caso normal ele corrige, commita e aprova) |

`--test-cmd` pode repetir; `{testes}` vira a lista de arquivos de teste do diff. Sem `--test-cmd`, o
`fix-noop` pula em vez de adivinhar. O `em-dash` é o único que commita no repositório. Em projeto
Python use `python -B`: sem ele o `.pyc` em cache esconde a reversão do código.

## Carga em lote (`scan` e `import`)

```sh
erratum scan execucao-42.jsonl      # a task de cada erro é o nome do arquivo
erratum import historico.jsonl
```

`import` lê uma linha por erro: `{"ts", "project", "text"}`, com `kind`, `stage`, `tool` e `task`
opcionais. Só `text` é obrigatório: sem `project` vale o `--project`, sem `ts` vale agora. Os dois
são idempotentes (`import_key` é o hash da linha), então reler a mesma fonte não duplica nada.

## Busca externa (`ERRATUM_SEARCH_CMD`)

Se a variável existir, `find` e `err` rodam também o seu comando, com a consulta como último
argumento, e cada linha do stdout entra como achado `external`, abaixo dos do ledger.

```sh
export ERRATUM_SEARCH_CMD="minha-busca --limite 5"   # roda: minha-busca --limite 5 "<consulta>"
```

Sem shell, limite de 10 segundos. Saída diferente de 0, timeout ou comando inexistente viram aviso no stderr e a
busca segue só com o ledger.

## Para colar no SKILL.md / CLAUDE.md do seu agente

```
Ao errar, rode `erratum err "<texto do erro>"` antes de tentar de novo: se vier "correção
conhecida", aplique. Ao corrigir algo novo, `erratum fix <id> "<o que resolveu>"`. Passe limpo
(entregou sem erro no caminho), `erratum win "<o que entregou>"`.
```

## Onde ficam os dados

`$ERRATUM_DB` (padrão `~/.local/state/erratum/ledger.db`), SQLite em WAL: várias CLIs podem
escrever ao mesmo tempo. Um ledger serve vários projetos (coluna `project`).

```
errors(id, ts, project, kind, stage, tool, signature, text, context_json, import_key)
fixes(id, ts, project, signature, note, ref, test, source, import_key)
wins(id, ts, project, task, what, cost_usd, context_json)
gate_runs(id, ts, project, gate, verdict, detail)
ledger_fts = fts5(signature, text, note, src)   -- índice de errors e fixes
```

## Não-objetivos

Não é daemon, não é pipeline, não usa embeddings. É uma lib e uma CLI que o seu fluxo chama.

## Testes

```sh
python -m unittest -v
```
