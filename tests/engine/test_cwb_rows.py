"""Result-set files of engine.cwb (no CWB needed)."""

from engine import cwb


def test_write_and_read_rows(tmp_path):
    rows = [(i * 3, i * 3 + 1, f"doc{i % 4}", i // 2) for i in range(101)]
    cwb.write_rows(tmp_path / "s", rows)
    assert (tmp_path / "s" / "rows.bin").stat().st_size == 101 * 16
    pages = [cwb.read_rows(tmp_path / "s", lo, lo + 10) for lo in range(0, 110, 10)]
    assert [r for p in pages for r in p] == rows
    assert cwb.read_rows(tmp_path / "s", 100, 150) == rows[100:]
    assert cwb.read_rows(tmp_path / "s", 200, 210) == []
    cwb.write_rows(tmp_path / "empty", [])
    assert cwb.read_rows(tmp_path / "empty", 0, 50) == []


def test_count_rows():
    rows = [(0, 0, "a", 0), (2, 3, "a", 0), (9, 9, "a", 1), (1, 1, "b", 0)]
    assert cwb.count_rows(rows) == cwb.Counts(4, 3, 2, True)
    assert cwb.count_rows([]) == cwb.Counts(0, 0, 0, True)
