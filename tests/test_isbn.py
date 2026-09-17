from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from import_xlsx import normalize_isbn, parse_year, pad_short, GENRE_MAP


def test_isbn_strips_hyphens():
    assert normalize_isbn("978-4-06-544112-1") == "9784065441121"
    assert normalize_isbn(" 9781250341587 ") == "9781250341587"
    assert normalize_isbn("bad") == ""


def test_parse_year():
    assert parse_year(2026)[0] == 2026
    assert parse_year("2026年9月")[0] == 2026
    assert parse_year("西班牙")[0] is None


def test_genre_map():
    assert GENRE_MAP["推理犯罪"][0] == "推理"


def test_pad_short_length():
    text = pad_short("很短。", "喜欢推理的人", "推理")
    assert 80 <= len(text) <= 150


def test_duplicate_key_skips():
    assert normalize_isbn("978-0-306-40615-7") == "9780306406157"


def test_featured_count():
    from folio.featured import FEATURED
    from collections import Counter
    c = Counter(x["languageCode"] for x in FEATURED)
    assert len(FEATURED) == 48
    assert all(c[lang] == 8 for lang in ["en", "es", "ja", "ko", "fr", "it"])


def test_import_xlsx_dedup(tmp_path, monkeypatch):
    from openpyxl import Workbook
    import import_xlsx as m

    folder = tmp_path / "英文原版书籍"
    folder.mkdir()
    wb = Workbook()
    ws = wb.active
    ws.append([
        "原文书名", "作者", "首次出版年", "原版代表出版社",
        "ISBN-13（代表版，下单请再核）", "主类型", "一句话简介",
    ])
    blurb = "这是一本足够长的测试简介，用来确认导入脚本能处理中文简介并且不会因为单行错误中断。"
    ws.append(["Alpha Book", "Jane", 2026, "Pub", "978-1-234-56789-7", "文学", blurb])
    ws.append(["Alpha Book", "Jane", 2026, "Pub", "978-1-234-56789-7", "文学", "重复行"])
    ws.append(["", "No", 2026, "Pub", "", "文学", "空书名应跳过"])
    wb.save(folder / "t.xlsx")
    monkeypatch.setattr(m, "INSPIRATION", tmp_path)
    monkeypatch.setattr(m, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(m, "REPORT_DIR", tmp_path / "data" / "reports")
    payload = m.import_all()
    assert payload["bookCount"] == 1
    payload2 = m.import_all()
    assert payload2["bookCount"] == 1
    assert payload["books"][0]["isbn13"] == "9781234567897"

