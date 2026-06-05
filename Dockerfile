FROM python:3.12-alpine

ENV TOROB_UPSTREAM_SCHEME=https
ENV TOROB_UPSTREAM_HOST=api.torob.com
ENV PROXY_TOKEN=change-this-token
ENV CORS_ALLOW_ORIGIN=*
ENV PORT=80

WORKDIR /app
COPY worker_proxy.py /app/worker_proxy.py

CMD ["python", "/app/worker_proxy.py"]
