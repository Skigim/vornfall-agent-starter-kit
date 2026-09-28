# Codex CLI profile (untested)

This profile follows the Codex CLI documentation but has not passed the kit's launch rehearsal.
Before running an agent unattended with it:

1. Run `codex exec --help` and confirm `--sandbox`, `-m`, `-c` and reading the prompt from `-` (stdin).
2. Confirm the MCP override keys (`mcp_servers.<name>.url`, `bearer_token_env_var`) for your version.
3. Confirm the agent sees only the Vornfall tools: run the rehearsal in RUNBOOK.md, step "Check the
   runtime sees only the game".
4. When it passes, set `"tested": true` in `runtime.json`.
