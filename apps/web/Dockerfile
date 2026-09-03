FROM node:20-alpine AS deps
WORKDIR /repo
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci

FROM node:20-alpine AS build
WORKDIR /repo
COPY --from=deps /repo/node_modules ./node_modules
COPY package.json package-lock.json ./
COPY apps/web ./apps/web

# Next inlines NEXT_PUBLIC_* at build time, not at run time, so this has to be
# present *here*. Setting it as a runtime environment variable on the deployed
# service does nothing — the bundle would still be asking for localhost:8000.
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build --workspace apps/web

FROM node:20-alpine AS run
WORKDIR /repo
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /repo/node_modules ./node_modules
COPY --from=build /repo/apps/web ./apps/web
COPY package.json ./
EXPOSE 3000
CMD ["sh", "-c", "npm run start --workspace apps/web -- -p ${PORT:-3000}"]
