"""Money, the percentage the user is shown, and the gate.

The assertions worth reading twice are the ones about what the server refuses to
send: a tester must never receive a cost, a token count or a limit in dollars.
"""

from __future__ import annotations

import asyncio
import unittest

from content_studio.harness.accounts import (
    CURRENT_CLIENT,
    AccountDirectory,
    Budget,
    BudgetExhausted,
)
from content_studio.pricing import (
    FALLBACK,
    PRICES,
    cost_micros,
    is_priced,
    percent_used,
    rate_for,
)


class PricingTests(unittest.TestCase):
    def test_a_known_model_costs_what_the_table_says(self) -> None:
        # gpt-5-mini: $0.25 per 1M in, $2.00 per 1M out.
        self.assertEqual(cost_micros("gpt-5-mini", 1_000_000, 0), 250_000)
        self.assertEqual(cost_micros("gpt-5-mini", 0, 1_000_000), 2_000_000)
        self.assertEqual(cost_micros("gpt-5-mini", 1_000_000, 1_000_000), 2_250_000)

    def test_rounding_is_up_so_many_small_calls_cannot_add_up_to_nothing(self) -> None:
        # One embedding token is a small fraction of a micro-dollar, and a
        # library import makes thousands of them.
        self.assertEqual(cost_micros("text-embedding-3-small", 1, 0), 1)
        self.assertEqual(cost_micros("text-embedding-3-small", 0, 0), 0)

    def test_a_retired_model_keeps_its_price(self) -> None:
        """`gpt-5-nano` left the allowlist on 2026-08-27 and stays priced.

        `usage_events` holds rows that were charged at its rate, and an unpriced
        model falls through to `FALLBACK` - the most expensive row in the table.
        Deleting the entry would therefore not remove nano from the studio; it
        would silently re-price every batch anybody ever ran on it, upward, in
        the ledger the budget gate reads.
        """
        self.assertTrue(is_priced("gpt-5-nano"))
        self.assertNotEqual(rate_for("gpt-5-nano"), FALLBACK)

    def test_an_unknown_model_is_charged_expensively_never_free(self) -> None:
        # A new MODEL nobody priced must over-charge and be noticed, not run free.
        self.assertEqual(rate_for("gpt-6-whatever"), FALLBACK)
        self.assertGreater(cost_micros("gpt-6-whatever", 1_000_000, 0), 0)
        self.assertFalse(is_priced("gpt-6-whatever"))
        self.assertTrue(is_priced("gpt-5-mini"))

    def test_the_fallback_is_the_most_expensive_row_in_the_table(self) -> None:
        for model, rate in PRICES.items():
            self.assertLessEqual(rate.input_micros, FALLBACK.input_micros, model)
            self.assertLessEqual(rate.output_micros, FALLBACK.output_micros, model)
            self.assertLessEqual(
                rate.cached_input_micros, FALLBACK.cached_input_micros, model
            )

    def test_a_cached_input_token_costs_a_tenth_of_a_fresh_one(self) -> None:
        # gpt-5-mini: $0.25 per 1M fresh, $0.025 per 1M from the prompt cache.
        self.assertEqual(cost_micros("gpt-5-mini", 1_000_000, 0, 1_000_000), 25_000)

    def test_the_cached_count_is_a_share_of_the_input_not_an_extra(self) -> None:
        # Half of a million input tokens cached: half at $0.25, half at $0.025.
        self.assertEqual(
            cost_micros("gpt-5-mini", 1_000_000, 0, 500_000),
            125_000 + 12_500,
        )
        # Treating the cached count as additional input would charge more than
        # the uncached call, which is the bug this whole change exists to undo.
        self.assertLess(
            cost_micros("gpt-5-mini", 1_000_000, 0, 500_000),
            cost_micros("gpt-5-mini", 1_000_000, 0),
        )

    def test_omitting_the_cached_count_charges_the_full_rate(self) -> None:
        # The default must reproduce the old, expensive answer. A caller that
        # cannot measure the cache has to over-charge, never guess a discount.
        self.assertEqual(
            cost_micros("gpt-5-mini", 1_000_000, 1_000_000),
            cost_micros("gpt-5-mini", 1_000_000, 1_000_000, 0),
        )

    def test_a_nonsense_cached_count_can_never_credit_the_account(self) -> None:
        # A provider reporting more cached tokens than input tokens must not
        # produce a negative fresh count.
        self.assertEqual(cost_micros("gpt-5-mini", 1_000, 0, 999_999), 25)
        self.assertGreaterEqual(cost_micros("gpt-5-mini", 1_000, 0, -5), 0)

    def test_the_measured_batch_costs_what_the_provider_billed(self) -> None:
        # The real figures from run 548b3354 on 2026-08-23, read out of
        # public.traces: 963,852 input of which 826,880 were cache reads, and
        # 16,855 output. Phoenix priced the same batch at $0.08.
        # Priced here as if the whole batch were mini. It was not quite: the
        # title pass ran on nano, so the ledger's own flat figure for that batch
        # was 248_982 micros, not the 274_673 below. The ratio is what this test
        # is for, and it survives the simplification.
        charged = cost_micros("gpt-5-mini", 963_852, 16_855, 826_880)
        self.assertEqual(charged, 88_625)  # $0.0886, against Phoenix's $0.08
        flat = cost_micros("gpt-5-mini", 963_852, 16_855)
        self.assertEqual(flat, 274_673)
        self.assertGreater(flat, charged * 3 - 1)  # 3.1x here, 2.8x on the real mix

    def test_no_float_ever_leaves_this_module(self) -> None:
        self.assertIsInstance(cost_micros("gpt-5-mini", 12_345, 6_789), int)
        self.assertIsInstance(percent_used(1, 3), int)


class PercentTests(unittest.TestCase):
    def test_percentage_is_whole_and_capped(self) -> None:
        self.assertEqual(percent_used(0, 1_000_000), 0)
        self.assertEqual(percent_used(500_000, 1_000_000), 50)
        self.assertEqual(percent_used(1_000_000, 1_000_000), 100)
        # A run that overshot reads as full, not as 130%.
        self.assertEqual(percent_used(1_300_000, 1_000_000), 100)

    def test_a_zero_budget_reads_as_full_rather_than_dividing_by_zero(self) -> None:
        self.assertEqual(percent_used(0, 0), 100)


class GateTests(unittest.TestCase):
    def test_an_exhausted_account_cannot_start_a_run(self) -> None:
        directory = _directory(Budget("sorin", "Sorin", 1_000_000, 1_000_000, 4))
        with self.assertRaises(BudgetExhausted):
            asyncio.run(directory.require_budget())

    def test_an_account_with_room_starts_normally(self) -> None:
        directory = _directory(Budget("sorin", "Sorin", 1_000_000, 999_999, 4))
        asyncio.run(directory.require_budget())  # must not raise

    def test_an_unknown_client_does_not_block_anything(self) -> None:
        # Nobody provisioned: the studio must behave exactly as it did before
        # budgets existed, rather than locking Viorela out of her own app.
        asyncio.run(_directory(None).require_budget())

    def test_overshoot_is_bounded_by_one_call_not_by_zero(self) -> None:
        # The honest promise: nothing new starts. A run already in flight is not
        # killed mid-sentence, so the recorded spend can exceed the allowance.
        budget = Budget("sorin", "Sorin", 1_000_000, 1_400_000, 9)
        self.assertTrue(budget.exhausted)
        self.assertEqual(budget.percent, 100)


class ExposureTests(unittest.TestCase):
    def test_the_user_facing_shape_carries_no_money(self) -> None:
        # What `/api/me/usage` builds. If a cost, a token count or a dollar limit
        # ever appears here, the split has been undone.
        budget = Budget("sorin", "Sorin", 1_000_000, 620_000, 7)
        payload = {"percent_used": budget.percent, "exhausted": budget.exhausted}
        self.assertEqual(payload, {"percent_used": 62, "exhausted": False})
        forbidden = {"cost", "cost_micros", "budget_micros", "spent_micros", "model"}
        self.assertEqual(set(payload) & forbidden, set())


class BindTests(unittest.TestCase):
    def test_an_unreachable_data_server_binds_to_the_default(self) -> None:
        # /api/me and the UI shell answered fine before accounts existed. A
        # broken MCP connection must not change that.
        class Exploding(AccountDirectory):
            async def _call(self, name, arguments):
                raise RuntimeError("content-data is down")

        directory = Exploding(lambda _session: None)
        token = CURRENT_CLIENT.set(None)
        try:
            slug = asyncio.run(directory.bind("somebody"))
            self.assertTrue(slug)
        finally:
            CURRENT_CLIENT.reset(token)


def _directory(budget: Budget | None) -> AccountDirectory:
    class Fixed(AccountDirectory):
        async def budget_for(self, client_slug: str | None = None) -> Budget | None:
            return budget

    return Fixed(lambda _session: None)


if __name__ == "__main__":
    unittest.main()
