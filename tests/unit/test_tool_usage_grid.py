"""The grid's labels, checked without a model, a container or a key.

`evals/tool_usage.py` spends real money per square, so the part that decides
WHAT a square expects has to be right before any of them run. Three things are
held here and each has a way of going wrong quietly:

  · the axes are the domain contract - a format the interface cannot produce is
    a case that measures fiction, and a format it CAN produce and the grid does
    not list is a hole nobody sees;
  · the expectation is composed from two manifests (`references.json` for the
    format half, `tool-usage-grid.json` for the source half) and a composition
    is exactly where a right table and a right table make a wrong answer;
  · the route is read out of shell commands by substring, which is loose on
    purpose - so the cases that must NOT match are worth more than the ones
    that must.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import get_args

from content_studio.harness.generation import (
    FormatChoice,
    PillarChoice,
    SourceChoice,
)
from content_studio.worker import reference_index
from evals.tool_usage import (
    Expectation,
    Route,
    all_cases,
    expectation,
    grid,
    references_for,
    route_from,
    scenario_of,
    spine,
    verdict,
)

SPEC = grid()


def fake_result(commands: list[str], tools: list[str]):
    """A finished run, in the only shape `calls_in` reads: `new_items`."""

    items = []
    for index, command in enumerate(commands):
        items.append(
            SimpleNamespace(
                type="tool_call_item",
                raw_item=SimpleNamespace(
                    call_id=f"shell-{index}",
                    name="exec_command",
                    arguments=f'{{"command": {command!r}}}'.replace("'", '"'),
                ),
            )
        )
    for index, tool in enumerate(tools):
        items.append(
            SimpleNamespace(
                type="tool_call_item",
                raw_item=SimpleNamespace(
                    call_id=f"tool-{index}", name=tool, arguments="{}"
                ),
            )
        )
    return SimpleNamespace(new_items=items, to_input_list=lambda: items)


class AxesAreTheDomainContract(unittest.TestCase):
    def test_the_axes_are_exactly_what_the_interface_can_ask_for(self) -> None:
        """Neither a value the form cannot produce, nor a hole where one is."""

        self.assertEqual(set(SPEC["axes"]["format"]), set(get_args(FormatChoice)))
        self.assertEqual(set(SPEC["axes"]["pillar"]), set(get_args(PillarChoice)))
        self.assertEqual(set(SPEC["axes"]["source"]), set(get_args(SourceChoice)))

    def test_every_source_has_a_rule_and_the_focus_axis_has_the_absent_case(self) -> None:
        self.assertEqual(set(SPEC["sources"]), set(get_args(SourceChoice)))
        # Focus is the one choice that may legitimately be missing, so "missing"
        # has to be one of the squares.
        self.assertIn(None, SPEC["axes"]["focus"])

    def test_the_grid_is_the_product_of_its_axes_and_every_id_is_unique(self) -> None:
        cases = all_cases(SPEC)
        axes = SPEC["axes"]
        expected = (
            2 * len(axes["format"]) * len(axes["pillar"]) * len(axes["source"])
            * len(axes["focus"])
        )
        self.assertEqual(len(cases), expected)
        self.assertEqual(len({c.id for c in cases}), expected)


class TheExpectationIsComposedFromBothManifests(unittest.TestCase):
    def test_reel_details_ask_for_one_reel_reference_and_refuse_the_rest(self) -> None:
        #: One, not four. On 2026-08-28 the per-format method and its worked
        #: examples were merged into one file each - the examples file was
        #: opened 0 times in 16 runs whenever a method file had already answered
        #: the format, and one file per format cannot be half-read. The hook
        #: formulations went further, into the body: they depend on nothing, and
        #: as a reference they were delivered 0/12 on the run that measured them.
        found = expectation(SPEC, "detalii", "Reel", "Memorie")
        self.assertEqual(found.references_required, ("dezvolta-postarea/reel.md",))
        for other in ("stories.md", "carusel.md"):
            self.assertIn(
                f"dezvolta-postarea/{other}", found.references_forbidden, other
            )

    def test_each_format_asks_for_its_own_and_forbids_the_other_two(self) -> None:
        """The whole point of the format axis: the tables must not overlap."""

        own = {
            format: set(expectation(SPEC, "detalii", format, "Memorie").references_required)
            for format in SPEC["axes"]["format"]
        }
        for format, required in own.items():
            forbidden = set(
                expectation(SPEC, "detalii", format, "Memorie").references_forbidden
            )
            self.assertFalse(required & forbidden, format)
            for other, theirs in own.items():
                if other != format:
                    # Everything unique to another format is refused here.
                    self.assertTrue(theirs - required <= forbidden | required, other)

    def test_titles_never_ask_for_a_phase_two_reference(self) -> None:
        for format in SPEC["axes"]["format"]:
            found = expectation(SPEC, "titluri", format, "Memorie")
            self.assertEqual(found.references_required, ())
            self.assertEqual(found.skill, "propune-postari")

    def test_the_source_decides_a_tool_and_never_a_file(self) -> None:
        """Since 2026-08-28 the two axes do not overlap at all.

        The shelf was the one reference the source owned, and it moved into the
        phase-1 body - it was 1.6 KB, and `titluri-reel-combinat` failed twice
        in a row on not opening it. So the source axis now decides tools only,
        and the format axis decides files only. Anything else here is a leak.
        """

        for source in SPEC["axes"]["source"]:
            for phase in ("titluri", "detalii"):
                found = expectation(SPEC, phase, "Reel", source)
                for name in (*found.references_required, *found.references_forbidden):
                    self.assertTrue(name.startswith("dezvolta-postarea/"), name)

        titles = expectation(SPEC, "titluri", "Reel", "Cărți")
        self.assertEqual(titles.references_required, ())
        self.assertEqual(titles.tools_required, ("search_books",))
        self.assertIn("search_web", titles.tools_forbidden)
        self.assertEqual(
            expectation(SPEC, "detalii", "Reel", "Cărți").tools_required,
            ("search_books",),
        )

    def test_memory_calls_nothing_in_either_phase(self) -> None:
        for phase in ("titluri", "detalii"):
            found = expectation(SPEC, phase, "Reel", "Memorie")
            self.assertEqual(found.tools_required, ())
            self.assertEqual(set(found.tools_forbidden), {"search_books", "search_web"})

    def test_combinat_is_any_of_rather_than_both(self) -> None:
        found = expectation(SPEC, "titluri", "Reel", "Combinat")
        self.assertEqual(found.tools_required, ())
        self.assertEqual(set(found.tools_any_of), {"search_books", "search_web"})
        self.assertEqual(found.tools_forbidden, ())

    def test_every_reference_a_scenario_asks_for_is_actually_on_disk(self) -> None:
        """A renamed file makes an expectation nothing can ever satisfy."""

        on_disk = set(reference_index())
        for phase in ("titluri", "detalii"):
            for format in SPEC["axes"]["format"]:
                scenario = scenario_of(SPEC, phase, format)
                required, forbidden = references_for(scenario)
                for name in (*required, *forbidden):
                    self.assertIn(name, on_disk, f"{scenario}: {name}")


class TheSpineCoversTheGrid(unittest.TestCase):
    def test_one_case_per_distinct_label_and_every_axis_value_present(self) -> None:
        cases = all_cases(SPEC)
        chosen = spine(cases)
        labels = {(c.phase, c.format, c.source) for c in cases}
        self.assertEqual(len(chosen), len(labels))
        self.assertEqual({(c.phase, c.format, c.source) for c in chosen}, labels)
        # The two axes that are rotated rather than enumerated still all appear -
        # that is the claim the reduction rests on.
        self.assertEqual({c.pillar for c in chosen}, set(SPEC["axes"]["pillar"]))
        self.assertEqual({c.focus for c in chosen}, set(SPEC["axes"]["focus"]))

    def test_the_spine_is_the_same_set_every_time(self) -> None:
        cases = all_cases(SPEC)
        self.assertEqual([c.id for c in spine(cases)], [c.id for c in spine(cases)])


class TheRouteIsReadOutOfTheShellCommands(unittest.TestCase):
    def test_a_healthy_reel_run_names_its_skill_references_and_tool(self) -> None:
        route = route_from(
            fake_result(
                [
                    "cat .agents/dezvolta-postarea/SKILL.md",
                    "cat .agents/dezvolta-postarea/references/reel.md",
                ],
                ["search_books"],
            )
        )
        self.assertEqual(route.skills, ["dezvolta-postarea"])
        self.assertEqual(route.references, ["dezvolta-postarea/reel.md"])
        self.assertEqual(route.tools, ["search_books"])

    def test_a_shell_that_read_nothing_leaves_the_route_empty(self) -> None:
        """The failure this whole shape has: `bash`, twice, and ten titles.

        Measured on 2026-08-27 with gpt-5-nano. Nothing raises, so the eval is
        the only thing that can say it happened.
        """

        route = route_from(fake_result(["bash", "bash"], []))
        self.assertEqual(route.skills, [])
        self.assertEqual(route.references, [])

    def test_reading_one_file_twice_is_one_reference(self) -> None:
        route = route_from(
            fake_result(
                [
                    "sed -n '1,200p' .agents/dezvolta-postarea/references/stories.md",
                    "sed -n '200,400p' .agents/dezvolta-postarea/references/stories.md",
                ],
                [],
            )
        )
        self.assertEqual(route.references, ["dezvolta-postarea/stories.md"])


class TheVerdictSplitsIntoThree(unittest.TestCase):
    LABEL = Expectation(
        skill="dezvolta-postarea",
        references_required=("dezvolta-postarea/reel.md",),
        references_forbidden=("dezvolta-postarea/stories.md",),
        tools_required=("search_books",),
        tools_any_of=(),
        tools_forbidden=("search_web",),
    )

    def test_a_correct_route_scores_one_everywhere(self) -> None:
        scored = verdict(
            Route(
                skills=["dezvolta-postarea"],
                references=["dezvolta-postarea/reel.md"],
                tools=["search_books"],
            ),
            self.LABEL,
        )
        self.assertEqual(
            (scored["router"], scored["references"], scored["tools"], scored["score"]),
            (1.0, 1.0, 1.0, 1.0),
        )

    def test_a_missing_reference_costs_only_the_reference_score(self) -> None:
        scored = verdict(
            Route(skills=["dezvolta-postarea"], references=[], tools=["search_books"]),
            self.LABEL,
        )
        self.assertEqual(scored["router"], 1.0)
        self.assertEqual(scored["tools"], 1.0)
        self.assertEqual(scored["references"], 0.0)
        self.assertEqual(scored["score"], 0.0)

    def test_a_reference_from_another_format_is_surplus_not_a_gap(self) -> None:
        scored = verdict(
            Route(
                skills=["dezvolta-postarea"],
                references=[
                    "dezvolta-postarea/reel.md",
                    "dezvolta-postarea/stories.md",
                ],
                tools=["search_books"],
            ),
            self.LABEL,
        )
        self.assertEqual(scored["missing"], [])
        self.assertTrue(scored["surplus"])
        self.assertEqual(scored["score"], 0.0)

    def test_a_tool_from_another_source_is_surplus(self) -> None:
        scored = verdict(
            Route(
                skills=["dezvolta-postarea"],
                references=["dezvolta-postarea/reel.md"],
                tools=["search_books", "search_web"],
            ),
            self.LABEL,
        )
        self.assertEqual(scored["tools"], 0.0)
        self.assertTrue(any("altă sursă" in reason for reason in scored["surplus"]))

    def test_any_of_is_satisfied_by_either_and_by_neither_it_is_not(self) -> None:
        label = Expectation(
            skill="propune-postari",
            references_required=(),
            references_forbidden=(),
            tools_required=(),
            tools_any_of=("search_books", "search_web"),
            tools_forbidden=(),
        )
        route = Route(skills=["propune-postari"], references=[], tools=["search_web"])
        self.assertEqual(verdict(route, label)["score"], 1.0)
        empty = Route(skills=["propune-postari"], references=[], tools=[])
        self.assertEqual(verdict(empty, label)["tools"], 0.0)

    def test_a_run_that_failed_scores_zero_everywhere_and_says_why(self) -> None:
        """Not silently 1: an absent route must never read as a clean route."""

        scored = verdict(Route(error="ModelBehaviorError: Invalid JSON"), self.LABEL)
        self.assertEqual(
            (scored["router"], scored["references"], scored["tools"], scored["score"]),
            (0.0, 0.0, 0.0, 0.0),
        )
        self.assertTrue(any("Invalid JSON" in reason for reason in scored["missing"]))


if __name__ == "__main__":
    unittest.main()
