# Deploying with Docker

One image, the CLI as its entrypoint. Anything `sobres` accepts, the container
runs:

```bash
docker run -p 8787:8787 -v sobres:/data aisolutionslab/sobres serve --host 0.0.0.0
docker run -v sobres:/data aisolutionslab/sobres optimize markowitz --portfolio core
docker run -v sobres:/data aisolutionslab/sobres doctor
```

The first command prints a **deployment token once** and stores it hashed.
Paste it into the browser at <http://localhost:8787>. Binding a non-loopback
address without a token is refused by design; `sobres serve token rotate`
replaces it.

## What the image is

| | |
|---|---|
| Registry | Docker Hub, `aisolutionslab/sobres` |
| Tags | exact version (`1.2.0`), minor series (`1.2`), `latest` |
| Architectures | `linux/amd64`, `linux/arm64` under one tag |
| User | `sobres`, uid `1000`, gid `1000` |
| Volume | `/data` — the SQLite database and, optionally, `config.toml` |
| Port | `8787` |
| Entrypoint | `sobres` (no default subcommand: `docker run <image>` prints help) |
| Health | `HEALTHCHECK` runs `sobres deploy health`, which asks `/api/v1/health` — doctor's own checks |
| Extras installed | `data`, `econ`, `web`, `otel` — tracing is inert until `OTEL_*` is set |

The runtime stage contains the published wheel and nothing else: no Node, no
compiler. Configuration is runtime-only, from environment variables or a config
file on the volume, with the same precedence the CLI uses everywhere (flag, then
environment, then config file, then default).

## Data

`SOBRES_DB_URL` defaults to `sqlite:////data/sobres.db` inside the image and
`/data` is declared as a volume. If `/data` is not writable the container exits
with exit code 3 naming the mount — it never persists into the container layer,
where `docker rm` would discard your portfolios silently.

Files on the volume are owned by uid 1000, so they are usable from the host. A
host-side `sobres` pointed at the same file sees the container's writes and
vice versa.

An external backend (`SOBRES_DB_URL=postgresql://…`) needs no different image
and no volume; `sobres deploy check` says so. A database URL is a secret: it is
redacted in logs and in every `sobres deploy` output.

## Generate the deployment instead of writing it

```bash
sobres deploy compose > docker-compose.yml   # from the configuration you resolve now
sobres deploy env > .env                     # every variable, its default, no secret values
sobres deploy check                          # doctor's checks + image, mount, bind, token, credentials
```

The compose file references secrets by name (`${SOBRES_FRED_API_KEY}`) and
never embeds a value, so it is safe to commit. `deploy check` reports a
non-loopback bind with no token as an **error**, not a warning.

## Upgrading

```bash
docker run --rm -v sobres:/data aisolutionslab/sobres db export /data/backup-$(date +%F).db
docker pull aisolutionslab/sobres:latest
docker compose up -d
```

Migrations run automatically the first time the new version opens the database
(after taking its own backup beside the file). Take yours first anyway.

## Signals and logs

`docker stop` sends SIGTERM; the server shuts down within its 10-second grace
period. A job still running at that point is asked to stop at its next
checkpoint, and anything left is recorded as failed with the reason — nothing
stays "running" forever. On the next start, jobs orphaned by a crash are marked
the same way.

Logs go to stderr as JSON (stderr is not a TTY in a container) and no log file
is written by default. `SOBRES_LOG_LEVEL=DEBUG` takes effect on the next run
with no rebuild. Standard `OTEL_*` variables activate tracing; an unreachable
collector warns once and never fails a command or the health check.

## Reverse proxy and TLS

The image serves plain HTTP. Put Caddy, nginx or Traefik in front for TLS —
that is the operator's choice, and nothing here depends on it. Keep the
deployment token; a proxy does not replace it.

## Publishing (maintainers)

The release workflow builds the image from the **exact wheel it just published
to PyPI**, asserts `sobres --version` inside it equals that version, checks the
compressed size is under 500 MB, scans it (fixable high/critical findings and
any secret fail the run; named exceptions go in `.trivyignore` with a reason),
refuses to overwrite an existing version tag, and only then pushes for both
architectures with a BuildKit provenance attestation and an SBOM. That
attestation is a build attestation, not an OIDC-signed identity.

Publishing is disarmed until two things exist:

| Where | Name | Value |
|---|---|---|
| Settings → Secrets → Actions (repository) | `DOCKERHUB_USERNAME` | the Docker Hub account |
| Settings → Secrets → Actions (repository) | `DOCKERHUB_TOKEN` | a scoped access token with write access to `aisolutionslab/sobres` only — never the password |
| Settings → Variables → Actions | `DOCKER_RELEASE_ENABLED` | `true` |

The secrets are repository-level because only this repository publishes an
image; they move to the organization the day a second one does. Only the push
job reads them.
