// Driver-base SPA. Alpine.js component + SortableJS for the sort chips.
// State (filters + sorts) is mirrored to the URL for shareability.

const SORTABLE_FIELDS = [
  { key: "manufacturer",              label: "Manufacturer",       numeric: false },
  { key: "model",                     label: "Model",              numeric: false },
  { key: "nominal_size_mm",           label: "Size",               numeric: true  },
  { key: "impedance_nominal_ohm",     label: "Impedance",          numeric: true  },
  { key: "fs_hz",                     label: "Fs",                 numeric: true  },
  { key: "qts",                       label: "Qts",                numeric: true  },
  { key: "qes",                       label: "Qes",                numeric: true  },
  { key: "qms",                       label: "Qms",                numeric: true  },
  { key: "vas_liters",                label: "Vas (L)",            numeric: true  },
  { key: "sd_cm2",                    label: "Sd (cm²)",           numeric: true  },
  { key: "xmax_mm",                   label: "Xmax",               numeric: true  },
  { key: "mms_g",                     label: "Mms",                numeric: true  },
  { key: "bl_tm",                     label: "Bl",                 numeric: true  },
  { key: "re_ohm",                    label: "Re",                 numeric: true  },
  { key: "le_mh",                     label: "Le",                 numeric: true  },
  { key: "sensitivity_db_1w_1m",      label: "SPL 1W/1m",          numeric: true  },
  { key: "sensitivity_db_2_83v_1m",   label: "SPL 2.83V/1m",       numeric: true  },
  { key: "power_aes_watts",           label: "AES (W)",            numeric: true  },
  { key: "power_long_term_watts",     label: "Continuous (W)",     numeric: true  },
  { key: "freq_low_hz",               label: "Freq low",           numeric: true  },
  { key: "freq_high_hz",              label: "Freq high",          numeric: true  },
  { key: "net_weight_kg",             label: "Weight (kg)",        numeric: true  },
];

const VISIBLE_COLUMNS = [
  "manufacturer",
  "model",
  "driver_kind",
  "nominal_size_mm",
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

const DRIVER_KIND_LABEL = {
  lf_woofer: "LF woofer",
  hf_compression: "HF compression",
  tweeter: "Tweeter",
  coax: "Coaxial",
  horn: "Horn",
  passive: "Passive",
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

function app() {
  return {
    drivers: [],
    schemaVersion: "?",
    generatedAt: "?",
    statusLabel: "loading…",

    filters: { q: "", mfg: [], kind: [], impedance: [], size_in: [] },
    sorts: [],
    pageSize: 500,

    sortableFields: SORTABLE_FIELDS,
    visibleColumns: VISIBLE_COLUMNS.map(
      (k) => SORTABLE_FIELDS.find((f) => f.key === k) ||
             { key: k, label: k, numeric: false }
    ),

    async init() {
      const state = parseURLState();
      Object.assign(this.filters, state.filters);
      this.sorts = state.sorts;

      try {
        const resp = await fetch("drivers.json", { cache: "no-store" });
        if (!resp.ok) throw new Error(`fetch drivers.json → ${resp.status}`);
        const data = await resp.json();
        this.schemaVersion = data.schema_version || "?";
        this.generatedAt = data.generated_at || "?";
        this.drivers = (data.drivers || []).map((d) => ({
          ...d,
          _size_bucket: sizeBucketOf(d.nominal_size_mm),
          _kind_label: DRIVER_KIND_LABEL[d.driver_kind] || d.driver_kind,
        }));
        this.statusLabel = `${this.drivers.length} drivers · updated ${this.generatedAt.slice(0, 10)}`;
      } catch (e) {
        console.error(e);
        this.statusLabel = "failed to load drivers.json";
      }

      // Materialize + SortableJS init AFTER data + first render.
      this.$nextTick(() => {
        try {
          M.FormSelect.init(document.querySelectorAll("select"));
        } catch (_) {}
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

    onAddSort(ev) {
      const field = ev.target.value;
      if (!field) return;
      if (!this.sorts.some((s) => s.field === field)) {
        this.sorts.push({ field, dir: "asc" });
        this.updateUrl();
      }
      ev.target.value = "";
      this.$nextTick(() => { try { M.FormSelect.init(ev.target); } catch (_) {} });
    },

    toggleSortDir(i) {
      this.sorts[i].dir = this.sorts[i].dir === "asc" ? "desc" : "asc";
      this.updateUrl();
    },

    removeSort(i) {
      this.sorts.splice(i, 1);
      this.updateUrl();
      this.$nextTick(() => {
        try { M.FormSelect.init(document.querySelectorAll("select")); } catch (_) {}
      });
    },

    installSortable() {
      const el = this.$refs.sortChips;
      if (!el || !window.Sortable) return;
      Sortable.create(el, {
        handle: ".drag-handle",
        animation: 150,
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

    fieldLabel(key) {
      return (this.sortableFields.find((f) => f.key === key) || { label: key }).label;
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
        const inches = v / 25.4;
        return `${Math.round(v)}<span class="null">·${inches.toFixed(1)}″</span>`;
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
