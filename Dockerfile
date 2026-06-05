FROM nginx:1.31-alpine

ENV TOROB_UPSTREAM_SCHEME=https
ENV TOROB_UPSTREAM_HOST=api.torob.com
ENV PROXY_TOKEN=change-this-token
ENV CORS_ALLOW_ORIGIN=*

COPY nginx/templates /etc/nginx/templates
