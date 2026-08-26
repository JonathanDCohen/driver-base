// Driver-base SPA. Alpine.js component. Reorderable column headers AND sort
// chips use native HTML5 drag events — Alpine remains the only DOM mutator
// so `x-for` re-renders in lockstep from the same array (no SortableJS/x-for
// fight, which was silently reverting sort-chip drops).
// State (filters + sorts) is mirrored to the URL for shareability.
// Column order + visibility and units preference persist in first-party cookies
// (`db_cols`, `db_units`).

const COLUMN_META = {
  manufacturer:              { label: "Manufacturer",       numeric: false, sortable: true  },
  model:                     { label: "Model",              numeric: false, sortable: true  },
  driver_kind:               { label: "Type",               numeric: false, sortable: true  },
  nominal_size_mm:           { label: "Size",               numeric: true,  sortable: true  },
  impedance_nominal_ohm:     { label: "Impedance",          numeric: true,  sortable: true  },
  fs_hz:                     { label: "Fs",                 numeric: true,  sortable: true  },
  qts:                       { label: "Qts",                numeric: true,  sortable: true  },
  qes:                       { label: "Qes",                numeric: true,  sortable: true  },
  qms:                       { label: "Qms",                numeric: true,  sortable: true  },
  vas_liters:                { label: "Vas",                numeric: true,  sortable: true  },  // unit appended by columnLabel()
  sd_cm2:                    { label: "Sd (cm²)",           numeric: true,  sortable: true  },
  xmax_mm:                   { label: "Xmax",               numeric: true,  sortable: true  },
  mms_g:                     { label: "Mms",                numeric: true,  sortable: true  },
  bl_tm:                     { label: "Bl",                 numeric: true,  sortable: true  },
  re_ohm:                    { label: "Re",                 numeric: true,  sortable: true  },
  le_mh:                     { label: "Le",                 numeric: true,  sortable: true  },
  sensitivity_db_1w_1m:      { label: "SPL 1W/1m",          numeric: true,  sortable: true  },
  sensitivity_db_2_83v_1m:   { label: "SPL 2.83V/1m",       numeric: true,  sortable: true  },
  power_aes_watts:           { label: "AES (W)",            numeric: true,  sortable: true  },
  power_long_term_watts:     { label: "Continuous (W)",     numeric: true,  sortable: true  },
  freq_low_hz:               { label: "Freq low",           numeric: true,  sortable: true  },
  freq_high_hz:              { label: "Freq high",          numeric: true,  sortable: true  },
  net_weight_kg:             { label: "Weight",             numeric: true,  sortable: true  },  // unit appended by columnLabel()
  // Compression-driver fields (also populate for coax records).
  throat_diameter_mm:        { label: "Throat",             numeric: true,  sortable: true  },
  diaphragm_material:        { label: "Diaphragm material", numeric: false, sortable: true  },
  diaphragm_shape:           { label: "Diaphragm shape",    numeric: false, sortable: true  },
  recommended_crossover_hz:  { label: "Rec. crossover",     numeric: true,  sortable: true  },
  winding_material:          { label: "VC winding material", numeric: false, sortable: true },
  former_material:           { label: "VC former material",  numeric: false, sortable: true },
  surround_material:         { label: "Surround material",   numeric: false, sortable: true },
  phase_plug_design:         { label: "Phase plug design",   numeric: false, sortable: true },
  flux_density_t:            { label: "Flux density (T)",    numeric: true,  sortable: true },
  xvar_mm:                   { label: "Xvar",                numeric: true,  sortable: true },
  recommended_enclosure_volume_liters: { label: "Rec. enclosure vol", numeric: true, sortable: true },
  // Coax HF-section fields — populated only for coaxial drivers. The generic
  // fields above hold the coax LF-section values; these carry the HF section.
  // Hidden by default (relevant to a small subset of records).
  coax_hf_impedance_nominal_ohm: { label: "(Coax) HF Impedance", numeric: true,  sortable: true  },
  coax_hf_impedance_min_ohm:     { label: "(Coax) HF Imp min",   numeric: true,  sortable: true  },
  coax_hf_power_aes_watts:       { label: "(Coax) HF AES (W)",        numeric: true,  sortable: true  },
  coax_hf_power_long_term_watts: { label: "(Coax) HF Continuous (W)", numeric: true,  sortable: true  },
  coax_hf_power_peak_watts:      { label: "(Coax) HF Peak (W)",       numeric: true,  sortable: true  },
  coax_hf_sensitivity_db_1w_1m:  { label: "(Coax) HF SPL 1W/1m", numeric: true,  sortable: true  },
  coax_hf_freq_low_hz:           { label: "(Coax) HF Freq low",  numeric: true,  sortable: true  },
  coax_hf_freq_high_hz:          { label: "(Coax) HF Freq high", numeric: true,  sortable: true  },
  coax_hf_voice_coil_diameter_mm:{ label: "(Coax) HF VC",         numeric: true,  sortable: true  },
  coax_hf_re_ohm:                { label: "(Coax) HF Re",        numeric: true,  sortable: true  },
};

const SORTABLE_FIELDS = Object.entries(COLUMN_META)
  .filter(([, m]) => m.sortable)
  .map(([key, m]) => ({ key, label: m.label, numeric: m.numeric }));

// Manufacturer + Model are always the first two columns, always visible, and
// live in a separate table so they can't be dragged or dropped on. Everything
// else is user-orderable via native drag-and-drop and hideable via the Columns
// picker.
const FIXED_KEYS = ["manufacturer", "model"];
const IS_FIXED = new Set(FIXED_KEYS);

// Default column order (visible) when no cookie is set.
const DEFAULT_COLUMN_ORDER = [
  ...FIXED_KEYS,
  "driver_kind",
  "nominal_size_mm",
  "surround_material",
  "net_weight_kg",
  "impedance_nominal_ohm",
  "fs_hz",
  "qts",
  "vas_liters",
  "xmax_mm",
  "sensitivity_db_1w_1m",
  "power_aes_watts",
  "power_long_term_watts",
  "bl_tm",
  "freq_low_hz",
  "freq_high_hz",
];

const COLUMN_COOKIE = "db_cols";
const UNITS_COOKIE = "db_units";
const THEME_COOKIE = "db_theme";
const COOKIE_MAX_AGE = 60 * 60 * 24 * 365;

const MM_PER_INCH = 25.4;
const LB_PER_KG = 2.2046226;
const CUFT_PER_LITER = 0.0353146667;

const DRIVER_KIND_LABEL = {
  lf_woofer: "LF woofer",
  hf_compression: "HF compression",
  tweeter: "Tweeter",
  coax: "Coaxial",
  horn: "Horn",
  passive: "Passive radiator",
  shaker: "Shaker",
  fullrange: "Fullrange",
  guitar_bass: "Guitar/bass",
};

const SIZE_BUCKETS_MM = [
  { label: '4"',  min:  90, max: 110 },
  { label: '5"',  min: 115, max: 140 },
  { label: '6.5"',min: 155, max: 180 },
  { label: '8"',  min: 195, max: 220 },
  { label: '10"', min: 245, max: 270 },
  { label: '12"', min: 295, max: 320 },
  { label: '15"', min: 375, max: 400 },
  { label: '18"', min: 445, max: 470 },
  { label: '21"', min: 520, max: 545 },
];

// Sort picker/menu entries alphabetically by label, with kind-specific fields
// (coax_hf_*) grouped after the generic ones. Keeps the dropdowns scannable
// while segregating the sub-catalog that only applies to a small subset of
// records. `keyOf` and `labelOf` are property accessors so this works for both
// pickerColumns entries ({key, visible}) and sortableFields entries ({key, label}).
function sortPickerEntries(entries, keyOf, labelOf) {
  const bucket = (e) => (keyOf(e).startsWith("coax_hf_") ? 1 : 0);
  return entries.slice().sort((a, b) => {
    const db = bucket(a) - bucket(b);
    if (db !== 0) return db;
    return labelOf(a).localeCompare(labelOf(b));
  });
}

function fmtNumber(v, decimals = 2) {
  if (v == null || Number.isNaN(v)) return null;
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10)  return v.toFixed(1);
  return v.toFixed(decimals);
}

// Escape a string for embedding in an HTML attribute value ("..."). Cell
// content is injected via x-html, so any user-supplied note text has to be
// safe against attribute-context injection.
function escapeAttr(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

// Short explanation for the spec-source dagger. Overrides carry a specific
// note from data/overrides.yaml (surfaced as driver.override_notes[key]);
// derived/inferred fall back to a generic phrase.
const GENERIC_SPEC_NOTE = {
  derived: "Derived from another spec (SPL 2.83 V ↔ 1 W via impedance, or program ↔ AES ×2).",
  inferred: "Inferred from context — e.g. driver kind from the category slug.",
  override: "Manually corrected; upstream spec was wrong.",
};
function specSourceNote(d, key) {
  const src = d.spec_source && d.spec_source[key];
  if (!GENERIC_SPEC_NOTE[src]) return null;
  if (src === "override" && d.override_notes && d.override_notes[key]) {
    return d.override_notes[key];
  }
  return GENERIC_SPEC_NOTE[src];
}

function sizeBucketOf(mm) {
  if (mm == null) return null;
  for (const b of SIZE_BUCKETS_MM) if (mm >= b.min && mm <= b.max) return b.label;
  return null;
}

function cmpWithDir(a, b, dir) {
  if (a == null && b == null) return 0;
  if (a == null) return 1;          // nulls last, regardless of direction
  if (b == null) return -1;
  if (typeof a === "string" && typeof b === "string") {
    const cmp = a.localeCompare(b, undefined, { numeric: true });
    return dir === "asc" ? cmp : -cmp;
  }
  const cmp = a < b ? -1 : a > b ? 1 : 0;
  return dir === "asc" ? cmp : -cmp;
}

function multiSort(items, sorts) {
  if (!sorts.length) return items;
  const arr = items.slice();
  arr.sort((x, y) => {
    for (const { field, dir } of sorts) {
      const c = cmpWithDir(x[field], y[field], dir);
      if (c !== 0) return c;
    }
    return 0;
  });
  return arr;
}

function parseURLState() {
  const p = new URLSearchParams(window.location.search);
  const arr = (k) => (p.get(k) ? p.get(k).split(",").filter(Boolean) : []);
  const num = (v) => (isNaN(+v) ? v : +v);
  return {
    filters: {
      q: p.get("q") || "",
      mfg: arr("mfg"),
      kind: arr("kind"),
      impedance: arr("imp").map(num),
      size_in: arr("size"),
    },
    sorts: arr("sort")
      .map((s) => s.split(":"))
      .filter(([f, d]) => f && (d === "asc" || d === "desc"))
      .map(([field, dir]) => ({ field, dir })),
  };
}

function writeURLState(state) {
  const p = new URLSearchParams();
  if (state.filters.q) p.set("q", state.filters.q);
  if (state.filters.mfg.length) p.set("mfg", state.filters.mfg.join(","));
  if (state.filters.kind.length) p.set("kind", state.filters.kind.join(","));
  if (state.filters.impedance.length) p.set("imp", state.filters.impedance.join(","));
  if (state.filters.size_in.length) p.set("size", state.filters.size_in.join(","));
  if (state.sorts.length)
    p.set("sort", state.sorts.map((s) => `${s.field}:${s.dir}`).join(","));
  const qs = p.toString();
  const url = qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
  window.history.replaceState(null, "", url);
}

// Cookie format: comma-separated tokens in display order for the non-fixed
// columns only. Each token is `key` (visible) or `key:h` (hidden). Fixed
// columns are always first and always visible, so they're not stored.
function readColumnsCookie() {
  const m = document.cookie.match(/(?:^|; )db_cols=([^;]*)/);
  if (!m) return null;
  return m[1].split(",").filter(Boolean).map((tok) => {
    const [key, flag] = tok.split(":");
    return { key, visible: flag !== "h" };
  });
}

function writeColumnsCookie(columns) {
  const val = columns
    .filter((c) => !IS_FIXED.has(c.key))
    .map((c) => (c.visible ? c.key : `${c.key}:h`))
    .join(",");
  document.cookie = `${COLUMN_COOKIE}=${val}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

function readUnitsCookie() {
  const m = document.cookie.match(/(?:^|; )db_units=([^;]*)/);
  if (!m) return null;
  return m[1] === "imperial" ? "imperial" : m[1] === "metric" ? "metric" : null;
}

function writeUnitsCookie(units) {
  document.cookie = `${UNITS_COOKIE}=${units}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

function writeThemeCookie(theme) {
  document.cookie = `${THEME_COOKIE}=${theme}; path=/; max-age=${COOKIE_MAX_AGE}; SameSite=Lax`;
}

function defaultColumns() {
  const inDefault = new Set(DEFAULT_COLUMN_ORDER);
  const rest = Object.keys(COLUMN_META).filter((k) => !inDefault.has(k));
  return [
    ...DEFAULT_COLUMN_ORDER.map((k) => ({ key: k, visible: true })),
    ...rest.map((k) => ({ key: k, visible: false })),
  ];
}

// Reconcile a stored cookie against the current catalog: prepend fixed keys,
// drop unknown/duplicate keys, then append any new catalog keys as hidden so
// schema additions surface in the picker without hijacking a returning user's
// layout.
function reconcileColumns(stored) {
  if (!stored) return defaultColumns();
  const known = new Set(Object.keys(COLUMN_META));
  const seen = new Set();
  const out = FIXED_KEYS.map((k) => {
    seen.add(k);
    return { key: k, visible: true };
  });
  for (const c of stored) {
    if (!known.has(c.key) || seen.has(c.key) || IS_FIXED.has(c.key)) continue;
    seen.add(c.key);
    out.push({ key: c.key, visible: !!c.visible });
  }
  for (const k of Object.keys(COLUMN_META)) {
    if (!seen.has(k)) out.push({ key: k, visible: false });
  }
  return out;
}

function app() {
  return {
    drivers: [],
    generatedAt: "?",

    filters: { q: "", mfg: [], kind: [], impedance: [], size_in: [] },
    sorts: [],
    pageSize: 500,

    sortableFields: SORTABLE_FIELDS,
    columns: [],           // ordered { key, visible } — includes fixed keys at [0..1]
    units: "metric",       // "metric" | "imperial" — affects Size, Weight, Vas display + labels
    theme: "light",        // "light" | "dark" — pre-hydration script in index.html sets the
                           // actual data-theme attribute before styles load; init() reads it
                           // back so Alpine's toggle icon starts in sync.
    pickerOpen: false,
    sortPickerOpen: false,
    scrolled: false,       // right table has scrollLeft > 0 — drives shadow on fixed table
    hoverIdx: null,        // row index currently hovered in either table — drives shared highlight

    dragKey: null,         // column key currently being dragged
    dragOverKey: null,     // column key currently hovered as drop target
    dragSide: null,        // 'left' | 'right' — which half of the hovered th we're over

    sortDragField: null,   // sort chip field currently being dragged
    sortDragOverField: null,
    sortDragSide: null,

    // Spec-source popover, opened by clicking a dagger in a cell.
    // `top`/`left` are viewport-relative px; the popover uses position:fixed.
    specPopover: { open: false, text: "", top: 0, left: 0 },

    async init() {
      const state = parseURLState();
      Object.assign(this.filters, state.filters);
      this.sorts = state.sorts;
      this.columns = reconcileColumns(readColumnsCookie());
      this.units = readUnitsCookie() || "metric";
      this.theme = document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";

      try {
        const resp = await fetch("drivers.json", { cache: "no-store" });
        if (!resp.ok) throw new Error(`fetch drivers.json → ${resp.status}`);
        const data = await resp.json();
        this.generatedAt = data.generated_at || "?";
        this.drivers = (data.drivers || []).map((d) => ({
          ...d,
          _size_bucket: sizeBucketOf(d.nominal_size_mm),
          _kind_label: DRIVER_KIND_LABEL[d.driver_kind] || d.driver_kind,
        }));
      } catch (e) {
        console.error(e);
      }
    },

    // --- computed properties ---
    get filterGroups() {
      const counts = (getter) => {
        const map = new Map();
        for (const d of this.drivers) {
          const v = getter(d);
          if (v == null) continue;
          const arr = Array.isArray(v) ? v : [v];
          for (const x of arr) map.set(x, (map.get(x) || 0) + 1);
        }
        return map;
      };
      const groups = [];
      const mCounts = counts((d) => d.manufacturer);
      groups.push({
        key: "mfg",
        label: "Manufacturer",
        options: [...mCounts.entries()]
          .sort()
          .map(([value, count]) => ({ value, label: value, count })),
      });
      const kCounts = counts((d) => d.driver_kind);
      groups.push({
        key: "kind",
        label: "Type",
        options: [...kCounts.entries()]
          .sort()
          .map(([value, count]) => ({ value, label: DRIVER_KIND_LABEL[value] || value, count })),
      });
      const impCounts = counts((d) => d.impedance_nominal_ohm);
      groups.push({
        key: "impedance",
        label: "Impedance",
        options: [...impCounts.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([value, count]) => ({ value, label: `${value} Ω`, count })),
      });
      const sCounts = counts((d) => d._size_bucket);
      groups.push({
        key: "size_in",
        label: "Size",
        options: SIZE_BUCKETS_MM
          .map((b) => ({ value: b.label, label: b.label, count: sCounts.get(b.label) || 0 }))
          .filter((o) => o.count > 0),
      });
      return groups;
    },

    get filtered() {
      const f = this.filters;
      const q = (f.q || "").trim().toLowerCase();
      return this.drivers.filter((d) => {
        if (f.mfg.length && !f.mfg.includes(d.manufacturer)) return false;
        if (f.kind.length && !f.kind.includes(d.driver_kind)) return false;
        if (f.impedance.length && !f.impedance.includes(d.impedance_nominal_ohm)) return false;
        if (f.size_in.length && !f.size_in.includes(d._size_bucket)) return false;
        if (q && !(`${d.manufacturer} ${d.model}`.toLowerCase().includes(q))) return false;
        return true;
      });
    },

    get sortedFiltered() {
      return multiSort(this.filtered, this.sorts);
    },

    get visibleRows() {
      return this.sortedFiltered.slice(0, this.pageSize);
    },

    get paginated() {
      return this.sortedFiltered.length > this.pageSize;
    },

    get hasFilters() {
      return (
        this.filters.q ||
        this.filters.mfg.length ||
        this.filters.kind.length ||
        this.filters.impedance.length ||
        this.filters.size_in.length
      );
    },

    get unusedSortableFields() {
      const used = new Set(this.sorts.map((s) => s.field));
      return sortPickerEntries(
        this.sortableFields.filter((f) => !used.has(f.key)),
        (f) => f.key,
        (f) => f.label,
      );
    },

    get fixedColumns() {
      return FIXED_KEYS.map((k) => ({ key: k, ...COLUMN_META[k] }));
    },

    get reorderableColumns() {
      return this.columns
        .filter((c) => c.visible && !IS_FIXED.has(c.key))
        .map((c) => ({ key: c.key, ...COLUMN_META[c.key] }));
    },

    // Non-fixed rows shown in the picker checkbox list. Fixed columns
    // (Manufacturer, Model) are always on and don't appear here. Sorted
    // alphabetically for readability — the actual column display order
    // lives in `this.columns` (drag-reorderable) and is unaffected.
    get pickerColumns() {
      return sortPickerEntries(
        this.columns.filter((c) => !IS_FIXED.has(c.key)),
        (c) => c.key,
        (c) => COLUMN_META[c.key]?.label ?? c.key,
      );
    },

    // --- actions ---
    onFilterChange() { this.updateUrl(); },

    toggleFilter(group, value) {
      const arr = this.filters[group];
      const i = arr.indexOf(value);
      if (i >= 0) arr.splice(i, 1);
      else arr.push(value);
      this.updateUrl();
    },

    clearFilters() {
      this.filters = { q: "", mfg: [], kind: [], impedance: [], size_in: [] };
      this.updateUrl();
    },

    addSort(field) {
      if (!field) return;
      if (this.sorts.some((s) => s.field === field)) return;
      this.sorts.push({ field, dir: "asc" });
      this.updateUrl();
    },

    setUnits(u) {
      if (u !== "metric" && u !== "imperial") return;
      this.units = u;
      writeUnitsCookie(u);
    },

    toggleTheme() {
      this.theme = this.theme === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", this.theme);
      writeThemeCookie(this.theme);
    },

    toggleSortDir(i) {
      this.sorts[i].dir = this.sorts[i].dir === "asc" ? "desc" : "asc";
      this.updateUrl();
    },

    removeSort(i) {
      this.sorts.splice(i, 1);
      this.updateUrl();
    },

    // Native HTML5 drag handlers for sort chips — same shape as the column
    // header reorder, so Alpine stays the sole DOM mutator (no Sortable/x-for
    // fight, which was silently reverting drops).
    onSortDragStart(ev, field) {
      this.sortDragField = field;
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", field);
    },
    onSortDragOver(ev, field) {
      if (!this.sortDragField || field === this.sortDragField) return;
      ev.dataTransfer.dropEffect = "move";
      const rect = ev.currentTarget.getBoundingClientRect();
      this.sortDragSide = ev.clientX < rect.left + rect.width / 2 ? "left" : "right";
      this.sortDragOverField = field;
    },
    onSortDragLeave(field) {
      if (this.sortDragOverField === field) {
        this.sortDragOverField = null;
        this.sortDragSide = null;
      }
    },
    onSortDrop(targetField) {
      const src = this.sortDragField;
      if (!src || src === targetField) { this.onSortDragEnd(); return; }
      const srcIdx = this.sorts.findIndex((s) => s.field === src);
      const tgtIdx = this.sorts.findIndex((s) => s.field === targetField);
      if (srcIdx < 0 || tgtIdx < 0) { this.onSortDragEnd(); return; }
      let newPos = tgtIdx + (this.sortDragSide === "right" ? 1 : 0);
      if (srcIdx < newPos) newPos -= 1;
      const [moved] = this.sorts.splice(srcIdx, 1);
      this.sorts.splice(newPos, 0, moved);
      this.updateUrl();
      this.onSortDragEnd();
    },
    onSortDragEnd() {
      this.sortDragField = null;
      this.sortDragOverField = null;
      this.sortDragSide = null;
    },
    sortDragClass(field) {
      const parts = [];
      if (this.sortDragField === field) parts.push("dragging");
      if (this.sortDragOverField === field && this.sortDragSide) parts.push(`drop-${this.sortDragSide}`);
      return parts.join(" ");
    },

    // Native HTML5 drag handlers for column headers. Alpine is the sole DOM
    // mutator — drop mutates this.columns, and x-for re-renders both the
    // header <th>s and every body <td> from the same array on the same tick.
    onColDragStart(ev, key) {
      this.dragKey = key;
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", key);
    },

    onColDragOver(ev, key) {
      if (!this.dragKey || key === this.dragKey) return;
      ev.dataTransfer.dropEffect = "move";
      const rect = ev.currentTarget.getBoundingClientRect();
      this.dragSide = ev.clientX < rect.left + rect.width / 2 ? "left" : "right";
      this.dragOverKey = key;
    },

    onColDragLeave(key) {
      if (this.dragOverKey === key) {
        this.dragOverKey = null;
        this.dragSide = null;
      }
    },

    onColDrop(targetKey) {
      const src = this.dragKey;
      if (!src || src === targetKey) { this.onColDragEnd(); return; }
      const visible = this.columns.filter((c) => c.visible && !IS_FIXED.has(c.key));
      const targetVisIdx = visible.findIndex((c) => c.key === targetKey);
      const srcVisIdx = visible.findIndex((c) => c.key === src);
      if (targetVisIdx < 0 || srcVisIdx < 0) { this.onColDragEnd(); return; }
      // Insertion point in the visible sequence, before/after the target.
      let newPos = targetVisIdx + (this.dragSide === "right" ? 1 : 0);
      // Removing src first shifts positions past it left by one.
      if (srcVisIdx < newPos) newPos -= 1;
      this.reorder(src, newPos);
      this.onColDragEnd();
    },

    onColDragEnd() {
      this.dragKey = null;
      this.dragOverKey = null;
      this.dragSide = null;
    },

    colDragClass(key) {
      const parts = [];
      if (this.dragKey === key) parts.push("dragging");
      if (this.dragOverKey === key && this.dragSide) parts.push(`drop-${this.dragSide}`);
      return parts.join(" ");
    },

    // Splice `key` to visible-position `newPos` within this.columns (which
    // also carries hidden entries and the two fixed keys). Hidden columns
    // stay where they are relative to the visible reorder; if the user
    // unhides one later, it reappears at that parked slot.
    reorder(key, newPos) {
      const from = this.columns.findIndex((c) => c.key === key);
      if (from < 0) return;
      const [moved] = this.columns.splice(from, 1);
      let visCount = 0;
      let insertAt = this.columns.length;
      for (let i = 0; i < this.columns.length; i++) {
        const c = this.columns[i];
        if (IS_FIXED.has(c.key) || !c.visible) continue;
        if (visCount === newPos) { insertAt = i; break; }
        visCount++;
      }
      this.columns.splice(insertAt, 0, moved);
      writeColumnsCookie(this.columns);
    },

    toggleColumn(key) {
      const c = this.columns.find((x) => x.key === key);
      if (!c) return;
      c.visible = !c.visible;
      writeColumnsCookie(this.columns);
    },

    resetColumns() {
      this.columns = defaultColumns();
      writeColumnsCookie(this.columns);
    },

    columnLabel(key) {
      const meta = COLUMN_META[key] || { label: key };
      // Diameter-family fields (Size, Throat, coax HF VC, etc.) toggle unit in
      // the header rather than the cell.
      if (key.endsWith("_diameter_mm") || key === "nominal_size_mm") {
        return `${meta.label} (${this.units === "imperial" ? "in" : "mm"})`;
      }
      if (key === "net_weight_kg") return `${meta.label} (${this.units === "imperial" ? "lb" : "kg"})`;
      if (key === "vas_liters")    return `${meta.label} (${this.units === "imperial" ? "ft³" : "L"})`;
      return meta.label;
    },

    fieldLabel(key) {
      return this.columnLabel(key);
    },

    formatCell(d, col) {
      const v = d[col.key];
      if (v == null || v === "") return '<span class="null">–</span>';
      // Manufacturer + model link to the source page and never carry a sigil.
      if (col.key === "manufacturer" || col.key === "model") {
        const u = d.source_urls && d.source_urls[0];
        return u ? `<a href="${u}" target="_blank" rel="noopener">${v}</a>` : v;
      }
      // All other columns share a common tail: format the value, then append
      // the spec-source dagger (if any) uniformly. Prior versions returned
      // early for size/diameter/weight/vas/ohm, which meant those columns
      // never got a sigil even when spec_source flagged the value.
      let base;
      if (col.key === "driver_kind") {
        base = d._kind_label || String(v);
      } else if (col.key === "nominal_size_mm") {
        base = this.units === "imperial" ? (v / MM_PER_INCH).toFixed(1) : `${Math.round(v)}`;
      } else if (col.key.endsWith("_diameter_mm")) {
        base = this.units === "imperial" ? (v / MM_PER_INCH).toFixed(2) : `${Math.round(v)}`;
      } else if (col.key === "net_weight_kg") {
        base = this.units === "imperial" ? fmtNumber(v * LB_PER_KG) : fmtNumber(v);
      } else if (col.key === "vas_liters") {
        base = this.units === "imperial" ? fmtNumber(v * CUFT_PER_LITER) : fmtNumber(v);
      } else if (col.key.endsWith("_ohm")) {
        base = `${v}&nbsp;Ω`;
      } else {
        base = typeof v === "number" ? fmtNumber(v) : String(v);
      }
      const note = specSourceNote(d, col.key);
      if (note) {
        // Rendered as a real <button> so keyboard focus + click both work,
        // and Enter/Space activate it. Popover is opened by a delegated
        // click handler on the table body (see openSpecPopover).
        base += ` <button type="button" class="derived-mark" data-note="${escapeAttr(note)}" aria-label="spec-source explanation">†</button>`;
      }
      return base;
    },

    // Delegated click handler bound on the table body. When a dagger button
    // is clicked, position the popover above it and show the note.
    openSpecPopover(event) {
      const btn = event.target.closest(".derived-mark");
      if (!btn) return;
      event.stopPropagation();
      const note = btn.getAttribute("data-note") || "";
      const rect = btn.getBoundingClientRect();
      // Position: above the button, horizontally centered. Popover is
      // position:fixed so viewport coords are correct without scroll math.
      this.specPopover = {
        open: true,
        text: note,
        top: Math.round(rect.top),
        left: Math.round(rect.left + rect.width / 2),
      };
    },
    closeSpecPopover() { this.specPopover.open = false; },

    updateUrl() {
      writeURLState({ filters: this.filters, sorts: this.sorts });
    },
  };
}
