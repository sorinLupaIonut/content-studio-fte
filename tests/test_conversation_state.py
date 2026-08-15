import unittest

from conversation_state import construieste_rezumat


class TestConversationState(unittest.TestCase):
    def test_rezumat_fara_mesaje(self) -> None:
        self.assertEqual(construieste_rezumat({}), "Conversație fără mesaje.")

    def test_rezumat_factual_complet(self) -> None:
        rezumat = construieste_rezumat(
            {
                "mesaje_primite": 3,
                "mesaje_trimise": 2,
                "seturi_propuneri": 1,
                "postari_salvate": 1,
                "ultima_postare": "Limitele nu te fac egoistă",
                "actualizari_profil": 1,
                "erori": 1,
                "ultima_cerere": "Salvează postarea aleasă.",
            }
        )

        self.assertIn("3 mesaje de la Viorela și 2 răspunsuri", rezumat)
        self.assertIn("1 mesaj a rămas fără răspuns", rezumat)
        self.assertIn("1 set de propuneri generat", rezumat)
        self.assertIn("1 postare salvată, ultima: „Limitele nu te fac egoistă”", rezumat)
        self.assertIn("1 actualizare a profilului", rezumat)
        self.assertIn("1 eroare înregistrată", rezumat)
        self.assertIn("Ultima cerere: „Salvează postarea aleasă.”", rezumat)

    def test_ultima_cerere_este_scurtata(self) -> None:
        rezumat = construieste_rezumat(
            {
                "mesaje_primite": 1,
                "mesaje_trimise": 1,
                "ultima_cerere": "x" * 400,
            }
        )

        self.assertLess(len(rezumat), 300)
        self.assertIn("…", rezumat)


if __name__ == "__main__":
    unittest.main()
