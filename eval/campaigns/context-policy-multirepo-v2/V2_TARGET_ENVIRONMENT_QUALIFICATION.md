# V2 Target Environment Qualification

Status: qualified for proposed V2 review; this document does not freeze V2.

Qualification copies were created outside the canonical benchmark clones at:

```text
/Users/teobun/arc-study/qualification-v2-20260912/{click,httpx,python-dotenv}
```

The canonical clones under `/Users/teobun/arc-study/repos/` stayed unchanged,
clean, and at the frozen commits throughout this work. No benchmark task,
hidden test, or provider inference was used for target-environment
qualification.

## Frozen source identities

| Repository | Commit |
| --- | --- |
| Click | `6aabf099bfdd4c1e75fe8d0e0d4241372b988ab1` |
| HTTPX | `b5addb64f0161ff6bfe94c124ef76f6a1fba5254` |
| python-dotenv | `a00cb2eed0704cd6d2071b2004c37e95ccc86ee5` |

## Qualified harnesses

### Click — `click-macos-py310-uv-locked-tox-v1`

Source inspection found `pyproject.toml`, `uv.lock`, and CI's locked
`uv`/`tox` invocation. The disposable environment used CPython 3.10.7:

```text
uv venv --python /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 .venv
uv sync --locked --no-default-groups --group dev
TOX_ENV=py3.10 uv run --locked --no-default-groups --group dev tox run -e py3.10
```

Result: `2058 passed, 25 skipped, 31000 deselected, 1 xfailed`.

### HTTPX — `httpx-macos-py311-requirements-resourcewarning-filter-v1`

Source inspection found `requirements.txt` and the repository scripts. The
declared requirements were installed in a disposable CPython 3.11.16
environment, including editable installation of HTTPX. The unfiltered macOS
run reproducibly failed one `tests/test_timeouts.py::test_write_timeout[trio]`
case because Trio's async-generator teardown `ResourceWarning` is converted
to a pytest unraisable-warning failure (`1417 passed, 1 failed`). The fixed
macOS harness records that platform behavior explicitly and uses:

```text
venv311/bin/python -m pytest -q -W ignore::ResourceWarning
```

Result: `1418 passed, 1 skipped`.

This warning filter is a harness-level platform accommodation, not a source
change and not a hidden-test exemption. A Linux CI/container qualification
would be preferable for a future environment refresh; Docker was unavailable
on this host during this qualification.

### python-dotenv — `python-dotenv-macos-py310-gnu-printenv-v1`

Source inspection found `requirements.txt`, `tox.ini`, and the CI workflow.
The disposable environment used CPython 3.10.7, installed the declared
requirements, and installed the candidate editable. The repository's CLI
tests invoke `dotenv` and expect GNU `printenv --version`; macOS's BSD
`/usr/bin/printenv` is incompatible, so Homebrew GNU coreutils was installed
and the harness places both the candidate venv and GNU `gnubin` first on
`PATH`:

```text
PATH="$PWD/venv/bin:/opt/homebrew/opt/coreutils/libexec/gnubin:$PATH" \
  venv/bin/python -m pytest -q
```

Result: `255 passed, 28 warnings`.

## Candidate-worktree import proof

Each disposable clone received only an untracked marker module and a
qualification-only pytest file. The marker was imported by the test process
and its resolved `__file__` was asserted to be below the candidate clone:

```text
click:          1 passed
httpx:          1 passed
python-dotenv:  1 passed
```

This proves the environment installs/imports the candidate worktree rather
than the canonical frozen clone. The marker and qualification files are not
part of any benchmark repository or V2 commit.

## V2 contract consequence

The original shared `python -m pytest -q` command is not retained as a
cross-repository assumption. V2 records the three fixed repository-specific
harnesses in `campaign_contract.json`; treatment, task sequence, budgets,
repetitions, repositories, and hidden benchmark digests remain unchanged.
