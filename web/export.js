// In-browser driver exporter. Dual CJS + window attachment so the pure
// builders are usable from Node tests (require("../web/export.js")) and
// the browser (window.DriverExport.*). See docs/superpowers/plans/2026-11-02-driver-export.md.

(function () {
  const FIELD_ORDER = [
    "Brand",
    "Model",
    "Manufacturer",
    "ProvidedBy",
    "Comment",
    "DateAdded",
    "DateModified",
    "Qts",
    "Znom",
    "Fs",
    "Pe",
    "SPL",
    "Re",
    "Le",
    "fLe",
    "KLe",
    "BL",
    "Xmax",
    "Xlim",
    "Cms",
    "Qms",
    "Qes",
    "Rms",
    "Mms",
    "Sd",
    "Vas",
    "Dia",
    "Vd",
    "no",
    "Dd",
    "EBP",
    "numVC",
    "Hc",
    "Hg",
    "SPLmax",
    "SPLmaxLF",
    "USPL",
    "alfaVC",
    "Rt",
    "Ct",
    "gamma",
    "Rme",
    "Mpow",
    "Mcost",
    "Gloss",
    "VCCon",
    "c",
    "roo",
    "Thick",
    "Depth",
    "MagDepth",
    "Magnet",
    "Basket",
    "Outer",
    "Vcd",
    "DVol",
  ];

  const FFS_REQUIRED = ["fs_hz", "qms", "re_ohm", "bl_tm", "mms_g", "sd_cm2"];
  const SANITIZE_RE = /[\\/:*?"<>|\r\n\t]+/g;

  function sanitize(name) {
    return (name || "").replace(SANITIZE_RE, " ").trim().replace(/\s+/g, " ");
  }

  function num(x, def = 0) {
    if (x == null) return def;
    const n = typeof x === "number" ? x : parseFloat(x);
    return Number.isFinite(n) ? n : def;
  }

  // Python :.15g emulation: up to 15 sig figs, trim trailing zeros,
  // switch to scientific notation when exponent < -4 or >= 15 with a
  // two-digit zero-padded exponent (e.g. "9e-05", not "9e-5").
  function formatValue(v) {
    if (typeof v === "string") return v;
    if (v === 0) return "0";
    if (Number.isInteger(v) && Math.abs(v) < 1e15) return String(v);
    const absV = Math.abs(v);
    const exp = Math.floor(Math.log10(absV));
    if (exp < -4 || exp >= 15) {
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
    if (s.includes("e")) s = Number(v).toString();
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
    if (driver.xmech_mm != null) {
      commentBits.push(`Xlim=${formatValue(num(driver.xmech_mm))}mm`);
    }

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
      fLe: 0,
      KLe: 0,
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
      Hc: 0,
      Hg: 0,
      SPLmax: 0,
      SPLmaxLF: 0,
      USPL: 0,
      alfaVC: 0,
      Rt: 0,
      Ct: 0,
      gamma: 0,
      Rme: 0,
      Mpow: 0,
      Mcost: 0,
      Gloss: 0,
      VCCon: 1,
      c: 343.68,
      roo: 1.20095,
      Thick: 0,
      Depth: num(driver.depth_mm) / 1000,
      MagDepth: 0,
      Magnet: 0,
      Basket: 0,
      Outer: num(driver.overall_diameter_mm) / 1000,
      Vcd: num(driver.voice_coil_diameter_mm) / 1000,
      DVol: 0,
    };

    const lines = ["[Driver]"];
    for (const k of FIELD_ORDER) lines.push(`${k}=${formatValue(rec[k])}`);
    const text = lines.join("\r\n") + "\r\n";
    return { ok: true, text, filename: buildFilename(driver, "wdr") };
  }

  function buildFfs(driver) {
    const missing = FFS_REQUIRED.filter((k) => driver[k] == null);
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
    return {
      ok: true,
      text: JSON.stringify(rec, null, 2),
      filename: buildFilename(driver, "ffsdrv"),
    };
  }

  function buildBulkEntries(drivers, format, { today } = {}) {
    const entries = {};
    const skipped = [];
    const seen = new Set();
    for (const d of drivers) {
      const r = format === "ffs" ? buildFfs(d) : buildWinisd(d, { today });
      if (!r.ok) {
        skipped.push({
          canonical_id: d.canonical_id,
          manufacturer: d.manufacturer,
          model: d.model,
          missing: r.missing,
        });
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
    const r =
      format === "ffs"
        ? buildFfs(driver)
        : buildWinisd(driver, { today: todayYmd() });
    if (!r.ok) return r;
    const mime = format === "ffs" ? "application/json" : "text/plain";
    triggerBrowserDownload(r.filename, r.text, mime);
    return { ok: true };
  }

  function downloadDatabase(drivers, format, { scope, generatedAt } = {}) {
    const { entries, skipped } = buildBulkEntries(drivers, format, {
      today: todayYmd(),
    });
    if (Object.keys(entries).length === 0) return { written: 0, skipped };
    const enc = new TextEncoder();
    const zipInput = {};
    for (const [name, text] of Object.entries(entries)) {
      zipInput[name] = enc.encode(text);
    }
    const zipBytes = window.fflate.zipSync(zipInput);
    const prefix = (generatedAt || "").slice(0, 10);
    const date = /^\d{4}-\d{2}-\d{2}$/.test(prefix)
      ? prefix
      : new Date().toISOString().slice(0, 10);
    const kind = format === "ffs" ? "ffs" : "winisd";
    const zipName = `driver-base-${scope}-${kind}-${date}.zip`;
    triggerBrowserDownload(zipName, zipBytes, "application/zip");
    return { written: Object.keys(entries).length, skipped };
  }

  const api = {
    buildWinisd,
    buildFfs,
    buildBulkEntries,
    downloadDriver,
    downloadDatabase,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof window !== "undefined") window.DriverExport = api;
})();
