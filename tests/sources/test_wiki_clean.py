import importlib.util
import unittest

from pipelines.sources.wiki_clean import UnsupportedWikitext, extract, source_spans


@unittest.skipUnless(importlib.util.find_spec("mwparserfromhell"), "run in pinned source-cleaning experiment venv")
class WikiCleaningTests(unittest.TestCase):
    def test_display_link_unicode_offsets(self):
        result = extract("甲[[目标|显示😀]]乙")
        self.assertEqual(result["canonical_text"], "甲显示😀乙")
        self.assertEqual(source_spans(result, 1, 4), [{"canonical": [1, 4], "source": [6, 9], "precision": "exact_copy"}])

    def test_removed_blocks_cannot_form_one_index_segment(self):
        result = extract("ab{{T|x}}cd<!--n-->ef")
        self.assertEqual(result["canonical_text"], "ab\n\ncd\n\nef")
        self.assertEqual(result["index_segments"], [[0, 2], [4, 6], [8, 10]])
        spans = source_spans(result, 1, 5)
        self.assertTrue(any(s["source"] is None and s["precision"] == "synthetic" for s in spans))
        self.assertFalse(any(a <= 1 and b >= 5 for a, b in result["index_segments"]))
        self.assertNotIn("abcd", result["canonical_text"])

    def test_entity_many_to_one_and_combining_codepoints_preserved(self):
        result = extract("e\u0301😀&amp;\r\n\t末")
        self.assertEqual(result["canonical_text"], "e\u0301😀&\n 末")
        self.assertEqual(source_spans(result, 3, 4), [{"canonical": [3, 4], "source": [3, 8], "precision": "source_span"}])
        self.assertEqual(source_spans(result, 4, 5)[0]["source"], [8, 10])
        multi = extract("&NotEqualTilde;")
        self.assertEqual(multi["canonical_text"], "≂̸")
        self.assertEqual(source_spans(multi, 1, 2)[0]["source"], [0, 15])

    def test_tables_refs_and_namespaces_are_excluded(self):
        result = extract('前\n{| class="wikitable"\n| secret-table\n|}\n后<ref>secret-ref</ref>[[Category:secret]]末')
        self.assertNotIn("secret", result["canonical_text"])
        self.assertEqual([e["reason"] for e in result["exclusions"]], ["tag:table", "tag:ref", "namespace_or_pipe_trick_link"])

    def test_formatting_nowiki_and_external_label(self):
        result = extract("'''粗'''<nowiki>[[X]]</nowiki>[https://example.com 说明]")
        self.assertEqual(result["canonical_text"], "粗[[X]]说明")
        self.assertTrue(all(s["precision"] == "exact_copy" for s in source_spans(result, 0, 8)))

    def test_unhandled_syntax_rejects_instead_of_claiming_body(self):
        for source in ("前-{zh-hans:简;zh-hant:繁}-后", "前{{unclosed", "{{TemplateOnly}}"):
            with self.subTest(source=source), self.assertRaises(UnsupportedWikitext):
                extract(source)


if __name__ == "__main__":
    unittest.main()
