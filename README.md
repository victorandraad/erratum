# erratum

Agente de código erra, alguém conserta, e na semana seguinte o mesmo erro volta porque a correção
ficou num log que ninguém lê. `erratum` é um ledger local: registra o erro, guarda a correção pela
**assinatura** do erro e a devolve na hora em que ele reaparece. Python puro (stdlib), um SQLite.

## Instalar

Requisitos: Python 3.9+ e SQLite com FTS5 (vem no Python de quase toda distribuição). Confira:

```sh
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)'); print('FTS5 ok')"
```

```sh
pipx install git+https://github.com/<org>/erratum     # recomendado: comando global `erratum`
pip install git+https://github.com/<org>/erratum      # dentro de um venv
git clone https://github.com/<org>/erratum && PYTHONPATH=$PWD/erratum python3 -m erratum top   # sem instalar
```

Primeiro uso: semeie o ledger.

```sh
erratum seed          # idempotente; `erratum seed --list` mostra o que vem
```

As **sementes** são 30 correções genéricas para os erros que mais se repetem e mais custam quando
se roda agente de código em git e CI: agente que termina sem commit, conflito de merge na branch do
agente, CI vermelho por infra, worktree sem dependências, limite de uso do provedor, push rejeitado,
teste que passa sem a correção. Depois do `seed`, colar um desses erros em `erratum err`, em
qualquer projeto, já devolve a correção. Semente não é ocorrência: não entra no `top` nem zera
streak.

## Em 30 segundos

```sh
erratum err "Exit code 127 /tmp/w-1/bin/runner: No such file"
# erro #1 registrado [acme] assinatura: exit code N /PATH: no such file

erratum fix 1 "rodar o prep do worktree antes do runner" --ref abc123 --test test_prep
# correção #1 registrada [acme] para: exit code N /PATH: no such file

erratum err "Exit code 1 /tmp/w-99/bin/runner: No such file"
# erro #2 registrado [acme] assinatura: exit code N /PATH: no such file
#   correção conhecida: rodar o prep do worktree antes do runner [ref: abc123, teste: test_prep]

erratum find "bin/runner no such file"
# 1. [fts] exit code N /PATH: no such file
#    correção: rodar o prep do worktree antes do runner [ref: abc123, teste: test_prep]
```

A assinatura normaliza o que é volátil (caminhos viram `/PATH`, números viram `N`, contador de
rodada some), então uma correção cobre as ocorrências passadas e as futuras.

## Comandos

| Comando | Faz |
|---|---|
| `seed [--list]` | carrega as correções genéricas embarcadas (idempotente); `--list` só mostra |
| `err "<texto>" [--stage --tool --kind --task]` | registra o erro e já devolve a correção conhecida: a melhor pista vem inteira, as demais em uma linha (`talvez:`) |
| `fix <id\|texto> "<nota>" [--ref --test]` | registra a correção pela assinatura do erro |
| `find "<texto>" [-n N] [--resolved]` | busca no ledger (assinatura, depois FTS); `--resolved` fica só com achados que já têm correção (o `-n` vale depois desse filtro); não registra |
| `top [--days N] [--all-projects] [--resolved]` | lista o que se repete, agrupado por assinatura (não resolvido primeiro, peso `max(tasks, 1)`, depois ocorrências), e a taxa de reprovação de cada portão |
| `win "<o que>" [--task --cost]` | registra um acerto |
| `gate <portões> --base <ref> [--worktree DIR] [--test-cmd "..."]` | roda portões determinísticos no diff e grava o veredito |
| `scan <stream.jsonl>` | minera os `tool_result` com `is_error` de um stream-json de agente |
| `import <arquivo.jsonl>` | carrega erros de um JSONL genérico |

O streak de `win` conta os acertos do projeto com timestamp depois do último erro do mesmo projeto; um erro zera a sequência.

Todos aceitam `--json` e `--project` (padrão: nome da raiz do git). Texto `-` lê do stdin.
Saída 0 sempre, com duas exceções: `gate` com algum portão reprovado sai com 1, e uso errado sai com 2.
Pipe fechado (`erratum top | head`) sai 0, sem traceback e sem nada no stderr: vale para qualquer comando.

## Portões (`gate`)

Checagens sem modelo sobre o diff entre `--base` e o `HEAD` do `--worktree` (padrão: diretório atual).
Cada veredito (`aprovou`, `reprovou`, `pulou`) vai pra `gate_runs`, e o `top` mostra quanto cada
portão reprova: portão que nunca dispara é portão que não está servindo. Se todas as rodadas
pularam, a linha humana termina com `[!] nunca decidiu: portão quebrado?` e o JSON traz
`nunca_decidiu: true`.

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

## Usar com a sua IA

O ledger só rende se o agente chamar nos três momentos: **falhou** (`err` antes de investigar),
**resolveu** (`fix` com causa, ref e teste), **acertou de primeira** (`win`), mais o `gate` antes do
commit. O mínimo, para colar em `CLAUDE.md`, `AGENTS.md` ou nas regras do seu editor:

```
Ao errar, rode `erratum err "<texto do erro>"` antes de investigar: se vier "correção conhecida",
aplique. Ao corrigir algo novo, `erratum fix <id> "<causa + o que fazer>" --ref <commit> --test <teste>`.
Passe limpo (entregou sem erro no caminho), `erratum win "<o que funcionou>"`. Antes do commit,
`erratum gate stub-neutro,fix-noop --base <branch base> --test-cmd "<runner> {testes}"`.
```

O bloco completo, a skill do Claude Code (`skills/erratum/`), o hook que minera a sessão no fim e
a integração por `--json` estão em [docs/usar-com-ia.md](docs/usar-com-ia.md).

## API

`Ledger.registrar_correcao` aceita `ts=None` (None usa o relógio) e continua devolvendo a
`Correcao`. Importação idempotente: `registrar_correcao_importada(...)` devolve
`(correcao, inseriu)`, no mesmo espírito de `registrar_erro_importado`.
`Ledger.buscar(texto, n=5, so_resolvidos=False)` com `so_resolvidos=True` devolve só achados
com correção; o `n` corta depois do filtro.
`Semeador(ledger, caminho=None).semear()` carrega um JSON de sementes (o embarcado, ou o do seu
time) e devolve quantas entraram; `Ledger.registrar_semente(dict)` grava uma.

## Onde ficam os dados

`$ERRATUM_DB` (padrão `~/.local/state/erratum/ledger.db`), SQLite em WAL: várias CLIs e agentes
podem escrever ao mesmo tempo, na mesma máquina. Um ledger serve todos os projetos. Banco comum
para vários usuários, o que não fazer (volume de rede) e backup:
[docs/ledger-compartilhado.md](docs/ledger-compartilhado.md).

## O que isto não é

- **Não é daemon nem orquestrador**: nada roda em segundo plano, nada dispara agente. É uma lib e
  uma CLI que o seu fluxo chama.
- **Não é memória geral**: guarda erro, correção, acerto e veredito de portão. Preferência, decisão
  de produto e contexto de projeto vão para a memória do seu agente.
- **Não usa embeddings nem modelo**: assinatura normalizada e FTS5. Se quiser busca semântica,
  plugue a sua por `ERRATUM_SEARCH_CMD`.
- **Não sincroniza entre máquinas.**

## Privacidade

Tudo que você registra fica no seu banco local: o `erratum` não faz rede. O repositório não
embarca dado de ninguém além das sementes genéricas, e um teste (`tests/test_privacidade.py`)
reprova qualquer arquivo versionado que carregue termo privado de quem mantém. Do seu lado: nunca
cole segredo, token ou dado de cliente no texto de um erro, porque ele vai para o banco em claro.

## Testes

```sh
python -m unittest
```

Como contribuir e como proteger os termos privados do seu fork: [CONTRIBUTING.md](CONTRIBUTING.md).
