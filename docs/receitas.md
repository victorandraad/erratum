# Receitas: o comando do negócio, em vez do improviso

O agente refaz na mão o que um script já faz. Cada vez de um jeito, cada jeito com a sua taxa de
erro: o laço de `sleep` com `gh` para esperar CI, o `python -c` montado na hora para olhar um
SQLite, a suíte rodada sem a variável que isola o estado. O comando certo existe, só não estava na
frente do agente na hora.

Uma **receita** guarda esse comando. O escopo é estreito de propósito:

| Campo | O que é |
|---|---|
| `comando` | o comando executável, com `<marcador>` onde entra valor |
| `quando` | quando usar, em uma frase (é o que o `how` busca) |
| `em_vez_de` | regex dos improvisos que ela substitui (é o que o `check-cmd` barra) |
| `notas`, `perigo` | o porquê, e o aviso que acompanha o comando toda vez que ele é mostrado |

Conhecimento solto não entra. Se não tem comando para rodar, não é receita: é memória do seu
agente, ou é uma correção (`fix`).

## Cadastrar

```sh
erratum recipe add esperar-ci \
  --quando "esperar o CI de um PR terminar" \
  --cmd "gh pr checks <pr> --watch --fail-fast" \
  --em-vez-de '\bsleep\s+\d+[\s\S]{0,200}?\bgh\s+pr\s+checks\b' \
  --notas "rode em background e siga outro trabalho" \
  --project geral

erratum recipe ls
erratum recipe show esperar-ci
erratum recipe rm esperar-ci --project geral
```

`add` com um nome que já existe no projeto atualiza a receita. O projeto `geral` vale para todos;
receita de um projeto tem prioridade sobre a `geral` de mesmo nome. Sem `--project`, vale o projeto
atual (nome da raiz do git).

`erratum seed` já traz cinco receitas genéricas em `geral`: esperar o CI de um PR, consultar SQLite
sem o binário, rodar a suíte com estado isolado, criar worktree para trabalho isolado e reiniciar
serviço com confirmação de saúde. O `seed` nunca pisa numa receita sua de mesmo nome.

## Perguntar antes de improvisar: `how`

```sh
$ erratum how "esperar o CI do PR fechar"
1. [fts] talvez (0.30) esperar-ci
   quando: esperar o CI de um PR terminar
   rode: gh pr checks <pr> --watch --fail-fast

$ erratum how "pintar a tela de azul"
sem receita pra isso
```

A busca é a mesma dos erros: FTS sobre `nome + quando + notas`, o mesmo contrato
`match | talvez | abstain`, os mesmos limiares (`ERRATUM_LIMIAR_*`) e o mesmo `ERRATUM_JUDGE_CMD`,
se definido ([busca-e-juiz.md](busca-e-juiz.md)). Sem achado confiante ele diz que não tem, e sai 0.

## A peça central: `check-cmd`

```sh
$ erratum check-cmd "while true; do gh pr checks 12; sleep 30; done"
use a receita esperar-ci: gh pr checks <pr> --watch --fail-fast
$ echo $?
1
```

É 100% determinístico: `re.search` de cada `em_vez_de` das receitas visíveis (projeto atual mais
`geral`) contra o comando. Não abre o FTS e não chama modelo, porque roda a cada comando do agente.

| Caso | Saída | Código | Grava |
|---|---|---|---|
| o comando casa com um `em_vez_de` | `use a receita <nome>: <comando>` e o `perigo` | 1 | `desvio` |
| o comando já é a receita | nada | 0 | `uso` |
| nenhuma receita fala dele | nada | 0 | nada |

"Já é a receita" é decidido antes do `em_vez_de`, então uma receita pode barrar a própria versão
incompleta (a suíte sem a variável de estado) sem barrar a versão certa. O padrão canônico sai do
campo `comando`: literal, com cada `<marcador>` valendo qualquer texto e o que vem depois do
primeiro trecho opcional (` [--flag ...]`) ignorado.

### Regex do usuário e ReDoS

A stdlib do Python não tem timeout de regex. As defesas são de tamanho:

- a regex é validada na entrada (`re.compile`); inválida é uso errado (código 2);
- no máximo 300 caracteres, e quantificador aninhado simples (`(a+)+`, `(\w*)*`) é recusado;
- só os primeiros **4 KB** do comando são avaliados. Improviso que começa depois disso passa.

Prefira quantificador com teto (`[\s\S]{0,200}?`) a `.*`. Regex podre que chegou ao banco por outro
caminho é ignorada, nunca derruba o `check-cmd`.

### Falso positivo é o que mata

Um `em_vez_de` que barra comando inocente ensina o agente a ignorar o aviso. Teste cada regex contra
o improviso **e** contra o vizinho legítimo: `gh pr view` não é "esperar CI", `sleep 2` sozinho não é
nada. As sementes são provadas assim em `tests/test_receitas_semente.py`: três improvisos e três
inocentes por receita.

## Correção que aponta para receita

```sh
erratum fix 12 "o worktree nasce sem dependências" --recipe prep-do-worktree
```

Na próxima vez que o erro aparecer, a pista do `err` traz o comando, não só o texto:

```
  correção conhecida: o worktree nasce sem dependências
  receita prep-do-worktree: bin/prep <worktree>
```

A pista entra no `efeito` com a origem `receita`.

## Medir: `scan`, `top`, `efeito`

- `erratum scan <stream.jsonl>` além dos erros conta, nos comandos Bash do transcript, quantos
  casam com um `em_vez_de` (desvio) e quantos já são a receita (uso). Reler o mesmo arquivo não
  duplica.
- `erratum top --days 14` ganha a seção **improvisos**: desvios por receita no período. É a lista
  do que o agente ainda faz na mão.
- `erratum efeito` ganha uso contra desvio por receita: `receita esperar-ci: 1 uso, 3 desvios (25%
  pela receita)`. Receita com muito desvio e pouco uso não está chegando no agente: ligue o hook.

## Hook `PreToolUse` do Claude Code

[`hooks/pretooluse-check-cmd.py`](../hooks/pretooluse-check-cmd.py) lê o JSON do hook no stdin,
pega `tool_input.command` das chamadas `Bash` e roda o `check-cmd` (a task é o `session_id`, o
projeto sai do `cwd` do payload). Em `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /caminho/do/clone/hooks/pretooluse-check-cmd.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

| Modo | Como liga | O que acontece num desvio |
|---|---|---|
| avisa (padrão) | nada a fazer | sai 0 e devolve `hookSpecificOutput.additionalContext`: o comando roda, e o modelo lê `use a receita ...` junto do resultado |
| bloqueia | `ERRATUM_HOOK_BLOQUEIA=1` no ambiente | sai 2 com a mensagem no stderr: o Claude Code nega a chamada e entrega o stderr ao modelo |

Comece avisando. Bloquear só depois de olhar o `top` e confiar que os seus `em_vez_de` não têm
falso positivo. Em qualquer falha (stdin torto, erratum não instalado, banco inacessível, mais de 5
segundos) o hook sai 0 em silêncio: ele nunca trava o Bash do agente. Se o comando `erratum` não
está no `PATH` do hook, aponte o interpretador que tem o pacote em `ERRATUM_PYTHON`.
