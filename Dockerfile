# Stage 1: build the React app
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# Stage 2: FastAPI serves the API and the built app
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY --from=web /web/dist frontend/dist
WORKDIR /app/backend
# SQLite lives on the container's disk (Render free has no persistent disk); it is re-created and re-seeded on startup.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
