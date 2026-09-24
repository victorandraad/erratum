# erratum

![16,055 real error occurrences from the ledger fall into 1,303 buildings, one per signature](docs/img/erratum.webp)

Not a memory store. A gate that **proves the fix actually fixes**, and a local ledger so the same
error is **not solved twice**. No model in the middle: Python 3.9+, stdlib, one SQLite file.

The agent says it fixed the bug. The test is green. The test would have been green without the
patch. The diff lands; the error comes back next week. That is the hole `erratum` fills.

Portuguese: [README.pt.md](README.pt.md).

## What it is, what it is not

| you want | use | do not use erratum |
|---|---|---|
| the new test would fail without the patch | **erratum** (`gate fix-noop`) | pytest alone (green does not prove the defect) |
| the same CI log not investigated again | **erratum** (`err` / `fix` / `find`) | Sentry (production, not the agent loop) |
| the agent stops improvising `sleep` + `gh pr checks` | **erratum** (`check-cmd` / recipes) | a paragraph in AGENTS.md (it falls out of context) |
| automatic session diary | [claude-mem](https://github.com/thedotmack/claude-mem) | erratum does not capture sessions |
| a curated fact ("this repo uses pnpm") | [memoro](https://github.com/victorandraad/memoro) | erratum refuses to be general memory |

## Install

Python 3.9+ and SQLite with FTS5 (ships with Python on most distros):

```sh
python3 -c "import sqlite3; sqlite3.connect(':memory:').execute('create virtual table t using fts5(x)'); print('FTS5 ok')"
```

```sh
git clone https://github.com/victorandraad/erratum.git
cd erratum
export PYTHONPATH="$PWD"
python3 -m erratum seed          # generic fixes and recipes (idempotent)
python3 -m unittest
```

Optional global command:

```sh
pipx install git+https://github.com/victorandraad/erratum.git
# or, in a venv: pip install git+https://github.com/victorandraad/erratum.git
```

The index name, when published, is `erratum-cli` (`erratum` was taken). The command stays
`erratum`; the import stays `import erratum`.

## Thirty seconds

```sh
erratum err "Exit code 127 /tmp/w-1/bin/runner: No such file"
erratum fix 1 "run worktree prep before the runner" --ref abc123 --test test_prep
erratum err "Exit code 1 /tmp/w-99/bin/runner: No such file"
# known fix: run worktree prep before the runner
erratum gate stub-neutro,fix-noop --base main --test-cmd "python3 -B -m unittest {testes}"
```

Signatures normalize volatile bits (paths become `/PATH`, numbers become `N`, branch names become
`<branch>`), so one fix covers past and future occurrences.

`erratum compact` only changes how history is stored: rows with the same signature collapse into
one per task (different tasks never merge), repetitions are summed and the oldest `ts` is kept.
`top` reports the same numbers before and after, FTS keeps one entry per surviving row, and fixes
stay findable. Run it with `--dry-run` first.

## Gates (`gate`)

Model-free checks on the diff between `--base` and `HEAD`:

| Gate | Fails when |
|---|---|
| `fix-noop` | the diff's tests pass even with the production code reverted: the fix does not fix, or the test always passes |
| `fix-noop` (`instrumento-morto`) | the diff's tests already fail with the fix applied: a test broken from birth proves nothing |
| `stub-neutro` | a new class meets the contract by returning a neutral constant (`[]`, `None`, `0`) from every method |
| `em-dash` | replacing a prose em dash with a comma breaks the tests (normally it fixes, commits and passes) |

Without `--test-cmd`, `fix-noop` skips instead of guessing. Real cases, with the diff and the gate's
actual output: [docs/casos.md](docs/casos.md) (Portuguese).

Portuguese command names still work. English aliases: `compact` (`compactar`), `outcome`
(`desfecho`), `effect` (`efeito`).

## Contributing

PRs welcome. Failing test first, then the implementation. No new dependency if the stdlib will do.

```sh
python3 -m unittest
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

Useful PRs: a case where `fix-noop` let a weak test through, a generic recipe agents keep
improvising, a `find` that guessed when it should `abstain`. See [CONTRIBUTING.md](CONTRIBUTING.md)
([Portuguese](CONTRIBUTING.pt.md)).

## License

[GPL-3.0](LICENSE). Use, modify, distribute. If you distribute a derivative, its code stays under
the GPL: the idea stays public. No model in the middle, no telemetry, the ledger lives on your
machine.

## Commands

Full table and the rest of the reference: [README.pt.md](README.pt.md) (Portuguese, same flags).
Hook for agents: [docs/usar-com-ia.md](docs/usar-com-ia.md).
