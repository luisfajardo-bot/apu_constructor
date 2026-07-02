# --- Etapa 1: compilar el frontend (Vite) ---
FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Las VITE_* son públicas (se bakean en el bundle). Se pasan como build-args.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
RUN npm run build   # produce /web/dist

# --- Etapa 2: backend Python que sirve API + SPA ---
FROM python:3.12-slim AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY apu_tool/ ./apu_tool/
COPY db/ ./db/
COPY run_cli.py run_web.py ./
COPY --from=frontend /web/dist ./web/dist
# Render inyecta $PORT; gunicorn con workers uvicorn, confiando en el proxy para la IP real.
ENV PORT=8000 WEB_CONCURRENCY=2
    # --forwarded-allow-ips="*": confiamos en X-Forwarded-For porque el ÚNICO ingreso
    # es el edge/proxy de Render. Si algún día el contenedor queda accesible directo
    # (VM/Docker -p sin proxy), restringir a los CIDR del proxy — con "*" el XFF es
    # spoofeable y se podría evadir el rate-limit.
CMD gunicorn apu_tool.servicio.app:app \
    -k uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY} \
    --bind 0.0.0.0:${PORT} \
    --forwarded-allow-ips="*" \
    --timeout 120
