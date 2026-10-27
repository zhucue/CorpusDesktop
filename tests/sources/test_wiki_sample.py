import io
import unittest

from pipelines.sources.probe import ROOT
from pipelines.sources.wiki_sample import (
    LimitedReader,
    select_articles,
    validate_receipt,
)


class WikiSampleTests(unittest.TestCase):
    def test_fixed_sample_filters_namespace_redirect_and_keeps_revision(self):
        rows = [f'<page><title>标题{i}</title><ns>{1 if i == 1 else 0}</ns><id>{i}</id>'
                f'{"<redirect/>" if i == 2 else ""}<revision><id>{100+i}</id><text>字😀 {i}</text></revision></page>'
                for i in range(6)]
        def select(items):
            return select_articles(io.BytesIO(('<mediawiki xmlns="urn:test">' + ''.join(items) + '</mediawiki>').encode()), "zhwiki", 2)
        first, candidates = select(rows)
        self.assertEqual(candidates, 4)
        self.assertEqual(first, select(list(reversed(rows)))[0])
        self.assertEqual(len(first), 2)
        for item in first:
            self.assertIn("字😀", item["text"])
            self.assertEqual(item["revision_id"], item["page_id"] + 100)
            self.assertIn(f'oldid={item["revision_id"]}', item["revision_url"])

    def test_expansion_limit(self):
        with self.assertRaisesRegex(ValueError, "byte limit"):
            LimitedReader(io.BytesIO(b"1234"), maximum=3).read()

    def test_receipt_path_rejected_before_download(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            validate_receipt(ROOT / "doc/download.json", "zhwiki")

    def test_receipt_wiki_and_url_must_match(self):
        name = "zhwiki-2026-10-01-p1p2.xml.bz2"
        url = "https://dumps.wikimedia.org/other/mediawiki_content_current/zhwiki/2026-10-01/xml/bzip2/" + name
        receipt = {"file": {"name": name, "url": url, "sha256": "a" * 64}, "request": {"url": url}}
        path = ROOT / "tmp/sources-s0/test/download.json"
        validate_receipt(path, "zhwiki", receipt)
        with self.assertRaises(ValueError):
            validate_receipt(path, "enwiki", receipt)
        receipt["file"]["url"] = url.replace("2026-10-01", "2026-09-01")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            validate_receipt(path, "zhwiki", receipt)


if __name__ == "__main__":
    unittest.main()
