# Combined backend + agent-making image. agent-making is imported as a
# plain Python module by path (app/agent_client.py does sys.path.insert),
# never called over HTTP/as a separate service -- see AGENT_STATE.md /
# the 2026-08-13 deploy-prep investigation for the full reasoning. That's
# why there's one image here, not two.
#
# MUST be built with the REPO ROOT as build context (not ./backend alone)
# -- this Dockerfile COPYs from ../agent-making relative to this file,
# which only resolves if the build context includes both directories. See
# docker-compose.yml's `build: {context: .., dockerfile: backend/Dockerfile}`.
#
# 2026-08-13: tested removing libpq-dev/gcc from the build stage per the
# deploy-prep report's own flag -- psycopg2-binary and bcrypt both ship
# prebuilt manylinux wheels for this base image's platform, and spacy's
# own C-extension deps (blis/thinc/etc.) do too, so no compiler is
# actually needed to build this image. Confirmed by a real build, not
# assumed -- if a future dependency bump ever needs a source build again,
# this comment is where to look first before silently re-adding them.

FROM python:3.12-slim AS build

WORKDIR /app

COPY backend/pyproject.toml ./
COPY backend/app ./app

# --no-cache-dir keeps the build stage itself smaller; --prefix=/install
# gives the runtime stage a clean, self-contained directory tree to copy
# (mirrors /usr/local's own layout, since both stages share this same
# base image -- copying it onto /usr/local in the runtime stage just
# works, no path translation needed).
RUN pip install --no-cache-dir --prefix=/install .

# spacy's model isn't installable via pip/pyproject.toml alone -- this is
# its own real, separate step, and it needs network access at build time
# (fetches a wheel-shaped release asset from GitHub). Installed into the
# SAME --prefix so it's captured by the single COPY --from=build below.
RUN PYTHONPATH=/install/lib/python3.12/site-packages pip install --no-cache-dir --prefix=/install \
    https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl

# agent-making's own runtime-necessary subset ONLY -- not its tests/,
# app.py (Streamlit POC), rules/generate_payor_rules.py or the per-payor
# generated JSON files (dead reference exports, removed from the repo
# entirely), rules/archive/, sample_tps/, docs, or .venv. Confirmed via
# the 2026-08-13 investigation report: pipeline/ (the whole package --
# api.py's own import chain pulls in most of it) + rules/rules.json (the
# one file _load_rules() actually reads) is the real, complete list.
COPY agent-making/agent/pipeline /agent-making-src/agent/pipeline
COPY agent-making/agent/rules/rules.json /agent-making-src/agent/rules/rules.json


FROM python:3.12-slim AS runtime

WORKDIR /app

COPY --from=build /install /usr/local
COPY --from=build /agent-making-src /agent-making
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic

# Matches settings.agent_making_agent_path's default ("../agent-making/agent",
# resolved relative to THIS directory's parent -- i.e. one level above
# /app/app, which is /app itself) -- so /agent-making/agent, a sibling of
# /app at the container root, is exactly where the existing default
# already looks. No env var override needed as long as this layout holds;
# AGENT_MAKING_AGENT_PATH remains available to override if it ever
# doesn't (e.g. a future image that vendors agent-making differently).

# Session-note-extraction cache (agent-making/agent/pipeline/
# session_note_extraction.py writes real, paid-for-avoidance cache files
# here) -- a named volume mounts over this in docker-compose.yml so a
# restart doesn't silently re-trigger billed calls for files already
# processed. Created here so the mount point exists with the right
# ownership even before the volume is first populated.
RUN mkdir -p /agent-making/agent/.cache/session_note_extractions

# Upload storage -- settings.upload_storage_dir defaults to "./data/uploads",
# resolved relative to the backend package directory (this WORKDIR). A
# named volume mounts over /app/data/uploads in docker-compose.yml so
# uploaded files survive restarts/redeploys -- the critical gap the
# 2026-08-13 investigation report flagged.
RUN mkdir -p /app/data/uploads

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
