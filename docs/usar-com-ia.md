# Usar com a sua IA

O `erratum` só rende se o agente chamar nos momentos certos. Ele não adivinha: alguém precisa
dizer isso nas instruções do agente. Há três jeitos, do mais simples ao mais automático.

## 1. Bloco de instruções (qualquer agente)

Cole em `CLAUDE.md`, `AGENTS.md`, nas regras do Cursor (`.cursor/rules/`), nas instruções do
Copilot ou no prompt de sistema do seu orquestrador:

```markdown
## Ledger de erros (erratum)

- FALHOU (comando, teste, build, deploy, merge): antes de investigar, rode
  `erratum err "<linha do erro, crua>" --stage <etapa> --tool <ferramenta>`.
  Se vier "correção conhecida", aplique essa primeiro. Linhas "talvez:" são candidatos fracos.
- RESOLVEU algo novo: `erratum fix <id do erro> "<causa + o que fazer>" --ref <commit> --test <teste de regressão>`.
  A nota tem de servir para quem nunca viu o caso.
- ANTES DE IMPROVISAR um procedimento (esperar CI, reiniciar serviço, rodar a suíte, consultar o
  banco, criar worktree): `erratum how "<o que quero fazer>"`. Se vier receita, rode o comando dela
  em vez de montar o seu. Se um comando seu voltar `use a receita <nome>: ...`, troque pelo da receita.
- ACERTOU de primeira, sem retrabalho: `erratum win "<o que funcionou e por quê>"`.
- ANTES DO COMMIT: `erratum gate stub-neutro,fix-noop --base <branch base> --test-cmd "<runner> {testes}"`.
  Saída 1 = reprovou: leia o motivo e corrija antes de commitar.
- Nunca cole segredo, token ou dado de cliente no texto do erro.
- Se o erratum falhar, siga o trabalho e avise no fim: o ledger nunca bloqueia.
```

Se o comando não está instalado globalmente, troque `erratum` por
`PYTHONPATH=<caminho do clone> python3 -m erratum` no bloco inteiro: alias de shell não sobrevive
entre as chamadas do agente.

## 2. Skill do Claude Code

O repositório traz uma skill pronta em [`skills/erratum/SKILL.md`](../skills/erratum/SKILL.md).
Para valer em todos os projetos da máquina:

```sh
mkdir -p ~/.claude/skills && cp -r skills/erratum ~/.claude/skills/
```

Para valer só num projeto, copie para `.claude/skills/` dentro dele. A skill carrega sozinha quando
algo falha, e também por `/erratum`.

## 3. Hook: minerar a sessão no fim (Claude Code, opcional)

Mesmo com as instruções, o agente esquece. O hook `Stop` recebe no stdin um JSON com
`transcript_path`, o JSONL da sessão, e o `erratum scan` extrai dele todo `tool_result` com
`is_error`. É idempotente: reler a mesma sessão não duplica nada. Em `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 -c \"import json,sys,subprocess; p=json.load(sys.stdin).get('transcript_path'); p and subprocess.run(['erratum','scan',p])\"",
            "timeout": 20
          }
        ]
      }
    ]
  }
}
```

Usamos `Stop` e não `PostToolUse` de propósito: o `scan` lê o transcript inteiro, e rodar isso a
cada chamada de ferramenta é custo sem ganho. O `scan` só registra ocorrências (alimenta o `top`);
a correção continua sendo um `fix` consciente.

Para quem orquestra agentes headless com saída `stream-json`: grave o stream num arquivo por task
e rode `erratum scan <arquivo>.jsonl` no fim. O nome do arquivo vira a task de cada erro.

## 4. Hook: barrar o improviso antes de rodar (Claude Code, opcional)

O `how` depende de o agente lembrar de perguntar. O hook `PreToolUse` não depende: passa cada
comando Bash pelo `erratum check-cmd` e, quando o comando é um improviso que uma receita substitui,
devolve `use a receita <nome>: <comando>` no contexto do modelo. Por padrão só avisa e deixa o
comando rodar; com `ERRATUM_HOOK_BLOQUEIA=1` ele nega a chamada. Nunca trava o Bash: qualquer falha
do erratum vira saída 0 em silêncio. O arquivo é
[`hooks/pretooluse-check-cmd.py`](../hooks/pretooluse-check-cmd.py); a configuração do
`settings.json`, os dois modos e como escrever um `em_vez_de` sem falso positivo estão em
[receitas.md](receitas.md).

## 5. Integrar por script

Todo comando aceita `--json`, com saída estável:

```sh
erratum err "$MSG" --stage ci --task "$TASK" --json | python3 -c "
import json, sys
pistas = json.load(sys.stdin)['pistas']
if pistas:
    print(pistas[0]['correcoes'][0]['nota'])"
```

Códigos de saída: 0 sempre, menos `gate` reprovado (1), `check-cmd` que achou improviso (1) e uso errado (2). Dá para usar o `gate`
direto como passo de CI ou hook de `pre-commit`.

Em Python, sem subprocesso:

```python
from erratum.banco import Banco
from erratum.ledger import Ledger

with Banco() as banco:
    ledger = Ledger.sobre(banco)
    erro, pistas = ledger.registrar_erro("texto do erro", "meu-projeto", etapa="ci")
```

## 6. Plugar uma memória externa (`ERRATUM_SEARCH_CMD`)

Se você já tem uma busca (wiki, base de incidentes, memória vetorial do seu agente), o `erratum`
consulta as duas:

```sh
export ERRATUM_SEARCH_CMD="minha-busca --limite 5"   # roda: minha-busca --limite 5 "<consulta>"
```

Cada linha do stdout entra como achado `external`, abaixo dos do ledger. Sem shell, limite de 10
segundos; falha do comando vira aviso no stderr e a busca segue só com o ledger.
