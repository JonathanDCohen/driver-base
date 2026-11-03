// Unit tests for web/export.js. Pure Node, no stubs, no sandbox.
// Run: node tools/test_export.cjs
// Exits non-zero on failed assertion.

const assert = require("node:assert/strict");
const { buildWinisd, buildFfs, buildBulkEntries } = require("../web/export.js");

// Synthetic driver matching the user-provided WinISD reference values —
// not pulled from drivers.json so the test is immune to scraper churn.
const REF = {
  canonical_id: "faital_pro__15xl1400__8ohm",
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
  vas_liters: 91.2,
  eta_zero_pct: 1.41,
  rms_ns_per_m: 4.4,
  voice_coil_diameter_mm: 100,
  overall_diameter_mm: 393,
  depth_mm: 217,
  power_aes_watts: 1400,
  power_long_term_watts: 1400,
  sensitivity_db_1w_1m: 96,
  ebp_hz: 112,
};

// Reference .wdr from the user's spec, verbatim. CRLF between lines,
// trailing CRLF after the final line.
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
  "Vas=0.0912\r\n" +
  "Dia=0\r\n" +
  "Vd=0.0010866\r\n" +
  "no=0.0141\r\n" +
  "Dd=0.327229958457699\r\n" +
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
    const got = out.text.split("\r\n");
    const want = REF_WDR.split("\r\n");
    for (let i = 0; i < Math.max(got.length, want.length); i++) {
      if (got[i] !== want[i]) {
        throw new Error(
          `WinISD line ${i + 1} mismatch:\n  got:  ${JSON.stringify(got[i])}\n  want: ${JSON.stringify(want[i])}`
        );
      }
    }
    throw new Error("WinISD byte-mismatch (length differs)");
  }

  // Filename sanitization strips reserved chars + collapses whitespace.
  const dirty = buildWinisd(
    { ...REF, manufacturer: "Weird / Co", model: "A:B?C" },
    { today: "20261028" }
  );
  assert.equal(dirty.filename, "Weird Co A B C (8ohm).wdr", `sanitize: ${dirty.filename}`);

  // Missing fs_hz → skip, no partial.
  const noFs = buildWinisd({ ...REF, fs_hz: null }, { today: "20261028" });
  assert.equal(noFs.ok, false);
  assert.deepEqual(noFs.missing, ["fs_hz"]);

  // Missing qts → skip.
  const noQts = buildWinisd({ ...REF, qts: null }, { today: "20261028" });
  assert.equal(noQts.ok, false);
  assert.deepEqual(noQts.missing, ["qts"]);
}

function runFfsTests() {
  const out = buildFfs(REF);
  assert.equal(out.ok, true, `buildFfs not ok: ${JSON.stringify(out.missing)}`);
  assert.equal(out.filename, "Faital Pro 15XL1400 (8ohm).ffsdrv");

  const obj = JSON.parse(out.text);
  const expectedKeys = [
    "bl", "fs", "le", "leLossN", "leakageQl",
    "mms", "powerW", "qms", "re", "sd", "xmaxMm",
  ];
  assert.deepEqual(Object.keys(obj), expectedKeys, "FFS key set/order mismatch");

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

  // 2-space indent (matches user-provided sample).
  assert.match(out.text, /^\{\n  "bl":/);

  // powerW fallback chain.
  const noAes = buildFfs({ ...REF, power_aes_watts: null });
  assert.equal(JSON.parse(noAes.text).powerW, 1400); // long_term still 1400
  const noPower = buildFfs({ ...REF, power_aes_watts: null, power_long_term_watts: null });
  assert.equal(JSON.parse(noPower.text).powerW, 100);

  // Missing required → skip, not partial.
  const noMms = buildFfs({ ...REF, mms_g: null });
  assert.equal(noMms.ok, false);
  assert.deepEqual(noMms.missing, ["mms_g"]);
}

function runBulkTests() {
  const good = [
    REF,
    { ...REF, canonical_id: "test__b2", manufacturer: "Test B", model: "B2" },
  ];
  const broken = { ...REF, canonical_id: "broken__x", fs_hz: null };
  const dupe = { ...REF, canonical_id: "dupe__y" };

  const r = buildBulkEntries([...good, broken, dupe], "winisd", { today: "20261028" });
  const names = Object.keys(r.entries);

  assert.equal(names.length, 3, `expected 3 entries, got ${names.length}: ${names}`);
  assert.equal(r.skipped.length, 1);
  assert.equal(r.skipped[0].canonical_id, "broken__x");
  assert.deepEqual(r.skipped[0].missing, ["fs_hz"]);

  assert.ok(names.some((n) => n === "Faital Pro 15XL1400 (8ohm).wdr"),
    `missing primary: ${names}`);
  assert.ok(names.some((n) => n.includes("[dupe__y]")),
    `missing dedup suffix: ${names}`);

  // Zero-eligible: all broken, no entries written.
  const empty = buildBulkEntries([broken], "winisd", { today: "20261028" });
  assert.deepEqual(Object.keys(empty.entries), []);
  assert.equal(empty.skipped.length, 1);

  // FFS mode produces .ffsdrv filenames.
  const ffs = buildBulkEntries(good, "ffs", { today: "20261028" });
  assert.ok(Object.keys(ffs.entries).every((n) => n.endsWith(".ffsdrv")),
    `FFS filenames: ${Object.keys(ffs.entries)}`);
}

runWinisdTests();
console.log("WinISD tests passed.");
runFfsTests();
console.log("FFS tests passed.");
runBulkTests();
console.log("Bulk tests passed.");
