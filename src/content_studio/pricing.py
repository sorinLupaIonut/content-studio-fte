"""What a model call costs, in integer micro-dollars.

One table, one place. Prices change, and a table copied into two modules drifts
without anyone noticing until a total looks wrong.

MICRO-DOLLARS, INTEGER, EVERYWHERE. 1_000_000 = $1.00. There is no float in this
module and none in the `usage_events` table, because money in binary floating
point eventually produces a total nobody can reproduce.

Verified against the OpenAI pricing page on 2026-08-21. Prices move; when they
do, edit here and nowhere else. Rows already written keep the cost they were
charged, on purpose - see the comment on `usage_events.cost_micros`.
"""

from __future__ import annotations

from typing import NamedTuple


class Rate(NamedTuple):
    """Micro-dollars per one million tokens."""

    input_micros: int
    output_micros: int
    cached_input_micros: int = 0


#: $0.25 / $2.00 per 1M for mini, $0.05 / $0.40 for nano, $0.02 in for the
#: embedding model. The third figure is what an input token already in the
#: provider's prompt cache costs — a tenth of a fresh one, across this family.
#:
#: CACHE WRITES ARE NOT PRICED HERE, AND THAT IS NOT AN OMISSION. Verified
#: against the pricing page on 2026-08-24: the "cache writes" column is `-` for
#: every gpt-5 model this project uses; only the gpt-5.6-* family charges for
#: them. If `MODEL` is ever pointed at one of those, this table needs a fourth
#: figure, or the studio will under-charge.
PRICES: dict[str, Rate] = {
    "gpt-5-mini": Rate(250_000, 2_000_000, 25_000),
    # Nano left the allowlist on 2026-08-27 and its price stays here anyway:
    # `usage_events` holds rows that were charged at it, and an unpriced model
    # falls through to the most expensive rate below - which would silently
    # rewrite the history of every account that ever ran a nano batch.
    "gpt-5-nano": Rate(50_000, 400_000, 5_000),
    "text-embedding-3-small": Rate(20_000, 0, 20_000),
}

#: What an unrecognised model is charged at. Deliberately the most expensive row
#: in the table rather than zero: if someone points `MODEL` at something new and
#: forgets to price it, the budget should over-charge and be noticed, never
#: under-charge and let a test account run free.
FALLBACK = Rate(250_000, 2_000_000, 250_000)


def rate_for(model: str) -> Rate:
    """The rate for a model, falling back expensively rather than to zero."""
    return PRICES.get(model, FALLBACK)


def is_priced(model: str) -> bool:
    """False when `rate_for` is guessing. Worth surfacing in an admin view."""
    return model in PRICES


def cost_micros(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> int:
    """Integer micro-dollars for one call, rounded up.

    `input_tokens` is the provider's total and ALREADY INCLUDES the cached ones,
    so the cached share is subtracted before the fresh rate is applied. Getting
    that backwards double-counts the largest number in the calculation.

    Ignoring the cache was this project's most expensive arithmetic mistake.
    Measured on 2026-08-23, one batch of ten ideas sent 963,852 input tokens of
    which 826,880 — 86% — were cache reads. Charged flat, that batch cost the
    account $0.249; the real bill was $0.089. Every allowance in the database was
    draining 2.8x faster than the money actually leaving the card.

    `cached_input_tokens` defaults to zero, which reproduces the old, expensive
    answer. That default is deliberate: a caller that does not know how many
    tokens were cached should over-charge, never guess a discount.

    Rounded up rather than to nearest so that a great many tiny calls cannot sum
    to less than they cost. The error is at most one micro-dollar per call, in
    the safe direction.
    """
    rate = rate_for(model)
    # Clamped rather than trusted. A provider that ever reports more cached
    # tokens than input tokens would otherwise produce a negative fresh count
    # and a call that credits the account.
    cached = max(0, min(int(cached_input_tokens), int(input_tokens)))
    fresh = int(input_tokens) - cached
    total = (
        fresh * rate.input_micros
        + cached * rate.cached_input_micros
        + int(output_tokens) * rate.output_micros
    )
    return -(-total // 1_000_000)  # ceil, without floats


def percent_used(spent_micros: int, budget_micros: int) -> int:
    """How much of the allowance is gone, 0-100, as a whole number.

    THE ONLY NUMBER THE USER IS EVER SHOWN. Sorin's rule: a tester must not learn
    what the model costs. Hiding the figure in the interface would not hide it -
    anyone can read a JSON response - so the split is here, on the server, and
    the endpoint that serves a tester returns this and nothing else.

    Capped at 100 because a run that overshot its allowance should read as full,
    not as 103%.
    """
    if budget_micros <= 0:
        return 100
    return min(100, (spent_micros * 100) // budget_micros)
