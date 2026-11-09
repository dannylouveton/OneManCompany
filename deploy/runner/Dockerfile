# OneManCompany runner: employees' work machine.
# A full developer workstation (like a well-equipped Mac), without the CEO's
# personal files, accounts or secrets.
# Build from the repository root:
#   docker compose -f deploy/runner/compose.yaml -f deploy/runner/compose.override.yaml build
FROM python:3.12-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    TZ=Europe/Paris \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    OMC_RUNNER_CONTAINER=1 \
    OMC_REMOTE_CONNECTORS=1

# Everyday tools: shell sandbox (bubblewrap + socat), search, JSON, media,
# documents, databases, archives, editors.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      bubblewrap socat procps tzdata \
      git git-lfs openssh-client curl wget ca-certificates gnupg \
      ripgrep fd-find jq yq tree less nano vim-tiny file rsync \
      zip unzip p7zip-full xz-utils \
      build-essential pkg-config cmake \
      ffmpeg imagemagick poppler-utils ghostscript qpdf pandoc \
      libreoffice-writer-nogui libreoffice-calc-nogui fonts-dejavu fonts-liberation fonts-noto-color-emoji \
      sqlite3 postgresql-client default-mysql-client redis-tools \
 && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/*

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o /usr/share/keyrings/githubcli.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/githubcli.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh && rm -rf /var/lib/apt/lists/*

# Node.js 22 LTS + pnpm / yarn (corepack), Bun
COPY --from=node:22-bookworm /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-bookworm /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && ln -sf /usr/local/lib/node_modules/corepack/dist/corepack.js /usr/local/bin/corepack \
 && corepack enable \
 && curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash

# Python tooling: uv, and Playwright with Chromium for browser automation / tests
RUN pip install --no-cache-dir uv \
 && npx -y playwright@1.56.1 install --with-deps chromium \
 && chmod -R a+rX /ms-playwright

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev && chmod -R a+rX /app

# Agents work as an unprivileged user (Claude Code refuses to skip
# permissions as root). Their home is a persistent volume: tools they install
# (npm -g, pip --user, uv tool…) and caches survive restarts.
RUN useradd --create-home --uid 1000 --shell /bin/bash omc
USER omc
RUN curl -fsSL https://claude.ai/install.sh | bash \
 && mkdir -p /home/omc/.claude /home/omc/.npm-global \
 && npm config set prefix /home/omc/.npm-global \
 && git config --global user.name "OneManCompany agent" \
 && git config --global user.email "agent@onemancompany.local" \
 && git config --global init.defaultBranch main
# OneManCompany's own venv is not on PATH: agents get the system Python.
ENV PATH=/home/omc/.local/bin:/home/omc/.npm-global/bin:$PATH \
    NPM_CONFIG_PREFIX=/home/omc/.npm-global

EXPOSE 8100
CMD ["/app/.venv/bin/python", "-m", "onemancompany.runner", "serve", "--host", "0.0.0.0", "--port", "8100"]
