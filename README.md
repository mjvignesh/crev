# crev

> AI-powered code review using Claude Code — runs locally as a pre-commit hook. Uses your existing Claude subscription. No API key juggling.

`crev` reads your git diff, sends it to Claude via the `claude` CLI with the surrounding file context, and surfaces concrete bugs, security issues, and style problems before your code ever leaves your laptop.

**Why this matters:** other AI review tools either run in the cloud (data leaves your machine), require their own API key + billing, or charge a SaaS subscription on top. `crev` reuses Claude Code, the CLI you've probably already installed for AI-assisted coding — so reviews are billed against your existing Pro/Max plan or API account, with no extra setup.

```
$ git commit -m "add login flow"

── src/auth.py ──

  🔴 [HIGH] (security) Plaintext password comparison:23
     `password == stored` enables timing attacks. Use hmac.compare_digest.
     → Replace with `hmac.compare_digest(password.encode(), stored.encode())`
     proposed fix:
       - if password == stored:
       + if hmac.compare_digest(password.encode(), stored.encode()):

  🟡 [MEDIUM] (bug) Missing rate-limit on login endpoint:41
     The /login route has no throttling. Brute-force attacks succeed easily.
     → Wrap with @limiter.limit("5/minute") or equivalent.

──────────────────────────────────────────────────
Summary: 1 high, 1 medium
```

## Requirements

1. **`claude` CLI (Claude Code)** — install once:
   ```bash
   npm install -g @anthropic-ai/claude-code
   claude   # sign in (uses Pro/Max subscription or API key)
   ```
2. **Python 3.10+**
3. **git**

Run `crev doctor` after install to verify everything's set up.

## Install

```bash
pipx install crev          # recommended (isolated)
# or
pip install crev
```

## Quick start

```bash
cd your-repo
crev doctor                # confirm claude CLI is installed and logged in
crev init                  # creates .crev.toml + .crevignore + installs pre-commit hook

# That's it. Now every commit runs through Claude:
git add some-file.py
git commit -m "wip"        # crev runs automatically; blocks if HIGH/CRITICAL found
```

If you'd rather not install the pre-commit hook, run `crev init --no-hook` (or install it later with `crev install-hook`).

Run on demand any time:

```bash
crev                       # review staged changes
crev --all                 # review staged + unstaged
crev --files src/auth.py   # review a specific file
crev --severity high       # only show high+ findings
crev --json                # machine-readable output
crev --fix                 # interactively apply Claude's auto-fixes
crev --model opus          # override model just for this run
```

## How it works

1. `crev` runs `git diff --cached` to get your staged changes.
2. It loads the full content of each changed file (so Claude sees context, not just hunks).
3. It shells out to `claude --bare -p "..." --output-format json --max-turns 1` with a structured review prompt.
4. Claude returns JSON findings with severity, category, line numbers, and optional auto-fix diffs.
5. `crev` formats findings, applies severity filters, and exits non-zero on blocking issues.

`--bare` mode is used by default so reviews don't pick up your project's `CLAUDE.md`, MCP servers, hooks, or other local Claude Code config — that way every teammate gets the same review for the same diff.

## Authentication

`crev` doesn't manage credentials. Whatever account `claude` is signed into is what `crev` uses. To switch, run `claude` interactively and re-authenticate.

That means:
- Pro/Max subscribers: reviews count against your subscription (no extra cost)
- API users: reviews are billed to your `ANTHROPIC_API_KEY`
- Bedrock/Vertex users: works the same way Claude Code does

## Configuration

Run `crev init` to drop a `.crev.toml` in your repo:

```toml
[crev]
model = ""                       # empty = use claude CLI's default; or "opus", "sonnet", "haiku"
checks = ["bugs", "security", "style"]
min_severity = "low"             # info | low | medium | high | critical
fail_on_blocking = true          # exit 1 on high/critical findings
ignore_file = ".crevignore"
max_context_tokens = 30000
bare_mode = true                 # use claude --bare (recommended)
timeout_seconds = 180
```

Or put the same keys under `[tool.crev]` in `pyproject.toml`.

Environment overrides: `CREV_MODEL`, `CREV_MIN_SEVERITY`, `CREV_CLAUDE_BIN` (path to claude binary).

## Ignoring files

`crev init` creates a `.crevignore` with sensible defaults (build artifacts, lockfiles, generated code). Patterns follow gitignore syntax:

```
dist/
*.min.js
**/fixtures/**
*_pb2.py
```

## Disabling per-commit

```bash
git commit --no-verify   # standard git escape hatch
```

Or set `fail_on_blocking = false` in `.crev.toml` to let commits through with warnings only.

## Comparison

| Tool          | Local | OSS | Uses your Claude sub | Custom rules | Auto-fix |
|---------------|-------|-----|----------------------|--------------|----------|
| **crev**      | ✅    | ✅  | ✅                   | ✅           | ✅       |
| CodeRabbit    | ❌    | ❌  | ❌                   | ✅           | ✅       |
| Greptile      | ❌    | ❌  | ❌                   | ✅           | ❌       |
| GitHub Copilot Review | ❌ | ❌ | ❌                | ❌           | ❌       |

## Roadmap

- [ ] Custom rule files (`.crev/rules/*.md`)
- [ ] Caching by diff hash to avoid re-reviewing
- [ ] GitHub Action wrapper
- [ ] PR-comment mode (post findings as review comments)
- [ ] Multi-file refactor suggestions
- [ ] Streaming output (`--output-format stream-json`)

## Uninstall

In each repo where you ran `crev init`, remove the hook and config first:

```bash
cd your-repo
crev uninstall-hook
rm .crev.toml .crevignore
```

Then uninstall the package itself. **Important:** `cd` somewhere that doesn't have a `crev` folder nearby (like your home dir), otherwise `pipx` will mistake the package name for a path:

```bash
cd ~
pipx uninstall crev
```

To find every repo where crev was set up:

```bash
find ~ -name ".crev.toml" 2>/dev/null
```

## Security

`crev` runs entirely on your machine. The only network calls are made by the `claude` CLI itself, going to Anthropic's API. Your code never touches a third-party SaaS.

A few specific protections worth noting:

- **Auto-fix patches are sandboxed.** When you run `crev --fix`, every patch from the model is validated before being applied: absolute paths, parent-directory traversal (`../`), oversized patches, and patches with no file paths are all rejected. `git apply` is invoked with `--directory` pointing at the repo root, so even if validation missed something, git itself refuses to write outside the working tree.
- **Every fix requires explicit confirmation.** `crev` never silently applies a patch. You see the diff and answer y/n.
- **Severity & category values from the model are validated.** Unknown values are coerced to safe defaults so a malformed response can't crash the tool or bypass severity filters.
- **`CREV_CLAUDE_BIN` overrides require an executable file.** Setting it to a non-executable file is rejected, so misconfiguration can't silently invoke unexpected binaries.

## Troubleshooting

**`error: The 'claude' CLI was not found on PATH`**
Install Claude Code: `npm install -g @anthropic-ai/claude-code`. If it's installed but not on PATH, set `CREV_CLAUDE_BIN=/path/to/claude`.

**`claude CLI exited with code 1 ... not authenticated`**
Run `claude` interactively once to log in.

**Reviews are slow**
Switch to a smaller model: `crev --model haiku` or set `model = "haiku"` in `.crev.toml`.

**Reviews are inconsistent across teammates**
Make sure `bare_mode = true` (the default). Without it, `claude` loads project-local config that varies per machine.

## Contributing

PRs welcome. See `CONTRIBUTING.md`.

```bash
git clone https://github.com/mjvignesh/crev
cd crev
pip install -e ".[dev]"
pytest
```

## License

MIT
