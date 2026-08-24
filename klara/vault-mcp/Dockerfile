# ============================================================
# Dockerfile — Loki Vault MCP Server
# Multi-stage: builder compiles TypeScript; production image
# contains only the compiled JS + production node_modules.
# ============================================================

# ------- Stage 1: build -------
FROM node:20-alpine AS builder

WORKDIR /app

# Install deps first (layer-cache friendly)
COPY package*.json ./
RUN npm ci

# Copy source and compile
COPY tsconfig.json ./
COPY src/            ./src/
RUN npm run build


# ------- Stage 2: production -------
FROM node:20-alpine AS production

# curl is needed for the Docker HEALTHCHECK command
RUN apk add --no-cache curl

WORKDIR /app

# Copy manifests and install production deps only
COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

# Copy compiled output from builder stage
COPY --from=builder /app/dist ./dist

# Non-root user for runtime security
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
USER appuser

EXPOSE 3141

HEALTHCHECK \
  --interval=30s \
  --timeout=10s  \
  --start-period=15s \
  --retries=3 \
  CMD curl -sf http://localhost:3141/health | grep -q '"status":"healthy"' || exit 1

CMD ["node", "dist/mcp-server-part3.js"]
