"""The detail phase has to be written in the language the batch was asked in.

This is the contract that was silently missing until 2026-08-31. `start_generation`
carried the language and `develop_generation_idea` did not, so the ten titles came
back in English and the post - the whole cost of a run - came back in Romanian.
Nothing raised: `DEFAULT_LANGUAGE` is a valid value, so the wrong answer was a
well-formed one.

Both doors are tested, because "one conversation, two doors" means a fix on one of
them is half a fix. The click stamps the language in `StudioApiClient`; the chat
trigger passes the language of the conversation it was asked in.
"""

import asyncio
import unittest
from uuid import UUID, uuid4

from content_studio.harness.service import HarnessService


class _Accounts:
    async def require_budget(self) -> None:
        return None


class _Generator:
    """Records what it was asked for, and answers the shape the caller expects."""

    def __init__(self, current: dict | None = None) -> None:
        self.develop_calls: list[dict] = []
        self._current = current

    async def develop(self, principal_id, batch_id, ordinal, **kwargs):
        self.develop_calls.append(
            {"principal_id": principal_id, "batch_id": batch_id, "ordinal": ordinal, **kwargs}
        )
        return {"id": str(batch_id)}

    async def current(self, principal_id, public=True):  # noqa: ARG002
        return self._current


def _service(generator: _Generator) -> HarnessService:
    service = HarnessService.__new__(HarnessService)
    service.generator = generator  # type: ignore[attr-defined]
    service.accounts = _Accounts()  # type: ignore[attr-defined]
    service.trail = None  # type: ignore[attr-defined]
    service._require_ready = lambda: (None, None)  # type: ignore[attr-defined]
    return service


class TheClickCarriesIt(unittest.TestCase):
    def test_english_reaches_the_detail_phase(self) -> None:
        generator = _Generator()
        batch_id = uuid4()
        asyncio.run(
            _service(generator).develop_generation_idea("p", batch_id, 3, language="en")
        )
        self.assertEqual(generator.develop_calls[0]["language"], "en")

    def test_romanian_reaches_it_too(self) -> None:
        generator = _Generator()
        asyncio.run(
            _service(generator).develop_generation_idea("p", uuid4(), 1, language="ro")
        )
        self.assertEqual(generator.develop_calls[0]["language"], "ro")

    def test_it_is_passed_by_name_not_by_position(self) -> None:
        """`develop` takes `language` before `trail` and `dictate`; a positional
        argument here would land the language in whichever slot moved next."""
        generator = _Generator()
        asyncio.run(
            _service(generator).develop_generation_idea("p", uuid4(), 0, language="en")
        )
        call = generator.develop_calls[0]
        self.assertIn("language", call)
        self.assertIn("dictate", call)

    def test_the_default_is_still_romanian(self) -> None:
        """A caller that names no language keeps the behaviour it always had."""
        generator = _Generator()
        asyncio.run(_service(generator).develop_generation_idea("p", uuid4(), 2))
        self.assertEqual(generator.develop_calls[0]["language"], "ro")


class TheChatCarriesItToo(unittest.TestCase):
    def test_a_develop_asked_in_english_chat_is_written_in_english(self) -> None:
        batch_id = uuid4()
        generator = _Generator(current={"id": str(batch_id)})
        service = _service(generator)
        asyncio.run(
            service._execute_chat_trigger("p", "develop_idea", {"idea": 4}, "en")
        )
        call = generator.develop_calls[0]
        self.assertEqual(call["language"], "en")
        self.assertEqual(call["ordinal"], 4)
        self.assertEqual(call["batch_id"], UUID(str(batch_id)))

    def test_the_chat_does_not_dictate_its_own_sentence_back(self) -> None:
        """She already typed it; the click is what needs dictating."""
        generator = _Generator(current={"id": str(uuid4())})
        asyncio.run(
            _service(generator)._execute_chat_trigger("p", "develop_idea", {"idea": 1}, "ro")
        )
        self.assertFalse(generator.develop_calls[0]["dictate"])

    def test_no_batch_means_no_call(self) -> None:
        generator = _Generator(current=None)
        asyncio.run(
            _service(generator)._execute_chat_trigger("p", "develop_idea", {"idea": 1}, "en")
        )
        self.assertEqual(generator.develop_calls, [])


if __name__ == "__main__":
    unittest.main()
