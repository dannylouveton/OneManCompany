# OneManCompany runner: executes employees' Claude Code sessions.
# Build from the repository root:  docker compose -f deploy/runner/compose.yaml build
FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    OMC_RUNNER_CONTAINER=1 \
    OMC_REMOTE_CONNECTORS=1

# Claude Code's shell sandbox (bubblewrap + socat) and the usual tools agents expect.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git ripgrep bubblewrap socat procps \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev && chmod -R a+rX /app

# Agents run as an unprivileged user (Claude Code refuses to skip
# permissions as root).
RUN useradd --create-home --uid 1000 omc
USER omc
# Claude Code CLI (native installer, kept up to date by `claude update`)
RUN curl -fsSL https://claude.ai/install.sh | bash \
 && mkdir -p /home/omc/.claude
ENV PATH=/home/omc/.local/bin:/app/.venv/bin:$PATH

EXPOSE 8100
CMD ["python", "-m", "onemancompany.runner", "serve", "--host", "0.0.0.0", "--port", "8100"]
