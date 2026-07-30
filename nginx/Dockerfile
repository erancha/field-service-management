# Edge image: builds the React SPA, then serves it from nginx and reverse-proxies the API.
# Build context is the repo root so both frontend/ (the app) and nginx/ (this config) are reachable.
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
# Needed by the entrypoint script below to mint the placeholder certificate that lets the public edge
# start before its real one has been issued.
RUN apk add --no-cache openssl
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/public.conf.template /etc/nginx/fsm/public.conf.template
COPY nginx/snippets/ /etc/nginx/snippets/
COPY nginx/docker-entrypoint.d/18-fsm-edge-mode.sh /docker-entrypoint.d/18-fsm-edge-mode.sh
RUN chmod +x /docker-entrypoint.d/18-fsm-edge-mode.sh
COPY --from=build /app/dist /usr/share/nginx/html
# 8001-8003 serve the per-port localhost edge; 80 and 443 the public per-hostname one.
EXPOSE 80 443 8001 8002 8003
