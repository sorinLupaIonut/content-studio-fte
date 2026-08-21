# Multi-user, budgets and an admin page — the design

Written 2026-08-21, from Sorin's brief: test accounts he creates himself, a money
cap per account so the model cannot run away with the bill, a per-user profile,
and an admin page that shows what each account has spent.

Nothing here is built yet. This file exists so the decisions are made once, in
the open, before any of it is written.

---

## The question he actually asked

> *"cred ca e mai bine sa facem logarea si cu user si parola, dar intr-un mod
> securizat, sa nu poata fi spart site-ul .. nu stiu daca e nevoie de un OpenID
> Connect (OIDC), provider extern"*

**Yes — an external OIDC provider. Do not build a password login into this
application.**

The reason is worth stating plainly, because it is the strongest security
property this project currently has and it would be thrown away by accident:

> **This application contains no authentication code at all.**
> Easy Auth runs as a sidecar container and does the whole login. `auth.py` only
> reads headers the platform injects and checks them against an allowlist. There
> is no password to steal, no session to forge, no reset link to abuse, no login
> form to brute-force — because none of those things exist in the codebase.

Adding email+password means owning, correctly and forever: Argon2id hashing with
per-user salts, per-account and per-IP lockout, credential-stuffing defence,
password-reset tokens that expire and cannot be replayed, session invalidation on
password change, and a plan for the day a hash dump leaks. Every one of those is
a place to be wrong, and being wrong in any one of them is precisely *"site-ul e
spart"*.

### What to use instead

**Microsoft Entra External ID** (the successor to Azure AD B2C). It is an OIDC
provider in which *Sorin creates the accounts himself* — email and password,
exactly the experience he described — while Microsoft stores the passwords, does
the lockout, the MFA and the breached-password checks.

- Easy Auth already speaks OIDC, so it is added **alongside** Google, not instead
  of it. Viorela keeps her Google button.
- **The application does not change at all.** It keeps reading
  `x-ms-client-principal-id`. `auth.py` is untouched.
- It has a free monthly-active-user tier that a handful of testers will not come
  close to. *(The exact figure is not quoted here on purpose — check the current
  Azure pricing page before relying on it. It has changed before.)*
- Cost is setup, not code: a tenant, an app registration, a sign-up/sign-in user
  flow, and one more provider block in `infra/`.

### The cheaper stopgap, if testers are needed this week

Google sign-in already works and the allowlist already exists. Any tester with a
Gmail address can be let in today by adding one line to `AUTH_ALLOWED_EMAILS`.
Publishing the Google app (currently in *Testing*) removes the 7-day
re-authentication and the 100-tester list.

That is zero work and available now. Its only real limitation is that a tester
must have a Google account.

### The point that matters most for sequencing

**Identity is not the hard part of what he asked for.** The budget cap, the
per-user profile and the admin page are the same amount of work whichever
provider issues the login, and none of them touch `auth.py`.

So the order is: build the multi-tenant and budget layer against the Google
sign-in that already works, and add Entra External ID afterwards without
touching any of it. Doing it the other way round blocks all the interesting work
behind a tenant setup.

---

## What is already there (more than expected)

This is not a rewrite. The database was designed multi-tenant from the start and
nobody has been using it that way:

- `public.clients` is **one row per client**, each with its own `profile_md`.
- `posts`, `generation_batches` and the rest already carry `client_id`.
- Generation batches already carry `owner_principal_id`.
- `OWNER_HEADER` already carries the authenticated principal to the MCP server on
  the trusted connection — a value the model cannot see or influence.

What is missing is exactly one link: **which client row does this logged-in
person own?** Today that is answered by a single global environment variable,
`CLIENT_SLUG=viorela`, read in `config.py` and baked into `PROFILE_URI` at import
time.

---

## The four pieces

### 1. `app_users` — the missing link  ✅ *server half built 2026-08-21*

```sql
CREATE TABLE IF NOT EXISTS public.app_users (
    principal_id  TEXT PRIMARY KEY,          -- from Easy Auth, never from the model
    email         TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT 'google',
    client_id     UUID NOT NULL REFERENCES public.clients(id) ON DELETE RESTRICT,
    role          TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    disabled_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**It is a link table, and the budget deliberately does not live here.** A
principal id belongs to the identity provider, not to the person: the same human
signing in through Google and through Entra External ID arrives as two different
ids, and the application cannot tell they are the same person. If the principal
were the key of the profile, that person would quietly acquire two profiles and
two budgets, with no clean way to merge them once each had been spent against.

So several rows may point at one `client_id`, and **the client row is the
account** — it owns the profile, the budget and the usage. One row per door, one
account behind them. This was not in the first draft of this plan; it came out of
working through what External ID actually changes.

`CLIENT_SLUG` stops being the answer and becomes the *seed default* only. Every
request resolves its client from the authenticated principal. `PROFILE_URI` is no
longer a module constant computed at import — it is `profile_uri(slug)`, and the
MCP resource is registered as a template, `content-data://client/{slug}/profile`.

**How a request finds its client**, in the order the server consults the three
sources — `client_of(ctx)` in `mcp_server/server.py`:

1. `X-Content-Client-Slug` on the connection, when the caller already knows.
2. The principal on the connection, looked up in `app_users`.
3. `CLIENT_SLUG`.

Never a tool argument, in any of the three. `save_post` is model-visible, and a
client the model can name is a client the model can get wrong — the same reason
`CONVERSATION_HEADER` and `OWNER_HEADER` already ride the connection.

Step 3 is what makes this safe to land in one piece: the CLI sets neither header
and an unprovisioned principal has no row, so both land on the configured
default. Until `app_users` has rows in it, **the behaviour is byte-for-byte what
it was**, which is why this went in without a deployment.

### 2. The budget — what is honest about it

**A budget cap is a stop-gate, not a ceiling.** The cost of a call is only known
after it returns, so the check is: *refuse to start if already at the limit.* A
run in flight is not killed mid-sentence.

Overshoot is therefore bounded by the largest single call, not by zero. That is
acceptable because `max_tokens` is already set everywhere (12k chat, 24k detail),
which puts a hard ceiling on any one call. It must be written down rather than
discovered later by someone who expected `$1.00` to mean `$1.00`.

```sql
CREATE TABLE IF NOT EXISTS public.usage_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id      UUID NOT NULL REFERENCES public.clients(id),  -- what is billed
    principal_id   TEXT NOT NULL,                                -- which door, for forensics
    run_id         UUID,
    model          TEXT NOT NULL,
    input_tokens   BIGINT NOT NULL,
    output_tokens  BIGINT NOT NULL,
    cost_micros    BIGINT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS usage_events_client_idx
    ON public.usage_events (client_id, created_at DESC);
```

Both columns, and they are not redundant. The budget is drawn against
`client_id`, so a person with two logins spends one allowance. `principal_id`
stays because "which login ran this" is the question you want answered when
something looks wrong, and it cannot be reconstructed later.

Money is stored as integer micro-dollars. Never as a float: `0.1 + 0.2` is a bug
waiting for a billing dispute. `budget_micros` goes on `public.clients` when
step 2 lands, not on `app_users`.

Where the numbers come from: the Agents SDK returns token usage on the run
result. A price table per model lives in code, in one place, versioned — prices
change and a stale table silently under-bills.

Where the gate goes:
- **Before** any run starts (chat, generation, profile update).
- **Between ideas** inside a generation batch. One batch is 1 title call plus 10
  detail calls; without a check in the loop, a user at 95% spends a whole batch.

Two things that also cost money and must be decided rather than forgotten:
`search_web` and the embedding calls. Either they are metered too, or they are
explicitly declared free and that decision is written here.

### 3. What the user sees, and what the server must never send

Sorin's instinct is right and worth making exact:

> *"Nu cati bani a consumat, ca el nu trebuie sa stie cat de ieftin sau scump e
> modelul AI, ci sa vada procent mai are pana la limita."*

**Hiding the figure in the interface is not hiding it.** If the API returns the
dollar amount and the page merely does not render it, anyone can read it in
devtools in four seconds. The split has to be on the server:

- `GET /api/me/usage` → `{"percent_used": 62}` and nothing else. No cost, no
  token counts, no model name, no limit in dollars.
- `GET /api/admin/users` → the real figures, and **403 for anybody whose row is
  not `role = 'admin'`**.

The admin check belongs in a FastAPI dependency next to the existing identity
dependency, so that forgetting it on a new route is a compile-time-shaped
mistake rather than a silent leak.

### 4. Profiles, and the copy Sorin asked for

- **Viorela** keeps the existing `clients` row. It is the original and only she
  edits it.
- **Sorin** gets his own row whose `profile_md` is a *copy* taken at creation
  time. He edits the copy; hers is untouched. This is what he asked for and it
  falls out of the design for free — a client row is just a row.
- **A new tester** gets an empty profile, plus one button: *"Load Viorela's
  profile"*, which copies the same starting text so they can try the product in
  a minute instead of an hour.

The copy is a copy, not a reference. A shared reference would mean one tester's
edit changing everybody's output, which is the whole thing he wants to avoid.

---

## Order of work

1. `app_users` + resolve the client from the principal. Nothing user-visible;
   everything else depends on it. **Riskiest step** — it touches `PROFILE_URI`,
   the MCP tools and the seed.

   **Server half done, 2026-08-21.** The table, `mcp_server/accounts.py`,
   `client_of(ctx)` with the three-source fallback, the profile resource as a
   template, `ui_resolve_account`, and every one of the ten hard-coded
   `CLIENT_SLUG` uses in the MCP tools replaced. `read_profile` takes a client.
   12 tests in `tests/unit/test_accounts.py`; 143 in total, `ruff` clean.

   **Harness half still open**, and it has one real decision in it. The harness
   must resolve the principal once per request and put the answer on
   `X-Content-Client-Slug`. It cannot simply widen `OWNER_HEADER` to every
   connection to let the server resolve it, because the *absence* of that header
   is what currently keeps `save_posts_batch` unreachable from the CLI and from
   the generation path — widening it would quietly hand a write tool to
   connections that were deliberately denied it. So the harness resolves through
   `ui_resolve_account`, and the open question is caching: a lookup per request
   is a round-trip per request, and accounts change rarely. A short TTL cache is
   the obvious answer; it needs to be a deliberate one.

   Nothing is seeded yet, on purpose. With `app_users` empty, every request falls
   through to `CLIENT_SLUG` and the studio behaves exactly as it did before.
2. Usage metering, recording only. No enforcement yet, so real numbers can be
   watched for a day before anything is refused.
3. The gate, plus the percentage endpoint and the strip in the rail.
4. The admin page: list users, create a user, set a budget, see spend.
5. Entra External ID as a second sign-in provider, when testers who lack a
   Google account actually appear.

Steps 1–4 are the work. Step 5 is configuration, and deliberately last.

---

## Answered, 2026-08-21

- **At the limit:** the run is refused, `402` with a code the interface turns
  into a sentence in the reader's language. No email.
- **Reset:** none. **The allowance is for life**, and Sorin raises it by hand
  from the admin page. His decision, verbatim: *"bugetul e pe viata, il modific
  eu"*. A monthly window would need a `period_start` on `clients` and a windowed
  `SUM`; neither is hard to add later, and neither is built.
- **Who creates users:** `role = 'admin'` only, checked in a FastAPI dependency
  so that forgetting it on a new route is visible at the top of the function.
  The first admin is made by `db/provision.py`, never through the interface.
- **`search_web` and embeddings:** **metered where they are model calls, free
  where they are not.** `search_web` runs through a model and is metered with
  everything else. Embeddings are not: `text-embedding-3-small` is $0.02 per
  million tokens, so a tester's whole allowance could not be spent on them, and
  the rate is in `pricing.py` for the day that stops being true.

## Still open

- **Nobody but Sorin is provisioned.** Viorela deliberately has no `app_users`
  row: she falls through to `CLIENT_SLUG` and keeps the original profile, which
  is the correct behaviour and needs no action until she should own it formally.
- ~~**Disabling an account** has a column and no button.~~ Done on
  2026-08-21: a Suspend/Restore button on the admin page, a timestamp rather
  than a delete, the directory cache invalidated on the spot so a revocation
  does not wait out its minute, and an administrator cannot suspend their own
  account - there would be no second admin to undo it.
- **`evals/cases.json`** still asserts Romanian only.
