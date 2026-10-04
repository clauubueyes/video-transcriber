FROM node:26-bookworm-slim AS pot-builder

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 --branch 2.0.1 \
       https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git /opt/bgutil

WORKDIR /opt/bgutil/server
RUN npm ci --no-audit --no-fund \
    && npx tsc \
    && npm prune --omit=dev --no-audit --no-fund \
    && node build/generate_once.js --version

RUN mv build/generate_once.js build/generate_once.original.js
COPY deploy/bgutil_generate_once.mjs /opt/bgutil/server/build/generate_once.js
RUN node build/generate_once.js --version

FROM python:3.12-slim-bookworm

# yt-dlp uses Deno to solve YouTube's JavaScript challenges.
COPY --from=denoland/deno:bin-2.9.7 /deno /usr/local/bin/deno
COPY --from=pot-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=pot-builder /opt/bgutil/server/build /opt/bgutil/server/build
COPY --from=pot-builder /opt/bgutil/server/node_modules /opt/bgutil/server/node_modules
COPY --from=pot-builder /opt/bgutil/server/package.json /opt/bgutil/server/package.json

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NODE_OPTIONS="--max-old-space-size=192 --max-semi-space-size=2" \
    VIDEO_TRANSCRIBER_YOUTUBE_PLAYER_CLIENTS=mweb,tv,web_safari \
    VIDEO_TRANSCRIBER_YOUTUBE_IMPERSONATE=chrome \
    VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_POLICY=always \
    VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_BASE_URL=http://127.0.0.1:4416 \
    VIDEO_TRANSCRIBER_YOUTUBE_PO_TOKEN_SERVER_HOME=/opt/bgutil/server

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates ffmpeg libatomic1 \
    && rm -rf /var/lib/apt/lists/*

COPY deploy/install_sing_box.py /tmp/install_sing_box.py
RUN python /tmp/install_sing_box.py && rm /tmp/install_sing_box.py

COPY pyproject.toml Readme.md ./
COPY app ./app

RUN pip install --no-cache-dir . \
    && deno --version \
    && python -m yt_dlp --version \
    && python -c "import yt_dlp_ejs; import yt_dlp_plugins.extractor.getpot_bgutil_script" \
    && node /opt/bgutil/server/build/generate_once.js --version

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/ready', timeout=3)"

ENTRYPOINT ["python", "-m", "app.container_entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
