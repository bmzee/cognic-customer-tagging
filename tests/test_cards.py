"""Tag cards: one per tag, generated from the taxonomy, never stale."""

import os
import unittest

from engine import cards
from tests.helpers import ROOT, TAXONOMY

CARDS = os.path.join(ROOT, "docs", "tags")


class TagCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = cards.render_all(TAXONOMY)

    def test_one_card_per_tag_and_an_index(self):
        self.assertEqual(sorted(self.files), sorted(["README.md"] + [t["id"] + ".md" for t in TAXONOMY.tags]))

    def test_committed_cards_match_the_taxonomy(self):
        """Regenerate with: python3 -m engine.cards --out docs/tags"""
        self.assertEqual(sorted(n for n in os.listdir(CARDS) if n.endswith(".md")), sorted(self.files))
        for name, text in self.files.items():
            with open(os.path.join(CARDS, name), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), text, name)

    def test_every_card_has_the_required_sections(self):
        for tag in TAXONOMY.tags:
            text = self.files[tag["id"] + ".md"]
            with self.subTest(tag=tag["id"]):
                for heading in ("## Purpose", "## Rule in words", "## Data used", "## Intended use",
                                "## Prohibited uses", "## Known limitations", "## Owner and review"):
                    self.assertIn(heading, text)
                for use in TAXONOMY.governance["prohibited_uses"]:
                    self.assertIn(use, text)
                self.assertIn(TAXONOMY.governance["review_date"], text)

    def test_stress_cards_say_support_only(self):
        for tag in TAXONOMY.tags:
            if tag["group"] == "financial-stress":
                self.assertIn("Support only", self.files[tag["id"] + ".md"], tag["id"])

    def test_check_mode_reports_a_stale_card(self):
        import contextlib
        import io
        import shutil
        import tempfile
        folder = tempfile.mkdtemp(prefix="tagging-cards-")
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cards.main(["--out", folder]), 0)
                self.assertEqual(cards.main(["--check", folder]), 0)
                with open(os.path.join(folder, "saver.md"), "a", encoding="utf-8") as handle:
                    handle.write("edited by hand\n")
                self.assertEqual(cards.main(["--check", folder]), 1)
        finally:
            shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
