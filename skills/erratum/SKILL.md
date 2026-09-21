---
name: erratum
description: Usa o ledger local de erros e acertos (erratum) durante qualquer trabalho de código, em qualquer repositório. Consulta a correção conhecida quando algo falha, registra a correção quando resolve e o passe limpo quando acerta de primeira. Use sempre que um comando, teste, build, deploy ou merge falhar; antes de investigar um erro do zero; ao fechar uma correção; e quando o usuário disser "já vi esse erro", "o que mais repete", "registra isso no ledger" ou "/erratum".
---

# erratum: não resolver duas vezes o mesmo erro

Um ledger por máquina, compartilhado por todos os projetos: erro corrigido num repositório vira
pista em outro. O banco fica em `$ERRATUM_DB` (padrão `~/.local/state/erratum/ledger.db`).

O comando é `erratum` (instalado por `pipx` ou `pip`). Sem instalar, use o comando inteiro a cada
chamada, porque alias não persiste entre chamadas de shell do agente:
`PYTHONPATH=<caminho do clone> python3 -m erratum ...`.

O projeto sai do nome da raiz do git; fora de um repositório, passe `--project <nome>`. Todo
comando aceita `--json`. Texto longo entra por stdin com `-`.

## Os três momentos

**1. Falhou: registre ANTES de investigar.** Cole o erro cru (a linha que importa, não o log todo).

```sh
erratum err "<erro cru>" --stage <dev|teste|ci|deploy|merge> --tool <Bash|pytest|...>
```

Se voltar `correção conhecida:`, aplique essa primeiro; só investigue do zero se ela não servir.
Linhas `talvez:` são candidatos fracos da busca por texto: leia, mas não confie às cegas.
Para consultar sem registrar: `erratum find "<texto>" -n 3 --resolved`.

**2. Resolveu: registre a correção.** A nota diz a CAUSA e o que fazer, em uma frase que sirva para
quem nunca viu o caso. `--ref` é commit, PR ou arquivo; `--test` é o teste de regressão.

```sh
erratum fix <id do erro|texto cru> "<causa + o que fazer>" --ref <hash> --test <caminho do teste>
```

A correção casa por assinatura: cobre as ocorrências antigas e as futuras. Correção sem teste de
regressão vale pouco; se não houver teste, diga na nota por quê.

**3. Acertou de primeira: registre o passe limpo.** Só quando foi limpo de verdade (sem retrabalho,
teste verde de primeira). Diga o que fez dar certo, não só o que foi feito.

```sh
erratum win "<o que funcionou e por quê>" --task <id> --cost <usd>
```

## Antes de commitar: portões determinísticos (zero modelo)

```sh
erratum gate em-dash,stub-neutro,fix-noop --base <branch base> --test-cmd "<comando de teste> {testes}"
```

Saída 1 = reprovou: leia o motivo e corrija. Exige worktree limpo e `--base` que resolva para um
commit. Em projeto Python use `python -B` no `--test-cmd`. `fix-noop` acusa correção que não muda o
resultado do teste; `stub-neutro` acusa classe nova que só devolve vazio; `em-dash` troca travessão
de prosa por vírgula (tire da lista se o projeto não tem essa regra).

## O que mais repete

```sh
erratum top --days 14                    # este projeto
erratum top --all-projects --days 30
```

Vem sem correção primeiro, ordenado por tasks distintas. O topo da lista é a próxima coisa que vale
consertar na raiz. `[!] nunca decidiu` num portão = portão quebrado, não portão saudável.

## Regras

- Não registre segredo, token nem dado de cliente no texto do erro: corte antes de colar.
- Não registre erro de digitação que você corrigiu em cinco segundos; registre o que custou tempo
  ou o que pode voltar.
- Escrita concorrente é segura (SQLite em WAL): vários agentes e CLIs podem usar o mesmo ledger.
- O ledger é só erro, correção, acerto e veredito de portão. Fato durável sobre o projeto ou sobre
  a pessoa vai para a memória do seu agente, não para cá.
- O ledger fora do ar nunca bloqueia o trabalho: se o comando falhar, siga e avise no retorno.
