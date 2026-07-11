FROM node:20-alpine

WORKDIR /app

# Install dependencies first
COPY package*.json ./
RUN npm install

# Copy application code
COPY . .

# Build-time env: API base for browser-side fetches (default: /api via nginx proxy)
ARG NUXT_PUBLIC_API_BASE=/api
ENV NUXT_PUBLIC_API_BASE=${NUXT_PUBLIC_API_BASE}

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/ || exit 1

# Build for production and run preview
RUN npm run build
ENV HOST=0.0.0.0
ENV PORT=3000
ENV NODE_ENV=production
CMD ["node", ".output/server/index.mjs"]
