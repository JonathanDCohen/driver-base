# Follow-up tasks

---

## Monacor duplicate canonical_ids

**Added:** 2026-11-02 (surfaced during export-feature verification)

`web/drivers.json` has 13 Monacor records with canonical_ids ending in
`__dup_<model>_<Z>` that are byte-identical to another record's canonical_id,
so the "dupe" suffix doesn't actually disambiguate. In the bulk export, this
causes 6 FFS-viable rows to overwrite each other in the entries map
(1554 viable per audit → 1548 written). The export dedup logic by filename
works correctly; the bug is upstream in the Monacor scraper's canonical_id
assignment. Example: `monacor__an2075__8ohm__dup_an2075_8` appears twice.

Fix location: whatever Monacor scraper step assigns `__dup_` suffixes —
the suffix needs to be unique per occurrence (e.g. include a sequence
counter or a source-fragment hash).

---

## Close export-viability gaps on in-scope drivers

**Added:** 2026-11-02 (during export-feature build)

The in-browser exporter skips drivers that lack the minimum fields for the
chosen format, with a user-visible warning. Scan of `web/drivers.json`
(2026-11-02, 2212 drivers total) summarized below; **per-driver worklist
grouped by manufacturer in [`docs/export-viability.md`](export-viability.md)**.

- **FFS** (needs `fs_hz`, `qms`, `re_ohm`, `bl_tm`, `mms_g`, `sd_cm2`):
  1554 OK / 658 missing. Breakdown: `hf_compression` 352 (data-source
  reality — HF compression drivers don't publish full T/S anywhere, out of
  scope for closure), `guitar_bass` 92, `tweeter` 85, `lf_woofer` 49,
  `fullrange` 44, `passive` 35 (schema mismatch — no T/S applies).
- **WinISD** (needs `fs_hz`, `qts`): 1580 OK / 632 missing. Distribution
  mirrors FFS; `qts` missing on 616 rows is the biggest single gap.
- **Realistic ceiling** once HF compression (352) and passive (35) are
  excluded: ~1825/2212 for FFS. The addressable gap is ~270 drivers, most
  of them on the LF/midbass side where T/S is normally published.
- **Top manufacturers to work down** (FFS): Dayton 106, B&C 99,
  Celestion 98, 18Sound 84, Eminence 83, Beyma 58, Monacor 56.
- Most-missing field (FFS): `mms_g` (622), `sd_cm2` (593), `qms` (588),
  `bl_tm` (572), `fs_hz` (505), `re_ohm` (449).

Re-run the audit after each scraper fix:
```
python3 - <<'EOF'
# see tools/ or regenerate from the one-shot in commit history
EOF
```
(If this gets run repeatedly, promote the one-shot in
`docs/export-viability.md`'s generation to a proper
`tools/audit_export_viability.py`.)

---

## Framework gaps surfaced by SB Acoustics / Monacor / Peerless

**Added:** 2026-09-01 (during SB/Monacor/Peerless scraper landing)

The three new scrapers publish fields the framework has no slot for. All
deliberately deferred — v1 downstream consumers don't need them. Surface if
a downstream feature does.

- **`magnet_weight_kg`** — SB Acoustics, Monacor, Celestion, Beyma all publish
  it on every driver. Currently ignored. Would compose with `magnet_type` and
  `flux_density_t` for motor-strength approximations.
- **`voice_coil_winding_height_mm`, `magnetic_gap_height_mm`** — SB Acoustics
  publishes both; useful for excursion/BL derating math (Xmax = (VC winding −
  gap) / 2). Would enable one more consistency check.
- **`ean` / `gtin`** — Monacor publishes 13-digit GTINs on every product.
  Useful for retailer cross-linking in v2 (Parts Express carries some Monacor
  as MC-branded resells).
- **Coax HF sensitivity slot at 2.83V/1m** — `coax_hf_sensitivity_db_1w_1m`
  exists, but SB Acoustics coax HF sections publish at 2.83V/1m. Currently
  left null to avoid mis-slotting. Add `coax_hf_sensitivity_db_2_83v_1m`
  or a per-manufacturer conversion pass if this data becomes load-bearing.
- **`SpecSource.JSON_API` provenance for API-only data** — Peerless is the
  first scraper whose entire spec set comes from a JSON body (not HTML). The
  enum already covers it; `manufacturers.md` documents the pattern; but the
  framework doc (`docs/framework.md`) doesn't call out that `parse_artifact`
  is expected to dispatch on `raw.content_type` when a scraper serves
  multiple content types. Not urgent — no scraper needs the hybrid path
  today — but document if a second JSON scraper lands.

---

## Bring horns back with a horn-appropriate schema

**Added:** 2026-08-25 (globalized 2026-08-26)

We currently drop every `DriverKind.HORN` record — Faital `HF_Horns` never
enters the pipeline (skipped at enumerate), and every other scraper's horns
get filtered out in `orchestrator._post_parse_pipeline`. Passive horns don't
map to the transducer-shaped driver schema (no T/S, no impedance, no AES
power in the usual sense), and treating them like drivers leaves ~54 records
with mostly-null cells.

When we're ready to represent them:

- Design horn-appropriate fields — likely throat diameter, mouth diameter,
  cutoff frequency, horizontal + vertical dispersion, coverage pattern, gain.
  Populate for kind `HORN` only; existing `DriverKind.HORN` enum is already
  in place and used by every scraper.
- Remove the `DriverKind.HORN` filter in `orchestrator._post_parse_pipeline`.
- For Faital specifically: add the `HF_Horns` seed back in
  `scrapers/faital.py::discover_seeds` (page is static HTML — plain GET, same
  shape as coax) and reinstate the enumerate assertion.
- Add per-scraper parse tests for at least one horn fixture per manufacturer
  so the horn field mapping is regression-covered.



Backlog items surfaced during work but not landed in the same commit.
Newest at the top; date each entry with when it was written.

---

## Surface per-manufacturer assumptions to the reader

**Added:** 2026-08-25 (during Faital scraper rework)

We are quietly making semantic assumptions about published manufacturer specs —
these need a first-class place in the data model and/or the web UI, so a reader
can see *why* a field looks the way it does and whether they trust it.

**Concrete example that surfaced the need:**
Faital publishes `Xdamage` with the footnote "Maximum excursion before permanent
damage." The framework's `xmech_mm` field is nominally **peak-to-peak** (see
`model.py:103` — "peak-to-peak by convention"). Empirically Faital's number is
**one-way** — Xdamage/Xmax ratios cluster at ~1.7–1.85, which is physically only
possible if both are one-way (damage limit ~1.5–2× linear limit; a p-p Xdamage
under 2× a one-way Xmax would mean damage-onset is *inside* the linear range,
which is impossible). So we're storing Faital's Xdamage into a p-p-conventioned
field as a one-way value, and we've made the consistency gate skip Faital via
`_XMECH_ONE_WAY_MANUFACTURERS` in `consistency.py`. That's a load-bearing
assumption invisible to anyone reading `xmech_mm` in the output.

**What "surfacing" should look like** — sketch, not spec:
- A per-field assumption tag (co-located with `spec_source`) that names the
  assumption applied at parse time — e.g. `{"xmech_mm": "one_way_as_reported"}`
  vs `{"xmech_mm": "peak_to_peak_as_reported"}` vs `"doubled_from_one_way"`.
- Enumerated in code so we can grep for "which fields on which manufacturers
  are assuming X", and rendered in the web UI as a hover / info icon on the
  cell.
- Ideally: a manufacturer-summary panel that lists every semantic assumption
  the scraper makes ("Faital: Xdamage stored as one-way; xmech_mm gate
  bypassed. Beyma: Xdamage stored as peak-to-peak per explicit column label.").

**Adjacent scope worth touching in the same effort:**
- `SpecSource.DERIVED` is now a catch-all for several unrelated transforms —
  xmech doubled from one-way, power derived from AES/program, sensitivity
  derived from BL/Mms/Re, Vd from Sd×Xmax, EBP from Fs/Qes (see `derived.py`,
  `power.py`, `sensitivity.py`). It's really the same shape of concept as the
  assumption tags above — a semantic transform applied at parse — but as a
  single enum value it can't distinguish which transform. Either promote to a
  richer assumption tag or leave alone and add assumptions alongside.
- Faital's `Magnet` value discards magnet *shape* (`Neodymium Ring` → just
  `Neodymium`); users looking for slug vs ring vs bar are silently losing
  info. Same pattern: an assumption "shape suffix dropped."

---

## Faital: potential new fields identified but not added

**Added:** 2026-08-25

Fields present on Faital product pages that don't map into the current schema
and might be worth capturing:

- `Winding Material` (e.g. `Cu`, `Al`) — voice-coil wire material
- `Former Material` (e.g. `Glass Fiber`, `Kapton`) — VC former material
- `Flux Density` (e.g. `1.2 T`) — motor magnetic flux
- `Cone Surround` — surround material (Faital hides value in footnote text)
- `Mmd` — moving mass without air load (Mms minus air load)
- `AES/Max power at aggressive crossover` — HF drivers publish a second AES rating at a lower crossover (e.g. `AES above 0.65 kHz` alongside `AES above 0.9 kHz`); currently we drop the lower-crossover rating on the floor. Could live in a new `power_aes_aggressive_watts` field alongside a `power_aes_crossover_hz` for the crossover it's rated at.

Also present but probably not worth adding: `Bolt Circle Diameter`,
`Flange and Gasket Thickness`, `Shipping Box`, `Shipping Weight`,
`Basket Material`, `Demodulation` (motor construction note), `Spider Profile`.
