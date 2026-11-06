"""SB Audience (sbaudience.com) scraper.

SB Audience is SB Acoustics' pro-audio sister brand, on a separate Concrete5
site with nothing in common with sbacoustics.com's WooCommerce markup.

Enumeration: every page's superfish nav lists every product as
`/index.php/products/{category}/{slug}/` (64 products, 2026-11-06). The
site's `sitemap.xml` is stale (2014 sbacoustics.com URLs) — don't use it.
Category → DriverKind at enumerate time; `horns` are skipped there (the
pipeline drops HORN anyway, so fetching them is wasted work).

Extraction is two-phase via the orchestrator's followup round:
  1. The product HTML page carries NO spec text — only a spec JPG and a
     `Click to download Datasheet` link to `/index.php/download_file/-/view/{id}/`.
     parse_artifact emits a followup for that PDF, carrying the model (H1
     tail) and the product-page URL in SeedContext.
  2. The datasheet is a one-page text PDF with side-by-side tables
     (`Dimensions & Weight` | `Specs` | `Thiele Small Parameters`;
     compression drivers omit the T/S block; coax Specs has `LF Unit` /
     `HF Unit` value sub-columns). Four sheets render the column headers as
     images, so cells are anchored on the row LABELS, not the headers.

PDF text quirks: the PDFs embed literal space glyphs mid-token
(`0.23 m m/N`, `1 2.1 Tm`, `B I`). We drop whitespace glyphs and re-split
words purely by geometry (loose char boxes; gap > 1pt = word break), which
reproduces the rendered text exactly. Rows are grouped by glyph baseline.

Semantics (from the sheets' own footnotes):
  - `Sensitivity (1W/1m)` vs `(2.83V/1m)` — slotted by label.
  - `Maximum Power Handling` — "defined as 3dB greater than nominal power",
    i.e. 2× AES → `power_program_watts` (not peak).
  - `Xmax` — `((winding - gap)/2) + gap/3`, one-way → `xmax_mm` as-is.
  - `Xdamage` — "Maximum excursion (p-p) before permanent damage" →
    `xmech_mm` (p-p by convention). Ratio to Xmax is 2.2–4.7 across the
    catalog, so the consistency gate's p-p assumption holds.
  - Midrange (subtitle says `Midrange`) → FULLRANGE, per repo convention.
  - `nominal_size_mm` from the subtitle (`15” - Midwoofer - ...`); for
    compression drivers that's the throat size, matching other scrapers.
"""

from __future__ import annotations

import ctypes
import dataclasses
import re
from typing import Any, Callable, Optional
from urllib.parse import urljoin

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from bs4 import BeautifulSoup

from driver_base.interface import (
    DriverKind,
    EnumerateResult,
    ParseResult,
    RawArtifact,
    Scraper,
    SeedContext,
    SeedRef,
)
from driver_base.magnets import normalize_magnet_type
from driver_base.model import DriverFragment, SpecSource
from driver_base.scrapers import register
from driver_base.units import (
    parse_bl_tm,
    parse_compliance_mm_per_n,
    parse_float,
    parse_frequency,
    parse_impedance,
    parse_le_mh,
    parse_length_mm,
    parse_liters,
    parse_mass_g,
    parse_percent,
    parse_power,
    parse_range,
    parse_sd_cm2,
)

_BASE = "https://www.sbaudience.com"
_PRODUCTS_URL = f"{_BASE}/index.php/products/"

_PRODUCT_HREF_RE = re.compile(
    r'href="(?:https?://www\.sbaudience\.com)?'
    r'(/index\.php/products/([a-z0-9-]+)/[a-z0-9-]+/)"'
)

# Unlisted categories are skipped rather than guessed; `horns` deliberately.
_CATEGORY_TO_KIND: dict[str, DriverKind] = {
    "woofers": DriverKind.LF_WOOFER,
    "subwoofers": DriverKind.LF_WOOFER,
    "open-baffle-drivers": DriverKind.LF_WOOFER,
    "compression-drivers": DriverKind.HF_COMPRESSION,
    "coaxials": DriverKind.COAX,
}

# PDF geometry, in points.
_WORD_GAP_PT = 1.0  # glyphs closer than this belong to one word
_CHUNK_GAP_PT = 6.0  # words closer than this belong to one cell
_ROW_TOL_PT = 4.0  # baselines within this share a table row
_ADOPT_MAX_PT = 8.0  # how far off its label's baseline a value may sit

_FOOTNOTE_RE = re.compile(r"\(\d\)")
_LEADING_FOOTNOTES_RE = re.compile(r"^(?:\s*\(\d\))+")
_MODEL_RE = re.compile(r"^[A-Z][A-Z0-9-]{3,}$")
# Subtitle: `15” - Midwoofer- 700W - 100dB`, `1.4” - 200W - 109dB - ...`
_SUBTITLE_SIZE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[”″\"]")


def _weight_kg(s: Optional[str]) -> Optional[float]:
    g = parse_mass_g(s)
    return g / 1000.0 if g is not None else None


def _text(s: Optional[str]) -> Optional[str]:
    """String fields: `-` and `N/A` are the sheets' blanks."""
    if s is None:
        return None
    s = s.strip()
    return None if s in ("", "-", "N/A") else s


def _magnet(s: Optional[str]) -> Any:
    return normalize_magnet_type(_text(s))


_Parser = Callable[[Optional[str]], Any]

# Row label (lowercased) → (field, parser) for the single-value / LF column.
_LABEL_MAP: dict[str, tuple[str, _Parser]] = {
    # Dimensions & Weight
    "overall diameter": ("overall_diameter_mm", parse_length_mm),
    "baffle cutout diameter": ("mounting_diameter_mm", parse_length_mm),
    "mounting depth": ("depth_mm", parse_length_mm),
    "depth": ("depth_mm", parse_length_mm),  # compression drivers
    "net weight": ("net_weight_kg", _weight_kg),
    "nominal throat diameter": ("throat_diameter_mm", parse_length_mm),
    # Specs
    "nominal impedance": ("impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("impedance_min_ohm", parse_impedance),
    "rdc": ("re_ohm", parse_impedance),  # compression drivers' Re
    "aes power handling": ("power_aes_watts", parse_power),
    "maximum power handling": ("power_program_watts", parse_power),
    "sensitivity (1w/1m)": ("sensitivity_db_1w_1m", parse_float),
    "sensitivity (2.83v/1m)": ("sensitivity_db_2_83v_1m", parse_float),
    # NERO-5CCN125D's blank sensitivity row is followed by `With / No
    # Chamber 99/97 dB`; take the as-shipped figure (docs/manufacturers.md).
    "with / no chamber": ("sensitivity_db_2_83v_1m", parse_float),
    "recommended crossover frequency": ("recommended_crossover_hz", parse_frequency),
    "voice coil diameter": ("voice_coil_diameter_mm", parse_length_mm),
    "winding material": ("winding_material", _text),
    "former material": ("former_material", _text),
    "diaphragm material": ("diaphragm_material", _text),
    "phase plug design": ("phase_plug_design", _text),
    "flux density": ("flux_density_t", parse_float),
    "magnet": ("magnet_type", _magnet),
    "cone surround": ("surround_material", _text),
    "cone surround (lf) / dome (hf)": ("surround_material", _text),
    # Thiele Small Parameters
    "fs": ("fs_hz", parse_frequency),
    "re": ("re_ohm", parse_impedance),
    "qes": ("qes", parse_float),
    "qms": ("qms", parse_float),
    "qts": ("qts", parse_float),
    "vas": ("vas_liters", parse_liters),
    "sd": ("sd_cm2", parse_sd_cm2),
    "xmax": ("xmax_mm", parse_length_mm),
    "xdamage": ("xmech_mm", parse_length_mm),
    "mms": ("mms_g", parse_mass_g),
    "bl": ("bl_tm", parse_bl_tm),
    "bi": ("bl_tm", parse_bl_tm),  # the sheets' font renders `Bl` as `BI`
    "le": ("le_mh", parse_le_mh),
    "cms": ("cms_mm_per_n", parse_compliance_mm_per_n),
    "rms": ("rms_ns_per_m", parse_float),  # kg/s ≡ N·s/m
    "eta zero": ("eta_zero_pct", parse_percent),
    "ebp": ("ebp_hz", parse_float),
}

# Rows we recognise but don't store. They still have to be known labels:
# an unknown label's chunks would be swept into the previous cell's values.
_IGNORED_LABELS: frozenset[str] = frozenset(
    {
        "bolt circle diameter",
        "flange and gasket thickness",
        "90° mounting holes diameter",
        "shipping box",
        "gross weight",
        "recone kit",
        "lf-recone kit",
        "replacement diaphragm",
        "hf-replacement diaphragm",
        "notes",
        "winding depth",
        "magnetic gap depth",
        "basket material",
        "demodulation",
        "net air volume filled by driver",
        "net air volume filled by hf driver",
        "spider profile",
        "weather resistant",
        "total exit angle",
    }
)

# Coax HF column. HF max power / sensitivity have no slot (docs/tasks.md);
# the HF `Cone Surround` value is the dome → diaphragm_material, as Ciare.
_LABEL_MAP_COAX_HF: dict[str, tuple[str, _Parser]] = {
    "nominal impedance": ("coax_hf_impedance_nominal_ohm", parse_impedance),
    "minimum impedance": ("coax_hf_impedance_min_ohm", parse_impedance),
    "aes power handling": ("coax_hf_power_aes_watts", parse_power),
    "voice coil diameter": ("coax_hf_voice_coil_diameter_mm", parse_length_mm),
    "cone surround": ("diaphragm_material", _text),
    "cone surround (lf) / dome (hf)": ("diaphragm_material", _text),
}

# Longest first, so `magnet` can't shadow `magnetic gap depth` etc.
# `frequency range` is special-cased (one value → two fields).
_LABEL_KEYS: list[str] = sorted(
    {*_LABEL_MAP, *_IGNORED_LABELS, "frequency range"}, key=len, reverse=True
)


@dataclasses.dataclass
class _Chunk:
    """A run of words on one row with no gap wider than _CHUNK_GAP_PT."""

    text: str
    x0: float
    x1: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclasses.dataclass
class _Cell:
    label: str
    values: list[_Chunk]
    label_x1: float
    # x0 of the next label on the same row: the right edge of this cell's
    # column. Bounds where a wrapped value may be picked up from the next row.
    x_limit: float = float("inf")


@dataclasses.dataclass
class _Row:
    baseline: float  # points from the top of the page
    chunks: list[_Chunk]  # left → right


def _pdf_rows(body: bytes) -> list[_Row]:
    """Page 1 of the PDF as rows, top → bottom."""
    pdf = pdfium.PdfDocument(body)
    try:
        page = pdf[0]
        height = page.get_height()
        textpage = page.get_textpage()
        glyphs: list[tuple[float, float, float, str]] = []  # (baseline, x0, x1, ch)
        ox, oy = ctypes.c_double(), ctypes.c_double()
        for i in range(textpage.count_chars()):
            ch = textpage.get_text_range(i, 1)
            if not ch or ch.isspace():
                continue
            x0, _, x1, _ = textpage.get_charbox(i, loose=True)
            if not pdfium_c.FPDFText_GetCharOrigin(
                textpage.raw, i, ctypes.byref(ox), ctypes.byref(oy)
            ):
                continue
            glyphs.append((height - oy.value, x0, x1, ch))
    finally:
        pdf.close()

    grouped: list[tuple[float, list[tuple[float, float, float, str]]]] = []
    for g in sorted(glyphs, key=lambda g: g[0]):
        if grouped and g[0] - grouped[-1][0] <= _ROW_TOL_PT:
            grouped[-1][1].append(g)
        else:
            grouped.append((g[0], [g]))

    rows: list[_Row] = []
    for baseline, row_glyphs in grouped:
        chunks: list[_Chunk] = []
        for _, x0, x1, ch in sorted(row_glyphs, key=lambda g: g[1]):
            gap = x0 - chunks[-1].x1 if chunks else None
            if gap is not None and gap <= _CHUNK_GAP_PT:
                last = chunks[-1]
                last.text += (" " if gap > _WORD_GAP_PT else "") + ch
                last.x1 = max(last.x1, x1)
            else:
                chunks.append(_Chunk(ch, x0, x1))
        rows.append(_Row(baseline, chunks))
    return rows


def _match_label(text: str) -> Optional[tuple[str, str]]:
    """(label, inline remainder) if `text` starts with a known row label on a
    word boundary. Footnote markers (`(3)`) after the label are dropped."""
    lowered = text.lower()
    for key in _LABEL_KEYS:
        if not lowered.startswith(key):
            continue
        if len(lowered) > len(key) and lowered[len(key)].isalnum():
            continue
        rest = _LEADING_FOOTNOTES_RE.sub("", text[len(key) :]).strip()
        return key, rest
    return None


def _cells(rows: list[_Row]) -> list[_Cell]:
    """Label-anchored cells. A chunk starting with a known label opens a cell;
    following chunks on the row are its values.

    Scanning starts at the `Nominal Impedance` row (the tables' first row on
    every layout), so feature bullets above can't match a label. Only each
    label's first cell is kept: the response/impedance graphs below the
    tables carry `BL` / `RE` axis text that would otherwise fill a field
    whose table cell is blank.

    Chunks before the first label on a row (notes prose, drawing dimensions)
    are orphans. Some sheets set a value a few points above or below its
    label (`Cone Surround`, `Phase Plug Design`), so a cell that comes up
    empty adopts the nearest unclaimed orphan from an adjacent row (within
    _ADOPT_MAX_PT) that sits right of its label and inside its column.
    Other orphans are discarded."""
    start = next(
        (
            i
            for i, row in enumerate(rows)
            if any(c.text.lower().startswith("nominal impedance") for c in row.chunks)
        ),
        len(rows),
    )
    rows = rows[start:]
    row_cells: list[list[_Cell]] = []
    row_orphans: list[list[_Chunk]] = []
    for row in rows:
        cells: list[_Cell] = []
        orphans: list[_Chunk] = []
        for chunk in row.chunks:
            if _FOOTNOTE_RE.fullmatch(chunk.text):
                continue
            hit = _match_label(chunk.text)
            if hit is not None:
                label, rest = hit
                if cells:
                    cells[-1].x_limit = chunk.x0
                cells.append(_Cell(label, [], chunk.x1))
                if rest:
                    cells[-1].values.append(_Chunk(rest, chunk.x0, chunk.x1))
            elif cells:
                cells[-1].values.append(chunk)
            else:
                orphans.append(chunk)
        row_cells.append(cells)
        row_orphans.append(orphans)

    claimed: set[tuple[int, int]] = set()
    for i, cells in enumerate(row_cells):
        for cell in cells:
            if cell.values:
                continue
            candidates = [
                (abs(rows[j].baseline - rows[i].baseline), j, k)
                for j in (i - 1, i + 1)
                if 0 <= j < len(rows)
                and abs(rows[j].baseline - rows[i].baseline) <= _ADOPT_MAX_PT
                for k, o in enumerate(row_orphans[j])
                if (j, k) not in claimed
                and cell.label_x1 < o.x0
                and o.x1 <= cell.x_limit
            ]
            if candidates:
                _, j, k = min(candidates)
                claimed.add((j, k))
                cell.values.append(row_orphans[j][k])

    first: dict[str, _Cell] = {}
    for cells in row_cells:
        for cell in cells:
            first.setdefault(cell.label, cell)
    return list(first.values())


def _coax_split(
    values: list[_Chunk], hf_boundary_x: Optional[float]
) -> tuple[Optional[str], Optional[str]]:
    """(LF, HF) value texts for a coax Specs cell. With the `LF Unit` /
    `HF Unit` headers present, assign by x position (a blank side is just
    absent); otherwise fall back to left-to-right order."""
    if hf_boundary_x is None:
        lf = values[0].text if values else None
        hf = values[1].text if len(values) > 1 else None
        return lf, hf
    lf_vals = [v.text for v in values if v.center < hf_boundary_x]
    hf_vals = [v.text for v in values if v.center >= hf_boundary_x]
    return (lf_vals[0] if lf_vals else None), (hf_vals[0] if hf_vals else None)


def _hf_boundary(rows: list[_Row]) -> Optional[float]:
    """Midpoint between the `LF Unit` and `HF Unit` header centers, if both
    header labels are text on this sheet."""
    lf = hf = None
    for row in rows:
        for c in row.chunks:
            if c.text == "LF Unit":
                lf = c
            elif c.text == "HF Unit":
                hf = c
    if lf is None or hf is None:
        return None
    return (lf.center + hf.center) / 2.0


def _model_from_h1(soup: BeautifulSoup) -> Optional[str]:
    """`PRODUCTS > WOOFERS > BIANCO-15MW350` → `BIANCO-15MW350`."""
    h1 = soup.select_one("#left_column h1") or soup.select_one("h1")
    if h1 is None:
        return None
    tail = h1.get_text(" ", strip=True).replace("\xa0", " ").rsplit(">", 1)[-1]
    return tail.strip() or None


@register
class SBAudienceScraper(Scraper):
    name = "sbaudience"
    manufacturer_display = "SB Audience"
    schema_version = "1.0"
    expected_min_records = 50  # 60 drivers live (64 products − 4 horns)
    max_seed_rounds = 1

    def discover_seeds(self) -> list[SeedRef]:
        return [SeedRef(url=_PRODUCTS_URL, context=SeedContext())]

    def enumerate(self, seed_artifacts: list[RawArtifact]) -> EnumerateResult:
        products: list[SeedRef] = []
        seen: set[str] = set()
        for art in seed_artifacts:
            body = art.body.decode("utf-8", errors="ignore")
            for m in _PRODUCT_HREF_RE.finditer(body):
                path, category = m.group(1), m.group(2)
                kind = _CATEGORY_TO_KIND.get(category)
                if kind is None:
                    continue
                url = _BASE + path
                if url in seen:
                    continue
                seen.add(url)
                products.append(
                    SeedRef(
                        url=url,
                        context=SeedContext(
                            driver_kind_hint=kind, category_id=category
                        ),
                    )
                )
        return EnumerateResult(product_urls=products)

    def parse_artifact(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        if raw.body.startswith(b"%PDF"):
            return self._parse_datasheet(raw, seed_context)
        if seed_context.parent_source_url is not None:
            # A datasheet followup that came back as HTML (error page,
            # captcha). Raise so the orchestrator records the drop.
            raise ValueError(f"expected a datasheet PDF from {raw.url}")
        return self._parse_product_page(raw, seed_context)

    def _parse_product_page(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        soup = BeautifulSoup(raw.body, "lxml")
        # Some pages carry a second, empty-text download link (an old
        # revision); the datasheet is the one whose text says so.
        link = next(
            (
                a
                for a in soup.select('a[href*="/download_file/"]')
                if "datasheet" in a.get_text().lower()
            ),
            None,
        )
        if link is None:
            raise ValueError(f"no datasheet link on {raw.url}")
        followup_ctx = dataclasses.replace(
            seed_context,
            parent_model=_model_from_h1(soup),
            parent_source_url=raw.url,
        )
        return ParseResult(
            fragments=[],
            followups=[
                SeedRef(url=urljoin(raw.url, link["href"]), context=followup_ctx)
            ],
        )

    def _parse_datasheet(
        self, raw: RawArtifact, seed_context: SeedContext
    ) -> ParseResult:
        rows = _pdf_rows(raw.body)
        if not rows:
            raise ValueError(f"datasheet has no text layer: {raw.url}")

        title = rows[0].chunks[0].text.strip()
        page_model = seed_context.parent_model
        model = title if _MODEL_RE.match(title) else page_model
        if not model:
            raise ValueError(f"no model on datasheet or product page: {raw.url}")
        subtitle = next(
            (
                text
                for text in (" ".join(c.text for c in row.chunks) for row in rows[1:6])
                if _SUBTITLE_SIZE_RE.match(text)
            ),
            "",
        )
        cells = _cells(rows)

        kind = seed_context.driver_kind_hint
        if kind is None:
            # Context lost (e.g. a redirect changed the URL the orchestrator
            # keys followup context on): infer from the sheet itself.
            if "coax" in subtitle.lower():
                kind = DriverKind.COAX
            elif any(c.label == "nominal throat diameter" for c in cells):
                kind = DriverKind.HF_COMPRESSION
            else:
                kind = DriverKind.LF_WOOFER
        if "midrange" in subtitle.lower():
            kind = DriverKind.FULLRANGE

        frag = DriverFragment(
            manufacturer=self.manufacturer_display,
            source_url=seed_context.parent_source_url or raw.url,
            fetched_at=raw.fetched_at,
            driver_kind=kind,
            model=model,
        )
        if page_model and page_model != model:
            frag.warn_flags.append(
                f"model_mismatch:page={page_model},datasheet={model}"
            )

        # First value wins where labels share a field (`re`/`rdc`,
        # `sensitivity (2.83v/1m)`/`with / no chamber`, LF/HF cone surround).
        def put(
            field: str, value: Any, source: SpecSource = SpecSource.PDF_TABLE
        ) -> None:
            if value is None or field in frag.spec_source:
                return
            setattr(frag, field, value)
            frag.spec_source[field] = source

        is_coax = kind == DriverKind.COAX
        hf_boundary = _hf_boundary(rows) if is_coax else None
        for cell in cells:
            if not cell.values:
                continue
            if is_coax and (
                cell.label in _LABEL_MAP_COAX_HF or cell.label == "frequency range"
            ):
                lf_text, hf_text = _coax_split(cell.values, hf_boundary)
            else:
                lf_text, hf_text = cell.values[0].text, None

            if cell.label == "frequency range":
                for text, lo, hi in (
                    (lf_text, "freq_low_hz", "freq_high_hz"),
                    (hf_text, "coax_hf_freq_low_hz", "coax_hf_freq_high_hz"),
                ):
                    rng = parse_range(text)
                    if rng is not None:
                        put(lo, rng[0])
                        put(hi, rng[1])
                continue

            if cell.label in _IGNORED_LABELS:
                continue
            field, parser = _LABEL_MAP[cell.label]
            put(field, parser(lf_text))
            if hf_text is not None and cell.label in _LABEL_MAP_COAX_HF:
                hf_field, hf_parser = _LABEL_MAP_COAX_HF[cell.label]
                put(hf_field, hf_parser(hf_text))

        m = _SUBTITLE_SIZE_RE.match(subtitle)
        if m:
            put(
                "nominal_size_mm",
                round(float(m.group(1)) * 25.4, 2),
                SpecSource.PDF_TEXT,
            )

        return ParseResult(fragments=[frag])
