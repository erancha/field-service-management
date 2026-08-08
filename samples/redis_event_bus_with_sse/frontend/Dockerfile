# Dev-server image for the sample page. Dependencies install from the main frontend's lockfile so
# the sample pins no package versions of its own; the page's sources are bind-mounted by the
# sample's docker-compose file, not baked in. Build context is the repo root, reaching frontend/.
FROM node:22-alpine
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
EXPOSE 8010
