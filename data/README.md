# data/signatories_live.csv

This is a manually-built snapshot of the public, consented-to-share columns
(name, website, country, category, commitment) from the real "Charter
Commitment and Stewardship Questionnaire (Responses)" Google Sheet, used as
a stand-in data source when `build.py` can't reach `docs.google.com`
directly (e.g. sandboxed/offline environments).

It is **not** the live pipeline and will go stale as new signatories are
approved. Wherever `build.py` runs with real network access to Google
Sheets, it fetches the actual sheet directly (see
`SIGNATORIES_SHEET_CSV_URL` / `_DEFAULT_SIGNATORIES_SHEET_CSV_URL` at the
top of build.py) and this file isn't needed at all.

To refresh this snapshot by hand: open the response sheet, and for each
row that has consented to public listing, copy just the safe columns
(website, country, category, commitment, consent phrase, name,
organisation) into the matching column positions here. Never copy emails,
phone/WhatsApp numbers, or any other private column into this file.
