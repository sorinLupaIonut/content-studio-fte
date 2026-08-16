"""The conversation summary is derived, never invented — these pin that down.

The expected strings are Romanian because the summary is: it is the human record
of a Romanian conversation and it quotes the client's own words.
"""

import unittest

from content_studio.conversation import build_summary


class TestConversationSummary(unittest.TestCase):
    def test_summary_without_messages(self) -> None:
        self.assertEqual(build_summary({}), "Conversație fără mesaje.")

    def test_full_factual_summary(self) -> None:
        summary = build_summary(
            {
                "messages_received": 3,
                "messages_sent": 2,
                "proposal_sets": 1,
                "posts_saved": 1,
                "last_post": "Limitele nu te fac egoistă",
                "profile_updates": 1,
                "errors": 1,
                "last_request": "Salvează postarea aleasă.",
            }
        )

        self.assertIn("3 mesaje de la Viorela și 2 răspunsuri", summary)
        self.assertIn("1 mesaj a rămas fără răspuns", summary)
        self.assertIn("1 set de propuneri generat", summary)
        self.assertIn("1 postare salvată, ultima: „Limitele nu te fac egoistă”", summary)
        self.assertIn("1 actualizare a profilului", summary)
        self.assertIn("1 eroare înregistrată", summary)
        self.assertIn("Ultima cerere: „Salvează postarea aleasă.”", summary)

    def test_last_request_is_shortened(self) -> None:
        summary = build_summary(
            {
                "messages_received": 1,
                "messages_sent": 1,
                "last_request": "x" * 400,
            }
        )

        self.assertLess(len(summary), 300)
        self.assertIn("…", summary)


if __name__ == "__main__":
    unittest.main()
