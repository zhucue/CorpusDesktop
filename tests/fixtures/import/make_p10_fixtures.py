"""Builds the P10 import fixtures next to this file: text-layer.pdf, scanned.pdf (no text layer),
abstracts.xlsx (two sheets) and abstracts.jsonl. Texts are written for the tests (free to use)."""

import json
import zlib
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

OUT = Path(__file__).resolve().parent


def pdf(objects: list[bytes]) -> bytes:
    """objects[i] is the body of object i+1; object 1 must be the catalog."""
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for o in offsets:
        out += f"{o:010d} 00000 n \n".encode()
    info = len(objects)  # last object is the info dictionary
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def stream(data: bytes, extra: str = "") -> bytes:
    return (
        f"<< /Length {len(data)} {extra}>>\nstream\n".encode() + data + b"\nendstream"
    )


def text_page(lines: list[str]) -> bytes:
    ops = ["BT", "/F1 11 Tf", "14 TL", "72 760 Td"]
    for line in lines:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({esc}) Tj T*")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1")


PAGE1 = [
    "Reading Habits of Graduate Students",
    "",
    "This short report describes how graduate students in a language department",
    "use the university library. We asked forty students to keep a reading diary",
    "for two weeks and to note every book, article and dictionary they consulted.",
    "Most students read journal articles online, but printed books remain",
    "important for literature and translation courses.",
]
PAGE2 = [
    "Students who translate literary texts borrow more dictionaries and",
    "reference grammars than other students. Several participants said that",
    "they compare two or three translations of the same novel before they",
    "write their own version. The library plans to buy more parallel editions",
    "and to keep the reading room open later during the examination period.",
]


def text_pdf() -> bytes:
    c1, c2 = text_page(PAGE1), text_page(PAGE2)
    return pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            stream(c1),
            stream(c2),
            b"<< /Title (Reading Habits of Graduate Students) /Author (P10 test fixture) /Producer (hand-written) >>",
        ]
    )


def scanned_pdf() -> bytes:
    # a 64 x 16 grey image standing for a scanned page; no text operators at all
    w, h = 64, 16
    raw = bytes((x * 4 + y * 8) % 256 for y in range(h) for x in range(w))
    img = zlib.compress(raw)
    content = b"q 480 120 0 0 60 600 cm /Im1 Do Q"
    return pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>",
            stream(
                img,
                f"/Type /XObject /Subtype /Image /Width {w} /Height {h} /ColorSpace /DeviceGray"
                " /BitsPerComponent 8 /Filter /FlateDecode ",
            ),
            stream(content),
            b"<< /Title (Scanned page) /Producer (hand-written) >>",
        ]
    )


ROWS = [
    (
        "语料库与翻译教学",
        "zh",
        2021,
        "期刊",
        "本文介绍在翻译课堂中使用平行语料库的做法。学生先检索原文中的难点词语，再比较多个译本的处理方式，最后写出自己的译文。",
    ),
    (
        "Corpora in the writing classroom",
        "en",
        2022,
        "journal",
        "This article reports a classroom study in which students used a learner corpus to check their own collocations before revising their essays.",
    ),
    (
        "学习者口语中的停顿",
        "zh",
        2023,
        "会议",
        "研究分析了六十名大学生的口语录音，统计停顿的位置和长度，发现停顿多出现在名词短语之前。",
    ),
    (
        "语料库与翻译教学",
        "zh",
        2021,
        "期刊",
        "本文介绍在翻译课堂中使用平行语料库的做法。学生先检索原文中的难点词语，再比较多个译本的处理方式，最后写出自己的译文。",
    ),
]
ROWS_2025 = [
    (
        "Hedging in student theses",
        "en",
        2025,
        "thesis",
        "We compare hedging devices in master's theses written in English by Chinese and British students and find that Chinese students use fewer modal verbs.",
    ),
    (
        "新闻标题的修辞",
        "zh",
        2025,
        "期刊",
        "本文统计了三家报纸一年的新闻标题，分析了比喻、对偶和设问三种修辞手法的使用频率。",
    ),
]


def xlsx(path: Path):
    wb = Workbook()
    head = Font(name="宋体", bold=True)
    for ws, rows in ((wb.active, ROWS), (wb.create_sheet("2025"), ROWS_2025)):
        if ws.title == "Sheet":
            ws.title = "摘要"
        ws.append(["标题", "语言", "年份", "类型", "摘要"])
        for cell in ws[1]:
            cell.font = head
        for r in rows:
            ws.append(list(r))
    wb.save(path)


def jsonl(path: Path):
    lines = []
    for i, (title, lang, year, genre, text) in enumerate(ROWS + ROWS_2025, 1):
        lines.append(
            json.dumps(
                {
                    "id": i,
                    "title": title,
                    "lang": lang,
                    "body": text,
                    "meta": {"year": year, "genre": genre},
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    (OUT / "text-layer.pdf").write_bytes(text_pdf())
    (OUT / "scanned.pdf").write_bytes(scanned_pdf())
    xlsx(OUT / "abstracts.xlsx")
    jsonl(OUT / "abstracts.jsonl")
    print("written to", OUT)
