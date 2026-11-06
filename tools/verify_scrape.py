"""Compare a blind transcription of a manufacturer's live site against
web/drivers.json. The deterministic half of the `verify-scrape` skill
(.claude/skills/verify-scrape/SKILL.md). Run from the repo root:

    uv run python tools/verify_scrape.py \\
        --manufacturer "SB Audience" \\
        --transcription transcription.json \\
        --mapping mapping.json \\
        [--drivers web/drivers.json] [--require-full-coverage]

transcription.json — what the site says, copied verbatim by transcribers
who never see drivers.json or the scraper:

    [{"source_url": "https://.../product/x/",   # page the record cites
      "variant": 8,                 # optional: impedance, when one page
                                    #   yields several records
      "canonical_id": "...",        # optional: last-resort disambiguator
      "rows": [{"label": "Fs", "value": "45 Hz"},
               {"section": "HF", "label": "Nominal Impedance",
                "value": "8 Ohm"}]}]

mapping.json — label → field decisions, written by the verifier from the
manufacturer's own footnotes and docs/manufacturers.md (never from the
scraper code). Every decision is echoed in the report for human review:

    [{"label": "^Fs$", "field": "fs_hz"},
     {"label": "^Crossover", "field": "recommended_crossover_hz",
      "scale": 1000},                                     # kHz → Hz
     {"label": "^Frequency Range", "section": "HF",
      "field": ["coax_hf_freq_low_hz", "coax_hf_freq_high_hz"]},
     {"label": "^Sensitivity", "field": "sensitivity_db_2_83v_1m",
      "index": 0},                  # which number in the value (default 0)
     {"label": "^Magnet$", "field": "magnet_type", "type": "string",
      "values": {"ferrite": "ceramic"}},
     {"label": ".", "section": "No Chamber", "field": null}]   # ignore

Rules are tried in order; the first whose `label` regex (case-insensitive)
is found in the row label and whose `section` equals the row's section
(case-insensitive; both default null) claims the row. `field: null`
claims it without comparing.

Numbers compare at the source's printed precision: the record may differ
from the printed number by at most half a unit in its last printed digit,
times `scale`. Strings compare case- and whitespace-insensitively after the
optional `values` remap.

Exit 1 (FAIL) on any of:
  - a field mismatch, or a site value present but the record null;
  - the site blank / showing no number where the record has a value;
  - a record value for a mapped field that no row on its page supports
    (unless its spec_source is derived/inferred/override);
  - a transcribed page with no matching record, or an ambiguous one;
  - a matched page with fewer than 3 comparisons (empty or captcha
    fetches look like this);
  - an empty transcription, or no records for --manufacturer;
  - with --require-full-coverage, any record that wasn't transcribed.
Exit 2 on malformed input (unknown field names, bad rules, missing keys).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

# A leading minus only when it can't be a range separator (`49-6300`).
_NUMBER_RE = re.compile(r"(?<![\d.)])-?(?:\d+(?:\.\d+)?|\.\d+)")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")
_BLANKS = {"", "-", "--", "—", "–", "n/a", "na", "n.a.", "none"}
_UNCHECKED_SOURCES = {"derived", "inferred", "override"}
_MIN_FIELDS_PER_PAGE = 3


class InputError(ValueError):
    pass


@dataclass
class Report:
    mismatches: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    unsampled: list[str] = field(default_factory=list)
    unmapped_labels: dict[str, int] = field(default_factory=dict)
    unused_rules: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # whole-run failures
    checked: int = 0
    n_records: int = 0

    def failed(self, require_full_coverage: bool) -> bool:
        return bool(
            self.errors
            or self.mismatches
            or self.unmatched
            or (require_full_coverage and self.unsampled)
        )


def _norm_url(u: str) -> str:
    """Scheme- and fragment-insensitive; host case-insensitive; path exact."""
    p = urlsplit(u.strip())
    path = p.path.rstrip("/") or "/"
    return f"{p.netloc.lower()}{path}" + (f"?{p.query}" if p.query else "")


def _norm_str(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().casefold()


def _norm_section(s: Optional[str]) -> Optional[str]:
    return _norm_str(s) if s else None


def _numbers(text: str) -> list[tuple[float, float]]:
    """(value, half-unit-in-last-printed-digit) for each number in text."""
    text = text.replace("−", "-")  # unicode minus
    text = text.replace("–", " - ").replace("—", " - ")  # dashes
    text = _DECIMAL_COMMA_RE.sub(".", _THOUSANDS_RE.sub("", text))
    out = []
    for m in _NUMBER_RE.finditer(text):
        s = m.group(0)
        decimals = len(s.split(".", 1)[1]) if "." in s else 0
        out.append((float(s), 0.5 * 10.0**-decimals))
    return out


def _compile_rules(mapping: list[dict], known_fields: set[str]) -> list[dict]:
    rules = []
    for i, r in enumerate(mapping):
        where = f"mapping[{i}] {r!r}"
        if "label" not in r or "field" not in r:
            raise InputError(f"{where}: needs `label` and `field`")
        fields = r["field"] if isinstance(r["field"], list) else [r["field"]]
        if r["field"] is not None:
            unknown = [f for f in fields if f not in known_fields]
            if unknown:
                raise InputError(f"{where}: unknown field(s) {unknown}")
        if r.get("type") == "string" and len(fields) != 1:
            raise InputError(f"{where}: string rules map exactly one field")
        if float(r.get("scale", 1.0)) == 0:
            raise InputError(f"{where}: scale must be non-zero")
        rules.append(
            {
                **r,
                "_fields": [] if r["field"] is None else fields,
                "_re": re.compile(r["label"], re.IGNORECASE),
                "_section": _norm_section(r.get("section")),
                "_values": {_norm_str(k): v for k, v in r.get("values", {}).items()},
            }
        )
    return rules


def _find_record(records: list[dict], page: dict) -> tuple[Optional[dict], str]:
    if "source_url" not in page:
        raise InputError(f"transcribed page without source_url: {page!r:.120}")
    want = _norm_url(page["source_url"])
    hits = [
        r for r in records if want in {_norm_url(u) for u in r.get("source_urls", [])}
    ]
    if page.get("variant") is not None:
        hits = [
            r for r in hits if r.get("impedance_nominal_ohm") == float(page["variant"])
        ]
    if page.get("canonical_id"):
        hits = [r for r in hits if r["canonical_id"] == page["canonical_id"]]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, "no record cites this source_url (with the given variant/id)"
    ids = ", ".join(r["canonical_id"] for r in hits)
    return None, f"ambiguous ({ids}); add `variant` or `canonical_id`"


@dataclass
class _PageState:
    """Which mapped fields a page's rows showed a value for. Checked once the
    whole page is read: a blank site cell only counts against a record value
    if no other row on the page shows that field (some sheets print a blank
    labelled row with the value on a following row)."""

    shown: set[str] = field(default_factory=set)
    blank: dict[str, str] = field(default_factory=dict)  # field → message


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _unsupported(rec: dict, f: str) -> bool:
    """Record has a value for `f`, and it isn't one the pipeline computed."""
    sources = rec.get("spec_source") or {}
    return rec.get(f) is not None and sources.get(f) not in _UNCHECKED_SOURCES


def _compare_row(
    rec: dict, rule: dict, value: str, where: str, report: Report, state: _PageState
) -> None:
    fields = rule["_fields"]
    blank = _norm_str(value) in _BLANKS

    if rule.get("type") == "string":
        (f,) = fields
        got = rec.get(f)
        report.checked += 1
        if blank:
            state.blank[f] = f"{where} {f}: site blank, record {got!r}"
            return
        state.shown.add(f)
        want = _norm_str(value)
        want = _norm_str(rule["_values"].get(want, want))
        if not isinstance(got, str) or _norm_str(got) != want:
            report.mismatches.append(
                f"{where} {f}: site {value!r} → {want!r}, record {got!r}"
            )
        return

    nums = [] if blank else _numbers(value)
    if not blank and not nums:
        report.mismatches.append(f"{where} {fields}: site {value!r} has no number")
        state.shown.update(fields)  # reported here; don't re-report as unsupported
        return
    nums = nums[int(rule.get("index", 0)) :]
    state.shown.update(fields[: len(nums)])
    scale = float(rule.get("scale", 1.0))
    for i, f in enumerate(fields):
        got = rec.get(f)
        report.checked += 1
        if i >= len(nums):
            state.blank[f] = f"{where} {f}: site {value!r} has no value, record {got!r}"
            continue
        num, half_ulp = nums[i]
        want = num * scale
        tol = half_ulp * abs(scale) + 1e-9
        if got is None:
            report.mismatches.append(
                f"{where} {f}: site {value!r} → {want:g}, record null"
            )
        elif not _is_number(got) or not abs(got - want) <= tol:
            report.mismatches.append(
                f"{where} {f}: site {value!r} → {want:g} (±{tol:g}), record {got!r}"
            )


def verify(
    drivers: list[dict],
    manufacturer: str,
    transcription: list[dict],
    mapping: list[dict],
) -> Report:
    known_fields = {k for d in drivers for k in d}
    rules = _compile_rules(mapping, known_fields)
    mapped_fields = {f for r in rules for f in r["_fields"]}
    report = Report()
    records = [d for d in drivers if d.get("manufacturer") == manufacturer]
    report.n_records = len(records)
    if not records:
        report.errors.append(f"no records with manufacturer == {manufacturer!r}")
    if not transcription:
        report.errors.append("transcription is empty")

    rule_hits = [0] * len(rules)
    seen_ids: set[str] = set()
    for page in transcription:
        rec, why = _find_record(records, page)
        if rec is None:
            report.unmatched.append(f"{page['source_url']}: {why}")
            continue
        seen_ids.add(rec["canonical_id"])
        where = f"[{rec['canonical_id']}]"
        before = report.checked
        state = _PageState()
        for row in page.get("rows", []):
            if "label" not in row or "value" not in row:
                raise InputError(f"{where} row without label/value: {row!r}")
            section = _norm_section(row.get("section"))
            idx = next(
                (
                    i
                    for i, r in enumerate(rules)
                    if r["_section"] == section and r["_re"].search(row["label"])
                ),
                None,
            )
            if idx is None:
                key = f"{row['section'] + ': ' if row.get('section') else ''}{row['label']}"
                report.unmapped_labels[key] = report.unmapped_labels.get(key, 0) + 1
                continue
            rule_hits[idx] += 1
            if rules[idx]["_fields"]:
                _compare_row(rec, rules[idx], str(row["value"]), where, report, state)

        if report.checked - before < _MIN_FIELDS_PER_PAGE:
            report.mismatches.append(
                f"{where} only {report.checked - before} field comparisons "
                f"(< {_MIN_FIELDS_PER_PAGE}); empty/captcha fetch or stale mapping?"
            )
        for f in sorted(mapped_fields - state.shown):
            if _unsupported(rec, f):
                report.mismatches.append(
                    state.blank.get(f)
                    or f"{where} {f}: record {rec[f]!r} but no row on the page shows it"
                )

    report.unused_rules = [
        rules[i]["label"]
        + (f" [section {rules[i]['section']}]" if rules[i].get("section") else "")
        for i, n in enumerate(rule_hits)
        if n == 0
    ]
    report.unsampled = sorted(
        r["canonical_id"] for r in records if r["canonical_id"] not in seen_ids
    )
    return report


def _print_report(report: Report, mapping: list[dict], n_pages: int) -> None:
    print("Mapping decisions (review these — they encode semantics):")
    for r in mapping:
        extras = {k: v for k, v in r.items() if k not in ("label", "field")}
        print(f"  {r['label']!r:40} → {r['field']}" + (f"  {extras}" if extras else ""))
    print(
        f"\nPages transcribed: {n_pages}; records: {report.n_records}; "
        f"field comparisons: {report.checked}"
    )
    if report.unused_rules:
        print("Rules that matched no row (typo, or layout not sampled?):")
        for label in report.unused_rules:
            print(f"  {label}")
    if report.unmapped_labels:
        print("Unmapped site labels (not compared):")
        for k, n in sorted(report.unmapped_labels.items()):
            print(f"  {n:4d}× {k}")
    for title, items in (
        ("ERRORS", report.errors),
        ("UNMATCHED PAGES", report.unmatched),
        ("MISMATCHES", report.mismatches),
    ):
        if items:
            print(f"\n{title} ({len(items)}):")
            for line in items:
                print(f"  {line}")
    if report.unsampled:
        shown = ", ".join(report.unsampled[:10])
        more = (
            f", … (+{len(report.unsampled) - 10})" if len(report.unsampled) > 10 else ""
        )
        print(f"\nUnsampled records ({len(report.unsampled)}): {shown}{more}")


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--manufacturer", required=True, help="drivers.json `manufacturer` value"
    )
    p.add_argument("--transcription", type=Path, required=True)
    p.add_argument("--mapping", type=Path, required=True)
    p.add_argument("--drivers", type=Path, default=Path("web/drivers.json"))
    p.add_argument("--require-full-coverage", action="store_true")
    args = p.parse_args(argv)

    drivers = json.loads(args.drivers.read_text())["drivers"]
    transcription = json.loads(args.transcription.read_text())
    mapping = json.loads(args.mapping.read_text())

    try:
        report = verify(drivers, args.manufacturer, transcription, mapping)
    except InputError as e:
        print(f"bad input: {e}", file=sys.stderr)
        return 2
    _print_report(report, mapping, len(transcription))
    if report.failed(args.require_full_coverage):
        print("\nFAIL")
        return 1
    sampled = report.n_records - len(report.unsampled)
    print(f"\nPASS ({sampled}/{report.n_records} records verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
