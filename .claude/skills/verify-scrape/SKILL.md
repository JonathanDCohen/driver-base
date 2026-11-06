---
name: verify-scrape
description: Use when a driver-base scraper was added or changed, or web/drivers.json was regenerated, and its records must be checked against the manufacturer's live site — "check drivers.json against the site", "verify the scrape", "spot-check <manufacturer>".
---

# Verifying a scrape against the live site

## Overview

A check that reads the site the way the scraper does, or that learns the
field conventions from `drivers.json`, will confirm the scraper's mistakes.
So keep three roles apart:

- **Transcribers** never see the repo. They copy what the site says, verbatim.
- **The mapping** turns site labels into fields. You write it from the
  manufacturer's own footnotes, not from the scraper.
- **`tools/verify_scrape.py`** does the comparing, deterministically.

Work from the repo root and in your session scratchpad. Never commit as
part of this: report, show the diff, and wait for explicit approval.

## Steps

1. **Identity list (the only read of `drivers.json`).** Pull identity
   fields only. Never look at spec values.
   ```bash
   jq -c '.drivers[] | select(.manufacturer=="<display name>")
          | {canonical_id, url: .source_urls[0], z: .impedance_nominal_ohm, kind: .driver_kind}' \
     web/drivers.json > ids.jsonl
   ```
   The display name is the scraper's `manufacturer_display`.

2. **Coverage.** List the live catalog independently. Use whatever the
   site offers: sitemap, nav, category pages, or a platform feed such as
   Shopify `/products.json`. Do not use the scraper's `enumerate` to do
   this. Then compare the in-scope count with `ids.jsonl`. Every gap needs a
   named reason, such as "horns skipped by design" or a rejection reason
   from the run log.

3. **Scope and batches.** If the manufacturer has ≤100 records, transcribe
   all of them. Otherwise take ≥30, covering every `kind` and every layout
   variant listed in `docs/manufacturers.md`.
   - Split the URLs into batch files of about 15. When one URL yields
     several records, the batch file carries the `z` values.
   - Run at most 4 transcribers at once.
   - If robots.txt sets a `Crawl-delay`, put it in the brief.

4. **Blind transcription.** Each Sonnet subagent gets this brief:

   > Transcribe every spec table on these product pages: <batch file
   > contents>. Download each fresh with `curl -sSL -A "Mozilla/5.0"` into
   > <scratch>/<batch>/, waiting <delay>s between requests. An HTTP status
   > other than 200, a captcha, or a page with no specs is a FAILED fetch:
   > report it and don't transcribe it. Never read or write the
   > driver-base repo.
   >
   > How to read each source:
   > - **PDF / image:** open the downloaded file with the Read tool.
   > - **HTML:** extract the spec table text from the saved file (e.g. a
   >   short BeautifulSoup script printing each row's cells). Don't use
   >   WebFetch — it summarizes.
   > - **JSON API:** copy `key: value` pairs as rows.
   > - **Linked datasheet** (specs live in a link): follow the link and
   >   use the datasheet.
   >
   > Output only JSON: `[{"source_url": <URL exactly as given>, "variant":
   > <z as given, else omit>, "rows": [{"section": <column header, only
   > when a row has several value columns>, "label": <exact label incl.
   > footnote markers>, "value": <exact value incl. units>}]}]`.
   > - Include the product title and subtitle as rows labelled "title" and
   >   "subtitle".
   > - When a row has several value columns, emit one row per column, with
   >   that column's header as `section`.
   > - Copy every row, even irrelevant-looking ones. Write "-" for blanks.
   > - Never convert or interpret.

   Merge the outputs into `transcription.json`. Re-dispatch any failed
   fetches before going on.

5. **Mapping.** Write `mapping.json` in the format the tool's docstring
   describes. Field names come from `src/driver_base/model.py`; read only
   that file.
   - Base each decision on the site's own footnotes ("Xmax (p-p)", "3 dB
     above nominal", "SPL at 2.83 V"), on `docs/manufacturers.md`, and on
     the slot definitions in `docs/framework.md`.
   - Map only what the site publishes.
   - Section columns the record doesn't store (e.g. "No Chamber") get an
     ignore rule: `{"label": ".", "section": "<header>", "field": null}`.

6. **Compare.**
   ```bash
   uv run python tools/verify_scrape.py --manufacturer "<display name>" \
     --transcription T.json --mapping M.json --require-full-coverage  # drop flag when sampling
   ```
   Failure modes are listed in the tool's docstring.

   Also read the "unmapped labels" and "rules that matched nothing" lists.
   An unmapped label with a schema slot means a check you didn't run.

7. **Triage.** Every mismatch gets exactly one of these classes:

   | Class | Action |
   |---|---|
   | Scraper bug | Fix, re-scrape (normal fetch path, never `--refetch`), re-compare |
   | Transcription slip | Re-fetch the page yourself, quote the exact text in the report, then correct the transcription |
   | Mapping error | Fix the mapping only if you can quote the footnote or doc that justifies the new rule |
   | Intentional override | Cite the `src/driver_base/overrides.py` entry |
   | Source ambiguity | Record the decision in `docs/manufacturers.md` |

   Never edit the transcription or the mapping just to make a mismatch go
   away.

8. **Report to the user.**
   - Coverage: live count, record count, and the reason for each gap.
   - Pages and field comparisons checked.
   - Each mismatch, with its class and resolution.
   - What wasn't verified: derived fields, `driver_kind`, unsampled records.

## Common mistakes

| Mistake | Why it fails |
|---|---|
| Regex over the same HTML/PDF text layer the scraper parses | Shares the scraper's blind spots (text-layer glyph splits, wrong cell) |
| A fixed percentage tolerance | Hides wrong digits at high values and flags rounding at low ones. The tool uses printed precision instead |
| Debugging your own ad-hoc comparison script | Wasted time. Transcribe verbatim and let the tool parse |
