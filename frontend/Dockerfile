# Plain static SPA build (confirmed 2026-08-13 deploy-prep investigation:
# this is a Vite SPA using @tanstack/router-plugin for file-based routing
# at BUILD time, not the full TanStack Start SSR framework -- no server
# bundle, `dist/` is just index.html + assets/). node_modules, src/, and
# the test suite never reach the final image -- build-stage only.
#
# VITE_API_BASE_URL is read via `import.meta.env`, a Vite BUILD-TIME
# replacement -- it gets baked into the compiled JS, not read at container
# start. One build per environment (per this round's own explicit
# decision) -- pass the real backend URL as a build arg:
#   docker build --build-arg VITE_API_BASE_URL=https://api.example.com ...

FROM node:20-slim AS build

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* frontend/bun.lock* ./
RUN npm ci

COPY frontend/ ./

ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build


FROM nginx:1.27-alpine AS runtime

# SPA fallback -- every unmatched path serves index.html so the client-side
# router (TanStack Router, file-based routes) handles it, instead of nginx
# 404ing on a real, deep-linked route like /plans/TP123.
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
