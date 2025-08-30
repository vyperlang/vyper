Vyper Dev Environment: Virtualenv + Tests

Quick TL;DR
- Use the existing virtualenv: `. .venv/bin/activate` and run tests: `pytest` or `./quicktest.sh`.
- If creating fresh: `python3.12 -m venv .venv && . .venv/bin/activate && pip -U pip wheel setuptools && pip install -e .[test]`.

Supported Python
- Project supports Python 3.10–3.13. Prefer 3.12 for parity with CI.

System Prereqs (Linux)
- git (setuptools-scm reads the commit hash)
- build tools for any wheels that don’t have prebuilt binaries: `build-essential` (Debian/Ubuntu). Optional: `pkg-config`.
- If network-restricted in the CLI sandbox, request approval for network before running `pip install`.

Set Up From Scratch
1) Create venv
   - `python3.12 -m venv .venv`
   - `source .venv/bin/activate`
   - Upgrade basics: `pip install -U pip wheel setuptools`

2) Install package + test deps
   - `pip install -e .[test]`
     Includes: pytest, xdist, instafail, split, hypothesis[lark], py-evm, eth-account, hexbytes, pyrevm, etc.
   - If setuptools-scm missing (rare): `pip install setuptools_scm`

3) Verify compiler import
   - `python -c "import vyper; print(vyper.__version__)"`
   - If you see `ModuleNotFoundError: No module named 'Crypto'`, install `pycryptodome` (part of install_requires):
     `pip install pycryptodome`

Run Tests
- Full suite: `pytest` (parallel by default via xdist) or `./quicktest.sh` (bails on first failure).
- Faster dev loop: `./quicktest.sh -m "not fuzzing" -n0`
- Single test file: `pytest tests/functional/codegen/features/test_flag_iteration_type.py -q`
- Single test: `pytest tests/.../test_flag_iteration_type.py::test_iterate_over_flag_type -q`

Notes
- The repo writes commit hash into `vyper/vyper_git_commithash.txt` during editable install; ensure `git` is available.
- Some optional tests are marked `hevm`; they may require external tooling and are not run by default.
- If running inside the Codex CLI with network restrictions, most installs require network; ask for approval when needed.

Known Pitfalls
- Using system Python (e.g., 3.13) without the venv can miss dependencies (e.g., `Crypto`). Always activate `.venv`.
- If pip tries to build wheels from source and fails, install system build tools and retry (`build-essential`, `pkg-config`).

