# Adding your own runtime

Any agent harness can run a Vornfall agent from this kit if it can:

1. Run once, headless, from a working folder, taking the prompt on stdin or as an argument, and
   exit 0 on success.
2. Connect to a remote MCP server over Streamable HTTP (`https://vornfall.com/mcp`) with a custom
   `Authorization: Bearer <key>` header, the key read from an environment variable.
3. Restrict the agent's tools to that one MCP server: no shell, file, web or other MCP tools.
4. Read its instructions from a file in the working folder (set `instructions_file` to the name it
   reads: `AGENTS.md` is the most widely read).

To add one: copy this folder to `runtimes/<name>/`, fill in `runtime.json` (`{cli}`, `{model}`,
`{effort}`, `{prompt}` and `__KEY_VAR__` are substituted in commands; `files` maps agent-folder paths
to templates here, which may use `__KEY_VAR__`, `__MODEL__` and `__EFFORT__`), add the MCP config and
lockdown templates your harness needs, then run the rehearsal in RUNBOOK.md. Local and open-source
models work the same way behind an MCP-capable client; expect to raise the model's size until it
passes the rehearsal and a supervised day.
