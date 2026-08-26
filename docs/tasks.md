# Follow-up tasks

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
- `SpecSource.DERIVED` currently only means "xmech doubled from labelled
  one-way" (docstring at `model.py:42`). It's really the same shape of
  concept — a semantic transform applied at parse — but as a single enum
  value with a fixed comment it can't grow. Either promote to a richer
  assumption tag or leave alone and add assumptions alongside.
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
