# Edge image: builds the React SPA, then serves it from nginx and reverse-proxies the API.
# Build context is the repo root so both frontend/ (the app) and nginx/ (this config) are reachable.
FROM node:22-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/snippets/ /etc/nginx/snippets/
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8001 8002 8003
