# OneManCompany runner (Docker)

The control plane (web UI, secrets, API relay, approvals) stays where it is.
Employees' Claude Code sessions run in this container instead of on the
control plane's machine. The container only sees the company folder; API keys
and connector tokens never enter it.

## The work machine

The image is a full workstation: Python 3.12 + uv, Node 22 (npm, pnpm, yarn),
Bun, git + GitHub CLI, build tools, ripgrep/fd/jq/yq, ffmpeg, ImageMagick,
Poppler, Ghostscript, qpdf, Pandoc, LibreOffice (headless), SQLite /
PostgreSQL / MySQL / Redis clients, Playwright + Chromium. Agents can install
more for themselves (npm -g, pip --user, uv tool); their home folder is a
persistent volume.

Not there by design: your personal files, browser sessions, Keychain, SSH
keys and Mac apps.

## Set up (on the control plane machine)

```bash
# 1. Generate the runner files (--enable also points the control plane at it)
uv run python -m onemancompany.runner setup-docker --enable

# 2. Give the runner its own Claude Code login (subscription token)
claude setup-token          # copy the token it prints
#    then put it in deploy/runner/claude.env:  CLAUDE_CODE_OAUTH_TOKEN=...

# 3. Build and start
docker compose -f deploy/runner/compose.yaml -f deploy/runner/compose.override.yaml up -d --build

# 4. Restart OneManCompany: new sessions now run in the container
```

To go back to local execution, remove `runner:` from `config.yaml` and restart.

## What stays out of the container

- The company `.env` (provider keys, API keys, connector tokens): replaced
  by `secrets.env`, which only holds the runner token and the signing key.
- API keys: used by the control plane's relay (`api_request`).
- Connector tokens: the runner's launcher asks the control plane for a
  connector's spec per employee, signed; only granted connectors are served.
- Your home folder, source code and other projects.
