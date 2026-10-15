FROM alpine:3.19

RUN apk add --no-cache \
    python3 \
    bash \
    curl \
    ca-certificates \
    openssh-server \
    openssh-client \
    tzdata \
    && rm -rf /var/cache/apk/*

# ngrok agent
RUN curl -fsSL -o /tmp/ngrok.tgz \
    https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz \
    && tar -xzf /tmp/ngrok.tgz -C /usr/local/bin \
    && chmod +x /usr/local/bin/ngrok \
    && rm /tmp/ngrok.tgz

WORKDIR /app

COPY officialv3.py /app/officialv3.py
COPY health.py /app/health.py
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# render sets PORT for the http healthcheck side
ENV PORT=8080
EXPOSE 8080

CMD ["/app/entrypoint.sh"]
