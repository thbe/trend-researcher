# syntax=docker/dockerfile:1.7
# Trend Researcher — scheduler service.
# Tiny alpine + crond + docker-cli image that fires
# `docker compose run --rm crawler run-once` every 12h via the mounted host
# docker socket. See services/scheduler/README.md for the docker-socket
# trust-model note (single-operator internal tool, accepted).

FROM alpine:3.20

# - busybox-suid provides crond (cron daemon).
# - docker-cli + docker-cli-compose let this container drive `docker compose`
#   on the host via the mounted /var/run/docker.sock.
RUN apk add --no-cache \
        busybox-suid \
        docker-cli \
        docker-cli-compose

COPY services/scheduler/crontab /etc/crontabs/root
COPY services/scheduler/entrypoint.sh /entrypoint.sh

RUN chmod 0644 /etc/crontabs/root \
 && chmod 0755 /entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
