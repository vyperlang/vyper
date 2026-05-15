# Contributing

See also: [docs/contributing.rst](../docs/contributing.rst) for general contribution guidelines,
[docs/style-guide.rst](../docs/style-guide.rst) for code style, naming, imports, exceptions, tests, and docs conventions.

## Commit Messages

We use squash merges for PRs. The squash commit message is the permanent record — it goes into
`git log`, changelogs, and blame. The diff shows *what* changed; the PR shows *how* it evolved.
The commit message must explain **why**.

### Format

[Conventional Commits](https://www.conventionalcommits.org/). On squash-merge, the PR title becomes the commit subject line. The PR template's "Commit message" section becomes the body.

**PR title** (becomes subject line):
```
<type>[scope]: <description>
```

**PR "Commit message" section** (becomes body):
```
<body>
```

Types: `feat`, `fix`, `refactor`, `perf`, `chore`, `release`.
Scope is **required**. Validated by CI — see [pull-request.yaml](../.github/workflows/pull-request.yaml) for the canonical list.
Current scopes: `venom`, `lang`, `codegen`, `parser`, `stdlib`, `ux`, `ir`, `test`, `docs`, `ci`, `build`, `tool`.

### Subject Line (PR title)

- Imperative, present tense ("add X" not "added X")
- ~50 chars, lowercase, no period
- Scope in brackets: `feat[venom]: add tail-merge pass`

### Formatting

Wrap body at 72 chars. Use `fmt_commit_msg.py` to format — it defaults to `commitmsg.txt` and modifies in place.

**Workflow for writing/updating the commit message in a PR:**

```bash
# 1. Write the commit message BODY to commitmsg.txt
#    Do NOT include the subject line (type[scope]: description) —
#    that comes from the PR title on squash-merge.
cat > commitmsg.txt << 'EOF'
motivation paragraph here... (see "Body" section below)

implementation paragraph here...
EOF

# 2. Format it (wraps at 72 chars, preserves lists/code blocks)
python fmt_commit_msg.py   # reads/overwrites commitmsg.txt, prints result to stdout

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

Commit messages should not be tied to a particular issue tracker. Use `GH 1234` instead of `#1234` — the `#` syntax is GitHub-specific and creates links that are meaningless outside GitHub.

### Good Example (from recent history)

PR title: `fix[venom]: fix allocation in ternary fall through`

Commit message body:
```
`Mem2Var._fix_adds` ensures `add` instructions on alloca pointers are
recognized by `BasePtrAnalysis` so it can track pointer provenance
through arithmetic. When a ternary expression merges two
pointer paths via a `phi` node, the `add` sits downstream of the phi
rather than as a direct use of the alloca — so `_fix_adds` never saw it.

The same gap existed in the caller guard: `_process_alloca_var`
only dispatched to `_fix_adds` when a direct `add` use was present,
silently skipping allocas whose only non-trivial uses were behind
phi/assign nodes.

Additionally, following phi/assign chains introduces the possibility of
cycles through loop back-edges, so add a visited set to terminate
gracefully.
```

Note: explains the *mechanism* of the bug (why it happened), not just "fixed a crash in X".

### Another Good Example

PR title: `fix[venom]: treat immutables as global allocations`

Commit message body:
```
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
- PRs are squash-merged. See [Format](#format) for how the PR title and "Commit message" section map onto the final commit.
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
