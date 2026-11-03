# Driver Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-browser export of drivers from the web app to two formats — WinISD (`.wdr`) and FFS (`.ffsdrv`) — triggered from a per-row hover icon on the Model column (single driver) and a header icon next to the dark-mode toggle (database, with Current View / Full Database scope).

**Architecture:** `web/export.js` is a single plain JS file with the dual CJS+window attachment pattern (plain `<script>` in the browser attaches `window.DriverExport`; Node `require("../web/export.js")` returns the same API). Pure builders (`buildWinisd`, `buildFfs`, `buildBulkEntries`) take a driver record and return `{ok, text, filename}` / `{entries, skipped}` — no DOM, no fflate. The browser glue (`downloadDriver`, `downloadDatabase`) is a thin wrapper that calls the builders then triggers a Blob download (and for bulk, calls `window.fflate.zipSync` from the CDN). Unit tests in Node load `export.js` via `require()` — no sandbox, no stubs — and byte-compare WinISD output against the user-provided `.wdr` reference embedded in the test file. The browser glue is hand-verified in-browser (Task 7).

**Tech Stack:** Vanilla JS (ES2020), Alpine.js 3, Materialize CSS, `fflate@0.8.2` via jsDelivr CDN, Node 20+ for the test harness. No npm deps, no build step.

**Spec:** User-provided samples and brainstorming playback from the 2026-11-02 conversation. WinISD sample verbatim appears in the Task 1 test; FFS sample constrains the key set and format in Task 2.

## Global Constraints

- **No new npm dependency, no build step, no package.json.** `fflate` is loaded from the same jsDelivr CDN pattern as `@mdi/font` in `web/index.html`.
- **`web/export.js` module pattern.** Plain IIFE that exposes an API object and attaches it in both environments:
  ```javascript
  (function () {
    function buildWinisd(driver, { today } = {}) { /* ... */ }
    function buildFfs(driver) { /* ... */ }
    function buildBulkEntries(drivers, format, { today } = {}) { /* ... */ }
    function downloadDriver(driver, format) { /* ... */ }
    function downloadDatabase(drivers, format, opts) { /* ... */ }
    const api = { buildWinisd, buildFfs, buildBulkEntries, downloadDriver, downloadDatabase };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (typeof window !== "undefined") window.DriverExport = api;
  })();
  ```
- **Pure builders.** `buildWinisd`, `buildFfs`, `buildBulkEntries` never touch `document`, `window`, `Blob`, `URL`, or `fflate`. All three are callable from Node without any environment setup.
- **`today` is a parameter**, not `new Date()` inside the builder. Browser callers pass `new Date()`-derived YYYYMMDD; tests pass a fixed string. Keeps builders deterministic.
- **WinISD required fields:** `fs_hz` AND `qts`. Missing → `{ok: false, missing: [...]}`.
- **FFS required fields:** `fs_hz, qms, re_ohm, bl_tm, mms_g, sd_cm2`. Missing any → skip + warn (not partial emit).
- **FFS keys are a closed set, in this order:** `bl, fs, le, leLossN, leakageQl, mms, powerW, qms, re, sd, xmaxMm`. No extras, no missing, output is `JSON.stringify(obj, null, 2)` (2-space indent) + trailing newline matching the user-provided sample.
- **FFS field mapping (dataset native unit → FFS unit — all identity passes):**
  - `fs_hz → fs`, `qms → qms`, `re_ohm → re`, `bl_tm → bl`
  - `le_mh → le` (both mH)
  - `sd_cm2 → sd` (both cm²)
  - `mms_g → mms` (both g)
  - `xmax_mm → xmaxMm` (both mm)
  - `leLossN = 1` (constant)
  - `leakageQl = 100` (constant)
  - `powerW = power_aes_watts ?? power_long_term_watts ?? 100`
- **WinISD numeric formatting = Python `.15g` emulation.** Up to 15 significant digits, trailing-zero trim, no `.0` on integer floats, scientific notation when exponent < -4 or ≥ 15 with a **2-digit zero-padded exponent** (e.g. `9e-05`, not `9e-5`). This is the single highest-risk piece of the port — the user's sample has `Cms=9e-05` which exercises the sci-notation path. The test byte-matches the sample so the format is pinned.
- **WinISD field order (fixed, from the user's sample):** `Brand, Model, Manufacturer, ProvidedBy, Comment, DateAdded, DateModified, Qts, Znom, Fs, Pe, SPL, Re, Le, fLe, KLe, BL, Xmax, Xlim, Cms, Qms, Qes, Rms, Mms, Sd, Vas, Dia, Vd, no, Dd, EBP, numVC, Hc, Hg, SPLmax, SPLmaxLF, USPL, alfaVC, Rt, Ct, gamma, Rme, Mpow, Mcost, Gloss, VCCon, c, roo, Thick, Depth, MagDepth, Magnet, Basket, Outer, Vcd, DVol`. Line separator is `\r\n`, trailing `\r\n` after the last field.
- **Constants in WinISD output:** `Znom` from `impedance_nominal_ohm`; `numVC=1`, `VCCon=1`, `c=343.68`, `roo=1.20095`; all other zeros emitted as `0` (not `0.0`).
- **WinISD unit conversions:** `le_mh → Le`: ÷1000 (mH → H). `xmax_mm → Xmax`, `xmech_mm → Xlim`, `depth_mm → Depth`, `overall_diameter_mm → Outer`, `voice_coil_diameter_mm → Vcd`: ÷1000 (mm → m). `cms_mm_per_n → Cms`: ÷1000 (mm/N → m/N). `mms_g → Mms`: ÷1000 (g → kg). `sd_cm2 → Sd`: ÷10000 (cm² → m²). `vas_liters → Vas`, `vd_liters → Vd`: ÷1000 (L → m³). `eta_zero_pct → no`: ÷100 (% → fraction).
- **WinISD derived fields:**
  - `Dd` = `Math.sqrt(4 * Sd_m2 / Math.PI)` where `Sd_m2 = sd_cm2 / 10000`.
  - `Vd_m3` = if `vd_liters` present → `vd_liters / 1000`; else if `sd_cm2` and `xmax_mm` → `Sd_m2 * (xmax_mm / 1000)`; else `0`.
- **WinISD Comment field:** `"Xlim=<xmech_mm>mm"` if `xmech_mm` is non-null, else empty string.
- **Filenames:**
  - Single: `<Brand> <Model> (<Z>ohm).<ext>`. `Z` omitted if `impedance_nominal_ohm` is null. Sanitize brand+model: replace `[\\/:*?"<>|\r\n\t]+` with space, trim, collapse multiple whitespace to single space.
  - Bulk: `driver-base-<view|full>-<winisd|ffs>-YYYY-MM-DD.zip`. Date = first 10 chars of `generated_at` from `drivers.json`, falling back to today's ISO date if malformed.
  - Zip entries live at zip root (no subfolder). Collision disambiguation: second occurrence appends ` [canonical_id]` before the extension.
- **"Current View" scope** = `this.sortedFiltered` (post-filter, pre-pagination). `this.visibleRows` is a `.slice(0, pageSize=500)` of `sortedFiltered` — not what the user means by "Current View" when they filtered to 1600 rows.
- **No persistence.** Format and scope reset on every modal open.
- **CSS variable names (confirmed in `web/styles.css`):** `--surface`, `--text`, `--text-muted` (NOT `--muted-text`), `--text-faint`, `--border`, `--shadow-popover`, `--link`. Dark mode via `html[data-theme="dark"]` set in the pre-hydration script at `index.html:28-37`. Variables auto-switch; no per-theme override needed. Mirror `.spec-popover` / `.picker-popover` as the design precedent for modal surfaces.
- **Icon.** Material Icons `file_download` for both header and per-row.
- **Tooltips.** Header `title="Export Database"`; per-row `title="Export Driver"`.

## Review Focus

Spec-implied inputs the per-task tests cover:

1. **WinISD `.15g` sci-notation path for small values.** Task 1 reference includes `Cms=9e-05`. If the port emits `0.00009` instead, the byte-match fails on that line with a clear diff.
2. **WinISD CRLF line endings.** Task 1 explicit `includes("\r\n")` assertion plus the full-text byte-match.
3. **Filename sanitization (chars + whitespace collapse).** Task 1 asserts `"Weird / Co"` + `"A:B?C"` → `"Weird Co A B C (8ohm).wdr"` with single spaces.
4. **FFS strict-key enforcement (count, names, order).** Task 2 asserts `Object.keys(output)` deep-equals the 11-key list.
5. **FFS skip-not-partial on missing required field.** Task 2 asserts a driver missing `mms_g` returns `{ok: false, missing: ["mms_g"]}` and NOT a partial object with 10 keys.
6. **Bulk filename collision disambiguation.** Task 3 asserts two drivers with identical brand+model+Z produce distinct entry names with the second gaining ` [canonical_id]`.
7. **Bulk zero-eligible drivers.** Task 3 asserts `{entries: {}, skipped: [...]}` for an all-missing-fields input, so Task 4 glue can decide to show "Nothing to export" instead of a zero-byte zip.

---

## File Structure

- **Delete:** `tools/export_winisd.py` — one-off Python exporter, superseded by the browser version.
- **Create:** `web/export.js` — pure builders + browser-glue wrappers. Dual CJS+window attachment.
- **Create:** `tools/test_export.cjs` — Node unit tests. Loads `web/export.js` via `require()`. Zero stubs.
- **Modify:** `web/index.html` — fflate CDN script, `export.js` script, header export button, modal markup.
- **Modify:** `web/styles.css` — modal styles, per-row icon visibility, header icon alignment.
- **Modify:** `web/app.js` — Alpine state `exportModal`, methods, `formatCell` extension for Model column, delegated click handler on fixed tbody.

Why one `web/export.js` instead of splitting pure-vs-glue: the glue functions are five-line wrappers (`downloadDriver` just picks a builder and calls `triggerBrowserDownload`). Splitting into two files for 20 lines of code is overhead. The dual-attachment pattern keeps pure builders Node-loadable without touching DOM — glue functions only reference DOM/`fflate` *inside* their bodies, so top-level load in Node is safe.

---

## Task 0: Delete the Python exporter

**Files:**
- Delete: `tools/export_winisd.py`

### Steps

- [ ] **Step 1: Remove the file**

Run: `git rm tools/export_winisd.py`

- [ ] **Step 2: Grep for any lingering references**

Run: `grep -rn "export_winisd" --exclude-dir=.git .`
Expected: no results (or only this plan file, which references it as "deleted").

- [ ] **Step 3: Commit**

```bash
git commit -m "Remove one-off Python WinISD exporter

Superseded by the in-browser exporter in web/export.js (see
docs/superpowers/plans/2026-11-02-driver-export.md)."
```

---

## Task 1: WinISD Builder

**Files:**
- Create: `web/export.js`
- Create: `tools/test_export.cjs`

**Interfaces:**
- Consumes: driver record from `web/drivers.json#drivers[n]`
- Produces:
  - `buildWinisd(driver, { today }) → { ok: true, text: string, filename: string } | { ok: false, missing: string[] }`
  - `today` is a `YYYYMMDD` string. Required (no internal `new Date()`).

### Steps

- [ ] **Step 1: Scaffold `tools/test_export.cjs`**

```javascript
// Unit tests for web/export.js. Pure Node — no stubs, no sandbox.
// Run: node tools/test_export.cjs
// Exits non-zero on failed assertion.

const { buildWinisd, buildFfs, buildBulkEntries } = require("../web/export.js");
const assert = require("node:assert/strict");

// Synthetic driver matching the user-provided WinISD reference values.
// Hand-constructed so tests don't depend on scraper churn.
const REF = {
  manufacturer: "Faital Pro",
  model: "15XL1400",
  impedance_nominal_ohm: 8,
  fs_hz: 38,
  qts: 0.33,
  qms: 10.4,
  qes: 0.34,
  re_ohm: 5.4,
  le_mh: 1.6,
  bl_tm: 26.7,
  mms_g: 190,
  sd_cm2: 841,
  xmax_mm: 12.92,
  xmech_mm: 28,
  cms_mm_per_n: 0.09,
  vd_liters: 1.0866,
  eta_zero_pct: 1.41,
  rms_ns_per_m: 4.4,
  voice_coil_diameter_mm: 100,
  overall_diameter_mm: 393,
  depth_mm: 217,
  power_aes_watts: 1400,
  sensitivity_db_1w_1m: 96,
  ebp_hz: 112,
};

// Reference .wdr content from the user's spec, verbatim. Line separator
// is \r\n; final line is also followed by \r\n.
const REF_WDR =
  "[Driver]\r\n" +
  "Brand=Faital Pro\r\n" +
  "Model=15XL1400\r\n" +
  "Manufacturer=Faital Pro\r\n" +
  "ProvidedBy=driver-base\r\n" +
  "Comment=Xlim=28mm\r\n" +
  "DateAdded=20261028\r\n" +
  "DateModified=20261028\r\n" +
  "Qts=0.33\r\n" +
  "Znom=8\r\n" +
  "Fs=38\r\n" +
  "Pe=1400\r\n" +
  "SPL=96\r\n" +
  "Re=5.4\r\n" +
  "Le=0.0016\r\n" +
  "fLe=0\r\n" +
  "KLe=0\r\n" +
  "BL=26.7\r\n" +
  "Xmax=0.01292\r\n" +
  "Xlim=0.028\r\n" +
  "Cms=9e-05\r\n" +
  "Qms=10.4\r\n" +
  "Qes=0.34\r\n" +
  "Rms=4.4\r\n" +
  "Mms=0.19\r\n" +
  "Sd=0.0841\r\n" +
  "Vas=0.0912\r\n" +   // 91.2 L in dataset → 0.0912 m³. Add vas_liters: 91.2 to REF above during impl.
  "Dia=0\r\n" +
  "Vd=0.0010866\r\n" +
  "no=0.0141\r\n" +
  "Dd=0.327229958457699\r\n" +   // Math.sqrt(4 * 0.0841 / Math.PI)
  "EBP=112\r\n" +
  "numVC=1\r\n" +
  "Hc=0\r\nHg=0\r\nSPLmax=0\r\nSPLmaxLF=0\r\nUSPL=0\r\n" +
  "alfaVC=0\r\nRt=0\r\nCt=0\r\ngamma=0\r\n" +
  "Rme=0\r\nMpow=0\r\nMcost=0\r\nGloss=0\r\n" +
  "VCCon=1\r\n" +
  "c=343.68\r\nroo=1.20095\r\n" +
  "Thick=0\r\nDepth=0.217\r\n" +
  "MagDepth=0\r\nMagnet=0\r\nBasket=0\r\n" +
  "Outer=0.393\r\nVcd=0.1\r\nDVol=0\r\n";

function runWinisdTests() {
  const out = buildWinisd(REF, { today: "20261028" });
  assert.equal(out.ok, true, `buildWinisd not ok: ${JSON.stringify(out.missing)}`);
  assert.equal(out.filename, "Faital Pro 15XL1400 (8ohm).wdr", `filename: ${out.filename}`);

  if (out.text !== REF_WDR) {
    // Show first diverging line for a readable failure.
    const got = out.text.split("\r\n");
    const want = REF_WDR.split("\r\n");
    for (let i = 0; i < Math.max(got.length, want.length); i++) {
      if (got[i] !== want[i]) {
        throw new Error(
          `WinISD line ${i + 1} mismatch:\n  got:  ${JSON.stringify(got[i])}\n  want: ${JSON.stringify(want[i])}`
        );
      }
    }
    throw new Error("WinISD byte-mismatch (length)");
  }

  // Sanity: filename sanitization strips reserved chars + collapses whitespace.
  const dirty = buildWinisd(
    { ...REF, manufacturer: "Weird / Co", model: "A:B?C" },
    { today: "20261028" }
  );
  assert.equal(dirty.filename, "Weird Co A B C (8ohm).wdr", `sanitize: ${dirty.filename}`);

  // Missing fs_hz → skip.
  const noFs = buildWinisd({ ...REF, fs_hz: null }, { today: "20261028" });
  assert.equal(noFs.ok, false);
  assert.deepEqual(noFs.missing, ["fs_hz"]);

  // Missing qts → skip.
  const noQts = buildWinisd({ ...REF, qts: null }, { today: "20261028" });
  assert.equal(noQts.ok, false);
  assert.deepEqual(noQts.missing, ["qts"]);
}

runWinisdTests();
console.log("WinISD tests passed.");
```

**Note on `vas_liters`:** the REF constant above is missing `vas_liters` — the test expects `Vas=0.0912` in the output which maps to `vas_liters: 91.2`. Add `vas_liters: 91.2` to REF when implementing.

**Note on `Dd` precision:** Python's `math.sqrt(4 * 0.0841 / math.pi)` and JS `Math.sqrt(4 * 0.0841 / Math.PI)` both use IEEE 754 double-precision — they produce identical results. If the exact float differs from `0.327229958457699` in the user's sample, update the reference string to the actual computed value. The port is correct; the sample is a hand-copied artifact and may have been rounded.

- [ ] **Step 2: Run the test; verify it fails**

Run: `node tools/test_export.cjs`
Expected: fails with `Cannot find module '../web/export.js'`.

- [ ] **Step 3: Create `web/export.js` with the dual-attachment skeleton and `buildWinisd`**

```javascript
(function () {
  // --- Pure utilities ---
  const FIELD_ORDER = [ /* ... from Global Constraints ... */ ];
  const SANITIZE_RE = /[\\\/:*?"<>|\r\n\t]+/g;

  function sanitize(name) {
    return (name || "").replace(SANITIZE_RE, " ").trim().replace(/\s+/g, " ");
  }

  function num(x, def = 0) {
    if (x == null) return def;
    const n = typeof x === "number" ? x : parseFloat(x);
    return Number.isFinite(n) ? n : def;
  }

  // Python :.15g emulation. See Global Constraints.
  function formatValue(v) {
    if (typeof v === "string") return v;
    if (v === 0) return "0";
    if (Number.isInteger(v) && Math.abs(v) < 1e15) return String(v);
    const absV = Math.abs(v);
    const exp = Math.floor(Math.log10(absV));
    if (exp < -4 || exp >= 15) {
      // Scientific notation with Python's 2-digit zero-padded exponent.
      const parts = v.toExponential(14).split("e");
      let mantissa = parts[0];
      const e = parseInt(parts[1], 10);
      if (mantissa.includes(".")) {
        mantissa = mantissa.replace(/0+$/, "").replace(/\.$/, "");
      }
      const sign = e < 0 ? "-" : "+";
      return `${mantissa}e${sign}${String(Math.abs(e)).padStart(2, "0")}`;
    }
    let s = v.toPrecision(15);
    if (s.includes("e")) s = Number(v).toString(); // defensive, shouldn't fire
    if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
    return s;
  }

  function buildFilename(driver, ext) {
    const brand = sanitize(driver.manufacturer || "Unknown");
    const model = sanitize(driver.model || "Unknown");
    const z = driver.impedance_nominal_ohm;
    const zStr = z == null ? "" : ` (${Number(z)}ohm)`;
    return `${brand} ${model}${zStr}.${ext}`;
  }

  function buildWinisd(driver, { today } = {}) {
    const missing = [];
    if (driver.fs_hz == null) missing.push("fs_hz");
    if (driver.qts == null) missing.push("qts");
    if (missing.length) return { ok: false, missing };

    const sdCm2 = num(driver.sd_cm2);
    const sdM2 = sdCm2 / 10000;
    const ddM = sdM2 > 0 ? Math.sqrt((4 * sdM2) / Math.PI) : 0;

    let vdM3;
    if (driver.vd_liters != null) {
      vdM3 = num(driver.vd_liters) / 1000;
    } else if (sdM2 > 0 && driver.xmax_mm != null) {
      vdM3 = sdM2 * (num(driver.xmax_mm) / 1000);
    } else {
      vdM3 = 0;
    }

    const commentBits = [];
    if (driver.xmech_mm != null) commentBits.push(`Xlim=${formatValue(num(driver.xmech_mm))}mm`);

    const rec = {
      Brand: driver.manufacturer || "",
      Model: driver.model || "",
      Manufacturer: driver.manufacturer || "",
      ProvidedBy: "driver-base",
      Comment: commentBits.join("; "),
      DateAdded: today,
      DateModified: today,
      Qts: num(driver.qts),
      Znom: num(driver.impedance_nominal_ohm),
      Fs: num(driver.fs_hz),
      Pe: num(driver.power_aes_watts ?? driver.power_long_term_watts),
      SPL: num(driver.sensitivity_db_1w_1m),
      Re: num(driver.re_ohm),
      Le: num(driver.le_mh) / 1000,
      fLe: 0, KLe: 0,
      BL: num(driver.bl_tm),
      Xmax: num(driver.xmax_mm) / 1000,
      Xlim: num(driver.xmech_mm) / 1000,
      Cms: num(driver.cms_mm_per_n) / 1000,
      Qms: num(driver.qms),
      Qes: num(driver.qes),
      Rms: num(driver.rms_ns_per_m),
      Mms: num(driver.mms_g) / 1000,
      Sd: sdM2,
      Vas: num(driver.vas_liters) / 1000,
      Dia: 0,
      Vd: vdM3,
      no: num(driver.eta_zero_pct) / 100,
      Dd: ddM,
      EBP: num(driver.ebp_hz),
      numVC: 1,
      Hc: 0, Hg: 0, SPLmax: 0, SPLmaxLF: 0, USPL: 0,
      alfaVC: 0, Rt: 0, Ct: 0, gamma: 0,
      Rme: 0, Mpow: 0, Mcost: 0, Gloss: 0,
      VCCon: 1,
      c: 343.68, roo: 1.20095,
      Thick: 0, Depth: num(driver.depth_mm) / 1000,
      MagDepth: 0, Magnet: 0, Basket: 0,
      Outer: num(driver.overall_diameter_mm) / 1000,
      Vcd: num(driver.voice_coil_diameter_mm) / 1000,
      DVol: 0,
    };

    const lines = ["[Driver]"];
    for (const k of FIELD_ORDER) lines.push(`${k}=${formatValue(rec[k])}`);
    const text = lines.join("\r\n") + "\r\n";
    return { ok: true, text, filename: buildFilename(driver, "wdr") };
  }

  // (buildFfs, buildBulkEntries, downloadDriver, downloadDatabase added in later tasks)

  const api = { buildWinisd };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.DriverExport = api;
})();
```

- [ ] **Step 4: Run the test; verify it passes**

Run: `node tools/test_export.cjs`
Expected: exits 0, prints `WinISD tests passed.`

If the Faital reference mismatches on `Dd` or `Vas`, update the reference string to the computed value — the port is authoritative, the sample is a hand-copied artifact. Document the correction inline in the test.

- [ ] **Step 5: Commit**

```bash
git add web/export.js tools/test_export.cjs
git commit -m "Add WinISD browser-side exporter with Node unit tests"
```

---

## Task 2: FFS Builder

**Files:**
- Modify: `web/export.js` — add `buildFfs`
- Modify: `tools/test_export.cjs` — add FFS test block

**Interfaces:**
- Produces: `buildFfs(driver) → { ok: true, text: string, filename: string } | { ok: false, missing: string[] }`

### Steps

- [ ] **Step 1: Add FFS tests to `tools/test_export.cjs`**

Append before any `console.log("…passed.")`:

```javascript
function runFfsTests() {
  const out = buildFfs(REF);
  assert.equal(out.ok, true, `buildFfs not ok: ${JSON.stringify(out.missing)}`);
  assert.equal(out.filename, "Faital Pro 15XL1400 (8ohm).ffsdrv");

  const obj = JSON.parse(out.text);
  const expectedKeys = ["bl","fs","le","leLossN","leakageQl","mms","powerW","qms","re","sd","xmaxMm"];
  assert.deepEqual(Object.keys(obj), expectedKeys, "FFS key set/order mismatch");

  // Value spot-checks (all identity unit passes).
  assert.equal(obj.bl, 26.7);
  assert.equal(obj.fs, 38);
  assert.equal(obj.le, 1.6);
  assert.equal(obj.leLossN, 1);
  assert.equal(obj.leakageQl, 100);
  assert.equal(obj.mms, 190);
  assert.equal(obj.powerW, 1400); // from power_aes_watts
  assert.equal(obj.qms, 10.4);
  assert.equal(obj.re, 5.4);
  assert.equal(obj.sd, 841);
  assert.equal(obj.xmaxMm, 12.92);

  // 2-space indent (user-provided sample style).
  assert.match(out.text, /^\{\n  "bl":/);

  // powerW fallbacks.
  const noAes = buildFfs({ ...REF, power_aes_watts: null });
  assert.equal(JSON.parse(noAes.text).powerW, REF.power_long_term_watts ?? 100);
  const noPower = buildFfs({ ...REF, power_aes_watts: null, power_long_term_watts: null });
  assert.equal(JSON.parse(noPower.text).powerW, 100);

  // Missing required field → skip, not partial.
  const noMms = buildFfs({ ...REF, mms_g: null });
  assert.equal(noMms.ok, false);
  assert.deepEqual(noMms.missing, ["mms_g"]);
}

runFfsTests();
console.log("FFS tests passed.");
```

- [ ] **Step 2: Run the test; verify it fails**

Run: `node tools/test_export.cjs`
Expected: fails on `buildFfs is not a function`.

- [ ] **Step 3: Add `buildFfs` to `web/export.js`**

```javascript
const FFS_REQUIRED = ["fs_hz", "qms", "re_ohm", "bl_tm", "mms_g", "sd_cm2"];

function buildFfs(driver) {
  const missing = FFS_REQUIRED.filter(k => driver[k] == null);
  if (missing.length) return { ok: false, missing };
  const rec = {
    bl: driver.bl_tm,
    fs: driver.fs_hz,
    le: driver.le_mh ?? 0,
    leLossN: 1,
    leakageQl: 100,
    mms: driver.mms_g,
    powerW: driver.power_aes_watts ?? driver.power_long_term_watts ?? 100,
    qms: driver.qms,
    re: driver.re_ohm,
    sd: driver.sd_cm2,
    xmaxMm: driver.xmax_mm ?? 0,
  };
  return { ok: true, text: JSON.stringify(rec, null, 2), filename: buildFilename(driver, "ffsdrv") };
}
```

Add `buildFfs` to the `api` object at the bottom.

- [ ] **Step 4: Run the test; verify it passes**

Run: `node tools/test_export.cjs`
Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add web/export.js tools/test_export.cjs
git commit -m "Add FFS exporter with closed 11-key schema"
```

---

## Task 3: Bulk Entry Builder (pure)

**Files:**
- Modify: `web/export.js` — add `buildBulkEntries`
- Modify: `tools/test_export.cjs` — add bulk test block

**Interfaces:**
- Produces: `buildBulkEntries(drivers, format, { today }) → { entries: Record<filename, string>, skipped: Array<{canonical_id, manufacturer, model, missing}> }`
- Pure. No fflate, no DOM. `entries[filename] = text` (string, not bytes — Task 4 glue encodes to Uint8Array for fflate).

### Steps

- [ ] **Step 1: Add bulk tests**

```javascript
function runBulkTests() {
  // Mix of valid and broken drivers.
  const good = [REF, { ...REF, manufacturer: "Test B", model: "B2" }];
  const broken = { ...REF, canonical_id: "broken__x", fs_hz: null };
  const dupe = { ...REF, canonical_id: "dupe__y" };

  const r = buildBulkEntries([...good, broken, dupe], "winisd", { today: "20261028" });
  const names = Object.keys(r.entries);

  assert.equal(names.length, 3, `expected 3 entries, got ${names.length}`);
  assert.equal(r.skipped.length, 1);
  assert.equal(r.skipped[0].canonical_id, "broken__x");
  assert.deepEqual(r.skipped[0].missing, ["fs_hz"]);

  // Collision disambiguation: REF and dupe share brand/model/Z, so dupe
  // gets " [dupe__y]" appended.
  assert.ok(names.some(n => n === "Faital Pro 15XL1400 (8ohm).wdr"), `missing primary: ${names}`);
  assert.ok(names.some(n => n.includes("[dupe__y]")), `missing dedup: ${names}`);

  // Zero-eligible case.
  const empty = buildBulkEntries([broken], "winisd", { today: "20261028" });
  assert.deepEqual(Object.keys(empty.entries), []);
  assert.equal(empty.skipped.length, 1);

  // FFS mode: filenames end in .ffsdrv.
  const ffs = buildBulkEntries(good, "ffs", { today: "20261028" });
  assert.ok(Object.keys(ffs.entries).every(n => n.endsWith(".ffsdrv")));
}

runBulkTests();
console.log("Bulk tests passed.");
```

- [ ] **Step 2: Run the test; verify it fails**

Run: `node tools/test_export.cjs`
Expected: fails on `buildBulkEntries is not a function`.

- [ ] **Step 3: Add `buildBulkEntries` to `web/export.js`**

```javascript
function buildBulkEntries(drivers, format, { today } = {}) {
  const builder = format === "ffs" ? buildFfs : buildWinisd;
  const entries = {};
  const skipped = [];
  const seen = new Set();
  for (const d of drivers) {
    const r = format === "ffs" ? builder(d) : builder(d, { today });
    if (!r.ok) {
      skipped.push({ canonical_id: d.canonical_id, manufacturer: d.manufacturer, model: d.model, missing: r.missing });
      continue;
    }
    let name = r.filename;
    if (seen.has(name.toLowerCase())) {
      const dot = name.lastIndexOf(".");
      name = `${name.slice(0, dot)} [${d.canonical_id}]${name.slice(dot)}`;
    }
    seen.add(name.toLowerCase());
    entries[name] = r.text;
  }
  return { entries, skipped };
}
```

Add to `api`.

- [ ] **Step 4: Run the test; verify it passes**

Run: `node tools/test_export.cjs`
Expected: exits 0.

- [ ] **Step 5: Commit**

```bash
git add web/export.js tools/test_export.cjs
git commit -m "Add bulk entry builder with collision dedup"
```

---

## Task 4: Browser Glue (DOM download + fflate zip)

**Files:**
- Modify: `web/export.js` — add `downloadDriver`, `downloadDatabase`, `triggerBrowserDownload`
- Modify: `web/index.html` — add fflate CDN script, add `export.js` script

**Interfaces:**
- `downloadDriver(driver, format) → { ok: true } | { ok: false, missing: string[] }`
- `downloadDatabase(drivers, format, { scope, generatedAt }) → { written: number, skipped: Array<...> }`
- Both side-effect: trigger a browser download via Blob + anchor click. For bulk, `window.fflate.zipSync(...)` is called synchronously; the zip bytes become the download Blob.
- Both are NOT tested in Node. They are hand-verified in Task 7.

### Steps

- [ ] **Step 1: Add glue to `web/export.js`**

```javascript
function triggerBrowserDownload(filename, body, mime) {
  const blob = new Blob([body], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function todayYmd() {
  const d = new Date();
  return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
}

function downloadDriver(driver, format) {
  const r = format === "ffs" ? buildFfs(driver) : buildWinisd(driver, { today: todayYmd() });
  if (!r.ok) return r;
  triggerBrowserDownload(r.filename, r.text, format === "ffs" ? "application/json" : "text/plain");
  return { ok: true };
}

function downloadDatabase(drivers, format, { scope, generatedAt } = {}) {
  const { entries, skipped } = buildBulkEntries(drivers, format, { today: todayYmd() });
  if (Object.keys(entries).length === 0) return { written: 0, skipped };
  // Encode text entries to Uint8Array for fflate.
  const zipInput = {};
  const enc = new TextEncoder();
  for (const [name, text] of Object.entries(entries)) zipInput[name] = enc.encode(text);
  const zipBytes = window.fflate.zipSync(zipInput);
  const prefix = (generatedAt || "").slice(0, 10);
  const date = /^\d{4}-\d{2}-\d{2}$/.test(prefix) ? prefix : new Date().toISOString().slice(0, 10);
  const zipName = `driver-base-${scope}-${format === "ffs" ? "ffs" : "winisd"}-${date}.zip`;
  triggerBrowserDownload(zipName, zipBytes, "application/zip");
  return { written: Object.keys(entries).length, skipped };
}
```

Add `downloadDriver` and `downloadDatabase` to `api`.

- [ ] **Step 2: Load fflate + export.js in `web/index.html`**

In the `<body>` script block near `<script src="app.js">` (line 538), add BEFORE `app.js`:

```html
<script src="https://cdn.jsdelivr.net/npm/fflate@0.8.2/umd/index.js"></script>
<script src="export.js"></script>
```

Order: Materialize JS (existing) → fflate → export.js → app.js → Alpine (deferred, existing).

- [ ] **Step 3: Verify the Node tests still pass**

Run: `node tools/test_export.cjs`
Expected: still exits 0 (the glue functions reference `window`/`document`/`fflate` only inside their bodies — top-level load in Node is clean).

- [ ] **Step 4: Smoke-test in browser**

Run: `cd web && python3 -m http.server 8000`, open the page, open devtools console:

```javascript
window.DriverExport.downloadDriver(
  Object.values(Alpine.$data(document.body)).find(x => x), // app() state
  "winisd"
);
```

(Alternatively: `document.body.__x?.$data.drivers.find(d => d.model === "15XL1400")` — grab any driver record from Alpine's state and pass to `downloadDriver`.)
Expected: `.wdr` file downloads. Open it; verify it matches the reference content.

- [ ] **Step 5: Commit**

```bash
git add web/export.js web/index.html
git commit -m "Add browser glue (DOM download + fflate zip)"
```

---

## Task 5: Export Modal (markup + Alpine state + methods)

**Files:**
- Modify: `web/index.html` — add modal markup
- Modify: `web/app.js` — add state and methods
- Modify: `web/styles.css` — modal styles

**Interfaces:**
- Alpine state and methods on the `app()` component:
  - `exportModal: { open, mode, driver, format, scope, result }`
  - `openExportDriver(driver): void`
  - `openExportDatabase(): void`
  - `confirmExport(): void`
  - `closeExportModal(): void`

### Steps

- [ ] **Step 1: Add Alpine state and methods to `web/app.js`**

In the `app()` return object (near `hoverIdx: null` at line 529), add:

```javascript
exportModal: {
  open: false,
  mode: "driver",   // "driver" | "database"
  driver: null,
  format: "winisd", // "winisd" | "ffs"
  scope: "view",    // "view" | "full"
  result: null,
},
```

In the methods section:

```javascript
openExportDriver(driver) {
  this.exportModal = { open: true, mode: "driver", driver, format: "winisd", scope: "view", result: null };
},
openExportDatabase() {
  this.exportModal = { open: true, mode: "database", driver: null, format: "winisd", scope: "view", result: null };
},
closeExportModal() {
  this.exportModal.open = false;
},
confirmExport() {
  const DX = window.DriverExport;
  if (this.exportModal.mode === "driver") {
    const r = DX.downloadDriver(this.exportModal.driver, this.exportModal.format);
    this.exportModal.result = r.ok
      ? { written: 1, skipped: [], nothingToExport: false }
      : {
          written: 0,
          skipped: [{
            canonical_id: this.exportModal.driver.canonical_id,
            manufacturer: this.exportModal.driver.manufacturer,
            model: this.exportModal.driver.model,
            missing: r.missing,
          }],
          nothingToExport: false,
        };
  } else {
    const rows = this.exportModal.scope === "full" ? this.drivers : this.sortedFiltered;
    const r = DX.downloadDatabase(rows, this.exportModal.format, {
      scope: this.exportModal.scope,
      generatedAt: this.generatedAt,
    });
    this.exportModal.result = {
      written: r.written,
      skipped: r.skipped,
      nothingToExport: r.written === 0 && r.skipped.length === 0,
    };
  }
},
```

- [ ] **Step 2: Add modal markup to `web/index.html`**

Before `</body>`:

```html
<!-- Export modal. Alpine-driven, not Materialize-initialized. -->
<div class="export-modal-backdrop"
     x-show="exportModal.open"
     x-cloak x-transition.opacity
     @click.self="closeExportModal()"
     @keydown.escape.window="closeExportModal()">
  <div class="export-modal" role="dialog" aria-modal="true">
    <h5 x-text="exportModal.mode === 'driver'
                ? `Export driver — ${exportModal.driver?.manufacturer || ''} ${exportModal.driver?.model || ''}`
                : 'Export database'"></h5>

    <div x-show="!exportModal.result">
      <fieldset class="export-radio-group">
        <legend>Format</legend>
        <label><input type="radio" class="with-gap" name="exportFormat" value="winisd" x-model="exportModal.format"/><span>WinISD (.wdr)</span></label>
        <label><input type="radio" class="with-gap" name="exportFormat" value="ffs" x-model="exportModal.format"/><span>FFS (.ffsdrv)</span></label>
      </fieldset>

      <fieldset class="export-radio-group" x-show="exportModal.mode === 'database'">
        <legend>Scope</legend>
        <label><input type="radio" class="with-gap" name="exportScope" value="view" x-model="exportModal.scope"/><span x-text="`Current view (${sortedFiltered.length})`"></span></label>
        <label><input type="radio" class="with-gap" name="exportScope" value="full" x-model="exportModal.scope"/><span x-text="`Full database (${drivers.length})`"></span></label>
      </fieldset>

      <div class="export-modal-actions">
        <button type="button" class="btn-flat" @click="closeExportModal()">Cancel</button>
        <button type="button" class="btn waves-effect teal" @click="confirmExport()">Export</button>
      </div>
    </div>

    <div x-show="exportModal.result">
      <p x-show="exportModal.result?.nothingToExport" class="grey-text">
        Nothing to export in the current view.
      </p>
      <p x-show="!exportModal.result?.nothingToExport">
        Exported <strong x-text="exportModal.result?.written"></strong> driver(s).
      </p>
      <template x-if="exportModal.result?.skipped?.length">
        <div class="export-skipped">
          <p>Skipped <strong x-text="exportModal.result.skipped.length"></strong> driver(s) with missing fields:</p>
          <ul>
            <template x-for="s in exportModal.result.skipped" :key="s.canonical_id">
              <li>
                <span x-text="`${s.manufacturer} ${s.model}`"></span>
                <span class="grey-text" x-text="`(missing: ${s.missing.join(', ')})`"></span>
              </li>
            </template>
          </ul>
        </div>
      </template>
      <div class="export-modal-actions">
        <button type="button" class="btn-flat teal-text" @click="closeExportModal()">Close</button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Add modal CSS to `web/styles.css`**

Use only existing CSS variables (`--surface`, `--text`, `--text-muted`, `--border`, `--shadow-popover`, `--link`). Mirror `.picker-popover` / `.spec-popover` for surface styling. Variables auto-switch dark/light.

```css
.export-modal-backdrop {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex; align-items: center; justify-content: center;
  z-index: 1000;
}
.export-modal {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 20px 24px;
  width: min(520px, calc(100vw - 32px));
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  box-shadow: var(--shadow-popover);
}
.export-modal h5 { margin: 0 0 12px 0; font-size: 1.1rem; font-weight: 500; }
.export-radio-group { border: none; padding: 0; margin: 12px 0; }
.export-radio-group legend { color: var(--text-muted); font-size: 0.9rem; margin-bottom: 4px; }
.export-radio-group label { display: block; margin: 6px 0; }
.export-modal-actions {
  display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px;
}
.export-skipped ul {
  max-height: 240px; overflow-y: auto;
  margin: 8px 0 0 0; padding-left: 20px;
  color: var(--text-muted);
}
```

- [ ] **Step 4: Smoke-test in browser**

Run the server, open the page. In devtools console:

```javascript
Alpine.$data(document.querySelector("body")).openExportDatabase()
```

Expected: modal appears centered with Format + Scope radios, Cancel and Export buttons. Clicking the backdrop or pressing Escape dismisses. No console errors. Toggle dark mode and reopen; surface and text contrast remain readable.

- [ ] **Step 5: Commit**

```bash
git add web/app.js web/index.html web/styles.css
git commit -m "Add export modal UI (state, markup, styles)"
```

---

## Task 6: Trigger Icons (header + per-row hover)

**Files:**
- Modify: `web/index.html` — add header export button, add `@click` on fixed tbody
- Modify: `web/app.js` — extend `formatCell` for Model column, add `onRowExportClick`
- Modify: `web/styles.css` — hover-reveal and header icon styles

### Steps

- [ ] **Step 1: Add header export button**

In the `.nav-actions-left` block (`index.html:65-83`), AFTER the theme switch div, add:

```html
<button type="button"
        class="nav-icon-btn export-btn-header"
        @click="openExportDatabase()"
        title="Export Database"
        aria-label="Export Database">
  <i class="material-icons" aria-hidden="true">file_download</i>
</button>
```

- [ ] **Step 2: Extend `formatCell` and add delegated click**

In `web/app.js:988-995`, split manufacturer and model handling:

```javascript
if (col.key === "manufacturer") {
  const u = d.source_urls && d.source_urls[0];
  return u ? `<a href="${u}" target="_blank" rel="noopener">${v}</a>` : v;
}
if (col.key === "model") {
  const u = d.source_urls && d.source_urls[0];
  const link = u ? `<a href="${u}" target="_blank" rel="noopener">${v}</a>` : v;
  const icon = `<button type="button"
    class="row-export-btn"
    data-cid="${d.canonical_id}"
    title="Export Driver"
    aria-label="Export Driver"><i class="material-icons" aria-hidden="true">file_download</i></button>`;
  return `${link}${icon}`;
}
```

Add method to the Alpine component:

```javascript
onRowExportClick(event) {
  const btn = event.target.closest(".row-export-btn");
  if (!btn) return;
  event.preventDefault();
  const cid = btn.dataset.cid;
  const driver = this.drivers.find(d => d.canonical_id === cid);
  if (driver) this.openExportDriver(driver);
},
```

Modify the FIXED table's `<tbody>` at `web/index.html:425` (the bare `<tbody>` with no existing attributes — NOT the reorderable one at line 466 which already has `openSpecPopover`). Change:

```html
<tbody>
```

to:

```html
<tbody @click="onRowExportClick($event)">
```

- [ ] **Step 3: Add icon CSS**

```css
.row-export-btn {
  background: transparent;
  border: 0;
  padding: 0 4px;
  margin-left: 6px;
  cursor: pointer;
  color: var(--text-muted);
  opacity: 0;
  vertical-align: middle;
}
.row-export-btn .material-icons { font-size: 18px; }
tr.row-hover .row-export-btn,
tr:hover .row-export-btn { opacity: 1; }
.row-export-btn:hover { color: var(--link); }

.export-btn-header {
  background: transparent;
  border: 0;
  padding: 6px 8px;
  cursor: pointer;
  color: inherit;
}
.export-btn-header:hover { opacity: 0.85; }
```

The `tr:hover` fallback alongside `tr.row-hover` covers the fast-cursor race between Alpine's `hoverIdx` and the click.

- [ ] **Step 4: Verify in browser**

Walkthrough:
- Hover any row's Model cell → export icon fades in to the right of the model name.
- Click the icon → modal opens with the correct driver's brand/model in the title.
- Click the header icon next to the dark-mode toggle → modal opens titled "Export database".
- Dark mode: both icons remain readable; hover color is the `--link` teal.

- [ ] **Step 5: Commit**

```bash
git add web/index.html web/app.js web/styles.css
git commit -m "Add export trigger icons (header + per-row hover)"
```

---

## Task 7: End-to-End Verification

No code changes — the one-off sanity test the user approved in brainstorming.

### Steps

- [ ] **Step 1: Node tests one last time**

Run: `node tools/test_export.cjs`
Expected: exits 0, prints all three "passed." lines.

- [ ] **Step 2: Full UI walkthrough**

Run: `cd web && python3 -m http.server 8000`.

1. Hover `Faital Pro 15XL1400` → click export icon → WinISD → Export → file downloads.
2. Open the downloaded `.wdr` in a text editor. Confirm it matches the user-provided reference (line-for-line, modulo the `DateAdded`/`DateModified` which will show today's date instead of `20261028`).
3. Repeat for FFS → verify 11-key JSON with 2-space indent.
4. Hover an HF-compression driver (missing T/S) → click → FFS → Export → modal shows result view listing the driver as skipped with the missing field list.
5. Click header icon → format=WinISD, scope=Current View → Export → downloads `driver-base-view-winisd-YYYY-MM-DD.zip`. Run `unzip -l` on it; verify one `.wdr` per eligible filtered driver.
6. Filter to zero results → open header export → Current View → Export → modal shows "Nothing to export in the current view."
7. Scope=Full Database → Export → zip downloads; result view lists ~658 skipped drivers (matches `docs/export-viability.md`).
8. Toggle dark mode and re-open modal; verify radios, buttons, and the skipped list are legible.

- [ ] **Step 3: Commit any polish fixes**

If the walkthrough surfaces CSS or copy issues, commit them in one tidy commit. Skip if the walkthrough is clean.

- [ ] **Step 4: Refresh `docs/export-viability.md` if the dataset was regenerated during the build**

If `web/drivers.json#generated_at` changed since the plan was written, regenerate the audit file.

---

## Doc-sync Checklist (run before each commit)

Per `~/.claude/CLAUDE.md` doc-sync gate:

- [ ] `README.md` — consider a one-sentence mention of in-browser export under "Using the dataset" (optional).
- [ ] `docs/tasks.md` — the "Close export-viability gaps" entry is still accurate; refresh counts if the dataset was regenerated.
- [ ] `docs/export-viability.md` — regenerate if the dataset changed.
- [ ] This plan file — if any task deviates from the plan, note the deviation inline before marking the plan complete.
