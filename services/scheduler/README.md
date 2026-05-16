# Scheduler service

Tiny alpine + crond + docker-cli container that fires the crawler on a
fixed cadence. Lives at `services/scheduler/`. Built into the local
stack by `docker-compose.yml` (see Plan 03-04 / T05).

## What it does

It runs BusyBox `crond` in the foreground inside a small alpine image,
reads `/etc/crontabs/root`, and on every tick executes:

```sh
cd /workspace && docker compose run --rm crawler run-once
```

`/workspace` is the repo root, mounted read-only into the container so
`docker compose` can read `docker-compose.yml`. `/var/run/docker.sock`
is mounted from the host so the scheduler can drive `docker compose`
against the same Docker daemon that runs everything else.

Output from each run is redirected to `/proc/1/fd/1`, i.e. the
entrypoint's stdout, so `docker logs trend-scheduler` shows every
crawler invocation interleaved with the cron events themselves.

## Cadence

Locked at twice daily, anchored to UTC: **00:00** and **12:00** every
day. This is requirement **ING-001** (12h crawl cadence) and is
expressed as `0 0,12 * * *` in `services/scheduler/crontab`. The
schedule is anchored, NOT a 12-hour drift from container start, so the
observation windows are predictable across restarts.

## Trust model — read before changing anything

This container mounts the host **docker socket** at
`/var/run/docker.sock`. Anyone with code-execution inside this
container has effective root on the host, because they can launch
arbitrary privileged containers via that socket.

That is accepted for Trend Researcher because this is a
single-operator internal tool running on the operator's own machine:

- there is no multi-tenant boundary;
- there is no untrusted code path into the scheduler (the crontab is
  baked into the image, not read from a volume or an env var);
- the alternative — running the crawler as a sidecar inside the
  scheduler image, or wiring up a separate cron host — adds
  operational surface area we don't want at this stage.

**Do not** copy this pattern into a multi-tenant deployment, a shared
CI runner, or any environment where untrusted users can reach the
container. If/when Trend Researcher leaves the single-operator regime,
the scheduler must be redesigned (e.g. systemd timer on the host, or
a queue-based worker model with no docker socket access).

## Changing the cadence

1. Edit `services/scheduler/crontab`. Keep the file at exactly two
   non-empty lines (comment + cron entry) so `wc -l` stays 2.
2. Rebuild the image: `docker compose build scheduler`.
3. Restart: `docker compose up -d scheduler`.
4. Verify the new schedule shows up in `docker logs trend-scheduler`
   (the entrypoint dumps the active crontab on startup).

## Verifying

```sh
docker compose up -d scheduler
docker logs -f trend-scheduler
```

You should see:

```
[scheduler] starting crond. crontab:
# Trend Researcher: trigger crawler every 12h at 00:00 UTC and 12:00 UTC
0 0,12 * * * cd /workspace && docker compose run --rm crawler run-once >> /proc/1/fd/1 2>&1
[scheduler] handing off to crond
```

…and at every scheduled tick a fresh block of crawler output (one new
`crawl_runs` row per tick, per Plan 03-01).

## Pointers

- Top-level README: `../../README.md`
- Phase 3 context: `../../.planning/phases/03-scheduler-ops-baseline/CONTEXT.md`
- Plan: `../../.planning/phases/03-scheduler-ops-baseline/03-04-PLAN.md`
