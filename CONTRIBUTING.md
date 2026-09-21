# Contributing

PRs welcome. Python 3.9+, standard library only. Failing test first, then the implementation.
License [GPL-3.0](LICENSE): distributed derivatives stay GPL.

Portuguese: [CONTRIBUTING.pt.md](CONTRIBUTING.pt.md).

```sh
python -m unittest
```

Install the hook before the first commit. It runs the `em-dash` and `stub-neutro` gates on what is
staged (details in [docs/portoes-no-commit.md](docs/portoes-no-commit.md)):

```sh
cp hooks/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## Repo privacy

`tests/test_privacidade.py` walks every versioned file (except `LICENSE`, which carries the
copyright holder by legal obligation) and fails on:

- em dashes in any file;
- generic regexes: superuser home path, internal domain, free-mail address, card id;
- **private tokens of whoever maintains the fork**, stored only as sha256. The test never contains
  the term, not even in pieces.

How to add a private term: see [CONTRIBUTING.pt.md](CONTRIBUTING.pt.md).
