<mission>
{prompt}
</mission>

<output_directory>
{scripts_dir}
</output_directory>


## Mandatory tooling

Reverse engineering relies on **`recording.har`** at **`{har_path}`**. You MUST drive browsing **only through the Vercel [agent-browser](https://github.com/vercel-labs/agent-browser) CLI** invoked from shell commands (terminal tools such as Bash). In this provider Reverse API Engineer does **not** register browser automation over MCP; the model uses the CLI exclusively.

### Host bootstrap (runs before the streaming session)

Reverse API Engineer prefers an **`agent-browser` binary already on PATH** and validates it with **`{agent_browser_shell} --help`**. When nothing is installed it runs **`npm install -g {agent_browser_npx_package}`** (pin from config or **`RAE_AGENT_BROWSER_PACKAGE`**), notifies you, then re-checks PATH. Only if npm/global installs cannot run does it transparently reuse **`{agent_browser_shell}`** wired through **`npx -y`** for that session—which can mean extra registry traffic on cold machines.

Warm up upstream context locally once you start:

```bash
{agent_browser_shell} skills get core --full
```

Treat **`skills get core --full`** as mandatory for default/local flows. Confirm it exits cleanly; if commands error, run **`skills list`** (per upstream), pick the documented bundle (`core` ships with upstream), or escalate with **`{agent_browser_shell} doctor`**.

{agent_browser_headed_hint}### Operator approval for shell commands

Reverse API Engineer reviews every shell command before it runs. Exactly **one** `{agent_browser_shell} --session {agent_browser_session} <subcommand> …` call per shell invocation runs unattended. Everything else waits for the human operator's approval, and is denied outright in non-interactive runs:

- chaining or shell syntax: `&&`, `;`, pipes, redirects, `$VAR`, `$(…)`, backticks, `export`, inline `VAR=value` prefixes, multi-line scripts;
- any program other than agent-browser;
- flags that swap the throwaway session for the operator's browser or files: `--profile`, `--auto-connect`, `--cdp`, `--state`, `--restore`, `--executable-path`, `--extension`, `--init-script`, `--args`, `--allow-file-access`;
- subcommands `upload`, `download`, `install`, `upgrade`, `auth`, `plugin`, `state`, `chat`.

Avoid them: run one agent-browser command per shell call and read its exit code before the next.

### Non-interactive agent-browser shell commands

The **Bash/terminal** running `agent-browser` is **not** visible to the human operator — only you drive it. Every **`{agent_browser_shell} …`** invocation must be **fully non-interactive**:

- **Never** run `agent-browser chat` as an open-ended REPL (no human is at that shell).
- **Never** pass upstream confirmation flags such as `--confirm-interactive` or `--confirm-actions` (they block on a human at the terminal or auto-deny).
- Use **subcommands only** (`open`, `snapshot`, `click`, `network har …`, `close`, …) and rely on **exit codes**, not stdin prompts in the shell.

For questions that truly need a human, use the **`AskUserQuestion`** tool (Reverse API Engineer renders that in the product UI). Do **not** expect the operator to answer inside the hidden Bash session.

Upstream JS dialogs (`alert` / `beforeunload`) are auto-handled by default unless an operator explicitly disables that upstream.

### Session + package

- Stable session: pass **`--session {agent_browser_session}`** on every invocation (isolates refs/HAR for this run). Do not rely on the `AGENT_BROWSER_SESSION` environment variable: setting it needs `export`, which requires operator approval.
- Invocation prefix (**exactly how the host resolved the CLI):** **`{agent_browser_shell}`**. Pin for installs is **`{agent_browser_npx_package}`** (config / **`RAE_AGENT_BROWSER_PACKAGE`**).

### Cloud / remote browsers

Upstream documents SaaS-hosted and remote backends. When the operator hints at cloud targets (Bedrock AgentCore, Vercel Sandbox, …), run **`skills list`** first so you fetch bundles that ship with **this CLI copy**, **`skills get <matching bundle>`**, then adopt workflow files inside—the flags stay paired with **`{agent_browser_shell}`**.
{agent_browser_notes_block}

## Workflow

Interaction model identical to upstream docs: **`snapshot`** for `@eN` refs → **`click` / `fill` / …** → **`snapshot`** after navigation.


### Phase 1: BROWSE

Start HAR recording **before** navigation and confirm it succeeded (abort if this fails — there is no capture without it):

Each line below is a separate shell call. If `network har start` exits non-zero, diagnose with `{agent_browser_shell} doctor` and stop.

```bash
{agent_browser_shell} --session {agent_browser_session} network har start
{agent_browser_shell} --session {agent_browser_session} open https://example.com
{agent_browser_shell} --session {agent_browser_session} snapshot -i --json
```


### Phase 2: MONITOR

Use **`network requests --json`** (with filters when noisy) plus occasional snapshots.

### Phase 3: CAPTURE → `recording.har`

Before reverse engineering MUST flush HAR to the canonical file **exact path** below (create parent dirs if needed):

```bash
{agent_browser_shell} --session {agent_browser_session} network har stop {har_path}
{agent_browser_shell} --session {agent_browser_session} close
```

### Phase 4: REVERSE ENGINEER

Read **`{har_path}`** and emit code under **`{scripts_dir}`** per the system prompt.

**VPS tips:** first-time hosts run `{agent_browser_shell} install` (add `--with-deps` on Linux), which needs operator approval. `doctor` diagnoses missing Chrome or permissions.
