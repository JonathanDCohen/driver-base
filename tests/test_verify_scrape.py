"""tools/verify_scrape.py — the deterministic comparer behind the
verify-scrape skill. Each failure mode must exit non-zero."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import verify_scrape  # tools/ is on pytest's pythonpath (pyproject.toml)

_URL = "https://example.com/product/a/"
_MAPPING = [
    {"label": "^Fs$", "field": "fs_hz"},
    {"label": "^Qts$", "field": "qts"},
    {"label": "^Frequency Range", "field": ["freq_low_hz", "freq_high_hz"]},
    {
        "label": "^Frequency Range",
        "section": "HF",
        "field": ["coax_hf_freq_low_hz", "coax_hf_freq_high_hz"],
    },
    {"label": "^Crossover", "field": "recommended_crossover_hz", "scale": 1000},
    {
        "label": "^Magnet$",
        "field": "magnet_type",
        "type": "string",
        "values": {"ferrite": "ceramic"},
    },
]


def _record(**over) -> dict:
    rec = {
        "manufacturer": "Acme",
        "canonical_id": "acme__a__8ohm",
        "source_urls": [_URL],
        "impedance_nominal_ohm": 8.0,
        "fs_hz": 45.0,
        "qts": 0.234,
        "freq_low_hz": 45.0,
        "freq_high_hz": 4600.0,
        "coax_hf_freq_low_hz": 1500.0,
        "coax_hf_freq_high_hz": 20000.0,
        "recommended_crossover_hz": 1800.0,
        "magnet_type": "ceramic",
    }
    rec.update(over)
    return rec


def _page(**over) -> dict:
    rows = [
        {"label": "Fs", "value": "45 Hz"},
        {"label": "Qts", "value": "0.23"},
        {"label": "Frequency Range", "value": "45 - 4600 Hz"},
        {"section": "HF", "label": "Frequency Range", "value": "1500 - 20000 Hz"},
        {"label": "Crossover", "value": "1.8 kHz"},
        {"label": "Magnet", "value": "Ferrite"},
        {"label": "Spider Profile", "value": "Constant height"},
    ]
    page = {
        "source_url": _URL.rstrip("/").replace("example.com", "EXAMPLE.com"),
        "rows": rows,
    }
    page.update(over)
    return page


def _run(
    tmp_path: Path,
    drivers: list,
    pages: list,
    *flags: str,
    mapping: list = _MAPPING,
) -> int:
    d = tmp_path / "drivers.json"
    t = tmp_path / "t.json"
    m = tmp_path / "m.json"
    d.write_text(json.dumps({"drivers": drivers}))
    t.write_text(json.dumps(pages))
    m.write_text(json.dumps(mapping))
    return verify_scrape.main(
        [
            "--manufacturer", "Acme",
            "--drivers", str(d),
            "--transcription", str(t),
            "--mapping", str(m),
            *flags,
        ]
    )  # fmt: skip


def test_all_match_passes(tmp_path: Path) -> None:
    # 0.234 vs printed "0.23" is within half a unit in the last digit;
    # trailing slash and host case in the URL don't matter.
    assert _run(tmp_path, [_record()], [_page()]) == 0


def test_wrong_value_fails_and_names_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, [_record(fs_hz=46.0)], [_page()]) == 1
    assert "fs_hz" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("qts", "ok"),
    [(0.234, True), (0.2349, True), (0.236, False), (0.224, False)],
)
def test_printed_precision_tolerance(tmp_path: Path, qts: float, ok: bool) -> None:
    assert _run(tmp_path, [_record(qts=qts)], [_page()]) == (0 if ok else 1)


def test_scale_and_section(tmp_path: Path) -> None:
    assert _run(tmp_path, [_record(recommended_crossover_hz=1700.0)], [_page()]) == 1
    assert _run(tmp_path, [_record(coax_hf_freq_low_hz=1400.0)], [_page()]) == 1


def test_null_in_record_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, [_record(qts=None)], [_page()]) == 1


def test_site_blank_but_record_populated_fails(tmp_path: Path) -> None:
    rows = [
        {"label": "Magnet", "value": "-"} if r["label"] == "Magnet" else r
        for r in _page()["rows"]
    ]
    page = _page(rows=rows)
    assert _run(tmp_path, [_record()], [page]) == 1
    assert _run(tmp_path, [_record(magnet_type=None)], [page]) == 0
    # A pipeline-derived value behind a blank site cell is fine.
    derived = _record(spec_source={"magnet_type": "derived"})
    assert _run(tmp_path, [derived], [page]) == 0


def test_string_remap(tmp_path: Path) -> None:
    assert _run(tmp_path, [_record(magnet_type="neodymium")], [_page()]) == 1


def test_unmatched_page_fails(tmp_path: Path) -> None:
    page = _page(source_url="https://example.com/product/other/")
    assert _run(tmp_path, [_record()], [page]) == 1


def test_variant_selects_impedance(tmp_path: Path) -> None:
    four = _record(canonical_id="acme__a__4ohm", impedance_nominal_ohm=4.0)
    # Two records cite the page: ambiguous without a variant.
    assert _run(tmp_path, [_record(), four], [_page()]) == 1
    assert _run(tmp_path, [_record(), four], [_page(variant=8)]) == 0
    assert _run(tmp_path, [_record()], [_page(variant=4)]) == 1


def test_full_coverage(tmp_path: Path) -> None:
    other = _record(canonical_id="acme__b__8ohm", source_urls=["https://x/b"])
    assert _run(tmp_path, [_record(), other], [_page()]) == 0
    assert _run(tmp_path, [_record(), other], [_page()], "--require-full-coverage") == 1


def test_too_few_comparisons_fails(tmp_path: Path) -> None:
    """An empty / captcha fetch transcribes to no rows; that must not PASS."""
    assert _run(tmp_path, [_record()], [_page(rows=[])]) == 1


def test_empty_transcription_or_unknown_manufacturer_fails(tmp_path: Path) -> None:
    assert _run(tmp_path, [_record()], []) == 1
    assert _run(tmp_path, [_record(manufacturer="Other")], [_page()]) == 1


def test_malformed_input_is_input_error(tmp_path: Path) -> None:
    typo = [*_MAPPING, {"label": "^Vas$", "field": "vas_litres"}]
    assert _run(tmp_path, [_record()], [_page()], mapping=typo) == 2
    no_url = {k: v for k, v in _page().items() if k != "source_url"}
    assert _run(tmp_path, [_record()], [no_url]) == 2


def test_record_value_without_site_row_fails(tmp_path: Path) -> None:
    rows = [r for r in _page()["rows"] if r["label"] != "Crossover"]
    assert _run(tmp_path, [_record()], [_page(rows=rows)]) == 1
    # ...unless the pipeline derived it.
    derived = _record(spec_source={"recommended_crossover_hz": "derived"})
    assert _run(tmp_path, [derived], [_page(rows=rows)]) == 0


def test_nan_and_bool_records_fail(tmp_path: Path) -> None:
    assert _run(tmp_path, [_record(fs_hz=float("nan"))], [_page()]) == 1
    assert _run(tmp_path, [_record(fs_hz=True)], [_page()]) == 1


def test_canonical_id_disambiguates(tmp_path: Path) -> None:
    dup = _record(canonical_id="acme__a__8ohm__dup")
    assert _run(tmp_path, [_record(), dup], [_page(variant=8)]) == 1
    assert _run(tmp_path, [_record(), dup], [_page(canonical_id="acme__a__8ohm")]) == 0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("49-6300 Hz", [49.0, 6300.0]),
        ("49 – 6300 Hz", [49.0, 6300.0]),
        ("−3 dB", [-3.0]),
        ("1,200 W", [1200.0]),
        ("1,5 mm", [1.5]),
        (".5 mm", [0.5]),
        ("65.5 mm (2.5 in)", [65.5, 2.5]),
    ],
)
def test_number_parsing(text: str, expected: list[float]) -> None:
    assert [n for n, _ in verify_scrape._numbers(text)] == expected


def test_blank_row_superseded_by_later_row(tmp_path: Path) -> None:
    """A labelled-but-blank row whose value is printed on another row of the
    same page (NERO-5CCN125D's sensitivity) isn't a mismatch."""
    rows = [*_page()["rows"], {"label": "Qts", "value": "-"}]
    assert _run(tmp_path, [_record()], [_page(rows=rows)]) == 0
    only_blank = [r for r in rows if not (r["label"] == "Qts" and r["value"] != "-")]
    assert _run(tmp_path, [_record()], [_page(rows=only_blank)]) == 1
