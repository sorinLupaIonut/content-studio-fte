# Accounts Sorin creates himself — Entra External ID

Written 2026-08-23. This is the execution plan for the piece
[MULTI-USER.md](MULTI-USER.md#what-to-use-instead) named and deliberately
deferred: an identity provider in which *Sorin issues the credentials*, so a
tester can be handed a username and a password instead of needing a Gmail
address.

The design decision was already taken there and is not reopened here. Sorin
confirmed the choice on 2026-08-23: **Microsoft Entra External ID**, a separate
tenant, alongside Google rather than instead of it. Free below 50,000 monthly
active users; $0.03 per MAU above that.

The reader-facing version, with the diagrams of who governs what, is the
artifact *Harta identităților*.

---

## What is already built

More than the brief assumes. Since 2026-08-21 the admin page lists clients,
edits budgets, suspends and restores principals, and `POST /api/admin/accounts`
creates an account with a role, a copied profile and a lifetime allowance. The
budget gate, the per-client library scoping and the audit are all in place.

None of that changes. `auth.py` keeps reading `x-ms-client-principal-*` and
never learns that a second provider exists.

## The shape changed on 2026-08-23

The first version of this plan had the admin page mint the identity itself,
through Graph, so that one form created both the credential and the studio.
Sorin asked the obvious question — *can the account not just be created in
Entra, and I hand out the username and password?* — and it collapses most of
the work.

It can, and the reason is that **membership of the external tenant is itself
the allowlist**. If nobody can enrol themselves, then "authenticated against
this tenant" means "Sorin created this person", which is precisely the fact the
`.env` allowlist exists to assert. Three pieces of the original plan fall away
with it: the Graph application permission, the pending-account binding keyed on
email, and moving the allowlist into the database.

What has to replace them is one much smaller thing: **the studio row is created
on first sign-in instead of by hand.** Entra can hold an identity; it cannot
hold a profile, a budget, a library or a saved post. Those are rows in Neon, and
without them a person signs in successfully and lands in an application that
does not know who they are.

### The one catch, and it is a real one

Self-service sign-up is on by default in a sign-up-and-sign-in user flow, and
**there is no control in the Entra admin center to turn it off**. It is a single
Microsoft Graph call, on a `beta` endpoint:

```http
PATCH https://graph.microsoft.com/beta/identity/authenticationEventsFlows/{user-flow-id}
{
  "@odata.type": "#microsoft.graph.externalUsersSelfServiceSignUpEventsFlow",
  "onInteractiveAuthFlowStart": {
    "@odata.type": "#microsoft.graph.onInteractiveAuthFlowStartExternalUsersSelfServiceSignUp",
    "isSignUpAllowed": false
  }
}
```

Sorin runs it once from Graph Explorer, signed in as an administrator of the
external tenant — it needs a delegated sign-in, not the application permission
the abandoned design required. Until it is run, anyone who reaches the sign-in
page can create themselves an account, and auto-provisioning would then hand
them a studio. **This call gates the whole design; it is not optional and it is
not a later polish.**

The user flow id cannot be read in the portal either; it is listed through Graph
from the application id, which the portal does show.

### Why auto-provisioning is safe here, and only here

A new account is written with the column default allowance — one dollar — and
the role `user`. It cannot be created as an admin: `db/provision.py` remains the
only path to that, for the reason it always was. Its library starts empty,
because the books are licensed material and copying them onto a tester's shelf
should be a decision. So the worst case of an unexpected sign-in is a stranger
holding an empty studio worth one dollar, and the admin page can suspend them.

The Google provider keeps the `.env` allowlist. Membership of *Google* is not
evidence of anything, so nothing about that door changes.

## Status, 2026-08-23

Everything on this side is written, tested and deployed. It is **inert** until
`AUTH_SELF_PROVISION_PROVIDERS` names a provider: `may_self_provision` stays
false, the new branch in `authenticated` is never entered, and the second
sign-in button is not drawn. That is why it could ship before the tenant exists.

| | |
|---|---|
| `config.py` | `AUTH_SELF_PROVISION_PROVIDERS`, and why it is safe only here |
| `harness/auth.py` | the named provider skips the allowlist; addresses are never matched across providers |
| `harness/main.py` | the branch in `authenticated`, and public `GET /api/auth/options` |
| `mcp_server/accounts.py` | `provision_self`, `slug_from_email` |
| `mcp_server/server.py` | `ui_provision_account`, with its audit row in the same transaction |
| `MainLayout.razor`, `Copy.cs`, `app.css` | the second button, drawn only when the provider exists |
| `infra/` | the OIDC registration, and the setting carried through bicep |

No schema change: `app_users` already accepted the row. What was missing was who
writes it and when.

Two defects were found while writing, both of which would have passed the tests:

- **`resolve_account` answers None for a suspended row**, so provisioning on that
  answer would have handed a revoked tester a new studio on their next request,
  and left an orphan client on every request after. The check is on the row's
  *existence* now.
- **`create_account` ends in `ON CONFLICT (slug) DO UPDATE`**, which is right for
  a hand-typed slug and catastrophic for one derived from an address: two people
  whose mail starts alike would have shared one profile, library and allowance.
  Provisioning has its own SQL, with `DO NOTHING`.

## Done, 2026-08-23 — the tenant exists

All of it was created from the command line rather than the portal, because the
account that owns the subscription becomes Global Administrator of the new
directory and can then reach it with the token it already holds.

| | |
|---|---|
| Tenant | `studioconturi.onmicrosoft.com`, CIAM, data in Europe, `RO` |
| Created by | `Microsoft.AzureActiveDirectory/ciamDirectories` ARM PUT |
| Application | `Studio Viorela`, redirect at `/.auth/login/entra/callback` |
| User flow | sign-up **disabled in the create call**, so the open window never existed |
| Easy Auth | provider `entra`, secret referenced by name |
| `.env` | tenant, tenant id, client id, secret, `AUTH_SELF_PROVISION_PROVIDERS=entra` |

Creating a tester is now: one Graph `POST /users` (or the portal form), hand over
the address and password. The studio appears on their first request.

**A consent screen shows once per person** — "Studio Viorela would like to view
your basic profile". Granting tenant-wide admin consent for the application
removes it; not done, because it was noticed during testing rather than planned,
and it is one click for the tester.

## Order of work

Steps 1 to 4 are Sorin's, at the portal and in Graph Explorer; nothing else can
start without the client credentials they produce, and step 4 must land before
the provider is ever reachable.

1. **Create the External ID tenant.** Separate from
   `sorinlupaciel.onmicrosoft.com`, so test users never enter the workforce
   directory and Security Defaults never forces MFA enrolment on a tester.
2. **Create the sign-up and sign-in user flow** and associate the application
   with it. External ID reaches an application through a user flow; there is no
   way to skip it.
3. **Register the application**: a client id and a client secret for Easy Auth.
   No Graph permission, no admin consent — the harness never calls Graph in this
   design.
4. **Disable sign-up**, with the Graph call above. See the warning there.
5. **Add the provider.** `az containerapp auth openid-connect add`, in
   `infra/enable-auth.ps1` next to the Google block, reading the secret from
   `.env` the way the Google secret already is. Drop
   `--redirect-provider google`: with two providers an automatic redirect would
   pick one for everybody.
6. **Two buttons** on the access screen in
   [MainLayout.razor](../ui/StudioViorela/Layout/MainLayout.razor). Both are
   full page navigations, both carry `prompt=select_account` — see the note
   below.
7. **Provision on first sign-in.** When a principal from this provider has no
   `app_users` row, write the `clients` and `app_users` rows in the same
   transaction as their audit row, and let the request continue. The allowlist
   check is satisfied by the provider, not by `.env`.
8. **Creating a person** is then Sorin in the Entra portal: new user, generated
   password, hand it over. Nothing in this repository runs.

## Notes worth keeping

- **`prompt=select_account` is not cosmetic.** Without it Easy Auth reuses the
  provider session and silently returns the same identity — which reads as "it
  will not let me sign in with another account". Added 2026-08-23 and verified
  against the live app.
- **Write the ampersand raw in Razor.** `&amp;` in a `.razor` attribute is
  encoded a second time and reaches the browser as a literal `&amp;`, which
  turns the next query parameter into `amp;post_login_redirect_uri`. The
  markup is static; `&` passes through as itself.
- **The password never touches this repository.** Microsoft generates it, shows
  it to Sorin in the portal, and forces a change at first sign-in. Nothing here
  stores it, logs it or can read it back — which is the main dividend of not
  building the Graph integration.
- **Nothing here needs a second `clients` row shape.** An account created this
  way is the same `clients` row the terminal already writes; only the identity
  behind it comes from somewhere new.
- **Sorin can hold two identities at once**, which is what he asked for: his
  Google address stays the admin, and a user he creates in the external tenant
  signs him into a separate, empty studio that is a test account in every
  respect. They are different principals, so they are different `clients` rows,
  and neither can see the other's library.
- **The principal id is the user's object id.** Written here earlier as a
  pairwise `sub`; that was wrong for this configuration. Verified on 2026-08-23:
  the value in `x-ms-client-principal-id` is exactly the `id` Graph returns for
  the user, so the portal and the header agree. Nothing depends on it either
  way — the id is never typed anywhere — but the note was misleading.
- **The name header is not an address for this provider.**
  `x-ms-client-principal-name` carries the *display name* from the external
  tenant, where for Google it carries the email. Three attempts to change that
  failed: `nameClaimType` on the provider, an `email` optional claim on the
  application, and correcting `scopes` to three values rather than one string.
  The address is in the token regardless, so `auth.py` reads it out of the
  `x-ms-client-principal` claims blob and keeps the display name separately —
  which turns out to be the better label for a studio anyway. Both end up used:
  the address in `app_users.email`, the name on `clients.name` and in the slug.

## Still Sorin's, not automatable

Creating the tenant, running the sign-up call once, and deciding which testers
exist. `db/provision.py` remains the only way to mint an admin — an admin page
that can create admins is one stolen session away from being somebody else's
admin page, and that reasoning does not weaken because the provider changed.
