# erratum

Prova que a correção conserta, sem modelo no meio, e guarda a correção para o erro não ser resolvido duas vezes.

## O problema

O agente diz que consertou. O teste passa. E o teste passaria igual sem a correção: ele nunca
exercitou o defeito. O diff entra, o erro volta na semana seguinte.

## O portão

`erratum gate` reverte só o código de produção do diff e roda de novo os testes que o próprio diff
trouxe. Verde sem a correção é reprovação:

```sh
$ git log --oneline -1
3f1c2aa corrige soma                      # troca a - b por a + b, e traz um teste novo
$ erratum gate fix-noop --base main --test-cmd "python3 -B -m unittest {testes}"
fix-noop: reprovou Testes do escopo continuam verdes sem a correção (no-op ou teste que sempre passa)
$ echo $?
1
```

O teste do commit era `assertTrue(callable(calc.soma))`: passa com o defeito e com o conserto. São
três portões, todos determinísticos (git, regex e o seu runner): `fix-noop`, `stub-neutro` (classe
nova que cumpre o contrato devolvendo `[]` em tudo) e `em-dash`. Rodam no pre-commit e no CI:
[docs/portoes-no-commit.md](docs/portoes-no-commit.md).

## E não resolva duas vezes

O ledger registra o erro, guarda a correção pela **assinatura** do erro e a devolve quando ele
reaparece. `err` ao falhar, `fix` ao resolver, `find` para consultar. Quando não há nada parecido
com confiança, ele diz isso em vez de chutar. Python puro (stdlib), um SQLite.

A mesma falha reemitida no mesmo card não vira mil linhas: a linha ganha um contador. Histórico
já inflado (import antigo, esteira que polia): `erratum compactar` (`--dry-run` primeiro).

## E não improvise o que já tem comando

O agente refaz na mão o que um script já faz: cada vez de um jeito, cada jeito com a sua taxa de
erro. Uma **receita** guarda o comando do seu negócio, quando usar e o improviso que ela substitui,
e o `check-cmd` barra o improviso antes de rodar:

```sh
$ erratum check-cmd "while true; do gh pr checks 12; sleep 30; done"
use a receita esperar-ci-do-pr: gh pr checks <pr> --watch --fail-fast
$ echo $?
1
```

Só regex contra o comando, sem modelo e sem busca: roda a cada comando do agente, pelo hook
`PreToolUse`, que por padrão avisa e deixa passar. `erratum how "<intenção>"` acha a receita antes de
improvisar, no mesmo contrato `match | talvez | abstain` da busca de erros, e o `top` lista os
improvisos que ainda acontecem. O escopo é estreito de propósito: receita é comando executável,
quando usar e o que ela substitui; conhecimento solto não entra.
[docs/receitas.md](docs/receitas.md).

## Por que não é mais uma memória para agente

- **Determinístico**: assinatura normalizada, FTS5 e regex. A mesma entrada dá a mesma saída.
- **Zero dependência**: stdlib do Python 3.9+, um arquivo SQLite, nenhuma rede.
- **Correção presa a teste**: `fix --test` aponta o teste de regressão, e o `fix-noop` prova que ele falha sem a correção.
- **Sabe dizer não sei**: todo achado sai como `match` ou `talvez`; abaixo do piso a resposta é `abstain` ([docs/busca-e-juiz.md](docs/busca-e-juiz.md)).
- **Mede o próprio efeito**: cada pista mostrada é registrada, o desfecho da task fecha a conta, e `erratum efeito` compara quem recebeu `match` com quem ficou sem pista.

## Instalar

Requisitos: Python 3.9+ e SQLite com FTS5 (vem no Python de quase toda distribuição). Confira:

```sh
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)'); print('FTS5 ok')"
```

```sh
pipx install git+https://github.com/victorandraad/erratum     # recomendado: comando global `erratum`
pip install git+https://github.com/victorandraad/erratum      # dentro de um venv
pipx install erratum-cli                               # pelo índice, quando a versão estiver publicada
git clone https://github.com/victorandraad/erratum && PYTHONPATH=$PWD/erratum python3 -m erratum top   # sem instalar
```

O pacote no índice se chama `erratum-cli` (o nome `erratum` já tinha dono); o comando continua
`erratum` e o import continua `import erratum`.

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

O `seed` traz também 5 **receitas** genéricas no projeto `geral` (esperar o CI de um PR, consultar
SQLite sem o binário, rodar a suíte com estado isolado, worktree para trabalho isolado, reiniciar
serviço com confirmação de saúde), cada uma com o improviso que ela substitui.

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
# 1. [fts] talvez (0.30) exit code N /PATH: no such file
#    correção: rodar o prep do worktree antes do runner [ref: abc123, teste: test_prep]

erratum find "a tela de login ficou azul"
# nada parecido com confiança no ledger
```

A assinatura normaliza o que é volátil (caminhos viram `/PATH`, números viram `N`, nome de branch
vira `<branch>`, hash de commit vira `<sha>`, valor em dinheiro vira `<valor>`, o prefixo de quem
reportou e o contador de rodada somem), então uma correção cobre as ocorrências passadas e as
futuras. A regra tem versão: depois de atualizar o erratum, `err` e `find` avisam no stderr quando o
banco foi gravado com a regra antiga, e `erratum reindex [--dry-run]` recalcula tudo numa transação.

## Comandos

| Comando | Faz |
|---|---|
| `seed [--list]` | carrega as correções e as receitas genéricas embarcadas (idempotente); `--list` só mostra |
| `err "<texto>" [--stage --tool --kind --task]` | registra o erro e já devolve a correção conhecida: a melhor pista vem inteira, as demais em uma linha (`talvez:`) |
| `fix <id\|texto> "<nota>" [--ref --test --task --recipe]` | registra a correção pela assinatura do erro; com `--recipe <nome>`, a pista do `err` passa a mostrar o comando da receita; com `--task`, fecha as pistas da task como `resolveu` |
| `find "<texto>" [-n N] [--resolved]` | busca no ledger (assinatura, depois FTS); `--resolved` fica só com achados que já têm correção (o `-n` vale depois desse filtro); cada achado traz veredito e confiança; não registra, salvo `--registrar [--task]` |
| `top [--days N] [--all-projects] [--resolved]` | lista o que se repete, agrupado por assinatura (não resolvido primeiro, peso `max(tasks, 1)`, depois ocorrências), a taxa de reprovação de cada portão e os improvisos por receita |
| `win "<o que>" [--task --cost]` | registra um acerto |
| `gate <portões> --base <ref> [--worktree DIR] [--test-cmd "..."]` | roda portões determinísticos no diff e grava o veredito; `--staged` julga o índice (pre-commit) |
| `desfecho <task> <resolveu\|nao_resolveu\|descartado>` | fecha as pistas abertas da task |
| `efeito [--days N]` | por origem e por veredito: pistas, % com desfecho, % `resolveu`; tasks com `match` contra tasks sem pista, com o N ao lado; e uso contra desvio por receita |
| `reindex [--dry-run]` | recalcula as assinaturas gravadas com a regra atual e reconstrói o FTS |
| `scan <stream.jsonl>` | minera os `tool_result` com `is_error` de um stream-json de agente, e conta os comandos Bash que são improviso (desvio) ou receita (uso) |
| `recipe add <nome> --quando "..." --cmd "..." [--em-vez-de "<regex>" ...] [--notas --perigo]` | cadastra ou atualiza uma receita; `recipe ls`, `recipe show <nome>`, `recipe rm <nome>` |
| `how "<intenção>" [-n 3] [--task]` | acha a receita pela intenção (FTS sobre nome, quando e notas), com veredito e confiança; sem achado confiante: `sem receita pra isso` |
| `check-cmd "<comando bash>" [--task]` | casa o comando com os `em_vez_de` das receitas do projeto e de `geral`: improviso imprime `use a receita ...` e sai 1; silêncio e 0 no resto |
| `import <arquivo.jsonl>` | carrega erros de um JSONL genérico |

O streak de `win` conta os acertos do projeto com timestamp depois do último erro do mesmo projeto; um erro zera a sequência.

Todos aceitam `--json` e `--project` (padrão: nome da raiz do git). Texto `-` lê do stdin.
Saída 0 sempre, com três exceções: `gate` com algum portão reprovado sai com 1, `check-cmd` que achou improviso sai com 1, e uso errado sai com 2.
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

## Medir se a pista ajudou (`desfecho` e `efeito`)

Cada pista que o `err` mostra vira uma linha (task, origem, veredito, confiança); quando ele se cala,
a linha é `abstain`. `fix --task`, `win --task` ou `erratum desfecho <task> ...` fecham as linhas da
task. `erratum efeito` então mostra a taxa de `resolveu` das tasks que receberam `match`, das que
ficaram sem pista e a geral, sempre com o N do grupo, e escreve `amostra pequena, não conclua`
quando N < 30. É comparação observacional, não experimento: serve para ver se vale manter a pista
ligada, não para provar causa.

## Busca externa (`ERRATUM_SEARCH_CMD`)

Se a variável existir, `find` e `err` rodam também o seu comando, com a consulta como último
argumento, e cada linha do stdout entra como achado `external`, abaixo dos do ledger.

```sh
export ERRATUM_SEARCH_CMD="minha-busca --limite 5"   # roda: minha-busca --limite 5 "<consulta>"
```

Sem shell, limite de 10 segundos. Saída diferente de 0, timeout ou comando inexistente viram aviso no stderr e a
busca segue só com o ledger. Para decidir entre candidatos em dúvida existe o `ERRATUM_JUDGE_CMD`,
também opcional: [docs/busca-e-juiz.md](docs/busca-e-juiz.md).

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
`Ledger.decidir(texto, n=5, so_resolvidos=False)` devolve `Decisao(veredito, confianca, achados)`;
`buscar` devolve só os achados dela. `Ledger.registrar_desfecho(task, desfecho, projeto=None)`,
`Ledger.efeito(projeto=None, dias=None)` e `Ledger.reindexar(simular=False)` espelham os comandos.
`Semeador(ledger, caminho=None).semear()` carrega um JSON de sementes (o embarcado, ou o do seu
time) e devolve quantas entraram; `Ledger.registrar_semente(dict)` grava uma.
Receitas: `Ledger.verificar_comando(comando, projeto, task="")` devolve o resultado do `check-cmd`
(`tipo` em `uso`, `desvio` ou `None`, e a `receita`), `Ledger.consultar_receita(texto, projeto)` é o
`how`, e `salvar_receita`, `receita_por_nome`, `receitas_visiveis` e `remover_receita` espelham o
`recipe`. A coluna `receita` da `Correcao` e o campo `receita` do `Achado` vieram por acréscimo.

## Onde ficam os dados

`$ERRATUM_DB` (padrão `~/.local/state/erratum/ledger.db`), SQLite em WAL: várias CLIs e agentes
podem escrever ao mesmo tempo, na mesma máquina. Um ledger serve todos os projetos. Banco comum
para vários usuários, o que não fazer (volume de rede) e backup:
[docs/ledger-compartilhado.md](docs/ledger-compartilhado.md).

## O que isto não é

- **Não é daemon nem orquestrador**: nada roda em segundo plano, nada dispara agente. É uma lib e
  uma CLI que o seu fluxo chama.
- **Não é memória geral**: guarda erro, correção, acerto, veredito de portão e receita (comando executável, não conhecimento solto). Preferência, decisão
  de produto e contexto de projeto vão para a memória do seu agente.
- **Não usa embeddings nem modelo**: assinatura normalizada e FTS5. Se quiser busca semântica,
  plugue a sua por `ERRATUM_SEARCH_CMD`; se quiser um juiz para os casos em dúvida, `ERRATUM_JUDGE_CMD`.
- **Não sincroniza entre máquinas.**

## Privacidade

Tudo que você registra fica no seu banco local: o `erratum` não faz rede. O repositório não
embarca dado de ninguém além das sementes genéricas (correções e receitas de ferramentas públicas), e um teste (`tests/test_privacidade.py`)
reprova qualquer arquivo versionado que carregue termo privado de quem mantém. Do seu lado: nunca
cole segredo, token ou dado de cliente no texto de um erro, porque ele vai para o banco em claro.

## Testes

```sh
python -m unittest
```

Como contribuir e como proteger os termos privados do seu fork: [CONTRIBUTING.md](CONTRIBUTING.md).
