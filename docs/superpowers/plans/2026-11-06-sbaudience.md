# SB Audience Scraper + verify-scrape Skill — Implementation Plan

**Status (2026-11-06):** All steps done, including the final style review fixes. Outcome: 60/60 records; verify-scrape full coverage gave 1,852 comparisons and 0 mismatches. See `docs/manufacturers.md` § SB Audience.

**Goal:** (1) Add an `sbaudience` scraper for sbaudience.com (SB Acoustics' pro-audio sister brand; separate site, separate CMS). (2) Add a project-level skill, `verify-scrape`, that checks a scraper's `web/drivers.json` output against fresh reads of the manufacturer site. (3) Run the skill on SB Audience before the commit.

## Recon findings (2026-11-06, live site)

- **CMS:** Concrete5 (`/index.php/...` URLs). `robots.txt` disallows only CMS internals (`/blocks`, `/concrete`, `/tools`, ...). Product pages are allowed. No `Crawl-delay`.
- **Enumeration:** `sitemap.xml` is stale (lists 2014 sbacoustics.com URLs), so don't use it. Every page's superfish nav lists every product as `/index.php/products/{category}/{slug}/`. **64 products** in 6 categories: `woofers` 24, `subwoofers` 14, `compression-drivers` 15, `open-baffle-drivers` 4, `coaxials` 3, `horns` 4.
- **Product HTML has NO specs.** The page has a spec JPG plus `<a href="/index.php/download_file/-/view/{id}/">Click to download Datasheet</a>`. Two pages (`bianco-44cd-pk`, `rosso-18sw750`) carry a second `download_file` link with empty text, so pick the anchor whose text contains "Datasheet".
- **Datasheet = one-page text PDF** (`Content-Disposition: attachment; filename="MODEL.pdf"`, `application/octet-stream`). All 64 are 1 page. Text layer present in all 64.
- **PDF layout:** title line 1 = model (`BIANCO-15MW350`); line 2 = subtitle `15” - Midwoofer- 700W - 100dB`. Then side-by-side tables:
  - Standard (38 sheets): `Dimensions & Weight` | `Specs` | `Thiele Small Parameters`
  - Compression (15 sheets): `Dimensions & Weight` | `Specs` (no T/S block)
  - Coax (3 sheets): Specs has `LF Unit` / `HF Unit` value sub-columns
  - Image headers (4 sheets: bianco-18sw450, rosso-18sw650, rosso-18sw750, rosso-15w400): column headers are images, so there's no header text to anchor on. Labels are still text.
- **Text quirks:** PDFs contain literal space glyphs mid-token (`0.23 m m/N`, `1 2.1 Tm`, `B I`). Fix: drop whitespace chars before `extract_words`, then split words geometrically (`x_tolerance=1.0`). Verified against all 64 sheets: removes every artifact, and real word gaps (~2.2pt) still split. Footnote markers (`Xmax (4)`) sometimes sit about 3pt below the label baseline. `Bl` renders as `BI`/`Bl`/`B I`. Re is `RDC` on compression sheets.
- **Sensitivity label varies:** `(1W/1m)`, `(1W/1m)(3)`, `(2.83V/1m) (3)`, `(2.83V/1m)`. Slot by label. All sampled drivers are 8Ω, so the two slots agree numerically.
- **Xmax** footnote: `((Winding depth - magnetic gap depth)/2) + (gap/3)` is one-way, so no halving. **Xdamage** = "Maximum excursion (p-p) before permanent damage" → `xmech_mm` (p-p by convention).
- **Power:** `AES Power Handling` → `power_aes_watts`; `Maximum Power Handling` ("3dB greater than nominal") → `power_program_watts`, the same call Ciare made.

## Design

- `src/driver_base/scrapers/sbaudience.py`, `name="sbaudience"`, `manufacturer_display="SB Audience"`.
- `discover_seeds` → `https://www.sbaudience.com/index.php/products/`.
- `enumerate` → regex nav hrefs; category → `DriverKind` (`woofers`/`subwoofers`/`open-baffle-drivers` → LF_WOOFER, `compression-drivers` → HF_COMPRESSION, `coaxials` → COAX). Skip `horns` at enumerate, because the pipeline drops HORN anyway and this saves 8 fetches. An unknown category is skipped, not guessed.
- `parse_artifact` two-phase via existing followup machinery (MAX_FOLLOWUP_ROUNDS):
  1. HTML product page → no fragments; one followup `SeedRef(pdf_url, SeedContext(driver_kind_hint, category_id, parent_model=<H1 tail>))`.
  2. Body starts with `%PDF` → parse → one `DriverFragment`.
- PDF parse: pdfplumber words → gap-chunks (≤6pt) → **label-anchored cells** (works without header text): each row is grouped by `top` within 4pt; walking chunks left→right, a chunk whose text starts with a known label opens a new cell; following chunks are its values; chunks before any label (notes, drawing numbers) are discarded. Longest-prefix label match strips a trailing footnote `(n)`.
- Coax: Specs cells with 2 value chunks → [LF, HF]. Header x positions (`LF Unit`/`HF Unit`) disambiguate single-value cells when present.
- Midrange: subtitle contains `Midrange` → FULLRANGE (repo convention: Dayton, HOQS, Monacor, SB Acoustics).
- `nominal_size_mm` from subtitle inches (`15”`, `1.4”`) → PDF_TEXT. HF compression: subtitle inches = throat, which matches the repo convention (nominal = throat). `throat_diameter_mm` comes from the `Nominal Throat Diameter` row.
- Model from PDF title line. Fall back to `parent_model` if absent. A test asserts they agree across fixtures.
- SpecSource: table fields `PDF_TABLE`; subtitle-derived `PDF_TEXT`.
- **Coax mapping (explicit):** LF column → the generic fields. HF column: nominal Z → `coax_hf_impedance_nominal_ohm`, min Z → `coax_hf_impedance_min_ohm`, AES → `coax_hf_power_aes_watts`, freq range → `coax_hf_freq_low/high_hz`, VC Ø → `coax_hf_voice_coil_diameter_mm`, `Cone Surround` HF value (PEEK dome) → `diaphragm_material` (Ciare/SB Acoustics precedent). **Dropped:** HF Maximum power (it is 2×AES = program-class, and `coax_hf_power_peak_watts` is peak-class, so don't mis-slot it), HF sensitivity (2.83V; no 2.83V coax_hf slot, same as SB Acoustics/Ciare). HF Re isn't published.
- Other dropped rows (no slot): winding/gap depth, basket, spider, demodulation, recone kit, shipping/gross. Log new ones to the `docs/tasks.md` framework-gap section.
- **Power slot is decided by the footnote, not the label word:** "Maximum Power Handling (2)", whose footnote is "defined as 3dB greater than nominal", goes to program, not `power_peak_watts`.
- **`source_url` = the product page, not the PDF download link** (the UI links model names to `source_urls[0]`). Add `parent_source_url: Optional[str]` to `SeedContext` (small, generic framework addition). The HTML phase sets it; the PDF phase uses it.
- **Xdamage → `xmech_mm` verified safe:** Xdamage/Xmax ratio across all 60 driver sheets is 2.19–4.74 (≥1.9 gate), consistent with the sheet's own "(p-p)" footnote. SB Audience is NOT added to `_XMECH_ONE_WAY_MANUFACTURERS`.
- `expected_min_records = 50`. Enumerate dedupes URLs (nav repeats). PDF logic lives in the scraper module (sole consumer). Promote it to `parsers/pdf.py` when a second PDF scraper appears.
- New runtime dependency: **`pypdfium2`** (PDFium; one binary wheel, no transitive deps). We first tried `pdfplumber`, but it pulls `pdfminer.six` → `cryptography`, and cryptography ≥49 ships no Intel-macOS wheels, so `uv add` tried a Rust source build and failed on this machine. We take the per-glyph loose boxes + baseline origins and do our own word/row grouping. `framework.md` already anticipates `parsers/pdf.py` / `SpecSource.PDF_TABLE`.

## Steps

Each step lists its model, its gate (a deterministic completion signal), and its reviewers.

### Step 1: Scraper + dependency + tests — **Opus** (layout-parsing design is the hard part)
- `uv add pdfplumber`. Write the scraper, register it in `scrapers/__init__.py`.
- Fixtures (`tests/fixtures/sbaudience/`): `seeds/products.html` (trimmed to nav), one product HTML, and image-stripped PDFs (pypdf `remove_images`; verified that stripping leaves pdfplumber output identical) for one sheet per layout: standard woofer, coax, compression, image-header sub, midrange.
- `tests/test_parse_sbaudience.py`: enumerate count/kinds/horn skip; HTML→followup (picks the "Datasheet" anchor); per-layout field assertions against values read by hand from `pdftotext -layout` of the same fixture; coax LF/HF split; midrange→FULLRANGE; model == parent_model.
- Orchestrator-level test (FakeFetcher: products page → product HTML → PDF) proving the followup context handoff (kind, model, source_url) end-to-end, because the followup path is otherwise unexercised in the repo.
- **Gate:** `uv run pytest -q` green; `uv run ruff format --check` clean and no new `ruff check` rule categories beyond the repo's existing `Optional`-style (UP045/UP035) baseline; a scratch script (sheets in the session scratchpad, not `data/cache`) runs parse + `enforce_consistency` over all 60 driver sheets and reports 0 parse exceptions, **exactly 60 records surviving consistency**, and prints every rejection reason if any.
- **Reviewers:** 2 adversarial (Sonnet), "assume bugs in this diff."

### Step 2: verify-scrape skill + deterministic comparer — **Opus** for the skill design, **Sonnet** for comparer review
- `tools/verify_scrape.py` + `tests/test_verify_scrape.py`.
  - Contract (input formats, matching, printed-precision tolerance, every failure mode) lives in the `tools/verify_scrape.py` docstring. Key points: transcribers copy raw label/value rows; a separate mapping encodes the semantics; records match by `source_url`; unmatched or unsupported values fail.
- `.claude/skills/verify-scrape/SKILL.md`: (a) fresh fetch into the scratchpad, never `data/cache` and never `--refetch` into the shared cache; (b) blind transcription by fresh-context subagents that never see `drivers.json` or the scraper code, who never see the repo and only transcribe (the semantics live in the mapping); (c) run `tools/verify_scrape.py`; (d) triage each mismatch (scraper bug / transcription slip / mapping error / override / source ambiguity); (e) coverage check: live product count vs records.
- **Gate:** `uv run pytest tests/test_verify_scrape.py` covers: all-match exits 0; one wrong value exits 1 and names the field; an unmatched source_url exits 1; a null-in-record exits 1; precision tolerance: half a unit in the last printed digit (`0.23` vs `0.236` fails; `0.23` vs `0.234` passes). The earlier "0.232 fails" spec was wrong, because 0.232 rounds to the printed 0.23.
- **Reviewers:** 2 adversarial (Sonnet).

### Step 3: Live scrape + verification — main loop (orchestration) + **Sonnet** transcribers
- `uv run driver-base --scraper sbaudience` (writes `web/drivers.json`; other scrapers rehydrate from prior).
- **Gate A:** `per_scraper_status.sbaudience` ok; **exactly 60** SB Audience records (followup failures are silent in the orchestrator, so a count short of 60 is a failure, not "explained"); `scraper_run_stats` fetch counts are consistent (1 seed + 60 HTML + 60 PDF); a script compares records keyed by `canonical_id` showing every non-SB-Audience record unchanged vs `HEAD` and the same count.
- Run verify-scrape at **full coverage**: 4 Sonnet transcribers × 15 sheets. Each fetches the product page + PDF fresh into its own scratch dir and reads the PDF with the Read tool (rendered page, which is independent of the pdfplumber text layer). They are blind to drivers.json and the scraper.
- **Gate B:** `tools/verify_scrape.py --require-full-coverage` exits 0. Any mismatch is either fixed in the scraper (then re-run) or recorded as a named source erratum with evidence.
- Reviewers: the verification itself is this step's adversarial check (independent extraction path: different extractor + LLM reading vs pdfplumber code).

### Step 4: Docs — **Haiku/Sonnet-level**, done in the main loop (small)
- `docs/manufacturers.md`: coverage-table row, full SB Audience section, update total estimate and manufacturer count.
- `docs/tasks.md`: new framework gaps (coax HF program power).
- `docs/framework.md`: note that `SpecSource.PDF_TABLE` is now exercised (if a "not yet exercised" claim exists).
- Memory: nothing new expected. Re-check `MEMORY.md` entries for staleness.
- **Gate:** `grep -n "SB Audience" docs/manufacturers.md` shows the table row + section; record count in the doc equals the actual count.

### Step 5: Final style/consistency/simplicity review — 2 reviewers (Sonnet)
- Land fixes, re-run pytest + ruff. Then show the diff and **wait for commit approval** (repo memory: no commits without explicit go-ahead).

## Plan-review reconciliation (2026-11-06)

Two adversarial reviewers. Accepted:
- `source_url` → product page via new `SeedContext.parent_source_url`.
- Orchestrator-level followup test.
- Consistency-surviving count gate (exactly 60).
- Xdamage ratio table, computed: all ≥2.19.
- Explicit coax table.
- Footnote-decided power slot.
- `data/rejections` claim dropped (consistency rejections aren't written there; the scratch script prints them instead).
- Comparer redesign: raw label/value transcription + separate mapping, URL-keyed matching, fail on unmatched, printed-precision tolerance, unit tests.
- Full coverage instead of an 18-sheet sample.
- Read-tool (rendered) transcription.
- `canonical_id`-keyed non-regression diff.
- Category count typo.

Declined: overloading `series` for the URL (a dedicated field is cleaner).
Noted: `pypdf` is used only ad hoc in the scratchpad for fixture stripping and is not added as a dependency. `docs/export-viability.md` is a dated snapshot and is not regenerated here.
