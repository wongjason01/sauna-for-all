# Sauna for All

Marketing site for Sauna for All and the Public Sauna-Bathing Charter.
Live at https://sauna-for-all.tiny-block-645d.workers.dev

## How it works

A small static-site generator. `build.py` writes the eight HTML pages from
Python templates, then `prepare_deploy.py` inlines the CSS and JS into each
page and copies the referenced images and files into `dist/`.

```
python3 build.py          # regenerates the .html pages
python3 prepare_deploy.py # writes the deployable dist/ folder
```

Standard library only — nothing to install. `dist/` is generated, not
committed.

## Deploys

Cloudflare Workers Builds is connected to this repo. A commit to `main`
rebuilds and redeploys automatically; `wrangler.toml` points it at `dist/`.
No manual upload step.

## Content

Most copy lives in `build.py` as the source of truth. The exception is the
signatories directory, which comes from the live Charter questionnaire
Google Sheet at build time, with `data/signatories_live.csv` as a committed
fallback for when the sheet can't be reached — so a build never publishes an
empty directory. The directory and homepage tally also refresh at runtime
from a feed worker, so new signatories appear without a rebuild.

## Signatory logos

The questionnaire's logo question ("upload your organisation's logo, or a
headshot if signing as an individual") writes uploads to its own Drive folder.
Each build reads the file id from the sheet, downloads the image through
Drive's thumbnail endpoint, and writes it to `images/signatories/<slug>.<ext>`,
where the page picks it up. Signatories without an upload get an initials
badge instead.

This works with no credentials because that folder is shared as **anyone with
the link can view**, and new uploads inherit that sharing — so a signatory who
uploads a logo has it appear on the next deploy with nobody intervening. Forms
gives every file-upload question its own folder, so this one holds only logos
and headshots; reference letters are in a separate, private folder and stay
that way.

If the fetch fails, the build says so per signatory and that card falls back to
an initials badge until the next build — nothing breaks, and nothing fails
silently. Downloads are gitignored: Drive is the source of truth. To override
one by hand, `git add -f images/signatories/<slug>.png`; a file already present
is never overwritten.

## Layout

| Path | What it is |
|---|---|
| `build.py` | page templates, copy, and the signatories loader |
| `prepare_deploy.py` | inlines assets and assembles `dist/` |
| `css/`, `js/` | source stylesheet and scripts (inlined at deploy time) |
| `images/`, `files/` | photos, headshots, principle icons, Charter PDF |
| `data/` | signatories snapshot and notes on refreshing it |
| `workers/` | the separate Substack feed worker |

`CMS_SETUP.md`, `DOMAIN_CUTOVER.md` and `PUNCH_LIST.md` cover the remaining
open work.
