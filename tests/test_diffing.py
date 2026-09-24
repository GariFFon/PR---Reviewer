from pathlib import Path

from prreviewer.diffing import parse_diff

FIXTURE = (Path(__file__).parent / "fixtures" / "sample.diff").read_text()


def test_parses_changed_file():
    result = parse_diff(FIXTURE)
    assert "api/orders.py" in result


def test_only_added_lines_are_changed():
    result = parse_diff(FIXTURE)
    file_diff = result["api/orders.py"]
    assert file_diff.changed_lines == {11}


def test_is_line_changed():
    file_diff = parse_diff(FIXTURE)["api/orders.py"]
    assert file_diff.is_line_changed(11) is True
    assert file_diff.is_line_changed(10) is False
    assert file_diff.is_line_changed(999) is False


def test_overlaps_changed_range():
    file_diff = parse_diff(FIXTURE)["api/orders.py"]
    assert file_diff.overlaps_changed_range(9, 12) is True
    assert file_diff.overlaps_changed_range(1, 5) is False


def test_changed_ranges_collapses_contiguous_lines():
    file_diff = parse_diff(FIXTURE)["api/orders.py"]
    assert file_diff.changed_ranges() == [(11, 11)]
