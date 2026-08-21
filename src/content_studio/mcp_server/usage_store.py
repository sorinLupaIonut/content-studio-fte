"""Recording what was spent, and answering how much is left.

Lives inside the MCP server because that is the only thing allowed to touch the
database (rule 1). The harness records and asks through internal `ui_*`
operations the model never sees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

INSERT_USAGE_SQL = """
INSERT INTO public.usage_events
    (client_id, principal_id, kind, model, input_tokens, output_tokens, cost_micros)
SELECT c.id, $2, $3, $4, $5, $6, $7
  FROM public.clients c
 WHERE c.slug = $1
RETURNING id
"""

# One round trip for both halves of the answer. LEFT JOIN, not JOIN: a client who
# has never spent anything has no rows in `usage_events` and must still come back
# with a budget rather than with nothing at all.
BUDGET_SQL = """
SELECT c.id                                  AS client_id,
       c.slug                                AS client_slug,
       c.name                                AS client_name,
       c.budget_micros                       AS budget_micros,
       COALESCE(SUM(u.cost_micros), 0)::BIGINT AS spent_micros,
       COUNT(u.id)::BIGINT                   AS events
  FROM public.clients c
  LEFT JOIN public.usage_events u ON u.client_id = c.id
 WHERE c.slug = $1
 GROUP BY c.id, c.slug, c.name, c.budget_micros
"""

SET_BUDGET_SQL = """
UPDATE public.clients SET budget_micros = $2, updated_at = NOW()
 WHERE slug = $1
RETURNING budget_micros
"""

# The admin view: every account, what it has and what it has used. Ordered by how
# close each is to its limit, because that is the row worth looking at first.
ALL_USAGE_SQL = """
SELECT c.slug                                  AS client_slug,
       c.name                                  AS client_name,
       c.budget_micros                         AS budget_micros,
       COALESCE(SUM(u.cost_micros), 0)::BIGINT AS spent_micros,
       COUNT(u.id)::BIGINT                     AS events,
       MAX(u.created_at)                       AS last_used_at
  FROM public.clients c
  LEFT JOIN public.usage_events u ON u.client_id = c.id
 GROUP BY c.id, c.slug, c.name, c.budget_micros
 ORDER BY (COALESCE(SUM(u.cost_micros), 0)::NUMERIC
           / GREATEST(c.budget_micros, 1)) DESC, c.slug
"""


@dataclass(frozen=True, slots=True)
class Budget:
    client_slug: str
    client_name: str
    budget_micros: int
    spent_micros: int
    events: int

    @property
    def remaining_micros(self) -> int:
        return max(0, self.budget_micros - self.spent_micros)

    @property
    def exhausted(self) -> bool:
        return self.spent_micros >= self.budget_micros

    def as_dict(self) -> dict[str, Any]:
        """The full figures. Never handed to a tester - see `pricing.percent_used`."""
        return {
            "client_slug": self.client_slug,
            "client_name": self.client_name,
            "budget_micros": self.budget_micros,
            "spent_micros": self.spent_micros,
            "remaining_micros": self.remaining_micros,
            "events": self.events,
            "exhausted": self.exhausted,
        }


async def record_usage(
    conn: Any,
    *,
    client_slug: str,
    principal_id: str,
    kind: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_micros: int,
) -> str | None:
    """Append one call. Returns None if the client slug does not exist.

    Silent on an unknown client rather than raising: this runs after a model call
    that already succeeded and whose answer is on its way to the user. Losing the
    meter row is bad; turning a delivered answer into an error because of the
    meter is worse.
    """
    row_id = await conn.fetchval(
        INSERT_USAGE_SQL,
        client_slug,
        principal_id,
        kind,
        model,
        int(input_tokens),
        int(output_tokens),
        int(cost_micros),
    )
    return str(row_id) if row_id is not None else None


async def load_budget(conn: Any, client_slug: str) -> Budget | None:
    row = await conn.fetchrow(BUDGET_SQL, client_slug)
    if row is None:
        return None
    return Budget(
        client_slug=row["client_slug"],
        client_name=row["client_name"],
        budget_micros=int(row["budget_micros"]),
        spent_micros=int(row["spent_micros"]),
        events=int(row["events"]),
    )


async def set_budget(conn: Any, client_slug: str, budget_micros: int) -> int | None:
    value = await conn.fetchval(SET_BUDGET_SQL, client_slug, max(0, int(budget_micros)))
    return int(value) if value is not None else None


async def all_usage(conn: Any) -> list[dict[str, Any]]:
    rows = await conn.fetch(ALL_USAGE_SQL)
    return [
        {
            "client_slug": row["client_slug"],
            "client_name": row["client_name"],
            "budget_micros": int(row["budget_micros"]),
            "spent_micros": int(row["spent_micros"]),
            "events": int(row["events"]),
            "last_used_at": (
                row["last_used_at"].isoformat() if row["last_used_at"] is not None else None
            ),
        }
        for row in rows
    ]
