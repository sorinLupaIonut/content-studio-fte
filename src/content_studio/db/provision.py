"""Create or update one account, from the terminal.

    uv run python -m content_studio.db.provision \
        --principal 103076558628586194559 --email sorin@example.com \
        --slug sorin --name "Sorin" --role admin --profile-from viorela --budget 5

THE FIRST ADMIN IS MADE HERE, BY HAND, AND ONLY HERE. There is deliberately no
way to grant `admin` through the interface: an admin page that can create admins
is one stolen session away from being somebody else's admin page. Sorin runs this
once against the database, and after that the interface can create ordinary
testers.

`--profile-from` copies another client's profile text. A copy, never a shared
reference - two accounts pointing at one profile row would mean one tester's edit
changing another tester's output, which is the whole thing this design avoids.

`--budget` is in DOLLARS here, because that is what a person types. It is stored
as integer micro-dollars; see `pricing.py` for why there is no float anywhere
past this argument.

WHICH ENDPOINT: this writes business data, so unlike `db.apply` it does not need
the direct endpoint. It uses the pooled one, like the app.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from content_studio import enable_utf8_output
from content_studio.config import MissingConfig, database_url, describe_database
from content_studio.mcp_server.accounts import create_account, list_accounts

enable_utf8_output()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--principal", help="x-ms-client-principal-id of the person")
    parser.add_argument("--email", help="their email, for display only")
    parser.add_argument("--slug", help="client slug, lowercase, e.g. `sorin`")
    parser.add_argument("--name", help="display name of the client")
    parser.add_argument("--provider", default="google")
    parser.add_argument("--role", default="user", choices=["user", "admin"])
    parser.add_argument(
        "--profile-from",
        default=None,
        help="copy this client's profile as a starting point",
    )
    parser.add_argument(
        "--budget", type=float, default=1.0, help="lifetime allowance in dollars"
    )
    parser.add_argument(
        "--list", action="store_true", help="print the provisioned accounts and exit"
    )
    return parser


async def run(args: argparse.Namespace) -> int:
    try:
        url, connect_args = database_url()
    except MissingConfig as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    print(f"Database: {describe_database(url)}")
    engine = create_async_engine(url, connect_args=connect_args, pool_pre_ping=True)
    try:
        async with engine.begin() as sa_conn:
            conn = (await sa_conn.get_raw_connection()).driver_connection

            if args.list:
                rows = await list_accounts(conn)
                if not rows:
                    print("No accounts provisioned yet.")
                for row in rows:
                    flag = " (disabled)" if row["disabled"] else ""
                    # THE LISTING IS OF CLIENTS, NOT SIGN-INS - the LEFT JOIN in
                    # `list_accounts` is deliberate, because listing `app_users`
                    # would hide any client nobody has signed in as, such as the
                    # original one, whose budget would then be unreachable from
                    # the only page that can change it. So both of these are
                    # normally NULL, and formatting None with a width raises:
                    # this listing crashed on exactly the row it exists to show.
                    email = row["email"] or "—"
                    principal = row["principal_id"] or "(no sign-in yet)"
                    print(
                        f"  {row['role']:<5} {row['client_slug']:<12} "
                        f"{email:<32} {principal}{flag}"
                    )
                return 0

            missing = [
                name
                for name in ("principal", "email", "slug", "name")
                if not getattr(args, name)
            ]
            if missing:
                print(
                    "Missing required arguments: " + ", ".join(f"--{m}" for m in missing),
                    file=sys.stderr,
                )
                return 1

            # Dollars in, micro-dollars stored. `round` rather than `int` so that
            # a typed 0.1 does not become 99_999 through binary floating point.
            budget_micros = round(args.budget * 1_000_000)
            account = await create_account(
                conn,
                principal_id=args.principal,
                email=args.email,
                client_slug=args.slug,
                client_name=args.name,
                provider=args.provider,
                role=args.role,
                profile_from=args.profile_from,
                budget_micros=budget_micros,
            )
    finally:
        await engine.dispose()

    source = args.profile_from or "gol"
    print(
        f"Provisioned {account.role} {account.client_slug!r} "
        f"({account.email}) with ${args.budget:.2f}, profile from: {source}"
    )
    return 0


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
