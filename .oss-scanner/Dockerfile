# Build environment for the Anthropic OSS Scanner.
# The image is built with network access; scanning happens offline, so every
# dependency needed to compile contracts and run the test suite is installed here.
FROM python:3.11-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git gcc libc6-dev libssl-dev libgmp-dev make \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

RUN git clone https://github.com/vyperlang/vyper.git /code
WORKDIR /code

ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy UV_OFFLINE=1
# editable install of vyper + test/lint deps (uv.lock is gitignored upstream,
# so dependencies are resolved at build time)
RUN UV_OFFLINE=0 uv sync --group test --group lint
ENV PATH="/code/.venv/bin:$PATH"

# fail the build early if anything is missing (must work offline later)
RUN vyper --version && \
    pytest -q -n 4 tests/unit -x -p no:cacheprovider
