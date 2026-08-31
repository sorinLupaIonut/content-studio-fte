# infra — Decision 3, Azure Container Apps

Nothing here has been run yet. Provisioning spends money and that is Sorin's call;
these files exist so the decision is reviewable before it costs anything.

Language follows [AGENTS.md](../AGENTS.md): this is a developer document, so it is
English. Nothing here is read by the client.

## What gets created

One resource group holding everything, so teardown is one command.

| Resource | Why |
|---|---|
| Container Registry (Basic, **admin disabled**) | holds the image; built by `az acr build`, so the laptop never pushes gigabytes |
| User-assigned managed identity + AcrPull | how both apps pull. No registry password is stored anywhere |
| Log Analytics workspace | Container Apps refuses to stream logs without one |
| Managed environment | the shared network both apps live in |
| `studio-harness` | **external** ingress on 8000. The only thing on the internet |
| `studio-mcp` | **internal** ingress on 8765. Reachable only from inside the environment |

Locked decision 6 in [../plans/DEPLOYMENT.md](../plans/DEPLOYMENT.md): one image,
two apps, different commands. The harness keeps the image's own `CMD`; the MCP app
overrides it with `content-studio-server`.

## Region

`eastus`, on purpose. Neon lives in `us-east-1`, and the traffic that matters is
app → MCP → Postgres, several round trips per request. Putting the compute in
Europe would pay ~90 ms on every one of them, while the client pays ~130 ms once
per request — invisible next to a generation that takes seconds. If the Neon
project ever moves to Europe, this choice moves with it.

## Order

PowerShell 7 is not installed on this machine and nothing here needs it: every
script declares `#Requires -Version 5.1` and uses no 7-only syntax, so Windows
PowerShell runs them. `-ExecutionPolicy Bypass` is unnecessary — the current
user's policy is `RemoteSigned` and these files are local.

```powershell
az login --use-device-code
powershell -File infra/deploy.ps1
powershell -File infra/enable-auth.ps1   # first pass: prints the redirect URI
#   register it in Google Cloud Console, put the two values in .env
powershell -File infra/enable-auth.ps1   # second pass: turns sign-in on
```

`deploy.ps1` is safe to re-run; every step creates or updates. `enable-auth.ps1`
comes second because the redirect URI contains an FQDN that does not exist until
the app does, and runs twice because Azure cannot mint Google credentials — the
first pass only tells you what to register.

To ship a code change afterwards, `deploy.ps1` again — it builds a new tag and
rolls a new revision. `-SkipBuild -Tag <existing>` redeploys an image already in
the registry.

Tearing everything down:

```powershell
powershell -File infra/teardown.ps1
```

## The two doors

They are different questions and both are enforced.

**Easy Auth** decides who may reach the container at all. Configured against a
Google OAuth client, so an unauthenticated visitor is redirected to a Google login
page and never touches Python. Google, not Entra, because the two identities the
client actually uses are Google accounts.

**`AUTH_ALLOWED_EMAILS`** decides who is Viorela, and here it carries more weight
than it would behind a single-tenant Entra registration: *any* Google account gets
through the first door. `auth.py` reads identity only from the
`x-ms-client-principal-*` headers the platform injects and refuses to invent one;
everyone outside the list is refused with 403.

Both the allowlist and the Google credentials are read from `.env`, never from a
command line — the client's address is deployment configuration, not source.

Once both identities have signed in, move the allowlist to
`AUTH_ALLOWED_PRINCIPAL_IDS`. `auth.py` already prefers it when set. An email
address can be re-pointed at a different person; a Google subject id cannot.

The order this creates matters: between `deploy.ps1` and `enable-auth.ps1` the
harness is reachable and answers **401 to everything**, because the headers are
absent. That is a closed door, not an open one — deploying before sign-in is
configured is safe.

`AUTH_MODE=azure` is set explicitly on the app. `auth.py` would refuse
`development` in Azure anyway, but nothing here depends on that detection.

## Adding a tester

One edit, one command:

```powershell
# 1. append the address to AUTH_ALLOWED_EMAILS in .env
powershell -File infra/deploy.ps1 -SkipBuild
```

`-SkipBuild` reads back the tag of the image already running, so nothing is
rebuilt and nothing is pushed; Container Apps rolls a revision with the new list
in about a minute. Revoking is the same edit in reverse and takes effect just as
fast - there is no session to expire, because the check runs per request.

Two things to know before handing an address out. Matching is exact: the address
as Google reports it, lowercased. And the first door does not filter, so the list
is the whole of the access control - an address on it is a person in the client's
workspace, with her posts and her audit log.

Note the interaction with `AUTH_ALLOWED_PRINCIPAL_IDS`: once that is set, the
email list is ignored entirely (see `auth.py`). Migrate both at the same time, or
adding a tester to the email list will silently do nothing.

## Secrets

Four values are read from `.env` at deploy time — `DATABASE_URL`,
`DATABASE_URL_DIRECT`, `OPENAI_API_KEY` and `E2B_API_KEY` — and land as Container
Apps secrets referenced by `secretRef`. The count said four while three were
named, and the unnamed one was the one nobody noticed was missing: the sandbox
key returned to the project on 2026-08-27 and reached this file on 2026-08-31,
after four days in which no deployed run could start. They are never printed, never written into
the template, and never passed on a command line: `deploy.ps1` writes a parameters
file into the temp directory and deletes it in a `finally` block, and the Bicep
parameters are `@secure()`, so they stay out of the deployment record too.

Three more values live in the same file without being secrets in that sense:
`AUTH_ALLOWED_EMAILS`, read by `deploy.ps1`, and `GOOGLE_CLIENT_ID` /
`GOOGLE_CLIENT_SECRET`, read by `enable-auth.ps1`.

`.env` itself is not in the image and not in git. The `-pooler`/direct split from
`config.py` is checked before anything is built, because a pooled endpoint used
for migrations fails intermittently, long after it looked fine.

## What this costs

The registry is the only thing that bills while nothing is happening: ACR Basic is
roughly USD 5 a month. Both apps have `minReplicas: 0`, so they sleep and cost
nothing when idle, and Container Apps' monthly free grant covers a workload this
small once they wake. Log Analytics ingestion at this volume stays inside its free
tier.

The Azure Free Trial is USD 200 over **30 days**. When it ends, first-party
services stop unless the subscription moves to pay-as-you-go. That is a billing
decision, not a technical one, and it is still open.

## Deliberate choices worth arguing with

**The harness runs at most one replica.** A chat stream keeps its queue in the
process that started the run, so a second replica would answer a poll belonging to
the first. One client, one process. The MCP server is `stateless_http` and scales
to three.

**Scale to zero on both.** The gate survives it: `RunState` is serialized into
Postgres, so an approval waiting overnight is not lost when the container sleeps.

**The liveness probe tolerates a cold database.** `/health` answers 200 even while
reporting `degraded`, and the probe allows five failures 30 s apart. A sleeping
Neon compute cannot get the container restarted.

## Known gaps, none of them fixed here

**Neon cold start.** `health()` gives Postgres 3 seconds under `asyncio.timeout`.
When both the app and the database have been asleep, the first request loses that
race and reports `degraded` before recovering on the second — reproduced locally
during D2. Harmless for the probe, visible to whoever opens the page first. Worth
deciding on, not worth patching blind.

**`--proxy-headers` and trusted proxies.** The Dockerfile passes `--proxy-headers`,
and uvicorn trusts `127.0.0.1` by default. In Container Apps the immediate peer is
the ingress sidecar, which is not loopback, so forwarded headers may be ignored.
Nothing in the app currently depends on them — the Blazor client uses relative
URLs and there are no scheme-sensitive redirects — so widening
`FORWARDED_ALLOW_IPS` is deferred until the trusted range is known rather than
guessed. Widening it wrongly lets a client forge its own source address.

**`enable-auth.ps1` has never been executed.** It is written from the documented
CLI contract, not from a run. Expect to correct a flag name on the first attempt;
it is the least proven file here.

**The client secret expires.** One year by default. Sign-in breaks that day with a
message that will not obviously say so. Re-running `enable-auth.ps1` rolls it.
