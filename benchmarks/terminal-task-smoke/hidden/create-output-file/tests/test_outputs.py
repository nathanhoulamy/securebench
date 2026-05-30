from pathlib import Path


def test_output_file():
    expected = "securebench terminal task\n"
    actual = Path("output.txt").read_text()
    assert actual == expected
