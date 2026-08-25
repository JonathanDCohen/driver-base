// Driver-base SPA. Alpine.js component + SortableJS for the sort chips.
// Reorderable column headers use native HTML5 drag events — Alpine remains
// the only DOM mutator so `x-for` re-renders header + body cells in lockstep
// from the same array (no Sortable/x-for fight).
// State (filters + sorts) is mirrored to the URL for shareability.
// Column order + visibility and units preference persist in first-party cookies
// (`db_cols`, `db_units`).

const COLUMN_META = {
  manufacturer:              { label: "Manufacturer",       numeric: false, sortable: true  },
  model:                     { label: "Model",              numeric: false, sortable: true  },
  driver_kind:               { label: "Type",               numeric: false, sortable: false },
  nominal_size_mm:           { label: "Size",               numeric: true,  sortable: true  },
  impedance_nominal_ohm:     { label: "Impedance",          numeric: true,  sortable: true  },
  fs_hz:                     { label: "Fs",                 numeric: true,  sortable: true  },
  qts:                       { label: "Qts",                numeric: true,  sortable: true  },
  qes:                       { label: "Qes",                numeric: true,  sortable: true  },
  qms:                       { label: "Qms",                numeric: true,  sortable: true  },
  vas_liters:                { label: "Vas",                numeric: true,  sortable: true  },
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
  net_weight_kg:             { label: "Weight (kg)",        numeric: true,  sortable: true  },
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
  amt: "AMT",
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

function fmtNumber(v, decimals = 2) {
  if (v == null || Number.isNaN(v)) return null;
  if (Math.abs(v) >= 100) return v.toFixed(0);
  if (Math.abs(v) >= 10)  return v.toFixed(1);
  return v.toFixed(decimals);
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
    pickerOpen: false,
    sortPickerOpen: false,
    scrolled: false,       // right table has scrollLeft > 0 — drives shadow on fixed table
    hoverIdx: null,        // row index currently hovered in either table — drives shared highlight

    dragKey: null,         // column key currently being dragged
    dragOverKey: null,     // column key currently hovered as drop target
    dragSide: null,        // 'left' | 'right' — which half of the hovered th we're over

    async init() {
      const state = parseURLState();
      Object.assign(this.filters, state.filters);
      this.sorts = state.sorts;
      this.columns = reconcileColumns(readColumnsCookie());
      this.units = readUnitsCookie() || "metric";

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

      // SortableJS init AFTER data + first render.
      this.$nextTick(() => {
        this.installSortable();
      });
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
      return this.sortableFields.filter((f) => !used.has(f.key));
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
    // (Manufacturer, Model) are always on and don't appear here.
    get pickerColumns() {
      return this.columns.filter((c) => !IS_FIXED.has(c.key));
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

    toggleSortDir(i) {
      this.sorts[i].dir = this.sorts[i].dir === "asc" ? "desc" : "asc";
      this.updateUrl();
    },

    removeSort(i) {
      this.sorts.splice(i, 1);
      this.updateUrl();
    },

    installSortable() {
      const el = this.$refs.sortChips;
      if (!el || !window.Sortable) return;
      Sortable.create(el, {
        animation: 150,
        filter: "a, .close",
        preventOnFilter: false,
        onEnd: (evt) => {
          const from = evt.oldIndex;
          const to = evt.newIndex;
          if (from === to) return;
          const moved = this.sorts.splice(from, 1)[0];
          this.sorts.splice(to, 0, moved);
          this.updateUrl();
        },
      });
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
      if (key === "nominal_size_mm") return this.units === "imperial" ? "Size (in)" : "Size (mm)";
      if (key === "net_weight_kg")   return this.units === "imperial" ? "Weight (lb)" : "Weight (kg)";
      if (key === "vas_liters")      return this.units === "imperial" ? "Vas (ft³)" : "Vas (L)";
      return (COLUMN_META[key] || { label: key }).label;
    },

    fieldLabel(key) {
      return this.columnLabel(key);
    },

    formatCell(d, col) {
      const v = d[col.key];
      if (v == null || v === "") return '<span class="null">–</span>';
      if (col.key === "manufacturer") {
        const u = d.source_urls && d.source_urls[0];
        return u ? `<a href="${u}" target="_blank" rel="noopener">${v}</a>` : v;
      }
      if (col.key === "model") {
        const u = d.source_urls && d.source_urls[0];
        return u ? `<a href="${u}" target="_blank" rel="noopener">${v}</a>` : v;
      }
      if (col.key === "driver_kind") return d._kind_label || v;
      if (col.key === "nominal_size_mm") {
        return this.units === "imperial" ? `${(v / MM_PER_INCH).toFixed(1)}″` : `${Math.round(v)}`;
      }
      if (col.key === "net_weight_kg") {
        return this.units === "imperial" ? fmtNumber(v * LB_PER_KG) : fmtNumber(v);
      }
      if (col.key === "vas_liters") {
        return this.units === "imperial" ? fmtNumber(v * CUFT_PER_LITER) : fmtNumber(v);
      }
      if (col.key === "impedance_nominal_ohm") return `${v}&nbsp;Ω`;
      let base = typeof v === "number" ? fmtNumber(v) : String(v);
      // A derived spec (sensitivity or power computed from another slot + Z or
      // 2x-AES) is marked in spec_source; append a subtle dagger + tooltip.
      const src = d.spec_source && d.spec_source[col.key];
      if (src === "derived") {
        base += '<sup class="derived-mark" title="derived from another spec (2.83V↔1W via impedance, or program↔AES ×2)">†</sup>';
      }
      return base;
    },

    updateUrl() {
      writeURLState({ filters: this.filters, sorts: this.sorts });
    },
  };
}
