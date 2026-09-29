import pytest

from app.domains.ingestion.records import build_records, normalize_columns, typed_value


@pytest.mark.parametrize(
    "cell,expected",
    [
        ("12", 12), ("-3", -3), ("3.5", 3.5), (".5", 0.5), ("1e3", 1000.0), (" 7 ", 7),
        ("abc", "abc"), ("", ""), ("12abc", "12abc"), ("1,200", "1,200"), ("$5", "$5"),
        ("nan", "nan"), ("inf", "inf"), ("1e999", "1e999"), ("9" * 40, "9" * 40),
        (None, None), (5, 5),
    ],
)
def test_typed_value(cell, expected):
    assert typed_value(cell) == expected


def test_normalize_columns_fills_blanks_and_dedupes_case_insensitively():
    assert normalize_columns(["Name", " ", "name", "NAME", ""]) == [
        "Name", "col_2", "name_2", "NAME_3", "col_5",
    ]
    assert len(normalize_columns(["x" * 200])[0]) == 60


def test_build_records_types_cells_and_tolerates_short_rows():
    cols, recs = build_records(["a", "b"], [["1", "x"], ["2"]])
    assert cols == ["a", "b"]
    assert recs == [{"a": 1, "b": "x"}, {"a": 2}]
