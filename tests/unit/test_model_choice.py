"""The model picker's four lists have to agree, and none of them can see the others.

A model name added on 2026-09-01 has to appear in four places before the picker
works and stays honest:

    config.GENERATION_MODELS          what an account may be offered
    generation.ModelChoice            what the request contract accepts
    pricing.PRICES                    what the budget is charged
    Values.cs → ModelLabel            what the client reads

Each failure is quiet and each is different. A name missing from `ModelChoice`
is a 422 on a button she just pressed. A name missing from `PRICES` falls
through to `pricing.FALLBACK`, which is deliberately the most expensive row in
the table — so the budget would be charged gpt-5 rates for whatever it was. A
name missing from `Values.cs` puts the string `gpt-5-mini` in front of a client
who is shown a percentage precisely so she never has to think about models.

`models_for` is here too, because it is the permission and not the shape check:
`ModelChoice` says the name is real, this says the account may spend at it.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import get_args

from content_studio import pricing
from content_studio.config import (
    CLIENT_SLUG,
    GENERATION_MODELS,
    MODEL_CHOICE_CLIENTS,
    models_for,
)
from content_studio.harness.generation import ModelChoice

VALUES_CS = (
    Path(__file__).resolve().parents[2]
    / "ui"
    / "StudioViorela"
    / "Localization"
    / "Values.cs"
)

ARM = re.compile(r'"([^"]+)"\s*=>\s*t\.Pick\(\s*"([^"]*)"\s*,\s*"([^"]*)"\s*\)')


def model_labels() -> dict[str, tuple[str, str]]:
    """{model id: (romanian, english)} exactly as the interface defines it."""
    text = VALUES_CS.read_text("utf-8")
    start = text.index("public static string ModelLabel(")
    body = text[start : text.index("};", start)]
    return {value: (ro, en) for value, ro, en in ARM.findall(body)}


class ModelListsAgree(unittest.TestCase):
    def test_the_contract_accepts_exactly_what_may_be_offered(self) -> None:
        self.assertEqual(
            sorted(GENERATION_MODELS),
            sorted(get_args(ModelChoice)),
            "GENERATION_MODELS and ModelChoice have drifted: one of them names a "
            "model the other refuses",
        )

    def test_every_offered_model_is_priced(self) -> None:
        # Not a style point. `pricing.rate_for` falls back to the most expensive
        # row in the table rather than to zero, on purpose - so an unpriced
        # model does not run free, it drains an allowance at gpt-5 rates while
        # the report says the account chose something else.
        for model in GENERATION_MODELS:
            with self.subTest(model=model):
                self.assertTrue(
                    pricing.is_priced(model),
                    f"{model} has no row in pricing.PRICES",
                )

    def test_every_offered_model_has_a_label_in_both_languages(self) -> None:
        labels = model_labels()
        for model in GENERATION_MODELS:
            with self.subTest(model=model):
                self.assertIn(
                    model, labels, f"Values.cs → ModelLabel has no arm for {model}"
                )
                romanian, english = labels[model]
                self.assertTrue(romanian.strip(), f"{model} has no Romanian label")
                self.assertTrue(english.strip(), f"{model} has no English label")

    def test_no_label_names_a_price(self) -> None:
        # The rule that survived the picker's removal and came back with it: the
        # labels say how carefully the thing is written, never what it costs.
        # The studio shows a tester a percentage and never a figure, and
        # "ieftin / scump" in a select would undo that in one glance.
        forbidden = (
            "ieftin", "scump", "cost", "price", "cheap", "expensive",
            "$", "dolar", "bani", "gratis", "free", "premium",
        )
        for model, (romanian, english) in model_labels().items():
            for word in forbidden:
                with self.subTest(model=model, word=word):
                    self.assertNotIn(word, romanian.lower())
                    self.assertNotIn(word, english.lower())


class WhoMayChoose(unittest.TestCase):
    def test_the_default_is_first(self) -> None:
        # `_batch_model` falls back to GENERATION_TITLE_MODEL, but every caller
        # that offers a list offers this one first, and an account with no
        # picker is served exactly it.
        self.assertEqual(models_for(None)[0], GENERATION_MODELS[0])

    def test_an_account_with_no_choice_gets_one_model(self) -> None:
        self.assertEqual(len(models_for("somebody-else")), 1)
        self.assertEqual(len(models_for(None)), 1)
        self.assertEqual(len(models_for("")), 1)

    def test_the_named_accounts_get_the_whole_list(self) -> None:
        self.assertTrue(MODEL_CHOICE_CLIENTS, "nobody may choose at all")
        for slug in MODEL_CHOICE_CLIENTS:
            with self.subTest(slug=slug):
                self.assertEqual(models_for(slug), GENERATION_MODELS)

    def test_the_client_is_one_of_them_by_default(self) -> None:
        # The picker exists to answer HER question about HER output. If the
        # default ever stops including her own account, the experiment it was
        # built for cannot be run from the interface at all.
        self.assertIn(CLIENT_SLUG, MODEL_CHOICE_CLIENTS)


if __name__ == "__main__":
    unittest.main()
