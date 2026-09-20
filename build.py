#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Static site builder for Sauna For All.
Assembles shared <head>, nav, footer around per-page content blocks
and writes finished HTML files to the project root.
"""
import os
import csv
import datetime
import io
import json
import re
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Live data source: Signatories are pulled from a published Google Sheet at
# build time, so approving a new signatory in the sheet is enough to update
# the site on the next rebuild -- no code change needed.
#
# Set SIGNATORIES_SHEET_CSV_URL (env var, or edit the default below) to the
# sheet's CSV export link:
#   https://docs.google.com/spreadsheets/d/<SHEET_ID>/export?format=csv&gid=<TAB_GID>
# (SHEET_ID and TAB_GID come from the sheet's normal share URL; the sheet
# needs "Anyone with the link -> Viewer" sharing for this to be fetchable
# with no auth.)
#
# Leave it blank to fall back to the placeholder rows below -- used for local
# preview, or automatically if the sheet is unreachable at build time.
#
# Defaults to the real "Charter Commitment and Stewardship Questionnaire
# (Responses)" sheet -- this only works once that sheet's link-sharing is
# set to "Anyone with the link -> Viewer" (Share button -> General access
# in Google Sheets). The sheet is currently owned by
# hello@loylyfloatingsauna.ca, so that account (or another editor with
# permission to change link-sharing) needs to be the one to flip it.
# ---------------------------------------------------------------------------
_DEFAULT_SIGNATORIES_SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1aZnRRh2BCUHODXV_Wvu9eNM2GUqghQWPsurygv--f7I/export?format=csv&gid=410857344"
)
SIGNATORIES_SHEET_CSV_URL = os.environ.get("SIGNATORIES_SHEET_CSV_URL", _DEFAULT_SIGNATORIES_SHEET_CSV_URL)

# The live source is the raw Google Form response sheet ("Charter Commitment
# and Stewardship Questionnaire (Responses)") -- not a clean signatories
# table. It has 40+ columns per submission, most of it private (email,
# WhatsApp, letters of reference, internal-only essay answers), and two
# columns share a header name with earlier ones (a second "Name" and
# "Organisation" pair in the signature section), so columns are addressed
# by their fixed sheet position rather than by header text.
#
#   G  = Country
#   K  = "Which best describes you?" (single-select role/category)
#   T  = the 350-char commitment blurb the form itself says is meant to
#        display on the Charter webpage
#   AH = the public-listing consent checkboxes ("Select all that apply...")
#   AJ = Name (signature section)
#   AK = Organisation (signature section)
#   E  = Website (used as the signatory's link)
#
# AH is a comma-joined multi-select. Two separate consents live in it, and
# they gate two separate things: a row is only included at all if the
# respondent checked "Please list me publicly as a Charter signatory";
# even then, the free-text commitment quote (T) is only shown if they
# *also* separately checked "You may share my commitments (Section 2)
# publicly on the Charter website or social media" -- someone who agreed to
# be listed but not to have their commitment text published still shows up
# (name/org/country/category) with no quote, rather than being dropped or
# having their answer shown without that specific consent.
_COL = {"timestamp": "A", "country": "G", "category": "K", "commitment": "T",
        "consent": "AH", "name": "AJ", "organisation": "AK", "website": "E",
        # Logo/photo upload added to the form in Sept 2026. The cell holds a
        # Drive link; the image itself has to be committed under
        # images/signatories/ (see logo_tile in page_signatories).
        "logo": "AO"}

_PUBLIC_LISTING_PHRASE = "please list me publicly as a charter signatory"
_COMMITMENT_SHARE_PHRASE = "you may share my commitments (section 2) publicly"

# The category question is single-select but its own answer text sometimes
# contains a comma (e.g. "Public or community sauna operator, bricks and
# mortar"), so it must NOT be comma-split like a real multi-select field.
# Maps each raw questionnaire answer onto the seven website filter categories
# from SPEC.md Section 7.1. This will eventually be computed by the
# "Website filter (auto)" column from the signatory-filters.gs Apps Script
# (not yet provided), so this map is the interim stand-in; anything
# unrecognized falls through unchanged and is logged at build time so it can
# be added here rather than silently mislabeled.
CATEGORY_MAP = {
    "public or community sauna operator, bricks and mortar": "Operators and Keepers",
    "public or community sauna operator, mobile/floating": "Operators and Keepers",
    # Raw sheet answer for one respondent's mobile/floating operator category
    # was entered as free text rather than the standard option -- see
    # data/README.md. Treated as Operators and Keepers per its own wording.
    "floating don't know if that is mobile": "Operators and Keepers",
    "sauna organisation or network": "Sauna Organisations and Networks",
    "wellness organisation": "Sauna Organisations and Networks",
    "municipality or government, including indigenous nations": "Governments and Public Bodies",
    "tourism organisation": "Governments and Public Bodies",
    "public health organisation": "Governments and Public Bodies",
    "designer or architect": "Designers, Builders and Suppliers",
    "builder or developer": "Designers, Builders and Suppliers",
    "manufacturer or supplier": "Designers, Builders and Suppliers",
    "researcher or educator": "Researchers and Educators",
    "funder or investor": "Funders and Investors",
    "individual supporter": "Bathers and Advocates",
}

SIGNATORY_FILTERS = [
    "Operators and Keepers",
    "Sauna Organisations and Networks",
    "Governments and Public Bodies",
    "Designers, Builders and Suppliers",
    "Researchers and Educators",
    "Funders and Investors",
    "Bathers and Advocates",
]


def _col_index(letter):
    n = 0
    for ch in letter:
        n = n * 26 + (ord(ch) - 64)
    return n


def _fetch_csv(url, timeout=15):
    """Downloads a published Google Sheet as CSV text. Returns None (rather
    than raising) on any failure, so a bad/expired URL or a build machine
    with no network access degrades to the placeholder data instead of
    breaking the whole build."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        return raw.decode("utf-8-sig")
    except Exception as e:
        print(f"  ! could not fetch signatories sheet ({e}); using placeholder data")
        return None


def _cell(row, letter):
    i = _col_index(letter) - 1
    return row[i].strip() if i < len(row) else ""


def _normalize_url(url):
    if not url:
        return "#"
    return url if re.match(r"^https?://", url, re.I) else f"https://{url}"



def _country_of(record):
    """Data is stored as 'City, Country' (or just 'Country') -- the stat
    strip counts distinct countries, so pull out the last comma segment."""
    country = record.get("country", "")
    return country.split(",")[-1].strip() if country else ""


def _join_names(names):
    """'A' / 'A and B' / 'A, B and C' -- SPEC.md 7.1: 'Show one card under the
    organisation name, listing everyone who signed for it.'"""
    names = [n for n in names if n]
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def _drive_file_id(cell):
    """The form's file-upload answer is a Drive link such as
    https://drive.google.com/open?id=<id>. Returns just the id, or "" if the
    signatory didn't upload anything."""
    if not cell:
        return ""
    m = re.search(r"[?&]id=([A-Za-z0-9_-]+)", cell) or re.search(r"/d/([A-Za-z0-9_-]+)", cell)
    return m.group(1) if m else ""

def _order_key(name):
    """Normalised name used to line a feed entry up with the build's
    ordering. Case and punctuation are dropped because the feed Worker and
    the sheet don't always agree on them ("humanswhobathe" vs "Humans Who
    Bathe"). Mirrored by orderKey() in js/signatories-feed.js -- change
    both together."""
    return re.sub(r"[^0-9a-zÀ-ɏ]+", "", (name or "").lower())

_TIMESTAMP_FORMATS = (
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
)

def _signed_at(cell):
    """Parses the form's Timestamp column (sheet column A) into something
    sortable. Google writes it in the sheet owner's locale, so several
    shapes are tried. Returns None when it can't be read -- callers fall
    back to the row's position in the sheet, which is already submission
    order, so an unparseable timestamp can never scramble the directory."""
    cell = (cell or "").strip()
    if not cell:
        return None
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.datetime.strptime(cell, fmt)
        except ValueError:
            continue
    return None

def load_signatories(csv_url, fallback):
    """Loads approved, consented signatory rows from the live Charter
    questionnaire response sheet (see _COL / consent notes above), mapped
    onto the dict shape the rest of build.py expects (name/url/country/
    categories/commitment). Falls back to placeholder rows if no URL is
    configured, the fetch fails, or no response has public-listing consent
    yet."""
    text = _fetch_csv(csv_url) if csv_url else None
    if text is None:
        # No network to docs.google.com (sandboxed/offline build). Rather than
        # emitting an empty directory -- which silently publishes a site with
        # no signatories on it -- fall back to the committed snapshot in
        # data/signatories_live.csv. See data/README.md; it's the same safe,
        # public columns, just hand-refreshed rather than live.
        snapshot = os.path.join(ROOT, "data", "signatories_live.csv")
        if os.path.isfile(snapshot):
            with open(snapshot, encoding="utf-8") as f:
                text = f.read()
            print("  ! live sheet unreachable; using data/signatories_live.csv snapshot")
        else:
            return fallback

    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header row

    people_rows = []
    unmapped_categories = set()
    for raw_row in reader:
        if not any(raw_row):
            continue
        person_name = _cell(raw_row, _COL["name"])
        if not person_name:
            continue

        consent = _cell(raw_row, _COL["consent"]).lower()
        if _PUBLIC_LISTING_PHRASE not in consent:
            continue  # no consent to be listed publicly at all -- skip entirely

        raw_category = _cell(raw_row, _COL["category"])
        category = CATEGORY_MAP.get(raw_category.lower(), raw_category)
        if raw_category and raw_category.lower() not in CATEGORY_MAP:
            unmapped_categories.add(raw_category)

        commitment = _cell(raw_row, _COL["commitment"]) if _COMMITMENT_SHARE_PHRASE in consent else ""
        url = _normalize_url(_cell(raw_row, _COL["website"]))
        organisation = _cell(raw_row, _COL["organisation"])

        people_rows.append({
            "signed_at": _signed_at(_cell(raw_row, _COL["timestamp"])),
            "row_index": len(people_rows),
            "person_name": person_name,
            "organisation": organisation,
            "url": url,
            "country": _cell(raw_row, _COL["country"]),
            "category": category,
            "commitment": commitment,
            "logo_upload": _drive_file_id(_cell(raw_row, _COL["logo"])),
        })

    if unmapped_categories:
        print(f"  ! signatories sheet: unrecognized category answer(s), shown as-is: {sorted(unmapped_categories)}")
        print(f"    (add them to CATEGORY_MAP in build.py to match the site's filter categories)")

    if not people_rows:
        return fallback

    # SPEC.md 7.1: "Multiple people from one organisation: Show one card
    # under the organisation name, listing everyone who signed for it."
    # Rows with no organisation (individual supporters / bathers and
    # advocates) each get their own card, keyed by their own name so they
    # are never merged with one another.
    groups = {}
    order = []
    for r in people_rows:
        key = ("org", r["organisation"].strip().lower()) if r["organisation"] else ("person", id(r))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    rows = []
    for key in order:
        members = groups[key]
        first = members[0]
        organisation = first["organisation"]
        people_names = _join_names([m["person_name"] for m in members])
        categories = []
        for m in members:
            if m["category"] and m["category"] not in categories:
                categories.append(m["category"])
        commitment = next((m["commitment"] for m in members if m["commitment"]), "")
        url = next((m["url"] for m in members if m["url"] and m["url"] != "#"), first["url"])
        # An organisation's place in the directory is set by whoever signed
        # for it first, not by whichever of its people the sheet happens to
        # list first -- so adding a second signatory to an existing
        # organisation never moves that card.
        earliest = min((m["signed_at"] for m in members if m["signed_at"]), default=None)
        rows.append({
            "signed_at": earliest,
            "row_index": min(m["row_index"] for m in members),
            "name": organisation or people_names,
            "signed_by": f"Signed by {people_names}" if organisation else "",
            "url": url,
            "country": first["country"],
            "categories": categories or [],
            "commitment": commitment,
            "logo_upload": next((m.get("logo_upload") for m in members if m.get("logo_upload")), ""),
        })

    # Ordered by when each signatory actually signed, earliest first, so the
    # directory reads as a lineage: founding signatories at the top, newest
    # arrivals at the bottom. Rows whose Timestamp cell couldn't be parsed
    # (and the committed snapshot, where that column is blank) keep their
    # position in the sheet, which is submission order already.
    # `rows` is still in sheet order here, so an undated row can borrow the
    # timestamp of the last dated row above it -- that keeps it among the
    # neighbours it was submitted between, rather than being flung to one
    # end of the directory.
    carried = datetime.datetime.min
    for r in rows:
        if r["signed_at"]:
            carried = r["signed_at"]
        r["_sort_at"] = r["signed_at"] or carried
    rows.sort(key=lambda s: (s["_sort_at"], s["row_index"]))
    for r in rows:
        del r["_sort_at"]
    return rows or fallback

# ---------------------------------------------------------------------------
# Substack posts for the News page
# ---------------------------------------------------------------------------
# Fetched and rendered at build time rather than from the browser. Substack's
# feed sends no CORS headers, so a page-load fetch would need a proxy worker
# deployed and kept alive; baking the posts in means the News page works with
# no extra infrastructure, renders without JavaScript, and can't show a broken
# grid if Substack is slow. New posts appear on the next deploy.
SUBSTACK_FEED_URL = os.environ.get(
    "SUBSTACK_FEED_URL", "https://saunaforall.substack.com/feed")
NEWS_POST_LIMIT = 9

def esc(text):
    """HTML-escape text coming from outside the repo (Substack titles and
    excerpts), so a stray & or < in a post title can't break the page."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def _rss_text(item, tag):
    el = item.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""

def _strip_html(markup):
    """Plain text from a snippet of post HTML.

    Uses html.unescape rather than a hand-written entity list: Substack posts
    are full of &mdash;, &rsquo; and friends, and missing one leaves the raw
    entity visible in the excerpt.
    """
    import html as _html
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text).replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()

def _excerpt(html, limit=165):
    text = _strip_html(html)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:\u2013\u2014-")
    return cut + "\u2026"

def load_substack_posts(feed_url=SUBSTACK_FEED_URL, limit=NEWS_POST_LIMIT):
    """Latest posts from the Substack RSS feed, newest first.

    Returns [] on any failure -- an unreachable feed, a parse error, an empty
    publication -- so the News page falls back to its existing empty state
    instead of rendering a broken grid.
    """
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime

    try:
        req = urllib.request.Request(feed_url, headers={"User-Agent": "sauna-for-all-build"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
    except Exception as exc:
        print(f"  ! could not fetch Substack feed ({type(exc).__name__}: {exc}); "
              "News page will show its empty state")
        return []

    posts = []
    for item in root.iterfind(".//item"):
        title = _rss_text(item, "title")
        link = _rss_text(item, "link")
        if not (title and link):
            continue

        # Substack usually gives the cover art as an <enclosure>; when it
        # doesn't, the first <img> in the post body is the next best thing.
        image = ""
        enc = item.find("enclosure")
        if enc is not None and (enc.get("type") or "").startswith("image/"):
            image = enc.get("url") or ""
        body = ""
        for tag in ("{http://purl.org/rss/1.0/modules/content/}encoded", "description"):
            el = item.find(tag)
            if el is not None and el.text:
                body = el.text
                break
        if not image and body:
            m = re.search(r'<img[^>]+src="([^"]+)"', body)
            if m:
                image = m.group(1)

        date_iso, date_label = "", ""
        raw_date = _rss_text(item, "pubDate")
        if raw_date:
            try:
                dt = parsedate_to_datetime(raw_date)
                date_iso = dt.date().isoformat()
                date_label = f"{dt.day} {dt.strftime('%B %Y')}"
            except Exception:
                pass

        description = _rss_text(item, "description") or body
        posts.append({"title": title, "link": link, "image": image,
                      "date_iso": date_iso, "date_label": date_label,
                      "summary": _excerpt(description)})
        if len(posts) >= limit:
            break
    return posts

# ---------------------------------------------------------------------------
# Signatory logos uploaded through the form
# ---------------------------------------------------------------------------
# The questionnaire's logo question writes its uploads to a dedicated Drive
# folder (Forms makes one per file-upload question, so this folder holds only
# logos and headshots -- reference letters live in a separate one). With that
# folder shared as "anyone with the link can view", new uploads inherit the
# sharing, and the build can fetch each image with no credentials and no
# manual step.
#
# Fetched at build time rather than linked at page load on purpose: a visitor
# never depends on Drive being up, and a failed fetch costs one initials badge
# until the next build instead of a broken image forever.
SIGNATORY_LOGO_DIR = os.path.join(ROOT, "images", "signatories")

# Drive's thumbnail endpoint returns an already-resized image, which keeps a
# 1.4MB phone photo from being shipped for an 80px tile and means the build
# needs no image library. Overridable so the fetch path can be tested against
# a local server.
SIGNATORY_LOGO_URL = os.environ.get(
    "SIGNATORY_LOGO_URL", "https://drive.google.com/thumbnail?id={id}&sz=w320")

_IMAGE_MAGIC = {b"\xff\xd8\xff": "jpg", b"\x89PNG\r\n\x1a\n": "png",
                b"GIF87a": "gif", b"GIF89a": "gif", b"RIFF": "webp"}

def _image_ext(blob):
    """The uploaded file's real type, from its leading bytes. Drive hands back
    an HTML error page rather than an HTTP error when a file isn't readable,
    so trusting the status code alone would write junk to disk."""
    for magic, ext in _IMAGE_MAGIC.items():
        if blob.startswith(magic):
            return ext
    return None

def fetch_signatory_logos(signatories):
    """Downloads each signatory's uploaded logo into images/signatories/.

    A file already sitting there wins and is left alone, so a hand-placed
    override survives. Returns (fetched, skipped, failed) for the build log.
    """
    fetched, skipped, failed = [], [], []
    for s in signatories:
        file_id = s.get("logo_upload")
        if not file_id:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", s["name"].lower()).strip("-")
        if any(os.path.exists(os.path.join(SIGNATORY_LOGO_DIR, f"{slug}.{e}"))
               for e in ("png", "jpg", "jpeg", "svg", "webp")):
            skipped.append(s["name"])
            continue
        url = SIGNATORY_LOGO_URL.format(id=file_id)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sauna-for-all-build"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                blob = resp.read()
        except Exception as exc:
            failed.append((s["name"], f"{type(exc).__name__}: {exc}"))
            continue
        ext = _image_ext(blob)
        if not ext:
            failed.append((s["name"], "not an image -- is the Drive folder shared "
                                      "as 'anyone with the link can view'?"))
            continue
        os.makedirs(SIGNATORY_LOGO_DIR, exist_ok=True)
        with open(os.path.join(SIGNATORY_LOGO_DIR, f"{slug}.{ext}"), "wb") as f:
            f.write(blob)
        fetched.append((s["name"], f"{slug}.{ext}", len(blob)))
    return fetched, skipped, failed

# ---------------------------------------------------------------------------
# Logo (curved wordmark, matches style guide lockup)
# ---------------------------------------------------------------------------
def logo_svg(color="var(--orange)", h=40):
    return f'''<svg viewBox="0 0 300 78" xmlns="http://www.w3.org/2000/svg" style="height:{h}px">
  <defs><path id="logoarc" d="M6,62 Q150,4 294,62" /></defs>
  <text font-family="Inter, sans-serif" font-weight="800" font-size="34" fill="{color}" letter-spacing="1">
    <textPath href="#logoarc" startOffset="50%" text-anchor="middle">SAUNA FOR ALL</textPath>
  </text>
</svg>'''

# ---------------------------------------------------------------------------
# Icons (simplified line icons, echoing the style guide icon set)
# ---------------------------------------------------------------------------
ICON_STROKE = 'stroke="#0A382D" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"'

# radial tick marks used for the two "coin edge" badge icons (sun, reciprocity),
# echoing the dial/rosette rims in the updated icon sheet
ICON_TICKS = "M27.30 16.00L29.30 16.00 M26.18 20.90L27.98 21.77 M23.05 24.83L24.29 26.40 M18.51 27.02L18.96 28.97 M13.49 27.02L13.04 28.97 M8.95 24.83L7.71 26.40 M5.82 20.90L4.02 21.77 M4.70 16.00L2.70 16.00 M5.82 11.10L4.02 10.23 M8.95 7.17L7.71 5.60 M13.49 4.98L13.04 3.03 M18.51 4.98L18.96 3.03 M23.05 7.17L24.29 5.60 M26.18 11.10L27.98 10.23"

ICONS = {
"network": f'<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="2.6" {ICON_STROKE}/><circle cx="16" cy="5" r="2.2" {ICON_STROKE}/><circle cx="27" cy="16" r="2.2" {ICON_STROKE}/><circle cx="16" cy="27" r="2.2" {ICON_STROKE}/><circle cx="5" cy="16" r="2.2" {ICON_STROKE}/><circle cx="23.5" cy="8.5" r="2.2" {ICON_STROKE}/><circle cx="23.5" cy="23.5" r="2.2" {ICON_STROKE}/><circle cx="8.5" cy="23.5" r="2.2" {ICON_STROKE}/><circle cx="8.5" cy="8.5" r="2.2" {ICON_STROKE}/><path d="M16 16L16 7M16 16L25 16M16 16L16 25M16 16L7 16M16 16L21.8 10.2M16 16L21.8 21.8M16 16L10.2 21.8M16 16L10.2 10.2" {ICON_STROKE}/></svg>',
"heat": f'<svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" rx="2" {ICON_STROKE}/><path d="M9 10c1.5 2 1.5 3-0 5s-1.5 3 0 5M15.3 10c1.5 2 1.5 3 0 5s-1.5 3 0 5M21.6 10c1.5 2 1.5 3 0 5s-1.5 3 0 5" {ICON_STROKE}/></svg>',
"leaf": f'<svg viewBox="0 0 32 32"><path d="M16 27V13" {ICON_STROKE}/><path d="M16 13c0-5 3.5-8.5 8.5-8.5C24.5 9.5 21 13 16 13Z" {ICON_STROKE}/><path d="M16 18c0-4-3-7-7.5-7C8.5 15 12 18 16 18Z" {ICON_STROKE}/></svg>',
# redesigned: smiling face inside a coin/dial-edged circle (was a literal sun)
"sun": f'<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" {ICON_STROKE}/><path d="{ICON_TICKS}" {ICON_STROKE}/><circle cx="12" cy="14" r="1" fill="#0A382D"/><circle cx="20" cy="14" r="1" fill="#0A382D"/><path d="M11 19c1.4 2 3.2 3 5 3s3.6-1 5-3" {ICON_STROKE}/></svg>',
"place": f'<svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" rx="2" {ICON_STROKE}/><circle cx="16" cy="16" r="6.5" {ICON_STROKE}/></svg>',
"lattice": f'<svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" rx="2" {ICON_STROKE}/><circle cx="11" cy="11" r="1.7" {ICON_STROKE}/><circle cx="21" cy="11" r="1.7" {ICON_STROKE}/><circle cx="11" cy="21" r="1.7" {ICON_STROKE}/><circle cx="21" cy="21" r="1.7" {ICON_STROKE}/><path d="M11 12.7v6.6M21 12.7v6.6M12.7 11h6.6M12.7 21h6.6" {ICON_STROKE}/></svg>',
# redesigned: fuller diagonal hatch fill within the frame (was 5 sparser lines)
"weave": f'<svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" rx="2" {ICON_STROKE}/><path d="M5 25L25 5M5 19L19 5M5 13L13 5M11 27L27 11M17 27L27 17M23 27L27 23" {ICON_STROKE}/></svg>',
# redesigned: leaf centered inside a coin/dial-edged circle badge (was abstract overlapping circles)
"reciprocity": f'<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" {ICON_STROKE}/><path d="{ICON_TICKS}" {ICON_STROKE}/><path d="M16 21V12" {ICON_STROKE}/><path d="M16 12c0-3 2-5 5-5 0 3-2 5-5 5Z" {ICON_STROKE}/><path d="M16 15.5c0-2.2-1.8-4-4-4 0 2.2 1.8 4 4 4Z" {ICON_STROKE}/></svg>',
# redesigned: heart at the center of the circulating-arrows ring (was an abstract blob)
"circulate": f'<svg viewBox="0 0 32 32"><path d="M16 23c-4.5-3-8-6.2-8-10.2C8 9.5 10.2 7 13 7c1.3 0 2.5.6 3 1.6.5-1 1.7-1.6 3-1.6 2.8 0 5 2.5 5 5.8 0 4-3.5 7.2-8 10.2Z" {ICON_STROKE}/><path d="M16 4a12 12 0 0 1 11 7M27 8v4h-4M16 28a12 12 0 0 1-11-7M5 24v-4h4" {ICON_STROKE}/></svg>',
# redesigned: five-point star inside the scalloped seal (was a checkmark)
"seal": f'<svg viewBox="0 0 32 32"><path d="M16 3.5l2.3 2.4 3.3-.7 1 3.2 3.2 1-.7 3.3 2.4 2.3-2.4 2.3.7 3.3-3.2 1-1 3.2-3.3-.7L16 28.5l-2.3-2.4-3.3.7-1-3.2-3.2-1 .7-3.3-2.4-2.3 2.4-2.3-.7-3.3 3.2-1 1-3.2 3.3.7Z" {ICON_STROKE}/><path d="M16 10.5l1.6 3.4 3.7.4-2.7 2.6.7 3.7-3.3-1.8-3.3 1.8.7-3.7-2.7-2.6 3.7-.4Z" {ICON_STROKE}/></svg>',
"charter": f'<svg viewBox="0 0 32 32"><path d="M8 4h16v24H8z" {ICON_STROKE}/><path d="M12 10h8M12 14h8M12 18h5" {ICON_STROKE}/></svg>',
"handshake": f'<svg viewBox="0 0 32 32"><path d="M4 15l6-4 5 3 4-2 9 6-4 5-3-2-4 3-8-5-5 3z" {ICON_STROKE}/></svg>',
"voice": f'<svg viewBox="0 0 32 32"><path d="M6 12h6l8-6v20l-8-6H6z" {ICON_STROKE}/><path d="M24 12c2 1.3 2 6.7 0 8" {ICON_STROKE}/></svg>',
}

def icon_svg_or_img(name):
    # The ten Charter principle icons are now finished, full-colour artwork
    # (images/icons/<name>.png) rather than the hand-drawn monoline SVGs in
    # ICONS -- prefer the image file when one exists for this name, and
    # fall back to the inline SVG for anything that doesn't have one yet.
    if os.path.exists(os.path.join(ROOT, "images", "icons", f"{name}.png")):
        return f'<img src="/images/icons/{name}.png" alt="" loading="lazy">'
    return ICONS[name]

def icon(name, css_class="ic-tan"):
    return f'<div class="icon-circle {css_class}">{icon_svg_or_img(name)}</div>'

# ---------------------------------------------------------------------------
# Nav / Footer
# ---------------------------------------------------------------------------
# External integration links (SPEC.md Section 4). Substack/press links are
# still [ADD LINK] placeholders in the spec -- update these three the moment
# Becky provides them; nothing else in the site needs to change.
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSf425hWeCCmQFa1IF_nrGu9ihbM8rB3MAqawdu-3lPVfFCtgg/viewform?usp=header"
OPEN_COLLECTIVE_URL = "https://opencollective.com/sauna_for_all"
SUBSTACK_URL = "https://saunaforall.substack.com"
# Every "Sign up" button goes straight to the subscribe form rather than the
# publication front page, so the call to action lands on the thing it asks
# for. The footer's "Newsletter" nav link still points at the publication.
SUBSTACK_SUBSCRIBE_URL = "https://saunaforall.substack.com/subscribe"

# Worker that proxies the live signatories Google Sheet as JSON, so the
# directory and the homepage tally update without a rebuild.
SIGNATORIES_FEED_ENDPOINT = "https://sauna-for-all-signatories-feed.tiny-block-645d.workers.dev"

# How many signatory cards the directory shows before the "Show more" button.
# Read by js/main.js off the grid, so this is the single place to change it.
SIGNATORY_PAGE_SIZE = 12
CONTACT_EMAIL = "hei@saunaforall.org"

NAV_ITEMS = [
    {"href": "/about", "label": "About", "dropdown": [
        ("/about", "Our story"),
        ("/about#stewards", "Founding Stewards"),
        ("/about#gratitude", "With gratitude"),
    ]},
    {"href": "/charter", "label": "The Charter", "dropdown": [
        ("/charter", "Read the Charter"),
        ("/resources", "Resources"),
        ("/faqs", "FAQs"),
    ]},
    {"href": "/signatories", "label": "Signatories", "dropdown": None},
    {"href": "/news", "label": "News", "dropdown": None},
    {"href": "/contact", "label": "Contact", "dropdown": None},
]

def nav(active):
    def nav_link(item):
        href, label, dropdown = item["href"], item["label"], item["dropdown"]
        is_active = active == href.strip("/") or (active == "home" and href == "/")
        active_attr = ' class="active"' if is_active else ""
        if not dropdown:
            return f'<a href="{href}"{active_attr}>{label}</a>'
        sub_links = "\n".join(f'<a href="{sub_href}">{sub_label}</a>' for sub_href, sub_label in dropdown)
        caret = '<svg class="nav-caret" viewBox="0 0 12 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M1 1.5l5 5 5-5"/></svg>'
        return f'''<div class="nav-item">
      <a href="{href}"{active_attr}>{label}{caret}</a>
      <div class="nav-dropdown">{sub_links}</div>
    </div>'''
    links = "\n".join(nav_link(item) for item in NAV_ITEMS)
    return f'''<header class="site-header">
  <div class="nav">
    <a href="/" class="nav-logo" aria-label="Sauna for All, home"><img src="/images/logo/sauna-for-all-orange.png" alt="" style="height:34px; width:auto;"></a>
    <nav class="nav-links" id="navLinks">
      {links}
    </nav>
    <div class="nav-cta">
      <a href="/signatories#sign" class="btn btn-primary">Sign the Charter</a>
    </div>
    <button class="nav-toggle" id="navToggle" aria-label="Toggle menu" aria-expanded="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M3 6h18M3 12h18M3 18h18"/></svg>
    </button>
  </div>
</header>'''

# ---------------------------------------------------------------------------
# Social links (footer)
# ---------------------------------------------------------------------------
# Inline SVG rather than an icon font or a third-party script: three glyphs
# don't justify another network dependency, and the site has already been
# bitten twice by outside services disappearing.
SOCIAL_LINKS = [
    ("Instagram", "https://www.instagram.com/sauna_for_all/",
     '<path d="M12 2.2c3.2 0 3.6 0 4.85.07 1.17.05 1.8.25 2.23.41.56.22.96.48 1.38.9.42.42.68.82.9 1.38.16.42.36 1.06.41 2.23.06 1.25.07 1.65.07 4.85s0 3.6-.07 4.85c-.05 1.17-.25 1.8-.41 2.23-.22.56-.48.96-.9 1.38-.42.42-.82.68-1.38.9-.42.16-1.06.36-2.23.41-1.25.06-1.65.07-4.85.07s-3.6 0-4.85-.07c-1.17-.05-1.8-.25-2.23-.41a3.8 3.8 0 0 1-1.38-.9 3.8 3.8 0 0 1-.9-1.38c-.16-.42-.36-1.06-.41-2.23C2.21 15.6 2.2 15.2 2.2 12s0-3.6.07-4.85c.05-1.17.25-1.8.41-2.23.22-.56.48-.96.9-1.38.42-.42.82-.68 1.38-.9.42-.16 1.06-.36 2.23-.41C8.44 2.21 8.84 2.2 12 2.2Zm0 1.8c-3.14 0-3.5.01-4.74.07-.9.04-1.38.19-1.7.31-.43.17-.73.37-1.05.69-.32.32-.52.62-.69 1.05-.12.32-.27.8-.31 1.7C3.45 8.5 3.44 8.86 3.44 12s.01 3.5.07 4.74c.4.9.19 1.38.31 1.7.17.43.37.73.69 1.05.32.32.62.52 1.05.69.32.12.8.27 1.7.31 1.24.06 1.6.07 4.74.07s3.5-.01 4.74-.07c.9-.04 1.38-.19 1.7-.31.43-.17.73-.37 1.05-.69.32-.32.52-.62.69-1.05.12-.32.27-.8.31-1.7.06-1.24.07-1.6.07-4.74s-.01-3.5-.07-4.74c-.04-.9-.19-1.38-.31-1.7a2.8 2.8 0 0 0-.69-1.05 2.8 2.8 0 0 0-1.05-.69c-.32-.12-.8-.27-1.7-.31C15.5 4.01 15.14 4 12 4Zm0 3.06a4.94 4.94 0 1 1 0 9.88 4.94 4.94 0 0 1 0-9.88Zm0 1.8a3.14 3.14 0 1 0 0 6.28 3.14 3.14 0 0 0 0-6.28Zm5.14-.72a1.15 1.15 0 1 1 0-2.3 1.15 1.15 0 0 1 0 2.3Z"/>'),
    ("LinkedIn", "https://www.linkedin.com/company/sauna-for-all/",
     '<path d="M4.98 3.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5ZM3 9.25h4v11.5H3V9.25Zm6.5 0h3.83v1.57h.06c.53-.95 1.84-1.95 3.78-1.95 4.04 0 4.79 2.5 4.79 5.76v6.12h-4v-5.43c0-1.3-.03-2.96-1.9-2.96-1.9 0-2.19 1.4-2.19 2.86v5.53h-4V9.25Z"/>'),
    ("Substack", "https://saunaforall.substack.com/",
     '<path d="M3.5 3.5h17v2.6h-17V3.5Zm0 4.55h17V10h-17V8.05Zm0 4.06L12 16.2l8.5-4.09V21L12 17.2 3.5 21v-8.89Z"/>'),
]

def social_icons_html():
    links = "".join(
        f'<a href="{url}" target="_blank" rel="noopener" aria-label="Sauna for All on {name}" title="{name}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{path}</svg></a>'
        for name, url, path in SOCIAL_LINKS)
    return f'<div class="social-links">{links}</div>'

def footer():
    return f'''<footer class="site-footer">
  <div class="container">
    <div class="footer-grid">
      <div class="footer-col" style="max-width:340px;">
        <a href="/" aria-label="Sauna for All, home"><img src="/images/logo/sauna-for-all-orange.png" alt="" style="height:36px; width:auto;"></a>
        <p class="small" style="margin-top:16px; opacity:0.75;">Public Sauna. Common Good.</p>
        {social_icons_html()}
      </div>
      <div class="footer-links">
        <div class="footer-col">
          <h4>The Charter</h4>
          <a href="/charter">Read the Charter</a>
          <a href="/signatories#sign">Sign the Charter</a>
          <a href="/signatories">Signatories</a>
          <a href="/resources">Resources</a>
          <a href="/faqs">FAQs</a>
        </div>
        <div class="footer-col">
          <h4>About</h4>
          <a href="/about">About Sauna for All</a>
          <a href="/about#stewards">Founding Stewards</a>
          <a href="/news">News</a>
        </div>
        <div class="footer-col">
          <h4>Get involved</h4>
          <a href="{SUBSTACK_URL or '#'}">Newsletter</a>
          <a href="{OPEN_COLLECTIVE_URL}">Support our work</a>
          <a href="/contact">Contact</a>
        </div>
      </div>
    </div>
    <div class="footer-bottom">
      <span>&copy; 2026 Sauna for All</span>
    </div>
  </div>
</footer>
<script src="js/main.js"></script>
<script src="js/news-feed.js"></script>
<script src="js/signatories-feed.js"></script>'''

HEAD_EXTRA = ""

def layout(title, description, active, body, body_class=""):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} | Sauna for All</title>
<meta name="description" content="{description}">
<link rel="stylesheet" href="css/style.css">
</head>
<body class="{body_class}">
{nav(active)}
<main>
{body}
</main>
{footer()}
</body>
</html>'''

def write(filename, html):
    path = os.path.join(ROOT, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", filename)

# ---------------------------------------------------------------------------
# Reusable section fragments
# ---------------------------------------------------------------------------
def wave(fill, backdrop, flip=False, h=56, bumps=5.5, amplitude=18.7, phase=1.5):
    """Generates the repeating scalloped wave divider seen throughout the
    style guide (regular, evenly-spaced ripples — not a single smooth S-curve).

    Default bumps/amplitude are measured directly off the brand's SFA_Wave.eps
    asset (peak-to-peak spacing vs. peak-to-trough depth, both scale-free
    ratios) so the curve matches the official artwork rather than an
    approximation: ~5.5 bumps across the full width, amplitude ~7.1% of one
    wavelength. `phase=1.5` starts the curve at a peak (x=0), same as the
    source asset's crop.

    `backdrop` MUST match the color of the section immediately before this
    divider in the DOM — it fills the space behind the wave peaks/troughs so
    there is never a sliver of the page's white background showing through.
    `fill` is the color of the section immediately after (the humps that
    poke upward into the backdrop).

    The SVG scales UNIFORMLY with viewport width (no preserveAspectRatio
    'none', no fixed pixel height) so the bump shape stays proportional and
    never turns spiky/zigzag on narrow screens — `h` sets the rendered
    height only at the 1440px reference width."""
    import math
    width = 1440
    view_h = h
    mid = view_h / 2
    wavelength = width / bumps
    pts = []
    steps = int(bumps * 24)
    for i in range(steps + 1):
        x = width * i / steps
        y = mid + amplitude * math.sin((2 * math.pi * x / wavelength) + (phase * math.pi))
        pts.append(f"{x:.1f},{y:.2f}")
    path_d = "M" + " L".join(pts) + f" L{width},{view_h} L0,{view_h} Z"
    cls = "wave wave-flip" if flip else "wave"
    return f'''<div class="{cls}" style="margin-top:-1px; margin-bottom:-1px; background:{backdrop}; line-height:0;">
<svg viewBox="0 0 {width} {view_h}" style="width:100%; height:auto; display:block;"><path fill="{fill}" d="{path_d}"/></svg>
</div>'''

def wave_mask(fill, edge="top", h=64, bumps=5.5, amplitude=18.7, phase=1.5):
    """A scalloped color mask that sits ON TOP of a photo (inside a
    position:relative container) and appears to bite a wavy edge into it —
    used for the homepage photography band. Unlike wave(), only the solid
    color region is painted; the rest of the SVG is transparent so the photo
    shows through underneath.

    `edge="top"` fills from the very top edge down to the curve (color dips
    down into the photo at each hump); `edge="bottom"` fills from the curve
    down to the bottom edge (color rises up into the photo at each hump).
    Same curve math and same uniform-scaling technique as wave() so it
    matches the brand asset and stays smooth at any width."""
    import math
    width = 1440
    wavelength = width / bumps
    steps = int(bumps * 24)
    pts = []
    for i in range(steps + 1):
        x = width * i / steps
        y = h / 2 + amplitude * math.sin((2 * math.pi * x / wavelength) + (phase * math.pi))
        pts.append(f"{x:.1f},{y:.2f}")
    curve = " L".join(pts)
    if edge == "top":
        path_d = f"M0,0 L{curve} L{width},0 Z"
        pos = "top:-1px;"
    else:
        path_d = f"M0,{h} L{curve} L{width},{h} Z"
        # -1px so the mask bleeds past the photo's edge. The SVG scales with
        # `height:auto`, so its rendered height rarely lands on a whole pixel
        # and a hairline of photo was showing below the wave.
        pos = "bottom:-1px;"
    return f'''<div class="wave-mask" style="position:absolute; left:0; right:0; {pos} line-height:0; pointer-events:none; z-index:1;">
<svg viewBox="0 0 {width} {h}" style="width:100%; height:auto; display:block;"><path fill="{fill}" d="{path_d}"/></svg>
</div>'''

# ---------------------------------------------------------------------------
# THE TEN PRINCIPLES (SPEC.md Section 6.3) -- shared between the Home page
# preview and the full Charter page. Copy is verbatim from the spec; do not
# rewrite, shorten, or add to it.
# ---------------------------------------------------------------------------
PRINCIPLES = [
    {"num": "01", "name": "Access for All", "icon": "network",
     "text": "Public sauna-bathing is for all people. Access means a door everyone can afford to walk through, a building every body can use, a culture where all people are welcomed and safe, and locations communities can actually reach."},
    {"num": "02", "name": "Shared Heat, Shared Space", "icon": "heat",
     "text": "Built on equality and presence, the public sauna-bath is a shared civic place, promoting the health of people and the living world. Community takes work: everyone who enters helps tend it, and is supported to do so."},
    {"num": "03", "name": "Honour Tradition", "icon": "leaf",
     "text": "We honour and support the many cultures and knowledge holders who keep sauna and sweat-bathing alive, entering each tradition as guests."},
    {"num": "04", "name": "Public Good Before Private Gain", "icon": "sun",
     "text": "Whatever the ownership model, a public sauna-bath is run for the public good. Profit may serve that mission, but never override it."},
    {"num": "05", "name": "A Sense of Place", "icon": "place",
     "text": "At its fullest, a public sauna-bath is a community sauna-bath, shaped by its place: in design, story and benefit. It is built with care for where it stands, carrying both the traditions it comes from and the stories of where it now lives, and keeping value in community rather than extracting it."},
    {"num": "06", "name": "Community First", "icon": "lattice",
     "text": "A community sauna-bath answers to its community, shaped by the hands and voices of the people it serves. Visitors are welcomed as guests, in ways that sustain the place rather than strain it."},
    {"num": "07", "name": "Tended With Care", "icon": "weave",
     "text": "Built to evidence-informed best practice, maintained for safety, and operated on safer-space principles, a public sauna-bath is stewarded responsibly, so people are treated with dignity and protected from harm."},
    {"num": "08", "name": "Reciprocity with the Natural World", "icon": "reciprocity",
     "text": "Public sauna-bathing lives in reciprocity with the natural world that sustains it: powered, built and run to tread lightly, giving back more than taking. It draws people into deepening relationship with the living world, with reverence for the peoples who have long bathed in balance with their surroundings."},
    {"num": "09", "name": "Wellbeing That Circulates", "icon": "circulate",
     "text": "Public sauna-bathing builds relational well-being, spreading care outward: for body, mind and spirit, for the bonds between people, for healthy, regenerative local economies. What we learn, we share across borders, building a common body of practice."},
    {"num": "10", "name": "Recognised and Resourced", "icon": "seal",
     "text": "Resilient social infrastructure, built responsibly today so communities can thrive for generations to come, deserves recognition and support: from local and regional government in planning, regulation and funding, and from investors who value it as a public good, not a private bet."},
]
PRINCIPLES_BY_NUM = {p["num"]: p for p in PRINCIPLES}

PRINCIPLE_GROUPS = [
    {"tag": "Practice", "sub": "Foundational values", "nums": ["01", "02", "03"]},
    {"tag": "Keeping", "sub": "Run for public good", "nums": ["04", "05", "06"]},
    {"tag": "Tending", "sub": "Ongoing care", "nums": ["07", "08"]},
    {"tag": "Stewardship", "sub": "Shared futures", "nums": ["09", "10"]},
]

# ---------------------------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------------------------
def page_home():
    # Real hero photo (SPEC.md names no specific file for this slot -- see
    # images/photos/CREDITS.md). This is one of the two Drive photos not
    # already placed elsewhere on the site (2026-13 is used below in
    # "who-we-are", 2026-04/05 on About), used here as the best available
    # interim choice until Becky supplies dedicated hero photography ("people
    # bathing together, documentary style, not lifestyle/stock").
    hero = f'''<section class="hero" id="hero">
  <div class="container hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">A grassroots global movement</span>
      <h1>SAUNA FOR ALL</h1>
      <p class="lede">Ten shared principles for public sauna that is safe, accessible, culturally stewarded, and rooted in the common good. Read and sign the Public Sauna-Bathing Charter.</p>
      <div class="hero-actions">
        <a href="/signatories#sign" class="btn btn-primary">Sign the Charter</a>
        <a href="/charter#principles" class="btn btn-outline-light">Read the Principles</a>
      </div>
    </div>
    <div class="hero-media">
      <img src="/images/photos/sauna-for-all-2026-14.jpg" alt="Sauna culture in Finland, inscribed on UNESCO's Representative List of the Intangible Cultural Heritage of Humanity" style="width:100%; height:100%; object-fit:cover;">
    </div>
  </div>
</section>
{wave("#b3d3f0", backdrop="#0A382D")}'''

    counter = f'''<section class="stat-strip" id="counter" data-feed-endpoint="{SIGNATORIES_FEED_ENDPOINT}">
  <div class="container stat-grid">
    <div class="stat-item"><div class="num" id="statSignatories">{len(SIGNATORIES)}</div><div class="label">Signatories</div></div>
    <div class="stat-item"><div class="num">10</div><div class="label">Principles</div></div>
    <div class="stat-item"><div class="num" id="statCountries">{SIGNATORY_COUNTRY_COUNT}</div><div class="label">Countries</div></div>
    <div class="stat-item"><div class="num">2026</div><div class="label">Introduced at World Sauna Forum</div></div>
  </div>
</section>'''

    # Full-bleed photography band (Lucy's mockup) -- a straight, flat cut
    # where it meets the light-blue counter above, and a wavy cream edge
    # where it meets the charter summary below (so the mask colour matches
    # that next section exactly).
    photo_band = f'''<section style="padding:0;" id="home-photo">
  <div style="position:relative; line-height:0;">
    <img src="/images/photos/sauna-for-all-2026-23.jpg" alt="Bathers walking the boardwalk between sauna and water, seen through birch" class="photo-band-img" style="object-fit:cover;">
    {wave_mask("#f7f4e9", edge="bottom")}
  </div>
</section>'''

    def band_item(p):
        n = p["num"]
        return f'''<a href="/charter#principle-{int(n)}" class="principle-item">
          <span class="icon-plain">{icon_svg_or_img(p["icon"])}</span>
          <span class="principle-item-text"><span class="num">{n}</span><span class="name principle-underline-{n}">{p["name"]}</span></span>
        </a>'''

    def movement_band(group):
        items_html = "".join(band_item(PRINCIPLES_BY_NUM[n]) for n in group["nums"])
        return f'''<div class="principle-band">
      <div class="principle-band-head"><span class="tag">{group["tag"]}: {group["sub"]}</span></div>
      <div class="principle-band-grid">
        {items_html}
      </div>
    </div>'''

    charter_summary = f'''<section class="section bg-cream" id="charter-summary">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">The Charter</span>
      <h2>Ten shared principles</h2>
      <p class="lede muted">Sauna-bathing is growing fast around the world. The Charter helps it grow well, with ten shared principles that keep equality, care, and community at the heart of public sauna.</p>
      <a href="/charter" class="btn btn-outline-dark" style="margin-top:20px;">Read the full Charter</a>
    </div>

    <div class="principle-band-list">
      {"".join(movement_band(g) for g in PRINCIPLE_GROUPS)}
    </div>

    <p class="small" style="margin-top:28px;">What does signing involve? <a href="/faqs" style="text-decoration:underline; font-weight:700;">Read the FAQs</a></p>
  </div>
</section>'''

    why_now = f'''<section class="section bg-white" id="why-now" style="background:#FDF4B0;">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Why now</span>
      <h2>Choices made today will shape public sauna for decades</h2>
    </div>
    <div class="card-grid">
      <div class="info-card"><h3>Decisions are being made now</h3><p>Cities, funders, and tourism organisations are starting to decide what public sauna is, what it should deliver, and how it should be run. Shared principles help those decisions rest on real practice and evidence.</p></div>
      <div class="info-card"><h3>Sauna traditions deserve respect</h3><p>Sauna has been carried by families and communities for generations. As it spreads to new places, the Charter asks that those traditions be understood, honoured, and shared with care.</p></div>
      <div class="info-card"><h3>Good practice should be easy to see</h3><p>As more saunas open, communities and decision-makers need a clear way to recognise places that are safe, well run, and respectful of sauna culture. The Charter gives them a common reference.</p></div>
    </div>
  </div>
</section>'''

    evidence = f'''<section class="section" id="evidence" style="background:#F0D8BC; color:var(--dark-green);">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">The evidence</span>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;">
        <h2 style="margin:0;">The benefits run deep</h2>
        <img src="/images/icons/thumbs-up.png" alt="" style="width:92px; height:92px; flex-shrink:0;" loading="lazy">
      </div>
      <p class="lede" style="margin-top:14px;">Sauna supports body, mind, and community. That is why how public sauna grows matters, and why the Charter asks for care in the way it is built and run.</p>
    </div>
    <ul class="is-list check-mint list-spaced" style="margin-top:6px; max-width:70ch;">
      <li><span><strong>Physical health.</strong> Regular sauna use is linked to lower cardiovascular mortality, and the benefit grows the more often people go.<sup>1</sup></span></li>
      <li><span><strong>Mental health and wellbeing.</strong> In a large study in northern Sweden, sauna bathers reported better mental health, more energy, and less pain, with mental health scores rising the more often they bathed.<sup>2</sup></span></li>
      <li><span><strong>Rest and connection.</strong> Regular bathers describe sauna as a place to recover mentally and to be with others, alongside the physical benefits.<sup>3</sup></span></li>
      <li><span><strong>Belonging.</strong> Frequent sauna use is linked to greater health and wellbeing, and part of that benefit comes from a stronger sense of belonging.<sup>4</sup></span></li>
      <li><span><strong>Local value.</strong> Cities already invest in pools and rinks for health and community. Well-run public saunas offer the same kind of value, close to home and open to all. <em>Case studies coming soon.</em></span></li>
    </ul>
    <p class="small" style="margin-top:16px; opacity:0.85;">Sources: (1) Laukkanen et al., <em>BMC Medicine</em>, 2018. (2) Engstr&ouml;m, H&auml;gglund et al., <em>International Journal of Circumpolar Health</em>, 2024. (3) Engstr&ouml;m, Wiell, H&auml;gglund &amp; Lennkvist, <em>International Journal of Circumpolar Health</em>, 2026. (4) Newson, McGrath et al., <em>Social Science &amp; Medicine</em>, 2026.</p>
  </div>
</section>'''

    who_we_are = f'''<section class="section bg-white" id="who-we-are">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--gold);">Who we are</span>
      <h2 style="margin:14px 0 18px;">Grassroots by design, guided by experience</h2>
      <p class="lede muted">Sauna for All has grown from the ground up, guided by stewards who run public saunas, study sauna culture, and build community, alongside the advisors, operators, and bathers who shape it with them.</p>
      <div style="margin-top:18px; display:flex; flex-direction:column; gap:8px;">
        <a href="/about#stewards" style="text-decoration:underline; font-weight:700;">Meet the founding stewards &rarr;</a>
        <a href="{OPEN_COLLECTIVE_URL}" style="text-decoration:underline; font-weight:700;">Support the movement &rarr;</a>
      </div>
    </div>
    <img src="/images/photos/sauna-for-all-2026-13.jpg" alt="Founding stewards and network members among the initial signatories of the Charter" style="width:100%; height:100%; object-fit:cover;">
  </div>
</section>'''

    newsletter = f'''<section class="section bg-cream" id="newsletter">
  <div class="container" style="max-width:720px; text-align:center;">
    <h2>Stay close on the bench</h2>
    <p class="lede muted" style="margin-top:14px;">Follow the Charter as it grows, learn from operators and researchers, and get invitations to online meet-ups. You&rsquo;ll also hear first when we open new rounds for signatories.</p>
    <a href="{SUBSTACK_SUBSCRIBE_URL}" class="btn btn-solid-orange" style="margin-top:22px; display:inline-block;">Sign up</a>
  </div>
</section>'''

    body = hero + counter + photo_band + charter_summary + why_now + evidence + who_we_are + newsletter
    write("index.html", layout(
        "Home",
        "Sauna for All is a grassroots global movement guiding public sauna-bathing as common good, through the Public Sauna-Bathing Charter.",
        "home", body))

# ---------------------------------------------------------------------------
# OVERVIEW PAGE (the Charter, in full — formerly charter.html)
# ---------------------------------------------------------------------------
CHARTER_PDF_URL = "/files/public-sauna-bathing-charter.pdf"
# The "Download PDF" button now points at the Drive folder (which holds the
# current PDF plus translations as they land) rather than the single file
# bundled in this repo.
CHARTER_DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/1xpRWK0kG0gFhcAJCtuxQe3FpbKu50loO?usp=drive_link"

def page_charter():
    charter_header = f'''<section class="section bg-cream" style="padding-bottom:0;" id="charter-header">
  <div class="container two-col" style="align-items:center;">
   <div>
    <span class="eyebrow" style="color:var(--gold);">The Public Sauna-Bathing Charter</span>
    <h1 style="font-size:clamp(2rem,4vw,2.9rem); margin:14px 0 20px; max-width:22ch;">Ten principles for public sauna as common good</h1>
    <p class="lede muted" style="max-width:64ch;">The Charter sets out shared principles for developing and caring for public sauna responsibly. It gives communities, operators, governments, funders, and researchers a common reference point. Signatories commit to showing how these principles guide their decisions and daily practice.</p>
    <div class="hero-actions" style="margin-top:26px;">
      <a href="/signatories#sign" class="btn btn-primary">Sign the Charter</a>
      <a href="{CHARTER_DRIVE_FOLDER_URL}" class="btn btn-outline-dark" target="_blank" rel="noopener">Download PDF</a>
    </div>
    <p class="small muted" style="margin-top:14px;">Version 1.0, August 19, 2026. Available in other languages soon.</p>
    <div style="margin-top:22px; display:flex; gap:22px; flex-wrap:wrap;">
      <a href="/faqs" style="text-decoration:underline; font-weight:700; font-size:0.92rem;">Read the FAQs &rarr;</a>
      <a href="{OPEN_COLLECTIVE_URL}" style="text-decoration:underline; font-weight:700; font-size:0.92rem;">Support our work &rarr;</a>
    </div>
   </div>
   <img src="/images/photos/sauna-for-all-2026-12.jpg" alt="Water poured over cupped hands in a sauna, a moment of care between bathers" style="width:100%; aspect-ratio:5/6; object-fit:cover;">
  </div>
</section>'''

    def pdetail(p):
        num, name, text = p["num"], p["name"], p["text"]
        icon_html = icon(p["icon"], f"principle-fill-{num}")
        return f'''<div class="principle-detail" id="principle-{int(num)}">
      <div class="principle-detail-icon">{icon_html}<span class="num">{num}</span></div>
      <div class="principle-detail-body">
        <h3>{name}</h3>
        <p>{text}</p>
      </div>
    </div>'''

    def movement_head(range_label, tag, sub):
        return f'''<div class="movement-title"><span class="bar"></span><span class="tag">{range_label} &middot; {tag}</span><span class="sub">&ndash; {sub}</span></div>'''

    RANGE_LABELS = {"Practice": "01&ndash;03", "Keeping": "04&ndash;06", "Tending": "07&ndash;08", "Stewardship": "09&ndash;10"}

    def movement(group):
        rows = "".join(pdetail(PRINCIPLES_BY_NUM[n]) for n in group["nums"])
        return f'''<div class="movement">
      {movement_head(RANGE_LABELS[group["tag"]], group["tag"], group["sub"])}
      <div class="principle-detail-list">{rows}</div>
    </div>'''

    principles = f'''<section class="section bg-cream" id="principles">
  <div class="container">
    <div class="section-head">
      <h2>Ten shared principles</h2>
    </div>
    {"".join(movement(g) for g in PRINCIPLE_GROUPS)}
    <div class="info-card" style="margin-top:20px; padding:32px;">
      <h3 style="font-size:1.15rem;">Putting the principles into practice</h3>
      <p class="muted" style="margin:10px 0 18px;">Sign up for news to receive practical guidance on applying each principle, along with case studies, resources, and invitations to online meet-ups with operators and communities doing this work.</p>
      <a href="{SUBSTACK_SUBSCRIBE_URL}" class="btn btn-solid-orange" style="display:inline-block;">Sign up</a>
    </div>
  </div>
</section>'''

    WHO_CAN_SIGN_GROUPS = [
        ("Those who build and run public sauna", "Operators and keepers, community sauna organisations and networks, designers, builders, and suppliers."),
        ("Those who shape the conditions for it", "Governments and public bodies, funders and investors, researchers and educators."),
        ("Those who use and champion it", "Bathers and advocates."),
    ]
    who_can_sign_html = "".join(
        f'<p style="margin-top:14px;"><strong>{title}.</strong> {body}</p>' for title, body in WHO_CAN_SIGN_GROUPS)

    who_can_sign = f'''<section class="section" id="who-can-sign" style="background:var(--light-blue); color:var(--green-dark);">
  <div class="container two-col" style="align-items:center;">
    <div>
      <div class="section-head">
        <span class="eyebrow">Who can sign</span>
        <h2>Built by, and for, everyone shaping sauna in their communities</h2>
        <p class="lede muted">Anyone working to strengthen public sauna as a common good can sign. You don&rsquo;t need to run a sauna. You simply state what you will do, in your own role, to support the Charter&rsquo;s principles.</p>
      </div>
      {who_can_sign_html}
      <p class="small" style="margin-top:24px; font-weight:700;">Want to join the movement? <a href="#how-signing-works" style="text-decoration:underline;">See how signing works &rarr;</a></p>
    </div>
    <img src="/images/photos/sauna-for-all-2026-21.jpg" alt="L&ouml;yly: water poured from a copper ladle over the hot stones of a sauna stove" style="width:100%; aspect-ratio:5/6; object-fit:cover;">
  </div>
</section>'''

    HOW_SIGNING_STEPS = [
        ("Read the Charter", "Get to know the ten principles and talk them through with your team, board, or council."),
        ("Find a reference", "Ask an existing signatory, a person or an organisation, for a few words of support. We can help if you don&rsquo;t know anyone yet."),
        ("Complete the questionnaire", "The form has three parts: Commitment, Contribution, and Consent and Affirmation."),
        ("Welcome", "The founding stewards review applications together, two to four times a year. Once confirmed, you join the signatories and the wider network, and we check in on your commitments as your work grows."),
    ]
    step_cards_html = "".join(
        f'<div class="info-card"><h3>{i+1}. {title}</h3><p>{body}</p></div>'
        for i, (title, body) in enumerate(HOW_SIGNING_STEPS))

    how_signing_works = f'''<section class="section bg-white" id="how-signing-works">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">How signing works</span>
      <h2>Four steps to joining the movement</h2>
      <p class="lede muted">Signing is free and takes about 15 to 30 minutes. You choose the principles closest to your work and say, in your own words, how you will put them into practice.</p>
    </div>
    <div class="card-grid-4">{step_cards_html}</div>
    <div class="hero-actions" style="margin-top:26px;">
      <a href="/signatories#sign" class="btn btn-primary">Sign the Charter</a>
      <a href="/signatories#list" class="btn btn-outline-dark">Find a signatory</a>
    </div>
    <p class="small muted" style="margin-top:14px;">The first intake round is open now. We&rsquo;d love to have you with us.</p>
  </div>
</section>'''

    is_isnt = f'''<section class="section bg-cream" id="is-isnt">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--purple);">What the Charter is</span>
      <ul class="is-list list-spaced" style="margin-top:18px;">
        <li><span><strong>A shared set of principles.</strong> A common basis for developing and caring for public sauna responsibly.</span></li>
        <li><span><strong>A common reference point.</strong> For communities, operators, governments, funders, researchers, and industry.</span></li>
        <li><span><strong>A guide.</strong> For planning, governance, operations, investment, and policy.</span></li>
        <li><span><strong>A commitment.</strong> To public sauna that is safe, accessible, culturally respectful, and trustworthy.</span></li>
        <li><span><strong>A foundation.</strong> For shared guidance, resources, and learning across the movement.</span></li>
      </ul>
    </div>
    <div>
      <span class="eyebrow" style="color:var(--brown);">What the Charter isn&rsquo;t</span>
      <ul class="isnt-list list-spaced" style="margin-top:18px;">
        <li><span><strong>A certification.</strong> It does not certify, audit, or rank public saunas.</span></li>
        <li><span><strong>A rulebook or technical standard.</strong> It sets out shared principles, and leaves technical detail to local codes and expertise.</span></li>
        <li><span><strong>A replacement for regulation.</strong> It works alongside existing laws and safety requirements.</span></li>
        <li><span><strong>A single model for everyone.</strong> It respects diverse cultures, traditions, and local contexts.</span></li>
        <li><span><strong>Fixed in place.</strong> Its principles are written to endure, and any revisions are rare, considered, and made in the open.</span></li>
      </ul>
    </div>
  </div>
</section>'''

    body = charter_header + principles + who_can_sign + how_signing_works + is_isnt
    write("charter.html", layout(
        "The Charter",
        "The Public Sauna-Bathing Charter: ten shared principles, who can sign, and how signing works.",
        "charter", body))

# ---------------------------------------------------------------------------
# SIGNATORIES PAGE
# ---------------------------------------------------------------------------
# SPEC.md 7.1: "Before the first confirmed signatories: Our first signatories
# will appear here soon." -- so the fallback, if the live sheet and the local
# snapshot are both unreachable, is a genuinely empty list rather than
# fabricated "Name TBD" placeholder rows.
_PLACEHOLDER_SIGNATORIES = []

SIGNATORIES = load_signatories(SIGNATORIES_SHEET_CSV_URL, _PLACEHOLDER_SIGNATORIES)

_logos_fetched, _logos_skipped, _logos_failed = fetch_signatory_logos(SIGNATORIES)
if _logos_fetched:
    print(f"  fetched {len(_logos_fetched)} signatory logo(s) from Drive:")
    for name, fn, size in _logos_fetched:
        print(f"      {name}  ->  images/signatories/{fn}  ({size // 1024} KB)")
if _logos_skipped:
    print(f"  {len(_logos_skipped)} signatory logo(s) already on disk, left as-is")
if _logos_failed:
    print(f"  ! {len(_logos_failed)} signatory logo(s) could not be fetched "
          "(those signatories fall back to an initials badge):")
    for name, why in _logos_failed:
        print(f"      {name}: {why}")
SIGNATORY_COUNTRY_COUNT = len({_country_of(s) for s in SIGNATORIES if _country_of(s)})

def page_signatories():
    # Photo sits beside the header text, same treatment as the About page's
    # "story" section (two-col, rounded corners). No padding-bottom:0 here --
    # the next section has a different background, so the header keeps its
    # normal bottom padding.
    signatories_header = f'''<section class="section bg-cream" id="signatories-header">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--gold);">Signatories</span>
      <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px; max-width:24ch;">You&rsquo;re in good company</h1>
      <p class="lede muted" style="max-width:52ch;">Signatories come from many places and many roles, and each one has said what they will do to support public sauna as a common good. See who has joined, find someone to support your application, or add your name.</p>
      <div class="hero-actions" style="margin-top:22px;">
        <a href="#sign" class="btn btn-primary">Sign the Charter</a>
        <a href="/charter" class="btn btn-outline-dark">Read the Charter</a>
      </div>
    </div>
    <img src="/images/photos/sauna-for-all-signatories-hero.jpg" alt="Signatories celebrating together on a lake dock after a sauna" style="width:100%; height:100%; object-fit:cover;">
  </div>
</section>'''

    BEFORE_YOU_BEGIN = [
        'Talk it through with your team, board, or council.',
        'Ask an existing signatory for a few words of support. <a href="#list" style="text-decoration:underline; font-weight:700;">Find a signatory &rarr;</a>',
        'Draft your commitments first. The form doesn&rsquo;t save as you go.',
    ]
    before_you_begin_html = "".join(f'<li><span>{item}</span></li>' for item in BEFORE_YOU_BEGIN)

    sign = f'''<section class="section" id="sign" style="background:#FDF4B0;">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Sign the Charter</span>
      <h2>Add your name</h2>
      <p class="lede muted">Signing means choosing the principles closest to your work and saying, in your own words, how you will put them into practice. It takes about 15 to 30 minutes.</p>
    </div>
    <div class="two-col">
      <div>
        <h3>Before you begin</h3>
        <ul class="is-list list-spaced" style="margin-top:14px;">{before_you_begin_html}</ul>
        <a href="{GOOGLE_FORM_URL}" class="btn btn-solid-orange" target="_blank" rel="noopener" style="margin-top:20px; display:inline-block;">Open the questionnaire</a>
        <p class="small muted" style="margin-top:10px;">Opens in Google Forms.</p>
      </div>
      <div>
        <h3>What happens next</h3>
        <p class="muted" style="margin-top:10px;">The founding stewards read every application together, two to four times a year. Once confirmed, you join the signatories and the wider network, and we check in on your commitments as your work grows.</p>
        <p class="small" style="margin-top:22px; font-weight:700;">Questions about signing? <a href="/faqs" style="text-decoration:underline;">Read the FAQs &rarr;</a></p>
      </div>
    </div>
  </div>
</section>'''

    def category_pills(cats):
        return "".join(f'<span class="category-pill">{c}</span>' for c in cats)

    def _initials(name):
        """Badge letters for a signatory name.

        Strips punctuation so a name like "SaunaGlo (and Willamette Sauna
        Festivaali)" doesn't turn a bracket into a letter, ignores lowercase
        connectives such as "and", and falls back to the first three
        characters for single-word names ("Saunthropology" -> SAU).
        """
        words = [re.sub(r"[^0-9A-Za-z\u00C0-\u024F]", "", w) for w in re.split(r"\s+", name)]
        words = [w for w in words if w]
        significant = [w for w in words if not w.islower()] or words
        if not significant:
            return "?"
        if len(significant) == 1:
            return significant[0][:3].upper()
        return "".join(w[0] for w in significant)[:3].upper()

    _missing_logos = []

    def _signatory_slug(name):
        return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def logo_tile(s):
        """An initials badge for every signatory, with a self-hosted logo file
        used instead when one exists.

        Two sources, in order: the image the signatory uploaded through the
        form (fetched from Drive at build time by fetch_signatory_logos and
        written to images/signatories/<slug>.<ext>), then an initials badge.

        There is deliberately no third source. Logos were once looked up from
        a favicon service keyed on the signatory's domain, which broke twice --
        Clearbit was retired and began returning 503 for every domain, and
        Google's replacement served 16px icons for some sites that looked poor
        scaled to 80px. Worse, both failed silently: a signatory with no logo
        and a dead service rendered identically, so nobody noticed. Nothing is
        fetched at page load now, so a tile can't break after it ships.
        """
        slug = _signatory_slug(s["name"])
        for ext in ("png", "jpg", "jpeg", "svg", "webp"):
            rel = f"images/signatories/{slug}.{ext}"
            if os.path.exists(os.path.join(ROOT, rel)):
                return (f'<div class="logo-tile" style="width:80px; height:80px; padding:4px; overflow:hidden;">'
                        f'<img src="/{rel}" alt="{s["name"]} logo" loading="lazy" '
                        f'style="max-width:100%; max-height:100%; object-fit:contain;">'
                        f'</div>')
        # Uploaded through the form but not yet committed here. Say so, rather
        # than silently showing initials -- that silence is exactly what made
        # the old favicon breakage invisible.
        if s.get("logo_upload"):
            _missing_logos.append((s["name"], slug, s["logo_upload"]))
        initials = _initials(s["name"])
        return (f'<div class="logo-tile" style="width:80px; height:80px; border-radius:50%; border:none; '
                f'background:var(--light-blue); font-size:0.85rem; font-weight:800; '
                f'color:var(--green-dark);">{initials}</div>')

    def signatory_card(s):
        cats_attr = "|".join(s["categories"])
        search_attr = f'{s["name"]} {s.get("signed_by", "")} {s["country"]}'
        commitment_html = (f'<p class="signatory-commitment">&ldquo;{s["commitment"]}&rdquo;</p>'
                            if s["commitment"] else "")
        signed_by_html = f'<div class="small muted">{s["signed_by"]}</div>' if s.get("signed_by") else ""
        name_html = (f'<a href="{s["url"]}" class="signatory-name-link" target="_blank" rel="noopener">{s["name"]}</a>'
                     if s["url"] and s["url"] != "#" else f'<span class="signatory-name-link">{s["name"]}</span>')
        return f'''<div class="signatory-card" data-categories="{cats_attr}" data-search="{search_attr}" data-country="{s["country"]}">
      <div class="signatory-card-top">
        {logo_tile(s)}
        <div class="category-pills">{category_pills(s["categories"])}</div>
      </div>
      {name_html}
      {signed_by_html}
      <div class="signatory-country">{s["country"]}</div>
      {commitment_html}
    </div>'''

    signatories_html = "".join(signatory_card(s) for s in SIGNATORIES)

    if _missing_logos:
        print(f"  ! {len(_missing_logos)} signatory logo(s) uploaded to the form but not in "
              "images/signatories/ -- showing initials for now:")
        for name, slug, file_id in _missing_logos:
            print(f"      {name}  ->  images/signatories/{slug}.jpg"
                  f"   (Drive id {file_id})")

    # Self-hosted signatory logos, handed to js/signatories-feed.js so cards it
    # renders from the live feed match the ones baked in here. Anything without
    # a file falls back to the initials badge in both places.
    _logo_map = {}
    _logo_dir = os.path.join(ROOT, "images", "signatories")
    if os.path.isdir(_logo_dir):
        for fn in sorted(os.listdir(_logo_dir)):
            stem, dot, ext = fn.rpartition(".")
            if dot and ext.lower() in ("png", "jpg", "jpeg", "svg", "webp"):
                _logo_map.setdefault(stem, f"/images/signatories/{fn}")
    # The live feed Worker returns signatories with no sign-up date on them,
    # so it cannot order them itself -- and because js/signatories-feed.js
    # replaces the whole grid, whatever order it returns would otherwise
    # override the one built here. So the build hands over the order it
    # worked out from the sheet's Timestamp column, as a list of normalised
    # names. Anyone the feed knows about who wasn't in this build is new by
    # definition, and sorts to the end, which is where "earliest first" puts
    # them anyway.
    signatory_order_script = (
        "<script>window.SIGNATORY_ORDER = "
        + json.dumps([_order_key(s["name"]) for s in SIGNATORIES], ensure_ascii=False)
        + ";</script>"
    )
    signatory_logos_script = (
        "<script>window.SIGNATORY_LOGOS = "
        + json.dumps(_logo_map, ensure_ascii=False)
        + ";</script>"
    )

    category_chips_html = "".join(
        f'<button type="button" class="filter-chip" data-category="{c}">{c}</button>' for c in SIGNATORY_FILTERS
    )

    if SIGNATORIES:
        empty_message = "No signatories match your search yet. Try another filter, or sign up for news to hear when new signatories join."
        list_html = f'''<div class="filter-bar">
      <span id="signatoryFilterLabel">Filter by role</span>
      <div class="filter-chips" id="signatoryFilters">
        <button type="button" class="filter-chip active" data-category="">All</button>
        {category_chips_html}
      </div>
      <input type="search" id="signatorySearch" class="filter-search" placeholder="Search by name or country&hellip;" aria-label="Search signatories">
    </div>
    <div class="signatories-grid" id="signatoriesGrid" data-feed-endpoint="{SIGNATORIES_FEED_ENDPOINT}" data-page-size="{SIGNATORY_PAGE_SIZE}">{signatories_html}</div>
    <p class="filter-empty" id="signatoryEmpty">{empty_message}</p>
    <div class="signatories-more">
      <button type="button" class="btn btn-outline-dark" id="signatoryShowMore" hidden>Show more</button>
    </div>'''
    else:
        list_html = '<p class="lede muted">Our first signatories will appear here soon.</p>'

    directory = f'''<section class="section bg-cream" id="list">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Signatories</span>
      <div style="display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap;">
        <h2 style="margin:0;">The people making it happen</h2>
        <img src="/images/icons/thumbs-up.png" alt="" style="width:56px; height:56px; flex-shrink:0;" loading="lazy">
      </div>
      <p class="lede muted" style="margin-top:14px;">These are the operators, communities, and advocates who have committed to public sauna as a common good. Find someone near you, or someone doing work like yours.</p>
      <p class="small muted" style="margin-top:10px;">We&rsquo;re open for new signatories right now. <a href="#sign" style="text-decoration:underline; font-weight:700;">Sign the Charter &rarr;</a></p>
    </div>
    {list_html}
  </div>
</section>'''

    WAYS_TO_HELP = [
        ("Donate.", "Every contribution goes directly to the work of the movement."),
        ("Offer space or hosting", "for gatherings and workshops."),
        ("Share your expertise", "in research, design and building, or translation."),
        ("Coordinate locally", "by connecting signatories in your region."),
        ("Partner with us", "through funding, grants, or sponsorship."),
    ]
    ways_to_help_html = "".join(
        f'<li><span><strong>{lead}</strong> {rest}</span></li>' for lead, rest in WAYS_TO_HELP)

    support = f'''<section class="section bg-green" id="support">
  <div class="container">
    <div class="two-col">
      <div>
        <span class="eyebrow">Support our work</span>
        <h2 style="margin:14px 0 18px; color:var(--white);">Help public sauna grow well</h2>
        <p class="lede" style="opacity:0.9;">Sauna for All is run by volunteers. Your support helps us look after the Charter, keep this site running, and develop gatherings, training, research, and case studies. Whether you can give funding, time, skills, or space, we&rsquo;d love to hear from you.</p>
      </div>
      <div class="stack-20">
        <div class="info-card on-green">
          <h3 style="color:var(--white);">Ways to help</h3>
          <ul class="is-list" style="margin-top:10px; color:var(--cream);">{ways_to_help_html}</ul>
        </div>
        <div class="hero-actions">
          <a href="{OPEN_COLLECTIVE_URL}" class="btn btn-primary">Make a donation</a>
          <a href="/contact" class="btn btn-outline-light">Get in touch</a>
        </div>
      </div>
    </div>
  </div>
</section>'''

    REGIONAL_PARTNERS = []  # SPEC.md 7.3: populated from the "Regional partners"
                             # spreadsheet tab, not yet provided -- shows the
                             # coming-soon line until that source exists.
    if REGIONAL_PARTNERS:
        partners_html = "".join(
            f'<div class="info-card"><h3>{p["name"]}</h3><p class="small muted">{p["region"]}</p><p>{p["description"]}</p>'
            f'<a href="{p["website"]}" style="text-decoration:underline; font-weight:700;">Visit website &rarr;</a></div>'
            for p in REGIONAL_PARTNERS)
        partners_body = f'<div class="card-grid">{partners_html}</div><p class="small muted" style="margin-top:20px;">Interested in coordinating in your region? <a href="/contact" style="text-decoration:underline; font-weight:700;">Get in touch &rarr;</a></p>'
    else:
        partners_body = '<p class="lede muted">Regional partners coming soon. Interested in coordinating in your region? <a href="/contact" style="text-decoration:underline; font-weight:700;">Get in touch &rarr;</a></p>'

    regional_partners = f'''<section class="section bg-white" id="regional-partners">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Regional partners</span>
      <h2>Coordinating locally, connected globally</h2>
      <p class="lede muted">Public sauna looks different in every place. Regional partners are independent organisations that bring signatories together in their area, share local knowledge, and help the Charter take root where they are.</p>
    </div>
    {partners_body}
  </div>
</section>'''

    body = (signatories_header + sign + directory + support + regional_partners
            + signatory_order_script + signatory_logos_script)
    write("signatories.html", layout(
        "Signatories",
        "Sign the Public Sauna-Bathing Charter, see who has already signed, and find out how to support the movement.",
        "signatories", body))

# ---------------------------------------------------------------------------
# ABOUT PAGE (mission + founding stewards, combined)
# ---------------------------------------------------------------------------
def page_about():
    STEWARDS = [
        ("Becky Pelkonen", "Kamu Sauna", "Canada", "becky-pelkonen.jpg"),
        ("Polly Wilson", "Community Sauna Baths", "United Kingdom", "polly-wilson.jpg"),
        ("Charlie Duckworth", "Community Sauna Baths", "United Kingdom", "charlie-duckworth.jpg"),
        ("Freddie Mehigan", "Community Sauna Network", "United Kingdom", "freddie-mehigan.jpg"),
        ("Ian Whelan", "Fád Saoil Saunas", "Ireland", "ian-whelan.jpg"),
        ("Steve Crosbie", "Fád Saoil Saunas", "Ireland", "steve-crosbie.jpg"),
        ("Jason Wong", "Kotisauna", "Canada", "jason-wong.jpg"),
        ("Azar Eskandarpour", "Humans Who Bathe", "Mexico", "azar-eskandarpour.jpg"),
        ("Juho Pelkonen", "Kamu Sauna", "Canada", "juho-pelkonen.jpg"),
        ("Niamh Murphy", "Kamu Sauna", "Canada", "niamh-murphy.jpg"),
    ]
    ADVISORS = [
        ("Mikkel Aaland", "Author, Historian, and Founder of SaunaAid, United States", "mikkel-aaland.jpg"),
        ("Dalva Lamminmäki", "Folklorist and Doctoral Researcher, Finland", "dalva-lamminmaki.jpg"),
        ("Carita Harju", "Sauna from Finland Founder and Executive Director, Finland", "carita-harju.jpg"),
    ]

    def person(name, role, photo=None):
        if photo:
            avatar = f'<img src="/images/headshots/{photo}" alt="{name}" loading="lazy">'
        else:
            initials = "".join([p[0] for p in name.split()[:2]])
            avatar = initials
        return f'''<div class="person"><div class="avatar">{avatar}</div><div class="name">{name}</div><div class="role">{role}</div></div>'''

    stewards_html = "".join(person(name, f"{org}, {country}", photo) for name, org, country, photo in STEWARDS)
    advisors_html = "".join(person(name, role, photo) for name, role, photo in ADVISORS)

    body = f'''<section class="section bg-cream" style="padding-bottom:0;" id="story">
  <div class="container two-col">
    <div>
      <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 18px;">Public sauna as common good</h1>
      <p class="lede muted" style="max-width:52ch;">Around the world, people are rediscovering public sauna, both for their own wellbeing and for the life it brings to communities.</p>
      <p class="lede muted" style="max-width:52ch; margin-top:16px;">Sauna for All is a grassroots movement guiding this resurgence through shared values, evidence, and collaboration.</p>
      <p class="lede muted" style="max-width:52ch; margin-top:16px;">Our aim is for public sauna to grow as a trusted part of civic and cultural life, rooted in the common good.</p>
      <a href="#stewards" style="display:inline-block; margin-top:18px; text-decoration:underline; font-weight:700;">Meet the founding stewards &rarr;</a>
    </div>
    <img src="/images/photos/sauna-for-all-2026-05.jpg" alt="Steve Crosbie and Ian Whelan of F&aacute;d Saoil Saunas, founding stewards of the Public Sauna-Bathing Charter" style="width:100%; aspect-ratio:5/6; object-fit:cover;">
  </div>
</section>

<section class="section bg-cream" id="what-we-do">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">What we do</span>
      <h2>A charter, a network, and a shared voice</h2>
    </div>
    <div class="card-grid">
      <div class="info-card"><h3>1. A charter</h3><p>Ten shared principles, shaped together by the people who build and run public sauna.</p></div>
      <div class="info-card"><h3>2. A network</h3><p>We connect operators, hosts, trainers, researchers, and stewards so no one has to build alone. Signatories can join our online community to share ideas and meet others doing this work.</p></div>
      <div class="info-card"><h3>3. A shared voice</h3><p>Together, we help funders, cities, and policymakers see community sauna as something worth investing in and planning for well.</p></div>
    </div>
    <a href="{OPEN_COLLECTIVE_URL}" class="btn btn-primary" style="margin-top:26px; display:inline-block;">Support our work</a>
  </div>
</section>

<section class="section bg-white" id="stewards">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Founding Stewards</span>
      <h2>Guided by an international steering group</h2>
      <p class="lede muted">The founding stewards are practitioners, researchers, and community leaders who run, study, and champion public sauna in their own communities. Together, they care for the Charter, support signatories in keeping their commitments, and help build the shared knowledge and research that strengthen public sauna around the world.</p>
    </div>
    <div class="people-grid">{stewards_html}</div>
    <p class="small muted" style="margin-top:34px; font-weight:700;">With Special Thanks to Advisors</p>
    <div class="people-grid" style="grid-template-columns:repeat(3,1fr); max-width:640px; margin-top:14px;">{advisors_html}</div>
  </div>
</section>

<section class="section bg-cream" id="gratitude">
  <div class="container two-col">
    <div>
      <span class="eyebrow">With gratitude</span>
      <h2>Many have carried the water</h2>
      <p class="lede muted">People across the sauna world have shared their knowledge and encouragement as the Charter took shape. We thank Sauna from Finland for welcoming this work at the World Sauna Forum, the International Sauna Congress for making room for it, and the grassroots organisers who have stepped forward as early signatories.</p>
      <a href="/signatories" style="display:inline-block; margin-top:18px; text-decoration:underline; font-weight:700;">Meet the signatories and wider network &rarr;</a>
    </div>
    <div>
      <img src="/images/photos/sauna-for-all-2026-04.jpg" alt="Sauna networking and community gathering as part of the World Sauna Forum in Jyväskylä, Finland" style="width:100%; height:100%; object-fit:cover;">
    </div>
  </div>
</section>

<section class="section bg-white" id="get-involved">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Get involved</span>
      <h2>Want to help shape what comes next?</h2>
    </div>
    <div class="card-grid-2">
      <div class="info-card cta-card">
        <h3>Sign the Charter</h3>
        <p>Ready to commit? Signing means sharing how the Charter&rsquo;s principles show up in your work. It takes about 15 to 30 minutes.</p>
        <a href="/signatories#sign" class="btn btn-outline-dark" style="margin-top:14px; display:inline-block; background:#fbec82;">Sign the Charter</a>
      </div>
      <div class="info-card cta-card">
        <h3>Support our work</h3>
        <p>Sauna for All is run by volunteers. Your contribution keeps the Charter, this site, and future gatherings going.</p>
        <a href="{OPEN_COLLECTIVE_URL}" class="btn btn-outline-dark" style="margin-top:14px; display:inline-block; background:#e7c196;">Make a donation</a>
      </div>
    </div>
    <div class="card-grid-2" style="margin-top:24px;">
      <div>
        <h3>Stay close on the bench</h3>
        <p class="small muted" style="margin-top:8px;">News, stories, and invitations to online meet-ups.</p>
        <a href="{SUBSTACK_SUBSCRIBE_URL}" style="display:inline-block; margin-top:10px; text-decoration:underline; font-weight:700;">Sign up &rarr;</a>
      </div>
      <div>
        <h3>Contact us</h3>
        <p class="small muted" style="margin-top:8px;">A question, an idea, or a story to share? We&rsquo;d love to hear from you.</p>
        <a href="/contact" style="display:inline-block; margin-top:10px; text-decoration:underline; font-weight:700;">Get in touch &rarr;</a>
      </div>
    </div>
  </div>
</section>'''
    write("about.html", layout(
        "About",
        "Sauna for All is a grassroots movement guiding public sauna-bathing as common good, and the founding stewards behind it.",
        "about", body))

# ---------------------------------------------------------------------------
# FAQS PAGE
# ---------------------------------------------------------------------------
def page_faqs():
    # SPEC.md 6.7: exact text of all 16 questions and answers from
    # /content/faqs.md ("The Public Sauna-Bathing Charter Frequently Asked
    # Questions, V1, August 19, 2026"), supplied by Becky via Drive and
    # transcribed verbatim below (content_source/faqs_v1.pdf).
    FAQS = [
        ("What is the Public Sauna-Bathing Charter?",
         '<p>The Charter is a shared statement of ten principles for advancing sauna-bathing as a public good. '
         'It unites the people and organisations who build, run and champion public saunas around the world, '
         'and gives municipalities, funders and communities a common reference for what responsible, accessible '
         'public sauna looks like, respectful of cultural origins.</p>'
         '<p>The Charter was drafted by community and public sauna advocate Becky Pelkonen (Kamu Sauna, Sauna '
         'from Finland, University of Eastern Finland) and introduced in draft at the World Sauna Forum 2026, '
         'held by Sauna from Finland in Jyv&auml;skyl&auml;, Finland. It was developed under the advice of Polly '
         'Wilson and Charlie Duckworth (Community Sauna Baths, UK), Freddie Mehigan (Community Sauna Network, '
         'UK), Azar Eskandarpour (Humans Who Bathe), Ian Whelan and Steve Crosbie (Fad Saoil Saunas, Ireland), '
         'Juho Pelkonen and Niamh Murphy (Kamu Sauna Canada), Jason Wong (Kotisauna Canada), and with guidance '
         'from knowledge holders Mikkel Aaland and Dalva Lamminm&auml;ki. As such, it is stewarded by a founding '
         'group representing community sauna champions and organisations across several countries.</p>'),
        ("What is the commitment of becoming a Charter signatory?",
         '<p>Signing means choosing the principles most relevant to your work and stating, in your own words, '
         'how you will put them into practice. Your commitments are recorded with your signature and revisited '
         'in future check-ins.</p>'
         '<p>The Charter values meaningful commitment over the number of signatories.</p>'),
        ("Who can sign?",
         '<p>Anyone working to strengthen public sauna as a common good can sign, including public sauna '
         'operators and keepers, community sauna organisations and networks, municipalities and Indigenous '
         'Nations, tourism and public health organisations, researchers and educators, designers, builders, '
         'manufacturers and suppliers, funders and investors, and individual bathers and advocates.</p>'
         '<p>You do not need to run a sauna. You simply need to state what you will do, in your own role, to '
         'support the Charter&rsquo;s principles.</p>'
         '<p>Two conditions apply:</p>'
         '<ul><li>A reference is required. New signatories need a letter or statement of reference from an '
         'existing signatory, either an individual or organisation. Founding and initial signatories are '
         'exempt.</li>'
         '<li>Public sauna operators should meet the Charter&rsquo;s definition of public sauna, outlined in the '
         'next answer.</li></ul>'),
        ("Saunas are found in spas, hotels, gyms, and clubs as amenities. Are they part of the movement?",
         '<p>Saunas in spas, hotels, gyms, and clubs are part of sauna culture, and many people first encounter '
         'the practice there. The Charter&rsquo;s focus is narrower: public sauna-baths where broad and equitable '
         'access is a priority.</p>'
         '<p>An amenity serves its guests. A public sauna-bath serves its public.</p>'
         '<p>For operators, this distinction may affect eligibility to sign. A sauna must offer published public '
         'sessions that people can attend individually, without requiring exclusive membership, an overnight '
         'stay, or the purchase of another product or service.</p>'
         '<p>Private sessions, memberships, and private hire can exist alongside public access. A sauna does not '
         'need to operate exclusively as a public sauna-bath to qualify. What matters is that meaningful public '
         'access is part of its regular operation.</p>'
         '<p>A sauna open only to exclusive members, hotel guests, private groups, or another restricted group is '
         'considered a private amenity and is not currently eligible to sign.</p>'
         '<p>Operators who do not yet meet the definition of public sauna are still welcome to connect with the '
         'movement, learn from the Charter, and work toward broader public access.</p>'
         '<p>Our wider aim is to strengthen sauna practice everywhere, and to showcase the many ways sauna '
         'can be operated for the public good.</p>'),
        ("Is this a certification? If I sign, can I tell the public I am certified?",
         '<p>No. Signing the Charter is a public commitment, not a certification.</p>'
         '<p>The Charter does not audit or accredit operations, and signing does not certify safety, quality, or '
         'authenticity. Signatories are welcome to say they have signed the Charter and to share their '
         'commitments, but should not describe themselves as certified, accredited, or endorsed by the Charter '
         'or its stewards.</p>'
         '<p>That distinction matters. It helps the public understand what signing means and protects the '
         'integrity of the commitments made by signatories.</p>'
         '<p>For now, the Charter is focused on building shared principles, stronger practice, and collective '
         'accountability across a growing movement. In time, we hope to work with wider networks, cultural '
         'representatives, and knowledge holders to explore training and accreditation that is genuinely grounded '
         'in sauna practice and tradition.</p>'),
        ("What are the requirements? Are there penalties if we fall short?",
         '<p>The Charter is voluntary and works through self-regulation, transparent reporting, and '
         'community-based accountability. There is no routine audit or inspection by the stewards.</p>'
         '<p>When signing, you choose the principles most relevant to your work, make specific commitments, and '
         'explain how you will know they are being put into practice. Future check-ins return to those '
         'commitments.</p>'
         '<p>Signing also requires a reference from an existing signatory, either an individual or an '
         'organisation.</p>'
         '<p>The Charter is intended to support learning and improvement, not punish honest shortcomings. '
         'However, if a signatory&rsquo;s practices are found to be causing serious harm to bathers, communities, '
         'or the traditions the Charter seeks to honour, the founding stewards may revoke signatory status by '
         'consensus.</p>'),
        ("How do we sign?",
         '<p>Start by building alignment within your organisation. For a municipality, that may mean council or '
         'the mayor&rsquo;s office; for an organisation, your board or team; for an individual, simply your own '
         'considered commitment.</p>'
         '<p>Then complete the signing questionnaire, which has three parts: Commitment, Contribution, and '
         'Consent and Affirmation. You will also need a reference from an existing signatory.</p>'
         '<p>Signing takes place in set intake rounds, two to four times per year, announced in advance. The '
         'stewards review each round together before new signatories are confirmed.</p>'),
        ("Is there a fee?",
         '<p>No. There is currently no mandatory fee to sign the Charter.</p>'
         f'<p>Donations are gratefully received and go directly toward the work of the movement. '
         f'<a href="{OPEN_COLLECTIVE_URL}" style="text-decoration:underline; font-weight:700;">Donate &rarr;</a></p>'
         '<p>Funds are stewarded by the founding stewards and used for Charter administration, online '
         'infrastructure, and the development of gatherings, training, research, and case studies.</p>'
         '<p>If you&rsquo;re interested in contributing time, skills, or other in-kind support instead of money, '
         'we&rsquo;d love to hear from you. '
         '<a href="/contact" style="text-decoration:underline; font-weight:700;">Get in touch &rarr;</a></p>'),
        ("What do we mean by these terms?",
         '<p><strong>Sauna-bathing.</strong> A living culture and practice rooted in Finnish, Baltic-Finnic, and '
         'Nordic traditions. Its heart is the sauna room and the pouring of water on hot stones, known in Finnish '
         'as l&ouml;yly. Sauna is a Finnish word; closely related traditions are known by other names, such as '
         'badstue in Norwegian, bastu in Swedish, and saun in Estonian.</p>'
         '<p><strong>Public sauna-bath.</strong> A sauna-bathing space where broad and equitable public access is '
         'the priority. People can attend individually during published public sessions, on clear terms, without '
         'needing an overnight stay, membership in a particular group, or the purchase of another product or '
         'service. Private hire and memberships may exist alongside public sessions. Public sauna-baths can be '
         'municipal, non-profit, cooperative, community-owned, social enterprise, commercial, or hybrid. What '
         'makes a sauna-bath public is access, not ownership.</p>'
         '<p><strong>Community sauna-bath.</strong> A public sauna-bath rooted in a particular place and shaped '
         'by the people who tend it. Community members have genuine belonging and stake, and the community is '
         'its primary beneficiary. Visitors are welcome as guests into something built for the community '
         'first.</p>'
         '<p><strong>Sweat-bathing.</strong> The wider family of heat- and steam-bathing traditions found across '
         'many cultures. These include sauna, hammam, banya, jjimjilbang, mushi-buro, temazcal, Indigenous '
         'sweat-lodge ceremonial practices, Tigh &rsquo;n Alluis and many others. Each has its own name, '
         'traditions, knowledge holders, and cultural meaning, and should be understood on its own terms.</p>'),
        ("Why does the Charter honour many sweat-bathing traditions?",
         '<p>Because precision and respect go together. Sweat-bathing belongs to many cultures. This Charter '
         'focuses on one branch of that wider family: sauna-bathing, a living culture rooted in Finnish, '
         'Baltic-Finnic, and Nordic traditions and practised in place-based ways around the world.</p>'
         '<p>Sauna is a Finnish word. Other cultures know their practices by their own names, and those names '
         'carry knowledge, history, and meaning. When every heated room is called a sauna, distinct traditions '
         'can become blurred. Holding the terms steady helps each remain visible. Many names, one river.</p>'
         '<p>The two sweat-bathing traditions currently inscribed on UNESCO&rsquo;s Representative List of the '
         'Intangible Cultural Heritage of Humanity, '
         '<a href="https://ich.unesco.org/en/RL/smoke-sauna-tradition-in-voromaa-00951" style="text-decoration:underline; font-weight:700;">the smoke sauna tradition of V&otilde;romaa in Estonia</a> '
         'and '
         '<a href="https://ich.unesco.org/en/RL/sauna-culture-in-finland-01596" style="text-decoration:underline; font-weight:700;">sauna culture in Finland</a> '
         ', are both Baltic-Finnic. The Charter also honours traditions including Tigh &rsquo;n Alluis, '
         'hammam, banya, jjimjilbang, mushi-buro, temazcal, Indigenous sweat-lodge ceremonial practices, and many '
         'others, each on its own terms rather than flattened into one.</p>'
         '<p>We enter every sauna-bath, every sweat-bath, and every culture&rsquo;s practice as guests.</p>'),
        ("Why does the Charter reference United Nations frameworks?",
         '<p>Sauna-bathing is a global movement, and public sauna-bathing is about the common good.</p>'
         '<p>The Charter connects its work to three wider UN frameworks: the '
         '<a href="http://www.harmonywithnatureun.org/" style="text-decoration:underline; font-weight:700;">Harmony with Nature programme</a>, '
         'the '
         '<a href="https://sdgs.un.org/goals" style="text-decoration:underline; font-weight:700;">Sustainable Development Goals</a>, '
         'and the '
         '<a href="https://www.untourism.int/sustainable-development/international-year-of-sustainable-and-resilient-tourism-2027" style="text-decoration:underline; font-weight:700;">UN International Year of Sustainable and Resilient Tourism (2027)</a>.</p>'
         '<p>Public sauna-bathing can be low-footprint, culturally rooted, community-led infrastructure. Linking '
         'the Charter to these wider frameworks helps governments, funders, and other decision-makers recognise '
         'its social, cultural, environmental, and community value.</p>'),
        ("Who are the founding stewards?",
         '<p>The founding stewards bring together practitioners, community sauna leaders, researchers, and '
         'knowledge holders from across the international sauna movement.</p>'
         '<p>They include Polly Wilson and Charlie Duckworth (Community Sauna Baths, UK), Freddie Mehigan '
         '(Community Sauna Network, UK), Azar Eskandarpour (Humans Who Bathe), Ian Whelan and Steve Crosbie (Fad '
         'Saoil Saunas, Ireland), Juho Pelkonen and Niamh Murphy (Kamu Sauna, Canada), and Jason Wong (Kotisauna, '
         'Canada), with guidance from knowledge holders Mikkel Aaland and Dalva Lamminm&auml;ki.</p>'
         '<p>The initiative is led by Becky Pelkonen (Kamu Sauna, Sauna from Finland, University of Eastern '
         'Finland).</p>'),
        ("How did we get here? The Sauna for All timeline",
         '<p>No single thread leads here. Public saunas have been built, revived, and tended by many hands in '
         'many places. The Charter gathers from that work. Some markers along the way:</p>'
         '<ul>'
         '<li><strong>2014</strong>: The smoke sauna tradition of V&otilde;romaa, Estonia, is inscribed on '
         'UNESCO&rsquo;s Representative List of the Intangible Cultural Heritage of Humanity.</li>'
         '<li><strong>2017</strong>: Sauna culture is added to Finland&rsquo;s National Inventory of '
         'Living Heritage, an important step toward UNESCO nomination. Sauna clubs and associations across '
         'Finland take up the campaign the following year.</li>'
         '<li><strong>2020</strong>: Sauna culture in Finland is inscribed on UNESCO&rsquo;s '
         'Representative List of the Intangible Cultural Heritage of Humanity, recognising sauna as living '
         'heritage and raising its international visibility.</li>'
         '<li><strong>2020s</strong>: A new wave of public and community saunas takes root across the UK, '
         'Ireland, the Nordics, North America, and beyond, alongside growing research on sauna, health, '
         'wellbeing, and social connection.</li>'
         '<li><strong>June 2026</strong>: Finland adds perinnesaunottaminen to its National Inventory of '
         'Living Heritage: the tradition of being bathed by a sauna healer, including sauna songs, spells, and '
         'practices marking important moments in life. The application is developed by practitioners through '
         'Perinnesaunottajat ry and Taivaannaula ry.</li>'
         '<li><strong>June 2026</strong>: At the World Sauna Forum in Jyv&auml;skyl&auml;, Finland, the '
         '&ldquo;Sauna for Society: Global Action for Community Sauna&rdquo; workshop brings together '
         'practitioners from multiple countries. The idea for a shared Public Sauna-Bathing Charter is carried '
         'forward from that gathering by the founding stewards.</li>'
         '<li><strong>2026&ndash;2027</strong>: The Charter is refined with stewards and founding '
         'signatories, the first signing rounds open, and Sauna for All begins building a wider international '
         'network around public sauna as a common good, including alignment with the UN International Year of '
         'Sustainable and Resilient Tourism 2027.</li>'
         '</ul>'
         '<p>This timeline will continue to grow as new milestones, gatherings, and developments unfold.</p>'),
        ("Why is 2027 significant?",
         '<p>The United Nations has declared 2027 the International Year of Sustainable and Resilient '
         'Tourism.</p>'
         '<p>Public sauna-bathing belongs in that conversation. At its best, it is low-footprint, '
         'community-rooted infrastructure that can keep value in place, strengthen local culture, and deepen '
         'visitors&rsquo; relationship with the communities they enter.</p>'
         '<p>The International Year gives the movement a global moment to show how public sauna can contribute '
         'to more regenerative, resilient, and community-led tourism.</p>'),
        ("How does the Charter change over time?",
         '<p>The ten principles are written to endure. The Charter may be revised when needed, but changes are '
         'rare, considered, versioned, and made openly.</p>'
         '<p>Any signatory may propose a change. Proposals are welcomed, but not every suggestion will result in '
         'a revision or be taken forward for formal consideration.</p>'
         '<p>Supporting guidance, resources, and tools can evolve more continuously as the movement learns and '
         'grows.</p>'),
        ("How do I express interest or ask a question?",
         f'<p>Web: <a href="/" style="text-decoration:underline; font-weight:700;">www.saunaforall.org</a><br>'
         f'Email: hei@saunaforall.org</p>'),
    ]

    def faq_item(n, q, a):
        return (f'<details class="faq-item" id="faq-{n}">'
                f'<summary>{q}<svg class="faq-caret" viewBox="0 0 12 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M1 1.5l5 5 5-5"/></svg></summary>'
                f'<div class="faq-answer">{a}</div></details>')
    faqs_html = "".join(faq_item(i, q, a) for i, (q, a) in enumerate(FAQS, start=1))

    version_line = '<p class="small muted" style="margin-top:14px;">Version 1, August 19, 2026</p>'

    body = f'''<section class="section bg-cream" style="padding-bottom:0;">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">FAQs</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px;">Frequently asked questions</h1>
    <p class="lede muted" style="max-width:64ch;">Answers to common questions about signing, the Charter&rsquo;s scope, and governance.</p>
    {version_line}
  </div>
</section>
<section class="section bg-cream">
  <div class="container" style="max-width:820px;">
    <div class="faq-list">{faqs_html}</div>
  </div>
</section>'''
    write("faqs.html", layout(
        "FAQs",
        "Frequently asked questions about the Public Sauna-Bathing Charter and the Sauna for All movement.",
        "faqs", body))

# ---------------------------------------------------------------------------
# NEWS PAGE
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# NEWS PAGE (SPEC.md Section 6.5 / 7.2 / 7.5)
# ---------------------------------------------------------------------------
# The Cloudflare Worker that fetches and caches the Substack feed (see
# workers/substack-feed/) -- set to its deployed URL once SUBSTACK_URL is
# known and the worker is deployed. Empty for now, which js/news-feed.js
# treats the same as "feed unreachable" and shows the spec's empty state.
NEWS_FEED_ENDPOINT = ""

# SPEC.md 7.5: logos live in a "Press logos" Drive folder (not yet shared)
# with an accompanying "Press links" sheet mapping each to its article.
# The section stays hidden until at least three exist, so an empty list
# here is the correct default, not a placeholder to fill by hand later --
# it should come from that folder once it exists.
PRESS_LOGOS = []  # [{"name": ..., "logo_url": ..., "article_url": ...}, ...]
ALL_COVERAGE_URL = ""  # SPEC.md Section 4: [ADD LINK]

def page_news():
    news_header = f'''<section class="section bg-cream" style="padding-bottom:0;" id="news-header">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">News</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px;">Stories and updates from the movement</h1>
    <p class="lede muted" style="max-width:64ch;">News from Sauna for All, and coverage of public sauna and the Charter from around the world.</p>
  </div>
</section>'''

    posts = load_substack_posts()

    def news_card(post):
        # If the image 404s or the CDN link has expired, swap in the branded
        # placeholder rather than leaving a broken 16:10 hole in the card.
        # (Grab the parent first: replacing the markup detaches this <img>.)
        fallback = ("var p=this.parentElement;"
                    "p.insertAdjacentHTML('afterbegin',"
                    "'&lt;div class=\\'placeholder-img\\'&gt;&lt;span&gt;Sauna for All&lt;/span&gt;&lt;/div&gt;');"
                    "this.remove();")
        cover = (f'<img class="cover" src="{esc(post["image"])}" alt="" loading="lazy" onerror="{fallback}">'
                 if post["image"]
                 else '<div class="placeholder-img"><span>Sauna for All</span></div>')
        date_html = (f'<div class="meta"><time datetime="{post["date_iso"]}">{post["date_label"]}</time></div>'
                     if post["date_label"] else "")
        summary_html = (f'<p class="small muted">{esc(post["summary"])}</p>'
                        if post["summary"] else "")
        return f'''<a class="news-card" href="{post["link"]}" target="_blank" rel="noopener">
      {cover}
      <div class="news-card-body">
        <h3>{esc(post["title"])}</h3>
        {date_html}
        {summary_html}
        <span class="news-card-more">Read more &rarr;</span>
      </div>
    </a>'''

    cards_html = "".join(news_card(p) for p in posts)
    # The empty state only shows when there is genuinely nothing to show.
    empty_style = "display:none;" if posts else ""

    updates = f'''<section class="section bg-cream" id="updates">
  <div class="container">
    <div class="card-grid" id="newsGrid" data-feed-endpoint="{NEWS_FEED_ENDPOINT}">{cards_html}</div>
    <p class="lede muted" id="newsEmpty" style="text-align:center; padding:20px 0; {empty_style}">News is on its way. Sign up to hear first.</p>
    <div style="text-align:center; margin-top:10px;">
      <button type="button" id="newsLoadMore" class="btn btn-outline-dark" style="display:none;">Load more</button>
    </div>
  </div>
</section>'''

    news_newsletter = f'''<section class="section bg-white" id="news-newsletter">
  <div class="container" style="max-width:640px; text-align:center;">
    <p class="lede"><strong>Stay close on the bench.</strong> Get updates like these in your inbox.</p>
    <a href="{SUBSTACK_SUBSCRIBE_URL}" class="btn btn-solid-orange" style="margin-top:14px; display:inline-block;">Sign up</a>
  </div>
</section>'''

    featured = ""
    if len(PRESS_LOGOS) >= 3:
        logos_html = "".join(
            f'<a href="{p["article_url"]}" class="logo-tile press-logo" target="_blank" rel="noopener">'
            f'<img src="{p["logo_url"]}" alt="{p["name"]}" style="max-width:100%; max-height:100%; object-fit:contain;"></a>'
            for p in PRESS_LOGOS)
        coverage_link = (f'<a href="{ALL_COVERAGE_URL}" style="text-decoration:underline; font-weight:700;">See all coverage &rarr;</a>'
                          if ALL_COVERAGE_URL else "")
        featured = f'''<section class="section bg-cream" id="featured">
  <div class="container">
    <div class="section-head">
      <h2>As featured in</h2>
    </div>
    <div class="logo-row">{logos_html}</div>
    {coverage_link}
  </div>
</section>'''

    body = news_header + updates + news_newsletter + featured
    write("news.html", layout(
        "News",
        "News from Sauna for All, and coverage of public sauna and the Charter from around the world.",
        "news", body))

# ---------------------------------------------------------------------------
# RESOURCES PAGE (SPEC.md Section 6.6 / 7.6)
# ---------------------------------------------------------------------------
RESOURCES = []  # Populated from the "Resources" tab in the signatory
                 # spreadsheet (Title, Category, Short description, Link,
                 # Related principles, Date, Show on website) once that tab
                 # exists. Until then every category shows "Coming soon".

RESOURCE_CATEGORIES = [
    ("Guidance", "Practical support for applying each principle."),
    ("Case studies", "Stories from public saunas around the world."),
    ("Research library", "Studies on sauna, health, wellbeing, and community."),
    ("Templates and tools", "Shared policies, procedures, and planning documents from signatories."),
]

def page_resources():
    def resource_category_card(name, desc):
        items = [r for r in RESOURCES if r.get("category") == name]
        if not items:
            return f'''<div class="info-card">
      <span class="small muted" style="font-weight:700; text-transform:uppercase; letter-spacing:0.04em;">Coming soon</span>
      <h3 style="margin-top:8px;">{name}</h3>
      <p>{desc}</p>
    </div>'''
        cards = "".join(
            f'<div class="info-card" style="margin-top:14px;"><span class="category-pill">{name}</span>'
            f'<h4 style="margin-top:8px;">{r["title"]}</h4><p class="small">{r["description"]}</p>'
            f'<a href="{r["link"]}" style="text-decoration:underline; font-weight:700;">View resource &rarr;</a></div>'
            for r in items)
        return f'<div><h3>{name}</h3><p class="muted">{desc}</p>{cards}</div>'

    categories_html = "".join(resource_category_card(name, desc) for name, desc in RESOURCE_CATEGORIES)

    body = f'''<section class="section bg-cream" style="padding-bottom:0;" id="resources-header">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">Resources</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px; max-width:20ch;">Tools for building public sauna well</h1>
    <p class="lede muted" style="max-width:64ch;">We&rsquo;re gathering guidance, research, and real examples to help operators, communities, and decision-makers put the Charter&rsquo;s principles into practice.</p>
  </div>
</section>
<section class="section bg-cream">
  <div class="container">
    <div class="card-grid-4">{categories_html}</div>
    <div class="info-card" style="margin-top:28px;">
      <p style="margin-bottom:14px;">Resources coming soon. Sign up for news to hear when they&rsquo;re ready.</p>
      <a href="{SUBSTACK_SUBSCRIBE_URL}" class="btn btn-solid-orange" style="display:inline-block;">Sign up</a>
    </div>
    <p class="small muted" style="margin-top:20px;">Have a resource to share? Want to collaborate on a case study? <a href="/contact" style="text-decoration:underline; font-weight:700;">Get in touch &rarr;</a></p>
  </div>
</section>'''
    write("resources.html", layout(
        "Resources",
        "Guidance, case studies, research, and templates and tools for building public sauna well.",
        "resources", body))

# ---------------------------------------------------------------------------
# CONTACT PAGE (SPEC.md Section 6.8)
# ---------------------------------------------------------------------------
CONTACT_REASONS = [
    "General question",
    "Signing the Charter",
    "Media enquiry",
    "Regional partnership",
    "Supporting our work",
    "Sharing a resource or case study",
    "Other",
]

def page_contact():
    reason_options_html = "".join(f'<option value="{r}">{r}</option>' for r in CONTACT_REASONS)

    body = f'''<section class="section bg-cream" style="padding-bottom:0;" id="contact-header">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">Contact</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px;">Get in touch</h1>
    <p class="lede muted" style="max-width:64ch;">Have a question, an idea, or a story to share? We&rsquo;d love to hear from you.</p>
  </div>
</section>
<section class="section bg-cream" style="padding-top:0;" id="media">
  <div class="container">
   <div style="max-width:640px; margin-top:40px;">
    <h2 style="font-size:1.3rem;">For media</h2>
    <p class="muted" style="margin-top:8px;">Writing about public sauna or the Charter? We&rsquo;re happy to help with background, key facts, logos, photos, and interviews with our founding stewards.</p>
    <p class="small muted" style="margin-top:10px;">Media enquiries: <a href="mailto:{CONTACT_EMAIL}" style="text-decoration:underline; font-weight:700;">{CONTACT_EMAIL}</a></p>
   </div>
  </div>
</section>
<section class="section bg-cream" style="padding-top:0;">
  <div class="container">
   <div style="max-width:640px;">
    <form id="contactForm" novalidate>
      <div class="field-stack">
        <label class="field-label" for="contactName">Name</label>
        <input type="text" id="contactName" name="name" required>

        <label class="field-label" for="contactEmail">Email</label>
        <input type="email" id="contactEmail" name="email" required>

        <label class="field-label" for="contactReason">Reason for contacting</label>
        <select id="contactReason" name="reason" required>
          <option value="" disabled selected>Choose one&hellip;</option>
          {reason_options_html}
        </select>

        <label class="field-label" for="contactMessage">Message</label>
        <textarea id="contactMessage" name="message" rows="6" required></textarea>
      </div>
      <button type="submit" class="btn btn-solid-orange" style="margin-top:22px;">Send message</button>
      <p class="small muted" id="contactSuccess" style="display:none; margin-top:16px;">Thank you. Your message is on its way, and we&rsquo;ll reply as soon as we can.</p>
    </form>
    <p class="small muted" style="margin-top:20px;">Or email <a href="mailto:{CONTACT_EMAIL}" style="text-decoration:underline; font-weight:700;">{CONTACT_EMAIL}</a></p>
   </div>
  </div>
</section>'''
    write("contact.html", layout(
        "Contact",
        "Get in touch with Sauna for All: questions, media enquiries, regional partnerships, and more.",
        "contact", body))

print("Helpers loaded.")

if __name__ == "__main__":
    page_home()
    page_charter()
    page_signatories()
    page_about()
    page_faqs()
    page_news()
    page_resources()
    page_contact()
    print("Build complete.")
