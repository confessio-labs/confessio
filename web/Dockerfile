# syntax=docker/dockerfile:1

# ---- deps: install dependencies (cached unless lockfile changes) ----
FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.15.5 --activate
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,target=/pnpm-store \
    pnpm config set store-dir /pnpm-store \
 && pnpm config set fetch-timeout 600000 \
 && pnpm config set fetch-retries 5 \
 && pnpm install --frozen-lockfile

# ---- builder: compile the Next.js standalone bundle ----
FROM node:22-alpine AS builder
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@9.15.5 --activate

# NEXT_PUBLIC_* values are inlined into the client bundle at build time,
# so they must be present here (not at runtime). Pass with --build-arg.
ARG NEXT_PUBLIC_MAP_TILER_API_KEY
ARG NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN
ARG NEXT_PUBLIC_POSTHOG_HOST
# Must be a valid URL — an empty value breaks new URL() at build time.
ARG NEXT_PUBLIC_SITE_URL=https://confessio.fr
ENV NEXT_PUBLIC_MAP_TILER_API_KEY=$NEXT_PUBLIC_MAP_TILER_API_KEY \
    NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN=$NEXT_PUBLIC_POSTHOG_PROJECT_TOKEN \
    NEXT_PUBLIC_POSTHOG_HOST=$NEXT_PUBLIC_POSTHOG_HOST \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# ---- runner: minimal image serving the standalone output ----
FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

# Runtime-only secrets (e.g. CRON_SECRET) are supplied via `docker run -e`.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# The daily /api/revalidate-dioceses cron that vercel.json used to run must now
# be driven externally (host cron / systemd timer hitting the endpoint).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
