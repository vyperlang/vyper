# Contributing

See also: [docs/contributing.rst](../docs/contributing.rst) for general contribution guidelines,
[docs/style-guide.rst](../docs/style-guide.rst) for code style, naming, imports, exceptions, tests, and docs conventions.

## Commit Messages

We use squash merges for PRs. The squash commit message is the permanent record — it goes into
`git log`, changelogs, and blame. The diff shows *what* changed; the PR shows *how* it evolved.
The commit message must explain **why**.

### Format

[Conventional Commits](https://www.conventionalcommits.org/):

```
<type>[scope]: <description>

<body>
```

Types: `feat`, `fix`, `refactor`, `perf`, `chore`, `release`.
Scope is **required**. Validated by CI — see [pull-request.yaml](../.github/workflows/pull-request.yaml) for the canonical list.
Current scopes: `venom`, `lang`, `codegen`, `parser`, `stdlib`, `ux`, `ir`, `test`, `docs`, `ci`, `build`, `tool`.

### Subject Line

- Imperative, present tense ("add X" not "added X")
- ~50 chars, lowercase, no period
- Scope in brackets: `feat[venom]: add tail-merge pass`

### Formatting

Wrap body at 72 chars. Use `fmt_commit_msg.py` to format — it defaults to `commitmsg.txt` and modifies in place.

**Workflow for writing/updating the commit message in a PR:**

```bash
# 1. Write the raw commit message (body) to commitmsg.txt
cat > commitmsg.txt << 'EOF'
motivation paragraph here... (see "Body" section below)

implementation paragraph here...
EOF

# 2. Format it (wraps at 72 chars, preserves lists/code blocks)
python fmt_commit_msg.py   # reads and overwrites commitmsg.txt

# 3. Get the current PR body
gh pr view <N> --json body -q .body > /tmp/pr_body.md

# 4. Replace the ```-fenced block under "### Commit message" in /tmp/pr_body.md
#    with the contents of commitmsg.txt (use Edit tool or sed)

# 5. Upload
gh pr edit <N> --body-file /tmp/pr_body.md
```

Do NOT write to `/tmp` or other locations and manually copy-paste — the script is designed to work on `commitmsg.txt` in the repo root. The file is gitignored.

### Body — Explain Why and Context

The body is the most important part. It should answer:

- **What problem does this solve?** What was broken, missing, or suboptimal?
- **Why this approach?** What alternatives were considered? What tradeoffs were made?
- **What are the non-obvious consequences?** Side effects, invariants established or broken, perf impact?

Don't enumerate every file touched or mechanically list what each function does — that's the diff.
Do explain the *reasoning* behind structural decisions, the bug mechanism, or the design rationale.

### Good Example (from recent history)

```
fix[venom]: fix allocation in ternary fall through (#4846)

`Mem2Var._fix_adds` converts `add` instructions on alloca pointers into
`gep` (get-element-pointer) so that `BasePtrAnalysis` can track pointer
provenance through arithmetic. When a ternary expression merges two
pointer paths via a `phi` node, the `add` sits downstream of the phi
rather than as a direct use of the alloca — so `_fix_adds` never saw it.

The same gap existed in the caller guards: `_process_alloca_var` and
`_process_palloca_var` only dispatched to `_fix_adds` when a direct
`add` use was present, silently skipping allocas whose only non-trivial
uses were behind phi/assign nodes.

Additionally, following phi/assign chains introduces the possibility of
cycles through loop back-edges, so add a visited set to terminate
gracefully.
```

Note: explains the *mechanism* of the bug (why it happened), not just "fixed a crash in X".

### Another Good Example

```
fix[venom]: treat immutables as global allocations (#4839)

the immutables region (allocated at position 0 during deploy) was not
reserved across function boundaries. when `ConcretizeMemLocPass` ran for
internal functions, it started with an empty reserved set, allowing
function-local buffers to overlap position 0 and clobber immutable
values.

add a `global_allocation` set to `MemoryAllocator` that persists across
per-function allocation rounds. register the immutables alloca as global
at IR conversion time.
```

Note: first paragraph is pure *why* (the bug mechanism). Second paragraph is a concise *what* — just enough to orient a reader, not a line-by-line walkthrough.

### Anti-Patterns

- ❌ "Fix bug" / "Update code" — says nothing
- ❌ Listing every changed file or function — that's the diff
- ❌ Only *what* with no *why* — "add field X to class Y, call Z in function W"
- ❌ Copying the PR description verbatim (PR descriptions track evolution and review; commit messages are the final, distilled record)

## Pull Requests

- Fork from `master`
- Write tests for new features; place them under `tests/`
- Larger changes: discuss in Discord `#compiler-dev` first
- PRs are squash-merged — the PR title becomes the commit subject. Keep PR title and commit message title in sync.
- Work from your individual fork. PRs target `vyperlang/vyper` upstream:
  ```bash
  gh pr create --repo vyperlang/vyper --base master --head <fork-owner>:<branch>
  ```
- Follow the PR template (`.github/PULL_REQUEST_TEMPLATE.md`): What/How/Verify/Commit message/Changelog
- To edit PR or issue bodies:
  ```bash
  gh pr view <N> --json body -q .body > /tmp/pr_body.md  # get current text
  # edit /tmp/pr_body.md with Edit tool
  gh pr edit <N> --body-file /tmp/pr_body.md              # upload
  ```
- **NEVER rebase and force-push a branch that is already under review.** Rebasing destroys review context (inline comments become orphaned, diff history is lost). If you need to pull in upstream changes on a PR branch, **merge `master` into your branch**.

## Keeping Docs Current

If anything you have done requires content updates to any files in `skills/` or `CLAUDE.md`, update them as part of the same PR.

## Git Quick Reference

```bash
# ALWAYS check what's pushed before amending.
# Only amend commits not yet pushed
git log --oneline origin/<branch>..HEAD

# undo a bad amend or commit (find the pre-amend state in reflog)
git reflog -10
git reset --mixed <good-sha>     # unstages changes, keeps working tree
git add <files> && git commit    # recommit cleanly

# sync with upstream on a branch under review (NEVER rebase+force-push)
git merge master

# interactive rebase doesn't work in non-interactive shells — use reset+cherry-pick instead
git stash                        # protect uncommitted work
git reset --hard <target>
git cherry-pick <commits>        # resolve conflicts manually
git stash pop
```

## Code Style Summary

Full details in [docs/style-guide.rst](../docs/style-guide.rst). Highlights:

- PEP 8, 100 char line length, enforced by `make lint`
- Type classes end in `T` (`IntegerT`, `ModuleT`)
- Method naming: `get_` (pure), `fetch_` (side effects), `build_` (creates new), `validate_` (raises or returns None)
- No builtin exceptions — use custom exception classes from `vyper/exceptions.py`
- f-strings for string formatting
- Import modules, not objects (avoids circular deps)
- Cross-package imports must not reach beyond root namespace of target package
- Tests: no mocking, no interdependence (xdist parallel), parametrize where logical
