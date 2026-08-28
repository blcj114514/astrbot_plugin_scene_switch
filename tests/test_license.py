from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_license_is_full_agpl_v3():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.lstrip().startswith("GNU AFFERO GENERAL PUBLIC LICENSE")
    assert "Version 3, 19 November 2007" in text
    assert "END OF TERMS AND CONDITIONS" in text
    assert len(text) > 20_000
