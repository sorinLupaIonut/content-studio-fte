"""Refusals the interface has to word itself.

Most errors carry a sentence, because most errors are read by whoever caused
them in the language the server happens to speak. A few are different: they are
shown to a client that may be running in either language, so the server sends a
stable machine code and the interface chooses the words.

The rule for deciding which kind an error is: if a bilingual page would have to
display the string verbatim, it needs a code. `BudgetExhausted` and the rate
limiter already work this way and predate this module; they keep their own
shapes because both are raised far from a route.
"""

from __future__ import annotations


class CodedError(RuntimeError):
    """An HTTP refusal whose wording belongs to the client, not to the server.

    `detail` stays English and is for logs and for anyone reading the API
    directly; `code` is the contract the interface switches on.
    """

    def __init__(self, status_code: int, detail: str, code: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
