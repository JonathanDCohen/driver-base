# Manufacturer scraping strategy (v1)

## How this was arrived at

Every claim below (URL patterns, extraction selectors, T/S values, catalog counts) came out of an empirical validation loop, not manufacturer marketing pages. Sonnet agents produced an initial recon per manufacturer (WebFetch a starting URL, propose an extraction strategy, capture sample T/S values from one product), then a second agent per manufacturer wrote and ran a throwaway Python script via `uv run --with httpx --with beautifulsoup4 --with lxml` that fetched the same page and applied the proposed extraction, comparing the extracted values to the recon's claims. If any numerical value disagreed by more than ±5 % OR the extraction returned an empty dict, the loop iterated with a refinement prompt. **9 of 10 manufacturers converged on iteration 1 with 0.00 % delta on sampled T/S values.** Faital Pro and La Voce each needed 2 iterations. Full workflow output lives at `/private/tmp/claude-501/-Users-jonathancohen-src-driver-base/f8a49839-7228-4a1a-8498-660f9a6beff4/tasks/w072etvbx.output` (regeneratable if pruned).

The selectors below are the ones the validator's script actually used. Substituting them into `parse_artifact()` should Just Work; if you find a selector that doesn't, the recon should be considered stale.

## Coverage summary

| Manufacturer | Homepage | Enumeration | Product page | Specs | Records | Notes |
|---|---|---|---|---|---|---|
| 18Sound | eighteensound.it | 6 category pages (5 static, 1 JS) | static HTML | `li.float30` (prose pairs) | ~320 | Tweeter category needs Playwright at discover time |
| B&C Speakers | bcspeakers.com | 2 category pages (Remix SSR) OR `_data=` JSON | static HTML | `div.grid.grid-cols-2` (grid pairs) | ~274 | Also has a hidden Remix `_data=` JSON API per product |
| Celestion | celestion.com | `product-sitemap.xml` (213 URLs) | static HTML | `div.product-detail-spec-col-line` (div pairs) | 213 | 10-second `Crawl-delay`; guitar-bass drivers exempt from T/S REJECT |
| Dayton Audio | daytonaudio.com | 14 subcategory pages with `?pagenum=N` | static HTML | `#collapseTwo table.table tbody tr` (table) | ~370 | Silent pagination wrap; extensive imperial units; `--` = null |
| Eminence | eminence.com | `/products.json?limit=250` (Shopify) | static HTML | `table#em-detail tr` (table) | 155 active / 201 with archived | No category on product → `classify_driver_kind()` from `product_type` |
| Faital Pro | faitalpro.com | 4 category listings — POST `<cat>/search.php` for LF+HF-drivers, static GET for coax+HF-horns | static HTML | `table.tbl_data tr` (table) | 158 URLs enumerated (104 LF + 35 HF + 14 coax + 5 horn) | Footnote suffixes on labels; `÷` frequency separator; POST bodies dropped on 301 → use no-www host |
| HOQS | hoqs.org | `/products.json?limit=250` (Shopify) | static HTML | `var speakerData = ({...});` (inline JS object) | 13 | **Sensitivity is `2.83V/1m`, not `1W/1m`** |
| RCF | rcf.it | 6 category pages via `?serieId=` | static HTML | `div.specifications div.row > div.col-md-6:first-child + div.col-md-6.font-family-semibold` (div pairs) | 137 (103 excl. Custom Designs) | No usable sitemap; Liferay OAuth endpoints 403 without token |
| Beyma | beyma.com | 12 English category pages (10 kept, 2 dropped) | static HTML | `div.block-product-features div.items div.item` (div pairs) | ~194 active | `passive-filter` + `accesories` slugs dropped at enumeration |
| Jensen | jensentone.com | `sitemap.xml` (63 product URLs across 7 categories) | static HTML | `div.jensentone-ohm-specs` (4 captioned `<table>`s) | ~120 (multi-impedance expansion from 63 URLs) | Every product is guitar/bass; many pages carry both 8Ω and 16Ω specs — one `DriverFragment` emitted per impedance column |

**Deferred:** La Voce (site unreachable — see `memory/la-voce-parked.md` and the "Deferred" section below).

**Total v1 records estimate:** ~1,700 across the 9 in-scope manufacturers (each impedance variant is a separate record per the ID scheme).

---

## 18Sound (`eighteensound`)

**Homepage:** https://www.eighteensound.it (Italy). `robots.txt` has no active directives (all commented out); no `sitemap.xml`.

**Enumeration.** Fetch each of the 6 category listing pages:
- `/en/products/lf-driver`
- `/en/products/hf-driver`
- `/en/products/coaxial`
- `/en/products/line-array-source`
- `/en/products/horn`
- `/en/products/tweeter` — **JS-rendered, requires Playwright.** The `<div class="content">` is empty in static HTML; category-id=8 lives in inline JS. Product pages for tweeters ARE static once you have the URL — Playwright is needed at enumerate time only.

Extract product URLs with the regex:
```
r'href="(/en/products/(?:lf-driver|hf-driver|coaxial|line-array-source|horn)/[0-9]+-[0-9]+/[0-9]+/[^"#?]+)"'
```

**URL pattern.** `/en/products/{category}/{diameter}/{impedance}/{model}` where `diameter` is a **hyphenated pair** like `18-0` (nominal-decimal), not just `18`. Example: `/en/products/lf-driver/18-0/8/18LW1400`. The second segment after `diameter` (impedance in ohms) means the same model at 4Ω vs 8Ω is two distinct URLs. Per the ID scheme, these become two separate `canonical_id`s (`18sound__18lw1400__4ohm` and `18sound__18lw1400__8ohm`), which is what we want.

**Sample product page:** https://www.eighteensound.it/en/products/lf-driver/18-0/8/18LW1400

**Extraction.** Every spec is a `<li class="float30">` inside `<div class="productDetailsContent">` sections. Structure:
```html
<li class="float30">
  <span>Resonance Frequency</span>
  <sup class="note">(1)</sup>       <!-- optional footnote, NOT inside <b> -->
  <b>31 Hz</b>
</li>
```
Selector: `li.float30`. Per element, `li.select_one("span").get_text(strip=True)` is the label; `li.select_one("b").get_text(strip=True)` is the value. Four sections exist (`id="specifications"`, `id="design"`, `id="parameters"`, `id="mounting_and_shipping_info"`); all use the same `li.float30` pattern.

**Sample data captured & validated (`18LW1400`, 8Ω):**
- Fs 31 Hz, Qts 0.29, Qes 0.31, Qms 7.2, Vas 297 dm³, Sd 1225 cm², Xmax 9 mm, Mms 190 g, Bl 24.7 T·m, Le 2.3 mH, Re 5.0 Ω, EBP 100 Hz
- Nominal impedance 8 Ω, Minimum impedance 6.4 Ω
- Sensitivity 98.0 dB, Frequency range 28–2500 Hz
- Nominal Power Handling 1000 W, Continuous Power Handling 1400 W
- Voice coil diameter 100 mm, Magnet Ferrite, Net weight 13.3 kg

**Field mapping (18Sound → Driver):**
- `Resonance Frequency` → `fs_hz` (label is verbose, not `Fs`)
- `Nominal Power Handling` → `power_aes_watts`
- `Continuous Power Handling` → `power_long_term_watts` (larger than nominal; NOT `power_program_watts`)
- `Sensitivity` → `sensitivity_db_1w_1m` (unlabelled → 1W/1m by 18Sound convention)
- `Frequency Range` → `freq_low_hz` / `freq_high_hz` (parse `28 - 2500 Hz` with `parse_range`)
- `Bl` value like `24.7 Txm` — the `x` is a multiplication token; `parse_bl_tm` handles it

**DriverKind mapping (from `SeedContext.driver_kind_hint`):**
```
lf-driver         → LF_WOOFER
hf-driver         → HF_COMPRESSION
coaxial           → COAX
line-array-source → FULLRANGE
horn              → HORN
tweeter           → TWEETER
```

**Quirks:**
- Some product slugs contain URL-encoded spaces: `12nd610%20-%2016ohm`. URL-decode BEFORE dedup; use case-insensitive comparison.
- `Vas` and `Sd` values contain nested `<sup>` for units (`dm³`); `b.get_text(strip=True)` returns clean text. Do NOT read `b.text` — nested markup could confuse.
- Recon estimate: **~194 LF + ~83 HF + ~18 coaxials + ~2 line-array + ~9 horns + unknown tweeters** = 320-350 total. Set `expected_min_records = 275`.

**Excluded from v1:** `/en/products/{cat}/archive` URLs (discontinued products). Extension point via `discover_archive()`.

---

## B&C Speakers (`bcspeakers`)

**Homepage:** https://www.bcspeakers.com (Italy). No `robots.txt` (returns 302 to `/en`); no `sitemap.xml`.

**Enumeration** — two complementary strategies:

1. **Category HTML** (fallback, simplest): fetch `/en/products/lf-driver` (175 unique product page-links) and `/en/products/hf-driver` (99 unique links). Products are server-rendered in the HTML as `<a href="/en/products/{category}/{inches}/{ohms}/{model}">`.
2. **Remix `_data=` JSON** (preferred): append `?_data=routes%2F%24locale_.products.(archive).%24category` to a category URL to get JSON grouped by `size` with each entry carrying a `variants[]` array listing `nominalImpedance` values. Reconstruct per-variant URLs from that. Also works per product: `?_data=routes%2F%24locale_.products_.(preview).%24category_.(archive).%24inches.%24ohms.%24code` returns structured T/S params (`product.params.{fs,re,qes,qms,qts,vas,sd,etaZero,xmax,mms,bl,le,ebp}.computedValue`) — cleaner than HTML regex.

**Sample product page:** https://www.bcspeakers.com/en/products/lf-driver/12/8/12FW64

**Extraction (HTML approach).** Specs are a `div.grid.grid-cols-2` Tailwind grid. Each cell pair: label is a `<p>` inside a `<div>`; value is inside `<h6><span>`. Selector: `div.grid.grid-cols-2 > div > p, div.grid.grid-cols-2 > h6 > span`.

**Caveat on the selector:** specs with a tooltip icon (Sensitivity, Nominal Power, Continuous Power) have a nested `<span>` inside `<span class="relative">` containing an SVG. Use `re.search` or `.get_text(separator="")` with careful slicing — do NOT read `h6.text` directly or you'll capture tooltip content. A more robust regex:
```
r'<div class="grid grid-cols-2[^"]*"><div><p[^>]*>([^<]+)</p></div><h6[^>]*><span[^>]*>([^<]+)'
```

The page duplicates spec rows for responsive layout (mobile vs desktop). ~92 rows, ~46 unique label-value pairs — deduplicate by label.

**Sample data (`12FW64`, 8Ω):**
- Fs 55 Hz, Qts 0.29, Qes 0.32, Qms 3.5, Vas 64 dm³, Sd 522 cm², Xmax 5 mm, Xvar 5 mm, Mms 47 g, Bl 15.5 Tm, Le 1 mH, Re 5.2 Ω, EBP 172 Hz, η₀ 3.6 %
- Nominal 8 Ω / Min 6.7 Ω, Nominal Power 250 W, Continuous Power 500 W, Sensitivity 98 dB, Range 55–3000 Hz
- Voice coil 64 mm, Flux 1.3 T, Net weight 5.65 kg

**Field mapping:** identical to 18Sound for power — `Nominal Power Handling` → `power_aes_watts`, `Continuous Power Handling` → `power_long_term_watts`.

**Sensitivity slot: `sensitivity_db_2_83v_1m`.** The `Sensitivity` cell has a tooltip icon whose `data-tooltip-content` attribute reads *"Applied RMS Voltage is set to 2.83 V for 8 ohms Nominal Impedance."* — so B&C is measuring at 2.83 V, not 1 W. Values are equivalent for 8 Ω drivers (2.83 V ≈ 1 W) but diverge by 3 dB for 4 Ω, so slot placement matters.

**DriverKind mapping:** `lf-driver` → LF_WOOFER; `hf-driver` → HF_COMPRESSION. (B&C has only these two active categories.)

**Recon counts:** 175 LF variants + 99 HF variants = 274 page URLs; ~110 unique LF models + ~60 unique HF models = ~170 unique models. Since each impedance variant is a separate `canonical_id`, `expected_min_records = 250`.

**Quirks:**
- Remix SSR → no headless browser needed; site returns full HTML.
- No `robots.txt` and no `sitemap.xml` (both redirect to `/en`).
- No rate-limiting observed during testing.

---

## Celestion (`celestion`)

**Homepage:** https://celestion.com (UK). **`robots.txt` sets `Crawl-delay: 10` seconds.** Product pages are not disallowed; sitemap index at `/sitemap_index.xml`.

**Enumeration.** `https://celestion.com/product-sitemap.xml` lists 213 product detail URLs (`https://celestion.com/product/*/`) plus one `/products/` index URL to filter out. Total: **213 product pages**.

**Sample product page:** https://celestion.com/product/tf1525/

**Extraction.** Specs are in `<div class="product-detail-spec-col-line">` elements. Each contains exactly two anonymous child `<div>`s: first is the label, second is the value. Selector: `div.product-detail-spec-col-line`. Two logical sections on pro drivers (Specifications: power, impedance, physical; Parameters: T/S) share the same CSS class, so one selector captures both.

**Ignore** `div.product-detail-spec-highlight` — these duplicate values already in the spec-col-line rows.

**Sample data (`TF1525`, 8Ω):**
- Fs 47.60 Hz, Qts 0.493, Qes 0.565, Qms 3.835, Vas 148.41 l, Sd 855.30 cm², Xmax 4.5 mm, Mms 77.93 g, BI 14.57 Tm, Cms 0.14 mm/N, Rms 6.08 kg/s, Le(1kHz) 0.90 mH, Re 5.15 Ω
- Rated impedance 8Ω, Sensitivity 98dB, Range 40-3000Hz
- Power rating 250W, Continuous 500W, EIA 400W
- Chassis Pressed steel, Magnet Ferrite (1.2kg), Voice coil 64mm copper, Cone Kevlar-loaded paper, Cutout 351mm, Unit weight 5.2kg

**Field mapping (Celestion):**
- `Power rating` → `power_aes_watts`
- `Continuous power rating` → `power_long_term_watts`
- `EIA power rating` → `power_eia_watts` (Celestion is the only manufacturer that publishes EIA)
- `Sensitivity` → `sensitivity_db_1w_1m` (Celestion convention)
- `Frequency range` → `freq_low_hz`/`freq_high_hz`
- Note the typo: some pages label it `BI` (letter I) instead of `Bl` (lowercase L). `labels.py` handles both.
- Guitar/bass drivers use variant labels: `Resonance frequency, Fs` (with trailing comma-Fs) and `DC resistance, Re`. Add these to `labels.py`.

**DriverKind mapping:** driven by product-page context, not URL. Guitar/bass speakers (Vintage 30, G12 EVH, etc.) → `GUITAR_BASS`. Pro-audio drivers → LF_WOOFER / HF_COMPRESSION / TWEETER / COAX. Set via a `classify_driver_kind()` map keyed on category breadcrumb text (needs to be captured from the product page HTML — no clean sitemap kind hint).

**GUITAR_BASS exemption:** these drivers legitimately lack Thiele-Small parameters (Qts, Qes, Qms, Vas) in the HTML. The cross-field consistency check `missing_ts_for_expected_kind` downgrades from REJECT to WARN for `GUITAR_BASS`; the populated-rate floor for T/S fields does not apply.

**Rate-limiting.** Respect the 10-second `Crawl-delay`. At 10s × 213 products ≈ 36 minutes wall time per full run just for Celestion, before parse. Cache-hits (7-day TTL) reduce iteration cost dramatically. Consider running Celestion on a separate bi-weekly cron if weekly is too aggressive.

**Quirks:**
- Values often carry dual units (`4.5mm / 0.18in`); parse the primary (metric) with `parse_length`.
- Ω is HTML-entity-encoded as `&Omega;` in some pages; parse HTML not plain text.
- `robots.txt` has a Yoast SEO block with a bare `Disallow:` at the end; parser must not misinterpret this as blocking everything.

---

## Dayton Audio (`daytonaudio`)

**Homepage:** https://www.daytonaudio.com (US; Parts Express house brand). `robots.txt` allows `/product/` and `/category/`; no `sitemap.xml` (404).

**Enumeration.** No sitemap available. Crawl 14 subcategory pages with `?pagenum=N` pagination (20 products/page):
```
/category/118/woofers            /category/121/subwoofers
/category/119/tweeters           /category/120/midranges
/category/123/full-range         /category/161/pro-audio-drivers
/category/125/passive-radiators  /category/178/mini-micro-speakers
/category/272                    /category/96/horns-waveguides    (compression, horns — no slug)
/category/274                    /category/126/replacement-diaphragms  (planar/ribbon, diaphragms)
```

**Pagination wrap detection is critical:** the site returns the SAME product set for `pagenum=N` and `pagenum=N+1` when N is past the end (does NOT 404 or return empty). The orchestrator's `enumerate()` compare-across-rounds detects this (already handled centrally: "no new URLs this round → stop"). Product URLs: `/product/{id}/{slug}`.

**Sample product page:** https://www.daytonaudio.com/product/22/dc160-8-6-1-2-classic-woofer-8-ohm

**Extraction.** Specs are in a Bootstrap accordion `#collapseTwo` containing `table.table`. Each row is `td/td` (NOT `th/td`) — first `td` is label (30 % width), second is value. Selector: `#collapseTwo table.table tbody tr`.

**Sample data (`DC160-8`, 8Ω, 6.5" classic woofer):**
- Fs 35.7 Hz, Qts 0.34, Qes 0.38, Qms 3.46, Vas 17.9 liters, Sd 134.8 cm², Xmax 3.15 mm, Mms 29.3 g, BL 10.7 Tm, Le 2.26 mH @1 kHz, Re 6.6 Ω, Cms 0.68 mm/N, Vd 42.5 cm³
- Impedance 8Ω, Sensitivity 86.1 dB @ 2.83V/1m, Range 30–4,000 Hz
- Power RMS 50W, Power max 100W
- Voice coil 35mm, Weight 3.3 lbs., Nominal 6.50", Cutout 144.6mm

**Field mapping (Dayton):**
- `Power Handling (RMS)` → `power_aes_watts` (Dayton's RMS ≈ AES for our purposes)
- `Power Handling (max)` → `power_peak_watts`
- `Sensitivity` label ends `@ 2.83V/1m` → parse into `sensitivity_db_2_83v_1m` slot (Dayton convention: 2.83V, NOT 1W)
- `Frequency Response` → `freq_low_hz`/`freq_high_hz` (handle commas in numbers: `4,000 Hz`)
- Voice coil inductance is labelled `@ 1 kHz`; canonical `le_mh`
- Actual HTML uses labels like `Diaphragm Mass Inc. Airload (Mms)`, `Surface Area Of Cone (Sd)`, `Basket/Frame Material` — `labels.py` normalizes.

**DriverKind mapping** (from category URL path):
```
118 (woofers)              → LF_WOOFER
121 (subwoofers)           → LF_WOOFER
119 (tweeters)             → TWEETER
120 (midranges)            → FULLRANGE (or a MID kind if we add one)
123 (full-range)           → FULLRANGE
161 (pro-audio-drivers)    → LF_WOOFER (usually; some HF compression here too — inspect at parse time)
125 (passive-radiators)    → PASSIVE
178 (mini-micro-speakers)  → FULLRANGE
272 (compression drivers)  → HF_COMPRESSION
96  (horns-waveguides)     → HORN
274 (planar-ribbon)        → TWEETER
126 (replacement-diaphragms) → skip at enumeration (not a driver)
```

**Quirks:**
- `--` in a cell means null/missing. Treat as `None`.
- Imperial units are common: `Weight: 3.3 lbs.`, `Nominal Diameter: 6.50"`. `parse_length` handles `"`, `in`, `lbs`, `oz`.
- Some categories (compression: 3, horns: 7, planar-ribbon: 7, diaphragms: 6) are very small; horns and diaphragms may lack T/S entirely and should not gate populated-field-floor for those DriverKinds.
- `Le` written as `2.26 mH @ 1 kHz` — parse handles the annotation.

**Recon count:** ~370 total. Set `expected_min_records = 300`.

---

## Eminence (`eminence`)

**Homepage:** https://eminence.com (US; Shopify-hosted). `robots.txt` explicitly allows `/products/`, no crawl-delay, `sitemap.xml` referenced.

**Enumeration.** `GET https://eminence.com/products.json?limit=250&page=1` returns all 155 active products as JSON in a single response (page=2 returns 0). Iterate the `products[]` array; each has a `handle`; product URL is `https://eminence.com/products/{handle}`. **The canonical host is `eminence.com`**, not `www.` — `www` returns 301.

For discontinued/archived coverage, `https://eminence.com/sitemap_products_1.xml?from=...&to=...` lists 201 handles (46 more than `/products.json`). Excluded from v1 (see discover_archive extension).

**Sample product page:** https://eminence.com/products/kilomax_pro_18a

**Extraction.** Server-rendered `<table id="em-detail">` with two-column rows (`td/td`: label / value). Section headers use `colspan="2"` with class `bebas orange`. Two logical sections: `SPECIFICATION` (general) and `THIELE & SMALL PARAMETERS`. Selector: `table#em-detail tr`; filter out `colspan` rows.

**Sample data (`kilomax_pro_18a`, 8Ω, 18" pro-audio):**
- Fs 32 Hz, Qts 0.47, Qes 0.49, Qms 10.15, Vas 331.5 liters, Sd 1159 cm², Xmax 10 mm, Xlim 19.2 mm, Mms 143 g, BL 17.2 T-M, Cms 0.18 mm/N, Le 1.59 mH, Re 5.07 Ω, EBP 65, Vd 1159 cc
- Nominal 8Ω, Program 2500W, Continuous 1250W, Sensitivity 95.8 dB
- Magnet 109 oz, VC 4"/102 mm, Net weight 27.4 lbs / 12.43 kg

**Field mapping (Eminence):**
- Labels are verbose with parenthetical abbreviations: `Resonant Frequency (fs)` → `fs_hz`; `Total Q (Qts)` → `qts`; `Compliance Equivalent Volume (Vas)` → `vas_liters`; `Maximum Linear Excursion (Xmax)` → `xmax_mm`; `Maximum Mechanical Limit (Xlim)` → `xmech_mm`.
- `Program Power` → `power_program_watts`; `Watts (Continuous Power)` → `power_long_term_watts` (Eminence's continuous is smaller than program; treat as long_term).
- `Sensitivity` → `sensitivity_db_1w_1m` (Eminence convention).
- `Vas` value can be dual-unit on one line: `331.5 liters / 11.71 cu.ft.` — split on ` / ` and take metric.
- `Le` is written as `1.59m H` (space before `H`, lowercase `m` for milli) — parse handles.
- `Bl` label: `BL Product (BL)` → `bl_tm`; value `17.2 T-M` (hyphen) — `parse_bl_tm` handles.
- `Rms` (mechanical resistance) is NOT listed in the spec table — only Q values.

**DriverKind mapping.** `products.json` returns a flat list without category info; URLs like `/products/kilomax_pro_18a` have no category slug. **Use `Scraper.classify_driver_kind()` post-parse:** inspect Shopify `product.product_type` (available in `/products.json`) or fall back to a handle-regex map. Common Eminence product_types map cleanly (`Pro Audio Woofers` → LF_WOOFER, `Compression Drivers` → HF_COMPRESSION, `Guitar Speakers` → GUITAR_BASS, `Bass Guitar Speakers` → GUITAR_BASS, `Coaxial Speakers` → COAX). Falls to LF_WOOFER default if unmapped, with `warn_flag: driver_kind_defaulted`.

**Quirks:**
- Some products are `Dealer Only` and redirect on fetch — treat as permanent 403/404 and skip.
- Products without T/S (crossovers, horn flares, cable accessories) have no `THIELE & SMALL PARAMETERS` section. Filter these out at parse or use `classify_driver_kind` to assign `PASSIVE` (which exempts them from T/S populated-rate gates).
- 46 sitemap-only handles are discontinued products; their pages may or may not still resolve.

**Recon count:** 155 active. `expected_min_records = 130`.

---

## Faital Pro (`faital_pro`)

**Homepage:** https://www.faitalpro.com (Italy). `robots.txt` allows product pages and the sitemap; disallows utility paths like `/tech_spec/`, `/where_to_buy/`, form submitters.

**Enumeration.** Seed the four category listing pages. The two large categories (`LF_Loudspeakers`, `HF_Drivers`) render their product tables via an XHR — the browser POSTs to `<category>/search.php` with the listing page's JS default filter and injects the response into `#main_content`. The scraper does the same POST directly. The two small categories (`Coaxial_Loudspeakers`, `HF_Horns`) ship their tables inline in the initial HTML — plain GET.

Either way, `enumerate` scrapes `product_details/index.php?id=<N>` occurrences from the response body and derives DriverKind from the seed URL. Recon (2026-08-25): **104 LF + 35 HF-drivers + 14 coax + 5 horns = 158 URLs**. (`sitemap.xml` was tried first — it only lists 18 non-archived English URLs, a fraction of the real catalog — and is now abandoned.)

**Sample product page:** https://faitalpro.com/en/products/LF_Loudspeakers/product_details/index.php?id=101050135 (`12PR320`, 8Ω)

**Host + URL case-sensitivity.** Two related quirks:
1. `www.faitalpro.com` 301-redirects to `faitalpro.com`. httpx drops POST bodies on 301 (RFC-compliant), so seeding `search.php` on the www host makes the filter payload vanish and the endpoint returns "No Results". Fix: seed the no-www host directly (`_BASE = "https://faitalpro.com"`).
2. Category paths are mixed-case (`LF_Loudspeakers`, `HF_Drivers`, `Coaxial_Loudspeakers`, `HF_Horns`); lowercase forms 404. The scraper embeds the mixed-case slugs in its seed URLs.

Detail pages themselves are static HTML.

**search.php filter payloads.** Copied verbatim from each listing page's `update_data()` JS init (the wide-open "show me everything" defaults). LF is 10 fields; HF-drivers adds shape/material/plug-design multi-selects. Stored as tuples-of-pairs in `faital.py` (`_LF_SEARCH_POST`, `_HF_SEARCH_POST`) so `SeedRef` stays hashable.

**Extraction.** `<table class="tbl_data">` — first `td`/`th` is label, second is value. Selector: `table.tbl_data tr`. Spec data is **duplicated across 6 `tbl_data` tables per page** (tables 0-2 and 4-5 repeat the same values); deduplicate by label (take first occurrence).

**Sample data (`12PR320`, 8Ω):**
- Fs 42 Hz, Qts 0.37, Qes 0.39, Qms 7.8, Vas 113.3 dm³, Sd 539 cm², Xmax 7.37 mm, Xdamage 17 mm, Mms 51.4 g, Mmd 37.3 g, Bl 13.5 N/A, Le 0.67 mH, Re 5.3 Ω, EBP 108 Hz, Cms 0.28 mm/N, Rms 1.7 kg/s, Eta Zero 2.06 %
- Nominal 8 Ω, Min 6.4 Ω, AES 300W, Max 600W, Sensitivity 97 dB @ 1W/1m, Range 45÷5000 Hz
- VC 65mm Aluminum, Former Glass Fiber, Magnet Neodymium Slug, Flux 1.2T

**Field mapping (Faital):**
- `AES Power Handling (1)` → `power_aes_watts` (strip footnote suffix `(N)`)
- `Maximum Power Handling (2)` → `power_peak_watts`
- `Sensitivity (1W/1m)` → `sensitivity_db_1w_1m` (labelled explicitly)
- `Xdamage (5)` → `xmech_mm` (peak-to-peak by Faital's convention; store as-reported per the framework rule)
- `Bl` value `13.5 N/A` — the `N/A` unit is Newton-per-Ampere, equivalent to T·m. `parse_bl_tm` returns 13.5.
- Frequency range separator is `÷` (division sign), not `-`: `45÷5000 Hz`. `parse_range` handles.
- `NET Air Volume filled by Loudspeaker` for LF → `air_volume_l` (custom field, low priority); HF uses `NET Air Volume filled by HF Driver` — normalize.
- `Push Terminals - 8 Ohm Version` (impedance in label) → part number sidecar, not a Driver field.

**Label taxonomy caution:** Faital uses BOTH stripped footnote parentheticals (`(1)`, `(2)`, `(3)`) that should be stripped by `FOOTNOTE_SUFFIX` and unit parentheticals (`Sensitivity (1W/1m)`) that should be `UNIT_ANNOTATION` (strip, but sensitivity slot depends on it). `labels.py` handles both.

**DriverKind mapping:** from the seed URL that yielded each product URL.
```
LF_Loudspeakers        → LF_WOOFER
HF_Drivers             → HF_COMPRESSION
Coaxial_Loudspeakers   → COAX
HF_Horns               → HORN
```

**Quirks:**
- `Shipping Box` label case varies: `Shipping Box(Single Carton Box)` (LF) vs `Shipping Box(Single carton box)` (HF, lowercase c). Compare case-insensitively.
- Some products have `Push Terminals`/`Recone Kit` fields that vary by impedance version (`- 8 Ohm Version`, `- 4 Ohm Version`). Not scraped as Driver fields; ignored or stored as sidecar SKU refs.

**Recon count:** 158 product URLs across 4 categories (2026-08-25 fetch). `expected_min_records = 120` declared inline in `scrapers/faital.py`. Last live run: 158 fragments parsed → 124 final drivers (34 dropped in `assign_canonical_ids` / `merge_fragments_by_id` / `enforce_consistency` — TODO: audit and either recover or document the reason per model).

---

## HOQS (`hoqs`)

**Homepage:** https://hoqs.org (small boutique brand). Standard Shopify `robots.txt`; explicitly warns AI agents not to complete checkouts and directs them to an MCP endpoint (`/api/ucp/mcp`) — irrelevant to scraping. Sitemap: `/sitemap.xml`.

**Enumeration.** `GET https://hoqs.org/products.json?limit=250&page=1` returns all 13 products in one page (Shopify JSON API, no auth). Also `https://hoqs.org/sitemap_products_1.xml` lists the same 13 URLs. Product URL pattern: `https://hoqs.org/products/{handle}`.

**IMPORTANT: the domain is `hoqs.org`, NOT `hoqs.com`.** Every URL in the scraper must use `.org`.

**Sample product page:** https://hoqs.org/products/n185c-18-neodymium-carbon-fiber-subwoofer

**Extraction.** Specs live in an **inline JS object literal** embedded in the HTML:
```javascript
var speakerData = {
  general:    {...},
  physical:   {...},
  thieleSmall: [ {name, symbol, value, unit}, ... ]  // or "ThieleSmall" (uppercase T) on N123
};
```

**No JavaScript execution required** — it's static text in the HTML. Extract with:
```python
import re, json
m = re.search(r'var speakerData = (\{.*?\});', html, re.DOTALL)
data = json.loads(m.group(1))
```

The `speakerData` variable appears 3+ times per page (duplicate script blocks used by different UI sections) — take the first match.

**T/S params live in the `thieleSmall` array as `{name, symbol, value, unit}` objects.** Use the `symbol` field as the canonical key. Case-inconsistent: most products use `thieleSmall`, one (N123) uses `ThieleSmall` — check both keys or use case-insensitive access.

**HF compression drivers** (e.g. `hoqs-hf143n-1-4`) have `thieleSmall: []` (empty) — no T/S. Handle gracefully; use `classify_driver_kind` → `HF_COMPRESSION` and rely on the guitar_bass-style exemption for T/S populated-rate.

**Sample data (`n185c`, 18" subwoofer):**
- Fs 29.5 Hz, Qts 0.21, Qes 0.21, Qms 14, Vas 242 liters, Sd 1225 cm², Re 5.7 Ω, Mms 281.5 g, Xmax 13.5 mm (Linear one-way), Xmech 54 mm (Peak to peak), BL 35.7 T/M, Le_1k 1.461 mH, EBP, Zmax, Zmin, Le_10k
- SPL (Sensitivity 2.83Vrms) **97.5424 dB** — **stored in `sensitivity_db_2_83v_1m` slot, NOT `sensitivity_db_1w_1m`**
- Nominal 8Ω, Power Handling Nominal 1700W, Program 3400W
- VC 125mm/5", Cone Carbon Fiber, Magnetic Neodymium, Net weight 13.5 kg

**Field mapping (HOQS):**
- `fs` → `fs_hz`; `Qts` → `qts`; `Vas` → `vas_liters`; etc. (symbol names are close to canonical)
- **`SPL` label with `(Sensitivity 2.83Vrms)` annotation → `sensitivity_db_2_83v_1m`** (this is where every 4Ω HOQS driver would silently mis-slot if we defaulted to 1W/1m)
- `Xmax (Linear one-way)` → `xmax_mm`
- `Xmech (Peak to peak)` → `xmech_mm` (as-reported; already PP)
- `Le_1k` → `le_mh` (canonical); `Le_10k` is a secondary reading, not stored in v1
- `Power Handling Nominal` → `power_aes_watts`
- `Power Handling Program` → `power_program_watts`
- `BL` value `35.7 T/M` — HOQS uses `T/M` as a multiplication token (equivalent to `Tm`); `parse_bl_tm` special-cases this.
- `n0 (Reference Efficiency)` → `eta_zero_pct`

**DriverKind mapping.** `products.json` returns `product_type` per product; use `Scraper.classify_driver_kind()`:
- `Speaker` (LF) → LF_WOOFER
- `Compression Driver` → HF_COMPRESSION
- other → skip at parse (not a driver)

**SpecSource:** `INLINE_JS`. Per the precedence order, ranked ABOVE the HTML variants because the JS object is the same structured data the HTML view is derived from server-side — high fidelity.

**Recon count:** 13. `expected_min_records = 10` (in `data/baselines.yaml`).

---

## RCF (`rcf`)

**Homepage:** https://www.rcf.it (Italy; Liferay CMS). `robots.txt` is `User-Agent: * / Disallow:` (allows all); `Sitemap:` directive points to `https://www.rcf-usa.com:443/sitemap.xml` which infinite-loops and is unusable.

**Enumeration.** No usable sitemap. **`/products/professional-audio/precision-transducers` redirects infinitely — use `/en/products/...` locale prefix.** The public path is per-series HTML search-results pages:

```
https://www.rcf.it/en/search-results?serieId={ID}
```

Series IDs (v1 scope, active only):
```
27 → Ferrite LF
51 → Neodymium LF
50 → Neodymium Compression Drivers
26 → Ferrite Compression Drivers
11 → Coaxial
34 → Horn Series
```

Excluded: `serieId=14` (Custom Designs, 34 items — mostly accessories, not standard transducers). Extract product slugs from each search-results page with `r'product-detail/([^"]+)"'`. Product URLs: `https://www.rcf.it/en/products/product-detail/{slug}`.

**Do NOT use:**
- `/o/v1/profile/searchDocuments`, `/o/v1/profile/productsForFilters`, or any other `/o/v1/*` Liferay REST endpoint — these require OAuth2 (return 403 without a bearer token).
- `/products/by-family/details/...` React pages — require JS execution.
- `lineId=5` single URL — only returns 127/137 products; per-serieId enumeration reaches 137.

**Sample product page:** https://www.rcf.it/en/products/product-detail/lf18n401

**Extraction.** Specs are server-rendered in `<div class="specifications">` (with Bootstrap classes `bg-gray-light py-3 px-3 p-md-7`). Structure: Bootstrap grid `div.row` where each row has two `col-md-6` children — first is the label, second (with class `font-family-semibold`) is the value. Selector: `div.specifications div.row > div.col-md-6:first-child + div.col-md-6.font-family-semibold`.

Six labelled sections: `General specifications`, `Thiele - small parameters`, `Mounting information`, `Standard compliance`, `Size / Weight`, `Shipping information`.

**Sample data (`LF18N401`, 8Ω, 18" neodymium LF):**
- Fs 32 Hz, Qts 0.26, Qes 0.27, Qms 6.50, Vas 257 liters, Sd 0.120 m² (= 1200 cm²), Xmax 9 mm, Mms 201.0 g, Bl 27.80 T x m, Le1k 2.50 mH, Re 5.10 Ω, Eff 3.01%
- Max. Excursion Before Damage 52 mm / 2.05 inch → `xmech_mm` stored as 52 (as-reported)
- Nominal 8Ω, Program 2400W, Power handling capacity 1200W, Sensitivity 98.0 dB, Range 30–1000 Hz
- VC 4"/102 mm, Weight 9.5 kg

**Field mapping (RCF):**
- `Program Power (watt)` → `power_program_watts` (RCF Program is 2× AES per AES convention)
- `Power handling capacity` → `power_aes_watts`
- `Sensitivity` → `sensitivity_db_1w_1m` (RCF convention)
- `Bl factor (Bl) (T x m)` value `27.80 T x m` — note the double-parenthetical label; `labels.py` handles by stripping the trailing unit annotation. `parse_bl_tm` handles `T x m` (letter x as multiplier).
- `Sd` reported in m² (`0.120 m²`) — `parse_sd_cm2` converts.
- `Max. Excursion Before Damage` → `xmech_mm` (peak-to-peak per empirical review; 52 mm on 18" is ratio 5.78× Xmax which is legit high-excursion neodymium territory).
- Voice coil, Weight, Overall dimensions in dual units (metric + imperial) — parse metric first.

**Compression drivers** publish **only** Bl, Sensitivity, FreqRange, Nominal Impedance — no T/S. `HF_COMPRESSION` DriverKind exempts them from the T/S populated-rate gate.

**DriverKind mapping (from `serieId`):**
```
27 → LF_WOOFER
51 → LF_WOOFER
50 → HF_COMPRESSION
26 → HF_COMPRESSION
11 → COAX
34 → HORN
```

**Quirks:**
- Some product slugs contain URL-encoded characters (e.g. `c-br-10%C2%B0-q-15`). Fetch honors URL encoding; the extraction regex captures encoded slugs verbatim.
- The `sitemap.xml` at both `rcf.it` and `rcf-usa.com` self-redirects infinitely; never use.
- `robots.txt` has no `Crawl-delay`; default 1 req/s applies.

**Recon count:** 137 products across the 7 series; excluding Custom Designs (34 items) leaves ~103. `expected_min_records = 90`.

---

## Beyma (`beyma`)

**Homepage:** https://www.beyma.com (Spain). `robots.txt` allows all except `/wp-admin/`; `sitemap.xml` exists but has only 8 URLs (site meta pages) — **useless for product enumeration**. `profesional.beyma.com` is confirmed defunct; use `www.beyma.com/en/` for English catalog.

**Enumeration.** Fetch each of 10 English category pages (dropping 2 non-driver categories):

```
/en/products/c/low-mid-frequency/
/en/products/c/coaxial/
/en/products/c/compression-driver/
/en/products/c/compression-driver-wave-guide/
/en/products/c/amt-driver/           ← use DriverKind.AMT
/en/products/c/compression-tweeter/
/en/products/c/dome-tweeter/
/en/products/c/full-range/
/en/products/c/horns/
/en/products/c/shaker/               ← use DriverKind.SHAKER; narrow-bandwidth exempt from freq_high>=freq_low+min gate
```

**Dropped at enumeration** (not drivers):
```
/en/products/c/passive-filter/       ← passive crossover, not a driver
/en/products/c/accesories/           ← accessories (note the typo, one 's', in the URL)
```

Also dropped: `/en/products/discontinued/` (v2 target).

Product URL regex:
```
r'href=["\'](https://www\.beyma\.com/en/products/c/[^"\']+/[A-Z0-9]+/[^"\']+)["\']'
```

Pattern: `/en/products/c/{category}/{PRODUCT-CODE}/{spanish-slug}/`. All products load on a single page per category (no pagination).

**Sample product page:** https://www.beyma.com/en/products/c/low-mid-frequency/118LEX16FE8/altavoz-18lex1600fe-8-oh/

**Extraction.** WordPress-rendered HTML. Specs are in sections `<div class="block-product-features">`, each with an `<h3 class="title text-special">` heading (e.g. `Technical specifications`, `Parameters Thiele & Small`, `Construction details`) and `<div class="items">` container with `<div class="item">` children. Each item has `<div class="title">` (label) + `<div class="description">` (value). Selector: `div.block-product-features div.items div.item`. Iterate all items and collect `{title.text: description.text}` regardless of section.

**Sample data (`18LEX1600Fe`, 8Ω, 18" low-mid):**
- Fs 34 Hz, Qts 0.38, Qes 0.4, Qms 7.4, Vas 188 l, Sd 0.1255 m² (=1255 cm²), Xmax 13 mm, Xdamage pp 60 mm, Mms 0.252 kg (=252 g), Cms 85 µm/N, Rms 7.4 kg/s, Bl 26.9 N/A, Le@1kHz 1.7 mH, Re 5.3 Ω, Efficiency 1.9%, Vd 1631 cm³
- Nominal 8Ω, Min 6.1Ω, Power capacity 1600W AES, Program 3200W, Sensitivity 97 dB 1W@1m@ZN, Range 35-1000Hz
- VC 101.6 mm/4", Winding 32mm, Air gap 15mm, Recommended enclosure 174 l, Net weight 14.9 kg, Total weight 16.2 kg, Magnet Ferrite

**Field mapping (Beyma):**
- `Power capacity (W AES)` → `power_aes_watts` (label carries `(W AES)` annotation, value like `1600 W AES`)
- `Program power (W)` → `power_program_watts` (Beyma convention: Program is 2× AES)
- `Sensitivity (dB 1W/1m)` → `sensitivity_db_1w_1m` (labelled explicitly)
- `BL factor (N/A)` — the `N/A` in the label is unit (Newton-per-Ampere = T·m); value like `26.9 N/A`. `parse_bl_tm` returns 26.9.
- `Xdamage pp (mm)` → `xmech_mm` (as-reported; the `pp` in the label makes peak-to-peak explicit)
- `Sd (m²)` → convert to cm² via `parse_sd_cm2`
- `Cms (µm/N)` → convert to mm/N via `parse_compliance`
- `Moving mass (kg)` value `0.252 kg` → convert to g
- `Le @1 kHz (mH)` → `le_mh`
- `Nominal diameter (mm/in)` value `460 mm 18 in` (dual-unit space-separated) → parse first token
- `Recommended enclosure volume (l)` → `recommended_enclosure_l` (custom field, low priority)

**DriverKind mapping (from category slug):**
```
low-mid-frequency         → LF_WOOFER
coaxial                   → COAX
compression-driver        → HF_COMPRESSION
compression-driver-wave-guide → HF_COMPRESSION
amt-driver                → AMT
compression-tweeter       → TWEETER
dome-tweeter              → TWEETER
full-range                → FULLRANGE
horns                     → HORN
shaker                    → SHAKER
```

**Quirks:**
- URL slugs use Spanish (`altavoz-*`) even on English pages; use `/en/` in the URL to get English spec labels.
- `accesories` misspelling is a real path (still dropped at enumeration).
- Values may contain non-breaking spaces (`85  µm / N` with double space) — normalize whitespace.
- PDF datasheets exist at `/speakers/Fichas_Tecnicas/beyma-speakers-data-sheet-{category}-{ModelCode}.pdf` but specs are complete in HTML; PDF not needed for v1.
- Shaker driver bandwidth is legitimately narrow (e.g. 20-60 Hz); `SHAKER` DriverKind gets a relaxed `freq_high >= freq_low + min_bw` gate.

**Recon count:** 194 active + 112 discontinued. v1 scrapes active only: `expected_min_records = 160`.

---

---

## Jensen (`jensen`)

**Homepage:** https://www.jensentone.com (Drupal site). `robots.txt` allows product pages; no `Crawl-delay` for the default UA. Sitemap at `/sitemap.xml`.

**Enumeration.** Parse `sitemap.xml`, filter to URLs that match one of the 7 known category slugs:
```
vintage-alnico   vintage-ceramic   vintage-neo
jet-series       mod-series        d-series
bass-speakers
```
Regex `^https?://www\.jensentone\.com/{cat}/[a-z0-9-]+/?$`. Yields 63 product URLs (2026-08-22). Every product maps to `DriverKind.GUITAR_BASS` — Jensen is exclusively guitar/bass amp speakers, kin to Celestion's guitar catalog. The GUITAR_BASS kind is exempt from the T/S-required consistency check, which matters because Jensen guitar drivers legitimately omit some parameters.

**Sample product page:** https://www.jensentone.com/vintage-alnico/p12n

**Extraction.** Specs live inside `div.jensentone-ohm-specs`, which contains **four `<table>`s** each with a `<caption>` naming its section:

| Caption | Row layout | How the parser reads it |
|---|---|---|
| `General Characteristics` | `label \| metric \| imperial` | `cell[1]` (metric) |
| `Thiele-Small Parameters` | `label \| symbol \| value_imp0 [\| value_imp1…]` | Impedance-indexed cell (see below) |
| `Constructive Characteristics` | `label \| empty \| value` | Last non-empty cell |
| `Electrical Characteristics` | `label \| empty \| value_imp0 [\| value_imp1…]` | Impedance-indexed cell |

**Multi-impedance emission.** Some products (e.g. P12N) ship in both 8Ω and 16Ω from a single URL. The scraper reads the first `Nominal Impedance` header row it finds, treats each non-empty value cell as an impedance column, and **emits one `DriverFragment` per impedance**. Canonical IDs then differ (`jensen__p12n__8ohm` vs `jensen__p12n__16ohm`). Rows with only one value column (e.g. `Electrical Q Factor | Q ES | 0.98`) apply that single value to every fragment.

**Sample data (P12N, 8Ω / 16Ω):**
- 8Ω: Fs 90 Hz, Qts 0.77, Qms 4.36, Vas 34.6 L, Re 6.03 Ω, Bl 10.62 T·m, Le 0.87 mH, Sensitivity 97.5 dB
- 16Ω: Fs 91 Hz, Qts 0.84, Qms 5.77, Vas 42.2 L, Re 12 Ω, Bl 13.71 T·m, Le 1.05 mH, Sensitivity 97.8 dB
- Shared: Qes 0.98 (single-value row), Xmax 1 mm, Mms 30.9/27 g, magnet ALNICO, 12″ / 307 mm, 3.1 kg, Rated 50 W, Musical 100 W

**Field mapping (Jensen):**
- `Rated Power` → `power_aes_watts`
- `Musical Power` → `power_peak_watts`
- `Sensitivity@1W,1m` → `sensitivity_db_1w_1m`
- `Force Factor` → `bl_tm` (value like `10.62 Wb/m` — Wb/m ≡ T·m)
- `Mechanical Compliance` → `cms_mm_per_n` (values in µm/N converted to mm/N)
- `Voice Coil Inductance @ 1kHz` → `le_mh`
- `Nominal Overall Diameter` → `nominal_size_mm`; `Overall Weight` → `net_weight_kg`; `Magnet` (Alnico/Ceramic/Neo) → `magnet_type` enum

**Quirks:**
- H1 text is the model name (`P12N`, `Vintage 30`-style is Celestion's; Jensen uses codes).
- Cells in the T/S table use spaced-out symbol notation (`R E`, `Q MS`, `M MS`) — `normalize_label` isn't involved for symbols; symbols live in `cell[1]` and are skipped.
- `Xmax` values include the `±` sign (`± 1 mm`) — `parse_length_mm` strips it.

**Recon count:** 63 product URLs. Multi-impedance expansion yields **120 driver records**. Set `expected_min_records = 55` (below 63 to allow parse-fail attrition).

---

## Deferred

### La Voce (`lavoce`)

**Status:** parked pending network fix. See `memory/la-voce-parked.md`.

**Blocker:** `lavocespeakers.com` (35.207.151.200) is unreachable from:
- macOS (`nc` → EBADF errno=9; `curl` → ECONNREFUSED; `httpx` → EBADF)
- Anthropic workflow subagent sandbox (same errors as above)

Both `lavocespeakers.com` and `www.lavoceitaliana.com` fail identically. Whether this is a temporary outage, a macOS-specific socket-layer quirk with this specific IP, or a persistent geoblock is undetermined as of 2026-08-22.

**Recon completed against Wayback Machine snapshot** (`web.archive.org/web/20241004083609/lavocespeakers.com/single-product/?id=113`):
- Specs live in `div.each_column_specifications` triples: `div.left_column_spec` (label) + `div.units_specifications` (unit) + `div.value_specifications` (value). 38 spec fields captured.
- Model in `div.title_p` (not `h1`/`h2`/`h3`).
- Product URL pattern: `https://lavocespeakers.com/single-product/?id={NNN}` with IDs 1-229.
- Catalog ~177 products (based on unique statuscode:200 CDX records).

**When to resume.** Test reachability with `nc -zv -w 5 lavocespeakers.com 443` and `curl -sSI https://lavocespeakers.com/`. If reachable, port the Wayback-validated schema straight into a `LaVoceScraper` subclass — the extraction (`div.each_column_specifications` triples, model in `div.title_p`) is already verified.

---

## Out of scope

### Retailer scrapers (v2)

Parts Express, Solen, Madisound, US Speaker. Design pattern documented in `docs/framework.md` under "Extension points → Retailer scrapers (v2)". Not implemented in v1. Deferred deliberately: retailer catalogs are large and heterogeneous, fuzzy matching against manufacturer records is a research problem in its own right, and pricing infrastructure (`data/store_links.json`, `data/price_history/`, FX snapshot direction) is a separate stability concern.

### Manufacturer archives / discontinued

18Sound `/archive`, Beyma `/discontinued/`, Faital `archived_products`, Eminence sitemap-only handles. Extension point via `Scraper.discover_archive()`; not exercised in v1. Ops task when needed: add per-scraper `discover_archive()` implementation, run scrape with `--include-archive`, verify `status=archived` records appear.
