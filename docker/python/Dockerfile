# Development image: the Python the tests run on, with uv inside, so dependency resolution and the test run share one
# runtime. Built on demand by bin/python and bin/uv (bin/lib/image.sh); PYTHON_VERSION selects the base image
# (3.11, 3.12, 3.13, 3.14; 3.15-rc until the 3.15 GA of 2026-10). The uv binary is pinned: Dependabot (docker) bumps it.
ARG PYTHON_VERSION=3.12
FROM ghcr.io/astral-sh/uv:0.12.12 AS uv
FROM python:${PYTHON_VERSION}-slim
COPY --from=uv /uv /uvx /bin/
# The workspace is a bind mount: hard links between the uv cache and the environment would cross file systems on
# macOS, so uv copies; the interpreter of the image is the one to use, never a downloaded one (the matrix is the tag).
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_CACHE_DIR=/app/var/uv-cache \
    UV_NO_PROGRESS=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
