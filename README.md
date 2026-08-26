# driver-base

A database of loudspeaker drivers — scraped, normalized, and published as
JSON for use by simulation tools, DIY builders, and research.

## Repository layout

- `src/driver_base/` — Python scraper and normalizer (per-manufacturer
  adapters, field mapping, cross-manufacturer reconciliation).
- `web/drivers.json` — the current published dataset, served alongside the
  web UI so a single Cloudflare Pages deploy covers both.
- `web/` — small web UI for browsing the dataset.
- `data/cache/` — scraped source pages (scraper input, not published).
- `data/rejections/` — records dropped during normalization, with reasons.
- `data/aliases.yaml` — manual canonical_id rewrites.
- `docs/` — design notes and field reference.

## Using the dataset

`web/drivers.json` is a single JSON file. Each record describes one driver
with a normalized set of fields (Thiele/Small parameters, physical
dimensions, power ratings, etc.). Simulation programs are welcome to bundle
or sync it — see the license section below.

## License

This project uses two licenses, one for code and one for the dataset. This
matches convention on both sides: software tooling expects a software
license; datasets expect a data license.

- **Code** (everything under `src/`, `web/`, `tests/`, and the project
  configuration) — [Apache License 2.0](LICENSE). Includes an explicit
  patent grant.
- **Dataset** (`web/drivers.json` and the schema/compilation it represents)
  — [Creative Commons Attribution 4.0](LICENSE-DATA)
  (CC BY 4.0). Attribute as:

  > Data from driver-base (https://github.com/JonathanDCohen/driver-base),
  > licensed under CC BY 4.0.

Individual specification values (Fs, Re, Xmax, frequency response numbers,
etc.) are factual and are not themselves subject to copyright — the CC BY
license covers the selection, arrangement, and curation. Manufacturer
names, model numbers, product images, and any verbatim marketing prose
remain the property of their respective owners.
