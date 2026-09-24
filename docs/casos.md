# Casos reais do `erratum gate`

Quatro disparos reais dos portões determinísticos, cada um montado num repo git temporário,
rodado de verdade contra `erratum gate` e com a saída colada sem edição (só o caminho do
temporário trocado por `/tmp/demo`).

## a) fix-noop: "fix" que não muda comportamento

Um commit que promete "melhorar a soma" mas só renomeia uma variável interna. O teste já
passava antes do commit e continua passando sem ele: não prova defeito nenhum.

```diff
--- a/src/calc.py
+++ b/src/calc.py
@@ -1,2 +1,4 @@
 def soma(a, b):
-    return a + b
+    # fix: melhora clareza
+    resultado = a + b
+    return resultado
```

Comando:

```sh
python3 -m erratum gate fix-noop --base HEAD~1 --worktree /tmp/demo --test-cmd "python3 -B -m unittest {testes}"
```

Saída:

```text
fix-noop: reprovou Testes do escopo continuam verdes sem a correção (no-op ou teste que sempre passa)
```

## b) stub-neutro: implementação stub pega pelo portão

Uma classe nova (`BuscadorPadrao`) implementa o contrato `Buscador.listar_itens(loja, params)`
mas devolve `[]` sem tocar em nenhum dos dois parâmetros: promessa de busca que nunca busca.

```diff
--- /dev/null
+++ b/src/impl/buscador_padrao.py
@@ -0,0 +1,6 @@
+from src.base import Buscador
+
+
+class BuscadorPadrao(Buscador):
+    def listar_itens(self, loja, params):
+        return []
```

Comando:

```sh
python3 -m erratum gate stub-neutro --base HEAD~1 --worktree /tmp/demo
```

Saída:

```text
stub-neutro: reprovou src/impl/buscador_padrao.py: `BuscadorPadrao` implementa `Buscador` e `listar_itens()` devolve [] ignorando `loja`, `params` sem consultar fonte nenhuma
```

## c) em-dash: travessão em código/comentário

Um comentário novo traz travessão (U+2014) dentro do código de produção. No diff abaixo ele
aparece como `<U+2014>`: este repo barra o caractere literal, inclusive na documentação.

```diff
--- a/src/status.py
+++ b/src/status.py
@@ -1,2 +1,3 @@
 def status(ativo):
-    return "ligado"
+    # liga<U+2014>desliga conforme o flag
+    return "ligado" if ativo else "desligado"
```

Comando (modo normal, com `--base`: o portão corrige e commita, diferente do `--staged` do
pre-commit, que só detecta e reprova):

```sh
python3 -m erratum gate em-dash --base HEAD~1 --worktree /tmp/demo
```

Saída:

```text
em-dash: aprovou corrigido em 1 arquivo(s)
```

## d) instrumento-morto: teste que já falha com o patch

Um "fix" adiciona `eh_impar` ao teste, mas a implementação de produção é um stub (`pass`).
O teste do escopo já falha rodando COM o patch aplicado (baseline), antes mesmo do portão
reverter a produção: não prova nada, e o `fix-noop` para aí em vez de seguir para o resultado
"aprovou/reprovou" normal. Ver `ce8fe17` e `tests/test_portoes_fix_noop.py` para a origem
dessa checagem de baseline.

```diff
--- a/src/valida.py
+++ b/src/valida.py
@@ -1,2 +1,7 @@
 def eh_par(n):
     return n % 2 == 0
+
+
+def eh_impar(n):
+    # TODO: falta implementar
+    pass
```

Comando:

```sh
python3 -m erratum gate fix-noop --base HEAD~1 --worktree /tmp/demo --test-cmd "python3 -B -m unittest {testes}"
```

Saída:

```text
fix-noop: reprovou instrumento-morto: os testes do escopo já falham com a correção aplicada (teste quebrado não prova nada):     self.assertTrue(eh_impar(3)) | AssertionError: None is not true | ---------------------------------------------------------------------- | Ran 2 tests in 0.009s | FAILED (failures=1)
```

## Reprodutibilidade

Os quatro casos são reproduzíveis: crie um repo git temporário (`mktemp -d`), faça os dois
commits do diff de cada caso (base e "fix"), aponte `ERRATUM_DB` para um banco temporário fora
de `~/.local/state/erratum` e rode o comando indicado em cada seção com
`python3 -m erratum gate ... --worktree <repo temporário>` a partir do checkout de `erratum`.
