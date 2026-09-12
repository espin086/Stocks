---
change: 0005-docker-distribution
milestone: v1.2
depends_on: [0003-local-persistence, 0004-web-ui, 0000-release-engineering]
status: proposed
---

# 0005 — Docker distribution

## Outcome

One command, one image, the whole tool:

```bash
docker run -p 8787:8787 -v quantfolio:/data espin086/quantfolio serve --host 0.0.0.0
```

The CLI is the image's entrypoint, so the container runs anything the tool can do:

```bash
docker run -v quantfolio:/data espin086/quantfolio optimize markowitz --portfolio core
docker run -v quantfolio:/data espin086/quantfolio db info
```

And the CLI generates the deployment rather than the user hand-writing it:

```bash
qf deploy compose > docker-compose.yml    # generated from current config
qf deploy check                           # what would run, with what config
```

## Why

"Install Python 3.11+, then pip install, then set env vars" is a real barrier for
something whose audience includes people who want to look at a chart. An image
with the UI, API, CLI and database in it reduces that to one command.

It also makes the deployment reproducible. The interesting failure mode for this
kind of tool is a working local install and a broken server install, because
configuration drifted between them. Generating the compose file from the same
config resolution chain the CLI already uses keeps those the same thing.

## What changes

- **New capability `deployment`.**
- Multi-stage `Dockerfile`: Node builds the 0004 frontend, Python builds the
  wheel, and a slim runtime stage carries neither toolchain.
- `docker-compose.yml`, `.dockerignore`.
- **New CLI group `qf deploy`** — `compose`, `check`, `env`.
- Docker Hub publishing added to 0000's release pipeline, on the same version gate
  and the same OIDC identity, for `linux/amd64` and `linux/arm64`.

## The CLI is the entrypoint

`ENTRYPOINT ["qf"]` rather than a shell or a server command. This is the decision
that keeps the image honest: there is no container-only code path, no separate
server binary, and no way for the containerized tool to diverge from the installed
one. `docker run <image> <anything the CLI accepts>` works, and `serve` is just one
of those things.

Configuration follows the same precedence chain the CLI already resolves — flag,
then environment variable, then config file, then default — so an environment
variable set in compose behaves exactly as it does in a shell.

## Non-goals

- **No Kubernetes manifests or Helm chart.** A single-user tool with a single
  SQLite file does not benefit from an orchestrator, and shipping a chart would
  imply a horizontal-scaling story that the storage model cannot support.
- No multi-replica deployment. One SQLite file means one writer.
- No bundled reverse proxy or TLS termination. The image serves HTTP; putting a
  proxy in front is the operator's choice and is documented, not vendored.
- No `latest`-only tagging. Every image is tagged with its exact version.
- No database server. Postgres remains off the roadmap, as in 0003.
- No image for the landing page. 0006 is static hosting.

## Risks

| Risk | Mitigation |
|---|---|
| The container writes the database to its own filesystem and the user loses everything on `docker rm` | `QUANTFOLIO_DB_URL` defaults to `sqlite:////data/quantfolio.db`; the image declares `/data` as a volume; startup fails loudly if `/data` is not writable, rather than silently persisting into the container layer |
| Root-owned files in a mounted volume become unusable from the host | The image runs as a non-root user with a fixed, documented uid/gid |
| Secrets baked into an image layer | Nothing is copied into the image but built artifacts; the build is proven secret-free by scanning the published image, and API keys arrive only as runtime environment or a mounted config |
| Image bloat from a Node toolchain and scientific wheels | Multi-stage build discards both toolchains; a size budget is a CI gate |
| A user exposes the container to the internet with no token | The image's default bind is loopback, which is useless in a container — so exposing it requires `--host 0.0.0.0`, which 0004 already gates on a token; the published docs lead with the token |
| Docker Hub and PyPI versions drift | Both publish from the same gated job on the same commit; the image tag is asserted equal to the wheel version before push |
