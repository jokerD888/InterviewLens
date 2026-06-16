# ============================================================
# InterviewLens · Next.js frontend image
# ============================================================

# ---- Stage 1: Build ----
FROM node:22-alpine AS builder

WORKDIR /app

RUN npm install -g pnpm@9

# Force flat node_modules (pnpm default isolation breaks Next.js bin resolution)
RUN echo "node-linker=hoisted" > .npmrc

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

ARG NEXT_PUBLIC_API_BASE=http://api:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

RUN pnpm build

# ---- Stage 2: Production runtime ----
FROM node:22-alpine AS runner

WORKDIR /app

RUN npm install -g pnpm@9
RUN echo "node-linker=hoisted" > .npmrc

COPY --from=builder /app/package.json /app/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./

EXPOSE 3000

CMD ["pnpm", "start"]
