# Busca que sabe dizer "não sei", e o juiz externo opcional

Busca que sempre devolve algo ensina quem a usa a ignorar o resultado. No erratum todo achado sai
com um **veredito fechado** e, quando nada passa do piso, a resposta é `abstain`, dita com todas as
letras (`nada parecido com confiança no ledger`), com exit 0.

| Veredito | Quando |
|---|---|
| `match` | assinatura exata (confiança 1.0), ou o primeiro colocado do FTS com folga sobre o segundo |
| `talvez` | passou do piso, mas sem folga: leia como hipótese, não como resposta |
| `abstain` | nada passou do piso; `--json` devolve `{"veredito": "abstain", "achados": []}` |

`confianca` (0 a 1) é **heurística, não calibrada**: vale a precisão observada do balde na amostra
abaixo, arredondada. Serve para ordenar e filtrar, não para fazer conta de probabilidade.

## As duas medidas

O bm25 cru do FTS5 não serve de limiar: depende do tamanho da consulta e do tamanho do banco (num
ledger só com as sementes ele passa de 30; num de 16 mil linhas, o mesmo grau de parentesco dá 9).
As duas medidas usadas não têm escala:

- **folga** (`ERRATUM_LIMIAR_MATCH`, padrão `1.6`): bm25 do primeiro colocado dividido pelo do
  segundo, entre os candidatos que sobraram. Só o primeiro pode virar `match`. Candidato único não
  tem folga medida e fica `talvez`.
- **cobertura** (`ERRATUM_LIMIAR_TALVEZ`, padrão `0.15`): fração do peso (idf) dos termos do erro que
  aparece no candidato. Termo que o ledger nunca viu pesa muito, então erro de assunto alheio cai
  abaixo do piso e é descartado.

Também dá para passar `Limiar(match=..., talvez=...)` ao `Ledger.sobre(..., limiar=...)`.

## Como o padrão foi escolhido

Amostra de 200 erros de um ledger real (16 mil erros, 100 correções, `random.seed(42)`), 28 textos
distintos, 84 pares erro/correção candidata julgados à mão. Critério, escrito antes de julgar: o par
é relevante quando a correção trata da **mesma causa** do erro; mesmo sintoma com causa diferente é
irrelevante. 20 dos 84 pares são relevantes (24%).

Depois do `reindex`, 82 dos 84 pares continuam candidatos. Precisão e recall do balde "acima do corte":

| Medida | Corte | Pares | Precisão | Recall |
|---|---|---|---|---|
| bm25 cru | 5 / 7 / 9 / 11 / 13 | 55 / 40 / 24 / 13 / 3 | 31% / 35% / 33% / 38% / 67% | 85% / 70% / 40% / 25% / 10% |
| cobertura | 0.15 / 0.2 / 0.3 / 0.4 / 0.5 | 71 / 63 / 41 / 23 / 14 | 24% / 22% / 27% / 39% / 43% | 85% / 70% / 55% / 45% / 30% |
| folga (com cobertura >= 0.15) | 1.1 / 1.3 / 1.4 / 1.5 / 1.6 | 20 / 6 / 5 / 3 / 2 | 45% / 50% / 60% / 67% / 100% | 45% / 15% / 15% / 10% / 10% |

Padrão escolhido: `match` = folga >= 1.6 (2 de 2 certos na amostra: **é pouco, não é prova**; recall
de 10%); piso do `talvez` = cobertura >= 0.15 (descarta 11 dos 82 pares e perde 3 dos 20 relevantes).
A confiança gravada é 0.8 para `match` por folga e 0.3 para `talvez`, que é a precisão do balde.

O que a curva diz, sem enfeite: num ledger cujas correções são textos longos, **nenhuma medida
léxica chega a 85% de precisão com recall útil**. A folga chega lá, mas só em poucos casos; quase
tudo que o FTS acha sai como `talvez`. No ledger só de sementes (textos curtos e focados) o quadro é
outro: as 10 variações testadas têm folga de 1.9 a 9.8 e saem `match`, e erro de assunto alheio cai
no piso de cobertura. É por isso que existe o juiz opcional abaixo: o limiar decide o que é seguro
afirmar; o resto ele entrega como dúvida. Dito sem rodeio: precisão alta em match **aproximado** pede
o `ERRATUM_JUDGE_CMD`; só com o léxico, `match` fica para a assinatura exata e para o FTS com folga alta.

## Juiz externo (`ERRATUM_JUDGE_CMD`)

Mesmo molde do `ERRATUM_SEARCH_CMD`: um comando seu, sem shell, que o erratum chama quando há
candidato do FTS (`match` ou `talvez`). Assinatura exata nunca passa pelo juiz. Sem a variável, nada
muda. O erratum não importa SDK de ninguém: o contrato é um JSON na entrada padrão e um JSON na saída.

Entrada (uma chamada por busca, com todas as perguntas juntas para amortizar a latência):

```json
{"erro": "...", "assinatura": "...",
 "candidatos": [{"id": "1", "nota": "...", "assinatura": "...", "score": 9.2}],
 "perguntas": ["serve", "mesmo_erro"]}
```

Saída:

```json
{"escolha": "1", "confianca": 0.9, "mesmo_erro": {"1": true, "2": false}}
```

- `escolha`: o `id` do candidato que serve, ou `"abstain"` (a decisão inteira vira `abstain`).
- o escolhido vira `match` com a `confianca` do juiz; candidato com `mesmo_erro: false` sai da lista.
- timeout de 5 s (o processo e os filhos dele são mortos), exit diferente de zero, JSON inválido,
  `id` desconhecido ou `confianca` fora de 0 a 1: aviso no stderr (`juiz externo falhou: ...`) e vale
  o resultado do limiar.

Qualquer coisa que responda esse JSON serve: um modelo de decisão tipada atrás de uma API, um modelo
local pequeno, uma regra sua. Exemplo com `curl` (endereço e chave vêm do ambiente; o serviço precisa
devolver o JSON acima no corpo):

```python
#!/usr/bin/env python3
# juiz.py: ERRATUM_JUDGE_CMD="python3 /caminho/juiz.py"
import json, os, subprocess, sys

pedido = sys.stdin.read()
resposta = subprocess.run(
    ["curl", "-sS", "--max-time", "4", os.environ["JUIZ_URL"],
     "-H", "Authorization: Bearer " + os.environ["JUIZ_CHAVE"],
     "-H", "Content-Type: application/json", "--data-binary", "@-"],
    input=pedido, capture_output=True, text=True)
if resposta.returncode != 0:
    sys.exit(1)                      # o erratum avisa e segue com o limiar
json.loads(resposta.stdout)          # lixo estoura aqui e vira aviso
sys.stdout.write(resposta.stdout)
```

O que o juiz decide entra no registro de pistas com origem `juiz`, então `erratum efeito` mostra se
ele ajuda ou só custa.
