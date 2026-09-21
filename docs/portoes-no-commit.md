# Portões rodando de verdade: pre-commit e CI

Portão que ninguém roda não barra nada. São dois pontos de instalação, e os dois gravam em
`gate_runs`, então `erratum top` mostra quanto cada portão reprova.

## pre-commit (o que está em stage)

```sh
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

O hook roda `erratum gate em-dash,stub-neutro --staged`. Com `--staged` o diff julgado é o índice
(`git diff --cached`), o conteúdo lido é o do índice (não o do disco), `--base` é dispensado e a
guarda de worktree limpo não se aplica, porque nesse modo nenhum portão escreve:

- `stub-neutro` só lê;
- `em-dash` só **detecta** (reprova e lista os arquivos); a correção automática com commit continua
  existindo no modo normal, com `--base`;
- `fix-noop` fica de fora: ele reverte arquivo de produção para provar o teste, e isso não se faz
  por cima de um worktree com edição pendente. `gate fix-noop --staged` é uso errado (exit 2).

Detalhes: o hook usa `python3`, ou o interpretador de `ERRATUM_PYTHON`; se o `erratum` não estiver
importável ele avisa no stderr e **não bloqueia** o commit. `git commit --no-verify` pula o hook,
como qualquer hook do git.

## CI (o diff do pull request)

O workflow `.github/workflows/testes.yml` roda, em pull request, os três portões contra a branch
base, com `ERRATUM_DB` temporário:

```sh
python -m erratum gate em-dash,stub-neutro,fix-noop --base origin/main --test-cmd "python -B -m unittest"
```

É no CI que o `fix-noop` trabalha: checkout limpo, sem edição pendente. Use `fetch-depth: 0` no
checkout, senão `origin/main` não resolve e o `gate` sai com 2.
