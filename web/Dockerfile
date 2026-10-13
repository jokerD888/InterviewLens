# ============================================================
# InterviewLens · Next.js frontend image
# ============================================================

# ---- Stage 1: Build ----
FROM node:22-alpine AS builder

WORKDIR /app

RUN npm install -g pnpm@11.25.0

# Force flat node_modules (pnpm default isolation breaks Next.js bin resolution)
RUN echo "node-linker=hoisted" > .npmrc

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG NEXT_PUBLIC_API_BASE=http://api:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

RUN pnpm build

# ---- Stage 2: Production runtime ----
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000 API_BASE=http://api:8000
RUN addgroup -g 10001 app && adduser -D -u 10001 -G app app
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public
USER app

EXPOSE 3000

CMD ["node", "server.js"]
