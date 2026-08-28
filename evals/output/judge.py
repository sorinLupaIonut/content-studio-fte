"""The grader, and why it is a stranger to the model being graded.

The eval course's first rule about LLM-as-judge is that the grader must not be
the model running the agent. Until now this project broke it twice over:
`trace-rubric.json` judged `gpt-5-mini` output with `gpt-5-mini`. Moving to
`gpt-5` would only shorten the family tree, not leave it.

DeepSeek shares no lineage with the gpt-5 family - not the data, not the
post-training, not the refusal style. That, and not the price, is why it is
here; at two runs a day the cost difference is pennies either way.

The books stay at OpenAI. Nothing in this module sends licensed passages
anywhere: `Hallucination` receives `context`, so a Cărți batch would - which is
why `attribution`, the criterion that exists to read passages, stays on the
OpenAI side in `evals/runs/trace-rubric.json` and is not reimplemented here.
"""

from __future__ import annotations

import json
import re
from typing import Any

from deepeval.models.base_model import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from content_studio.config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
)

#: The judge's verdict arrives as prose around an object often enough to be
#: worth handling rather than retrying: a fenced block, a preamble, or both.
FENCED = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class NoJudge(RuntimeError):
    """Raised when the judged metrics are asked for without a key."""


def _json_mode(schema: type[BaseModel] | None) -> dict[str, Any]:
    """DeepSeek's JSON mode, only when something is waiting to be parsed.

    Asking for it unconditionally would be worse than useless: the endpoint
    requires the word JSON in the prompt and errors without it, and not every
    call DeepEval makes is a structured one.
    """
    return {"response_format": {"type": "json_object"}} if schema else {}


def _parse(text: str, schema: type[BaseModel] | None) -> Any:
    """Raw text when nothing was asked for, a validated object when it was."""
    if schema is None:
        return text
    fenced = FENCED.search(text)
    body = fenced.group(1) if fenced else text
    start, end = body.find("{"), body.rfind("}")
    if start != -1 and end > start:
        body = body[start : end + 1]
    return schema.model_validate(json.loads(body))


class DeepSeekJudge(DeepEvalBaseLLM):
    """DeepSeek through its OpenAI-compatible endpoint.

    `GEval` scores by reading the log-probabilities of the verdict token when the
    provider returns them, and falls back to plain generation when it does not.
    `supports_log_probs` is answered honestly rather than optimistically: a False
    here costs resolution, a wrong True costs a crash mid-suite.
    """

    def __init__(
        self,
        model: str = DEEPSEEK_MODEL,
        *,
        api_key: str = DEEPSEEK_API_KEY,
        base_url: str = DEEPSEEK_BASE_URL,
    ) -> None:
        if not api_key:
            raise NoJudge(
                "DEEPSEEK_API_KEY lipsește din .env. Toate metricile au nevoie "
                "de judecător, deci se sar toate."
            )
        # NOT `self.model`: the base class sets that to `load_model()`, which by
        # its own convention returns the loaded client - here, this object. A
        # name kept there would be overwritten by `super().__init__` below and
        # then handed to the OpenAI client as the model, which fails at the
        # point the request body is serialized rather than at the assignment.
        self._model_name = model
        self._api_key = api_key
        self._base_url = base_url
        self._sync: OpenAI | None = None
        self._async: AsyncOpenAI | None = None
        super().__init__(model)

    def load_model(self, *args: Any, **kwargs: Any) -> DeepSeekJudge:
        return self

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        return f"deepseek/{self._model_name}"

    def supports_log_probs(self) -> bool:
        # `GEval` prefers to score from the log-probabilities of the verdict
        # token, through `a_generate_raw_response`, which only its own native
        # models implement. Saying False sends it down the schema path below
        # instead of letting it discover the missing method by AttributeError.
        return False

    def _client(self) -> OpenAI:
        if self._sync is None:
            self._sync = OpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._sync

    def _aclient(self) -> AsyncOpenAI:
        if self._async is None:
            self._async = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._async

    def generate(
        self, prompt: str, schema: type[BaseModel] | None = None, *a: Any, **kw: Any
    ) -> Any:
        reply = self._client().chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            **_json_mode(schema),
        )
        return _parse(reply.choices[0].message.content or "", schema)

    async def a_generate(
        self, prompt: str, schema: type[BaseModel] | None = None, *a: Any, **kw: Any
    ) -> Any:
        reply = await self._aclient().chat.completions.create(
            model=self._model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            **_json_mode(schema),
        )
        return _parse(reply.choices[0].message.content or "", schema)


def judge_or_none() -> DeepSeekJudge | None:
    """The judge if one is configured, otherwise nothing.

    Returning None rather than raising is what lets the suite SKIP on a machine
    with no judge key - a clean clone, a fork's CI - instead of erroring at
    collection. Skipped is honest; a suite that cannot run and says nothing is
    the failure this avoids. Since `CaptionLength` was removed on 2026-08-25
    nothing runs without a key, so the whole file skips rather than part of it.
    """
    try:
        return DeepSeekJudge()
    except NoJudge:
        return None
