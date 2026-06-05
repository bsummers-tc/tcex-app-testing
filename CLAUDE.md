# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is **tcex-app-testing** (the **TcEx App Testing Framework**, version 1.x) — the ThreatConnect
Exchange App **testing** framework. It is a Python **library/SDK** that provides functionality for
using **pytest** to test ThreatConnect Apps (Playbook, Job, Service, and External Apps): profile
management, input staging, output validation, a local key-value store, mock services, and a `pytest`
runner/CLI. It is not a web service; there is no Docker/DB/frontend stack.

- **Language**: Python 3.11+ (the local `.python-version` pins 3.13)
- **Models**: Pydantic **v1** (the codebase pins `pydantic<2.0.0`)
- **Packaging / envs**: managed with **uv** (`uv.lock` + `.venv` at the repo root). This is a plain
  project, **not** a `uv` workspace; the build backend is **setuptools**.
- **Type checker**: **ty** (Astral) (config in root `[tool.ty]`; run via the `ty` pre-commit hook)
- **Linter / formatter**: **ruff** (100-char line length)
- **CLI entry point**: `tcex-app-test = "tcex_app_testing.cli.cli:app"` (typer-based)

The repo root is exposed to Bash commands as the **`$PROJECT_ROOT`** environment variable, defined
per-machine in `.claude/settings.local.json` (see "Tool Invocation — Absolute Paths Only" →
"Per-machine setup"). The venv is always at `$PROJECT_ROOT/.venv`. In documentation and in paths passed
to Read/Write/Edit it is written as the **`<root>`** placeholder, since those tools do not expand
environment variables.

## Repository & Branching

This local repo is a **fork**. `origin` points at the fork; `upstream` is the ThreatConnect repo.

- **All work happens directly on the `main` branch** — `main` is the working branch here, not a
  protected trunk. Do **not** create feature branches; commit changes to `main` unless the operator
  has **manually** switched to another branch first.
- Claude Code must **never change branches itself** (enforced by `enforce_no_branch_change.sh`). If a
  branch change is genuinely needed, the human operator performs it; subsequent work then targets
  whatever branch is currently checked out.
- The usual "branch before committing on the default branch" convention does **not** apply to this
  fork — commits to `main` are expected (when the operator makes them — see below).

### Commits are the operator's job — Claude never commits

**Claude Code must NEVER create a git commit.** ALL commits — in the parent repo **and** in every
submodule — are made by the **human operator**. This is enforced by `enforce_no_commit.sh` (a
PreToolUse hook) and a `Bash(git commit:*)` deny rule; both block `git commit` in any form
(`-m`, `-a`, `--amend`, `git -C <submodule> commit`, after `&&`/pipes, …) with no override.

Claude's role stops at **preparing** the change:

- Make the edits, then `git add` the relevant paths (staging is allowed).
- Run `git status` / `git diff --cached` to show exactly what is ready.
- **Report** what is staged and the suggested commit message(s); the operator runs `git commit`.
- The same applies to submodule changes: stage inside the submodule and describe the two-step
  commit + pointer bump, but let the operator perform both commits.

## Git Submodules

Several parts of `tcex_app_testing/` are **independent git submodules**, each with its own repository
and its own `pyproject.toml`:

| Submodule path | Upstream repo | Notes |
|---|---|---|
| `tcex_app_testing/app/config` | `tcex-app-config` | install.json / app-spec models + transform builder |
| `tcex_app_testing/app/key_value_store` | `tcex-app-key-value-store` | KV store (redis / fakeredis) |
| `tcex_app_testing/app/playbook` | `tcex-app-playbook` | playbook create/read |
| `tcex_app_testing/pleb` | `tcex-pleb` | shared primitives (cached_property, scoped_property, registry) |
| `tcex_app_testing/requests_tc` | `tcex-requests-tc` | ThreatConnect session + auth |
| `tcex_app_testing/util` | `tcex-util` | general utilities |

**Editing a submodule is a two-step commit:** commit the change **inside the submodule repo first**,
then bump the submodule pointer in the parent repo. Never assume a parent-repo commit captures
submodule edits. A single logical change can therefore span the parent repo and one or more
submodules.

## Package Layout — `tcex_app_testing/`

There is **no generated code** in this project (no V3 API client, no code generator). All Python
under `tcex_app_testing/` is hand-written. Key areas:

| Area | Purpose |
|---|---|
| `cli/` | typer CLI (`tcex-app-test`) — create/update/run test profiles |
| `profile/` | test-profile models, interactive builder, migration |
| `test_case/` | pytest `TestCase` base classes (playbook / service / job / trigger) |
| `stager/` | stage inputs/data (KV store, threatconnect, env) before a run |
| `validator/` | validate App outputs (ABC + concrete validators) |
| `render/` | rich-based output rendering for the runner |
| `services/` | mock services for Service-App testing |
| `input/`, `config_model/`, `env_store/`, `logger/`, `registry.py` | framework plumbing |
| `app/`, `pleb/`, `requests_tc/`, `util/` | submodules (see table above) |
| `templates/` | Mako `*.tpl` templates (packaged data) |

## Development Commands

Dependencies are managed with **uv**. The workspace root holds `uv.lock` and `.venv`; the root
`pyproject.toml` declares runtime dependencies in `[project.dependencies]` and a single **dev**
dependency group in `[dependency-groups]`. Test tooling (`pytest`, `pytest-xdist`, `deepdiff`,
`fakeredis`, …) ships as **runtime** dependencies because the framework *is* a testing tool — there
is no separate `test` group.

```bash
# Sync the venv to the lock file (runtime + dev)
uv sync --group dev

# Code quality (always use the venv's absolute binary paths — see Tool Invocation)
$PROJECT_ROOT/.venv/bin/ruff check .
$PROJECT_ROOT/.venv/bin/ruff format .
$PROJECT_ROOT/.venv/bin/ty check
$PROJECT_ROOT/.venv/bin/pre-commit run --all-files

# Tests (pytest)
$PROJECT_ROOT/.venv/bin/pytest
```

> `ty`, `ruff`, and `ruff-format` each run **once over the whole project** as `local` system hooks
> (`pass_filenames: false`, `types_or` including `directory`). The tools discover and descend into the
> nested git submodules themselves, applying each submodule's own `pyproject.toml` — so there are no
> separate per-submodule hooks. An `osv-scanner` hook scans `uv.lock` for dependency CVEs. Always run
> `pre-commit run --all-files` before considering a change done.

**Managing dependencies:**

```bash
# Add a runtime dependency (lands in [project.dependencies])
uv add <package>

# Add a dev-only tool (root [dependency-groups] dev)
uv add --dev <package>

# Regenerate the lock file / sync
uv lock
uv sync --group dev
```

- **Dev tooling** (bandit, pre-commit, pyupgrade, ruff, ty) lives in the **root**
  `pyproject.toml` under `[dependency-groups]` (`dev`).
- **Runtime deps** (including pytest and friends) live in `[project.dependencies]`.
- `uv` may be invoked by bare name (it lives on `PATH` and uses multi-word subcommands).

## Tool Invocation — Absolute Paths Only

**Rule:** every tool invocation MUST use an absolute binary path; paths must **not** be resolved by
runtime *command substitution*. The repo root is provided as the **`$PROJECT_ROOT`** environment
variable (injected from `.claude/settings.local.json` — see "Per-machine setup" below); use it directly
in shell commands as `$PROJECT_ROOT/.venv/bin/…`. `$PROJECT_ROOT` is a **static, settings-injected
variable** — it is explicitly allowed and is **not** dynamic resolution. What remains forbidden is
resolving paths at runtime via `$(git rev-parse …)`, `$(pwd)`, `$(realpath …)`, `$(readlink …)`,
`$(cd …)`, `$HOME`, or `source .venv/bin/activate`. In documentation and in paths passed to
Read/Write/Edit (which do **not** expand environment variables), use the `<root>` placeholder or a
repo-root-relative path instead — never `$PROJECT_ROOT` there.

#### Per-machine setup (one time, per clone)

`$PROJECT_ROOT` is **not** committed (it would leak an absolute home path). Each machine sets it once in
the **untracked** `.claude/settings.local.json`, whose `env` block Claude Code injects into the Bash
tool environment:

```json
{
  "env": {
    "PROJECT_ROOT": "/absolute/path/to/your/clone/of/tcex-app-testing-1.0"
  }
}
```

Then **restart Claude Code** so the new `env` is loaded (environment changes do not take effect until a
restart). Shared, committed config (hooks, permissions, default agent) lives in `.claude/settings.json`;
`.claude/settings.local.json` is gitignored and holds only this machine-specific `PROJECT_ROOT`. Note
that `$CLAUDE_PROJECT_DIR` is populated only inside hook scripts, **not** in the normal Bash tool
environment — do not use it in command examples; use `$PROJECT_ROOT`.

Three `PreToolUse` hooks (in `.claude/scripts/`) enforce this — treat them as hard rules:

- `enforce_no_dynamic_paths.sh` (Bash) — blocks commands containing path-resolving substitutions:
  `$(git …)`, `$(pwd)`, `$(realpath …)`, `$(readlink …)`, `$(cd … )` (and the backtick forms).
- `enforce_pinned_paths.sh` (Bash) — blocks **bare-name** invocations of standard system utilities;
  use the absolute path instead. It checks **every** command segment (split on `| || && ; |&`), so a
  bare name *after* a pipe is blocked too.
- `enforce_us_spelling.sh` (Write/Edit/NotebookEdit) — blocks British (en-GB) spellings in written
  content.

Two more `PreToolUse` hooks guard git state: `enforce_no_branch_change.sh` and `enforce_no_commit.sh`
(see Repository & Branching).

### Python / venv tools (always absolute `.venv/bin/…`)

```bash
# CORRECT
$PROJECT_ROOT/.venv/bin/python -c "..."
$PROJECT_ROOT/.venv/bin/pytest tests/profile
$PROJECT_ROOT/.venv/bin/ruff check tcex_app_testing/util/code_operation.py
$PROJECT_ROOT/.venv/bin/ty check

# WRONG — re-prompts for every variant / blocked by hooks
cd <root> && .venv/bin/pytest
source .venv/bin/activate && python ...
python3 -c "..."
.venv/bin/pytest          # relative
```

Pass **absolute file paths as arguments**; do not `cd` first.

### System utilities — pinned to Homebrew GNU paths

This project standardizes on the **Homebrew GNU** builds of the standard utilities (coreutils, grep,
gnu-sed, findutils, gawk, gnu-tar, diffutils) in preference to the native macOS BSD tools.
`enforce_pinned_paths.sh` rejects bare-name invocations of these utilities and tells you the exact
absolute path to use. The pinned utilities and their paths:

| Tool(s) | Pinned path prefix |
|---|---|
| `cat head tail sort uniq wc cut tr ls cp mv rm mkdir chmod touch ln stat env date basename dirname tee echo printf du` | `/opt/homebrew/opt/coreutils/libexec/gnubin/` |
| `grep` | `/opt/homebrew/opt/grep/libexec/gnubin/` |
| `find xargs` | `/opt/homebrew/opt/findutils/libexec/gnubin/` |
| `sed` | `/opt/homebrew/opt/gnu-sed/libexec/gnubin/` |
| `awk` | `/opt/homebrew/opt/gawk/libexec/gnubin/` |
| `tar` | `/opt/homebrew/opt/gnu-tar/libexec/gnubin/` |
| `diff` | `/opt/homebrew/opt/diffutils/bin/` |
| `gzip gunzip zcat jq wget` | `/opt/homebrew/bin/` |
| `file` | `/usr/bin/` (no GNU build installed — stays native) |

The hook's `PINNED` map and the `settings.local.json` allowlist are the source of truth — keep all
three in sync. Examples:

```bash
# CORRECT — Homebrew GNU absolute paths
/opt/homebrew/opt/grep/libexec/gnubin/grep -r "pattern" tcex_app_testing/util
/opt/homebrew/opt/findutils/libexec/gnubin/find tcex_app_testing -name "*.py" -type f \
  | /opt/homebrew/opt/findutils/libexec/gnubin/xargs /opt/homebrew/opt/grep/libexec/gnubin/grep "foo"

# WRONG — bare names; the hook blocks with a corrective message naming the exact path
grep -r "pattern" .
find . -name "*.py"
```

> Note: `git`, `docker`, and `uv` are not pinned (multi-word subcommands have their own rules);
> `curl` and `file` stay native (`/usr/bin/`).

## Code Standards

### Style and Language Conventions
- **Spelling**: strictly American English (US) for all natural-language output, code comments, and
  docs. The `enforce_us_spelling.sh` hook blocks en-GB variants.
- Prefer `-ize` over `-ise`, `-or` over `-our`, `-er` over `-re`, single `l` over `ll`
  (e.g. "initialize", "color", "center", "canceled").

### Python
- **Formatter / linter**: ruff, 100-char line length, single-quote style, config in root
  `[tool.ruff]`.
- **Type hints**: required; checked with **ty** (config in root `[tool.ty]`). The `tests/` tree is
  excluded (`[tool.ty.src]`).
- **Type-checker suppressions**: ty uses `# type: ignore` (blanket, PEP 484) and
  `# ty: ignore[<rule>]` (targeted, with the specific ty rule name). Prefer a real type fix; use a
  targeted suppression only when the code is correct but ty cannot infer it. **Pyright-style codes
  (`# type: ignore[reportXxx]`) do not work in ty** — convert any you encounter.
- **Docstrings**: Google style. **Imports**: organized by isort.
- **pydantic v1** patterns throughout (`validator`, `ModelField`, `update_forward_refs`, etc.).

### Scripts CLI Standard — typer + rich, dry-run by default
Every operator-facing standalone script uses **typer** (CLI) + **rich** (output); mutating scripts
are **dry-run by default — pass `--commit` to write** (no `--dry-run`, no `--yes`). `temp_*` helpers
are exempt from the full standard. **All standalone scripts are authored by the
`python-script-specialist` agent** (see Agents).

### Bandit `# nosec` placement
The suppressor must sit on the **exact line** bandit flags, not a parent call. Always include the
specific test id and a justification, e.g. `subprocess.run(cmd)  # nosec B603 — args are static`.

### Shell / Bash
- **Never use `find -exec`** — pipe through `xargs` instead (`-exec` spawns a subprocess per match):
  ```bash
  /opt/homebrew/opt/findutils/libexec/gnubin/find tcex_app_testing -name "*.pyc" \
    | /opt/homebrew/opt/findutils/libexec/gnubin/xargs /opt/homebrew/opt/coreutils/libexec/gnubin/rm -f
  ```
  For paths with spaces, use `-print0` / `-0`.

## Testing

- The configured `testpaths = ["tests"]`; the test tree mirrors the package: `tests/<area>/`
  (e.g. `tests/profile`, `tests/validator`, `tests/stager`, `tests/app`, `tests/requests_tc`,
  `tests/util`, `tests/pleb`). Create the area dir when adding the first test for an area.
- pytest, pytest-xdist, deepdiff, and fakeredis are **runtime** dependencies, so `.venv/bin/pytest`
  is available after `uv sync`.
- Redis-backed code is tested with **fakeredis**; structural comparisons use **deepdiff**.

```bash
$PROJECT_ROOT/.venv/bin/pytest                  # all
$PROJECT_ROOT/.venv/bin/pytest tests/profile    # one area
$PROJECT_ROOT/.venv/bin/pytest -k "test_name"   # by pattern
```

## Agents

This project uses an orchestrator + specialist subagents (in `.claude/agents/`). The default agent is
`tcex-orchestrator` (set in `.claude/settings.local.json`).

| Agent | Use for |
|---|---|
| `tcex-orchestrator` | Analyzes the request, gathers context, writes a plan when required, delegates to specialists, then runs the security gate and reports. Does not write code itself. |
| `python-engineer` | **All** updates to the framework code under `tcex_app_testing/` (incl. submodules): models, framework logic, bug fixes, refactors, ty (type-checker) fixes, dependency changes. Not scripts, not tests. |
| `python-test-engineer` | **All** pytest test cases under `tests/`. Does not modify source. |
| `python-script-specialist` | **Sole author** of standalone scripts (typer + rich, dry-run/`--commit`). Writes to `.claude/scripts/`. |
| `python-security-auditor` | **Hard security gate** — runs after every code/test/script change; HIGH/critical findings block "done" until fixed. |

## One-Off Scripts (`.claude/scripts/`)

All standalone scripts are authored by `python-script-specialist`. Agent-written helpers live in
`.claude/scripts/` (alongside the `enforce_*.sh` PreToolUse hooks). A genuine one- or two-line `-c`
invocation for ad-hoc context-gathering is fine and does not need delegation. Python scripts must use
the venv's absolute `python` path.

| Script type | Prefix | Example |
|---|---|---|
| Reusable | _(none)_ | `audit_profile_fields.py` |
| Throwaway | `temp_` | `temp_check_counts.py` |

`temp_*` files are gitignored; reusable scripts are committed with the session.
