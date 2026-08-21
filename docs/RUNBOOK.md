# Runbook

What to do when something is wrong, written before it is wrong. Decision 9 of the
deployment course, kept to the failures this studio can actually have.

Every scenario below starts the same way, because every surface is joined by one
id. Get the `run_id` first — from the interface's error, from `public.runs`, or
from the log line — and the rest is following it.

```bash
az containerapp logs show -n studio-harness -g studio-viorela --tail 200
```

Log lines carry `[run=<id>]`. In Application Insights the same id is the
`studio.run_id` attribute on the span and a `customDimensions.run_id` on the
trace, so this finds a run end to end:

```kusto
union traces, dependencies, requests, exceptions
| where customDimensions.run_id == "<run_id>" or tostring(customDimensions["studio.run_id"]) == "<run_id>"
| order by timestamp asc
```

And the durable record, which does not depend on Azure being reachable at all:

```bash
uv run python -m content_studio.replay <run_id>
```

---

## 1. The interface answers, the agent does not

**Looks like:** the page loads, a run starts and never finishes, or returns an
error immediately.

1. `curl https://<harness>/health` — it always answers 200, so read the body, not
   the status. `status: degraded` names the backend that is down.
2. If `mcp` is inactive: the data plane is a separate Container App. Check it.
   ```bash
   az containerapp revision list -n studio-mcp -g studio-viorela -o table
   ```
   A revision in `Degraded` or with 0 replicas is the whole answer. Restart it:
   ```bash
   az containerapp revision restart -n studio-mcp -g studio-viorela --revision <name>
   ```
3. If `openai` is inactive, the key is missing from the deployment, not expired —
   `/health` never calls the model. See §5.

## 2. Neon is unreachable

**Looks like:** `/health` reports `postgres` inactive; runs fail at the first
turn; the log shows `ConnectionDoesNotExistError` or a timeout.

Neon suspends an idle compute. The first request after a quiet spell wakes it and
can take several seconds — that is normal and `pool_pre_ping=True` already
absorbs it. A sustained failure is different.

1. Check the project is not suspended or over its limit at console.neon.com.
2. Confirm the harness has the **pooled** endpoint and migrations have the
   **direct** one. A pooled endpoint used for a migration fails intermittently,
   which looks like a network fault and is not one.
3. Point-in-time recovery: Neon keeps a restore window. Branch from a timestamp
   before the damage, verify the branch, then repoint `DATABASE_URL`. Restoring
   into a branch rather than over the main one means a wrong guess costs nothing.

## 3. E2B is down, or out of quota

**Looks like:** runs fail with a sandbox error; `/health` reports `e2b`
configured but runs still fail.

The health check reports whether the key and the skills folder exist; it does not
create a sandbox, because creating one on every probe would cost money. So a
provider outage shows up only on a real run.

1. Check status.e2b.dev and the Hobby-tier usage on the E2B dashboard.
2. There is no automatic fallback, and that is deliberate: the method lives in
   `skills/`, mounted into the sandbox. Running without it would produce answers
   that look right and did not follow her method — worse than an error.
3. Tell the person to wait. Nothing is lost: a failed run is stamped `failed` in
   `public.runs` and its audit rows are already committed.

## 4. A run costs more than expected

**Looks like:** an account's percentage jumps.

1. The per-account figures are on the admin page, and only there.
2. The gate refuses to **start** a run past the limit. It cannot refuse mid-call,
   because a call's cost is known only when it returns — so the overshoot is
   bounded by one call, and `max_tokens` bounds that.
3. To stop an account immediately, suspend it on the admin page. That is a
   timestamp, reversible, and it keeps every usage row.
4. Subscription-level guard, set once:
   ```bash
   powershell -File infra/cost-alert.ps1 -MonthlyBudget 25 -Email <address>
   ```

## 5. Sign-in stops working

**Looks like:** everyone gets 401, or the app stops answering entirely.

The dangerous version of this is self-inflicted. Easy Auth keeps the Google
client secret as a container-app secret, and Bicep declares the secret list —
a declared list is the *whole* list to ARM. Deploying without
`GOOGLE_CLIENT_SECRET` in `.env` deletes it, the auth sidecar then fails to
start, and the replica is marked unhealthy: the application stops answering, not
just sign-in. `deploy.ps1` carries the value through for exactly this reason.

1. Confirm `.env` still has `GOOGLE_CLIENT_SECRET`, then redeploy.
2. Adding or removing a tester is `AUTH_ALLOWED_EMAILS` in `.env` plus
   `powershell -File infra/deploy.ps1 -SkipBuild`. No rebuild.

## 6. Deploying, and getting back

Container Apps keeps the previous revision. A bad deploy is one command away
from undone:

```bash
az containerapp revision list -n studio-harness -g studio-viorela -o table
az containerapp ingress traffic set -n studio-harness -g studio-viorela \
  --revision-weight <previous-revision>=100
```

`deploy.ps1` checks `/health` on the new revision before it finishes, so a
container that cannot start is reported at deploy time rather than discovered by
whoever opens the page next.

If `az acr build` returns `TasksOperationsNotAllowed`, Azure has refused the
subscription its serverless builder. Pushing to the registry still works:

```bash
powershell -File infra/deploy.ps1 -LocalBuild
```

## 7. Rotating a secret

Add beside, deploy, verify, then revoke — never the other way around, so that a
failure at any step leaves a working system.

| Secret | Where it is added | Then |
|---|---|---|
| `OPENAI_API_KEY` | a second key on the OpenAI dashboard | edit `.env`, `deploy.ps1 -SkipBuild`, check `/health`, revoke the old |
| `E2B_API_KEY` | E2B dashboard | same, then one real run to confirm |
| `DATABASE_URL` | Neon: reset the role password | edit both `DATABASE_URL` and `DATABASE_URL_DIRECT`, deploy, check `/health` |
| `GOOGLE_CLIENT_SECRET` | Google Cloud console | edit `.env`, `enable-auth.ps1`, sign out and in |

---

## What is deliberately not here

**Phoenix, DeepEval, Ragas and a nightly evaluation job.** Decision 8 wires four
frameworks and a scheduled grader. Every one of them runs the agent, and running
the agent costs money — which in this project is Sorin's decision, taken per run,
not a cron's. The evals exist and are run by hand:

```bash
uv run python evals/run.py --id 13
```

CI does gate what can be gated for free: lint, the 171 unit tests, and a check
that `evals/cases.json` is still well formed. A change that breaks the eval
*harness* is caught before merge; a change that makes the agent *worse* is caught
by running the evals, on purpose, with someone watching.

**The promotion ritual**, when it starts: read the failed runs from
`public.runs` where `status = 'failed'`, replay the interesting ones, and add the
turn to `evals/cases.json`. Each production failure becomes a future regression
test. This is written down here so it can start without a design session.
