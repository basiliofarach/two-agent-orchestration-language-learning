FROM node:24-alpine AS base
# Corepack cannot run pnpm 11+ and is no longer bundled from Node 25.
# Keep this version equal to `packageManager` in package.json.
RUN npm install --global pnpm@12.9.1
WORKDIR /app

# Manifests first, so a source-only change reuses the install layer.
FROM base AS development-dependencies-env
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM base AS production-dependencies-env
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile --prod

FROM base AS build-env
COPY --from=development-dependencies-env /app/node_modules ./node_modules
COPY . .
RUN pnpm run build

FROM base
ENV NODE_ENV=production
COPY package.json pnpm-lock.yaml ./
COPY --from=production-dependencies-env /app/node_modules ./node_modules
COPY --from=build-env /app/build ./build
USER node
EXPOSE 3000
# Same as `pnpm run start`, without pnpm in the runtime path: as a non-root
# user it cannot write its package-manager lockfile and exits.
CMD ["node_modules/.bin/react-router-serve", "./build/server/index.js"]
