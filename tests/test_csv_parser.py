from __future__ import annotations

import pytest

from securebench.verification.models import ParserRejected
from securebench.verification.parsers import (
    MAX_CSV_CELL_CHARACTERS,
    MAX_CSV_COLUMNS,
    MAX_CSV_ROWS,
    default_parser_registry,
)


PARSER = "securebench.strict-csv/v1"


def parse(content: bytes):
    return default_parser_registry().parse_bytes(PARSER, content)


def test_strict_csv_parser_returns_bounded_string_table():
    parsed = parse(b'from,to,note\r\nU,M,"quoted, value"\r\nR,M,"two\nlines"\r\n')

    assert parsed == {
        "header": ["from", "to", "note"],
        "rows": [["U", "M", "quoted, value"], ["R", "M", "two\nlines"]],
    }


@pytest.mark.parametrize(
    ("content", "code"),
    [
        (b"", "invalid_csv"),
        (b"a,a\n1,2\n", "invalid_csv_header"),
        (b"a,\n1,2\n", "invalid_csv_header"),
        (b"a,b\n1\n", "invalid_csv_shape"),
        (b"a,b\n1,2,3\n", "invalid_csv_shape"),
        (b"a\x00,b\n1,2\n", "invalid_csv"),
        (b"a\n\xff\n", "invalid_utf8"),
        (b'a,b\n"unterminated,2\n', "invalid_csv"),
    ],
)
def test_strict_csv_parser_rejects_malformed_inputs(content, code):
    with pytest.raises(ParserRejected) as raised:
        parse(content)

    assert raised.value.code == code


def test_strict_csv_parser_rejects_profile_capacity_overruns():
    too_many_columns = ",".join(f"c{index}" for index in range(MAX_CSV_COLUMNS + 1))
    with pytest.raises(ParserRejected, match="column bound"):
        parse((too_many_columns + "\n").encode())

    too_many_rows = b"a\n" + (b"1\n" * (MAX_CSV_ROWS + 1))
    with pytest.raises(ParserRejected, match="row bound"):
        parse(too_many_rows)

    oversized_cell = "x" * (MAX_CSV_CELL_CHARACTERS + 1)
    with pytest.raises(ParserRejected, match="cell that exceeds"):
        parse(f"a\n{oversized_cell}\n".encode())
