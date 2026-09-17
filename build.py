#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Static site builder for Sauna For All.
Assembles shared <head>, nav, footer around per-page content blocks
and writes finished HTML files to the project root.
"""
import os
import csv
import io
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
_COL = {"country": "G", "category": "K", "commitment": "T", "consent": "AH",
        "name": "AJ", "organisation": "AK", "website": "E"}

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


def _domain_of(url):
    """Bare domain (no scheme/www/path) for a signatory's website, used to
    pull their logo from Clearbit's free public logo API. Returns '' if the
    signatory gave no usable website."""
    if not url or url == "#":
        return ""
    host = re.sub(r"^https?://", "", url, flags=re.I).split("/")[0]
    host = re.sub(r"^www\.", "", host, flags=re.I)
    return host.strip().lower()


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


def load_signatories(csv_url, fallback):
    """Loads approved, consented signatory rows from the live Charter
    questionnaire response sheet (see _COL / consent notes above), mapped
    onto the dict shape the rest of build.py expects (name/url/country/
    categories/commitment). Falls back to placeholder rows if no URL is
    configured, the fetch fails, or no response has public-listing consent
    yet."""
    if not csv_url:
        return fallback
    text = _fetch_csv(csv_url)
    if text is None:
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
            "person_name": person_name,
            "organisation": organisation,
            "url": url,
            "country": _cell(raw_row, _COL["country"]),
            "category": category,
            "commitment": commitment,
            "logo_domain": _domain_of(url),
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
        rows.append({
            "name": organisation or people_names,
            "signed_by": f"Signed by {people_names}" if organisation else "",
            "url": url,
            "country": first["country"],
            "categories": categories or [],
            "commitment": commitment,
            "logo_domain": _domain_of(url),
        })

    rows.sort(key=lambda s: (_country_of(s), s["name"].lower()))
    return rows or fallback

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

def icon(name, css_class="ic-tan"):
    return f'<div class="icon-circle {css_class}">{ICONS[name]}</div>'

# ---------------------------------------------------------------------------
# Nav / Footer
# ---------------------------------------------------------------------------
# External integration links (SPEC.md Section 4). Substack/press links are
# still [ADD LINK] placeholders in the spec -- update these three the moment
# Becky provides them; nothing else in the site needs to change.
GOOGLE_FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSf425hWeCCmQFa1IF_nrGu9ihbM8rB3MAqawdu-3lPVfFCtgg/viewform?usp=header"
OPEN_COLLECTIVE_URL = "https://opencollective.com/sauna_for_all"
SUBSTACK_URL = ""       # [ADD LINK] -- SPEC.md Section 4
SUBSTACK_FEED_URL = ""  # [ADD SUBSTACK LINK]/feed -- SPEC.md Section 4
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
    <a href="/" class="nav-logo" aria-label="Sauna for All, home">{logo_svg("#df804f", 34)}</a>
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

def footer():
    return f'''<footer class="site-footer">
  <div class="container">
    <div class="footer-grid">
      <div class="footer-col" style="max-width:340px;">
        <a href="/" aria-label="Sauna for All, home">{logo_svg("#e7c196", 36)}</a>
        <p class="small" style="margin-top:16px; opacity:0.75;">Public Sauna. Common Good.</p>
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
<script src="js/news-feed.js"></script>'''

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
        pos = "top:0;"
    else:
        path_d = f"M0,{h} L{curve} L{width},{h} Z"
        pos = "bottom:0;"
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

    counter = f'''<section class="stat-strip" id="counter">
  <div class="container stat-grid">
    <div class="stat-item"><div class="num">{len(SIGNATORIES)}</div><div class="label">Signatories</div></div>
    <div class="stat-item"><div class="num">{SIGNATORY_COUNTRY_COUNT}</div><div class="label">Countries</div></div>
    <div class="stat-item"><div class="num">2026</div><div class="label">Introduced at World Sauna Forum</div></div>
  </div>
</section>'''

    def band_item(p):
        n = p["num"]
        return f'''<a href="/charter#principle-{int(n)}" class="principle-item">
          <span class="icon-plain">{ICONS[p["icon"]]}</span>
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

    why_now = f'''<section class="section bg-white" id="why-now">
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

    evidence = f'''<section class="section" id="evidence" style="background:var(--sand); color:var(--dark-green);">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">The Evidence</span>
      <h2>New to sauna or bathing for a lifetime, the benefits run deep</h2>
      <p class="lede">Research is catching up with what bathers have long known: sauna supports body, mind, and community.</p>
    </div>
    <div class="card-grid-5">
      <div class="info-card"><h3>Physical health</h3><p>A growing number of studies link regular sauna use to lower cardiovascular mortality, with the benefit growing the more often people go.<sup>1</sup></p></div>
      <div class="info-card"><h3>Mental health and wellbeing</h3><p>In a large population study in northern Sweden, people who sauna bathe reported better mental health, more energy, and less pain, and mental health scores rose with more frequent bathing.<sup>2</sup></p></div>
      <div class="info-card"><h3>Why people bathe</h3><p>Regular bathers describe sauna as a place for mental recovery, social togetherness, cleansing, and physical health, all working together.<sup>3</sup></p></div>
      <div class="info-card"><h3>Belonging</h3><p>Frequent sauna use, especially weekly, is linked to greater health and wellbeing, and part of that benefit comes from a stronger sense of belonging.<sup>4</sup></p></div>
      <div class="info-card"><h3>Local value</h3><p>Cities already invest in pools and rinks for health and community. Well-run public saunas can offer the same value. <em>Case studies coming soon.</em></p></div>
    </div>
    <p class="small" style="margin-top:16px; opacity:0.85;">Sources: (1) Laukkanen et al., <em>BMC Medicine</em>, 2018. (2) Engstr&ouml;m, H&auml;gglund et al., <em>International Journal of Circumpolar Health</em>, 2024. (3) Engstr&ouml;m, Wiell, H&auml;gglund &amp; Lennkvist, <em>International Journal of Circumpolar Health</em>, 2026. (4) Newson, McGrath et al., <em>Social Science &amp; Medicine</em>, 2026.</p>
  </div>
</section>'''

    who_we_are = f'''<section class="section bg-white" id="who-we-are">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--gold);">Who we are</span>
      <h2 style="margin:14px 0 18px;">Grassroots by design, guided by experience</h2>
      <p class="lede muted">Sauna for All has grown from the ground up. An international group of founding stewards guides the work, bringing years of experience running public saunas, researching sauna culture, and building community. The movement is shaped by many more: advisors, knowledge holders, operators, and bathers who contribute and help the Charter grow.</p>
      <div style="margin-top:18px; display:flex; flex-direction:column; gap:8px;">
        <a href="/about#stewards" style="text-decoration:underline; font-weight:700;">Meet the founding stewards &rarr;</a>
        <a href="{OPEN_COLLECTIVE_URL}" style="text-decoration:underline; font-weight:700;">Support the movement &rarr;</a>
      </div>
    </div>
    <img src="/images/photos/sauna-for-all-2026-13.jpg" alt="Founding stewards and network members among the initial signatories of the Charter" style="border-radius:var(--radius-lg); width:100%; height:100%; object-fit:cover;">
  </div>
</section>'''

    newsletter = f'''<section class="section bg-cream" id="newsletter">
  <div class="container" style="max-width:720px; text-align:center;">
    <h2>Stay close on the bench</h2>
    <p class="lede muted" style="margin-top:14px;">Follow the Charter as it grows, learn from operators and researchers, and get invitations to online meet-ups. You&rsquo;ll also hear first when we open new rounds for signatories.</p>
    <a href="{SUBSTACK_URL or '#'}" class="btn btn-solid-orange" style="margin-top:22px; display:inline-block;">Sign up</a>
  </div>
</section>'''

    body = hero + counter + charter_summary + why_now + evidence + who_we_are + newsletter
    write("index.html", layout(
        "Home",
        "Sauna for All is a grassroots global movement guiding public sauna-bathing as common good, through the Public Sauna-Bathing Charter.",
        "home", body))

# ---------------------------------------------------------------------------
# OVERVIEW PAGE (the Charter, in full — formerly charter.html)
# ---------------------------------------------------------------------------
CHARTER_PDF_URL = "/files/public-sauna-bathing-charter.pdf"

def page_charter():
    charter_header = f'''<section class="section bg-cream" style="padding-bottom:0;" id="charter-header">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">The Public Sauna-Bathing Charter</span>
    <h1 style="font-size:clamp(2rem,4vw,2.9rem); margin:14px 0 20px; max-width:22ch;">Ten principles for public sauna as common good</h1>
    <p class="lede muted" style="max-width:64ch;">The Charter sets out shared principles for developing and caring for public sauna responsibly. It gives communities, operators, governments, funders, and researchers a common reference point. Signatories commit to showing how these principles guide their decisions and daily practice.</p>
    <div class="hero-actions" style="margin-top:26px;">
      <a href="/signatories#sign" class="btn btn-primary">Sign the Charter</a>
      <a href="{CHARTER_PDF_URL}" class="btn btn-outline-dark">Download PDF</a>
    </div>
    <p class="small muted" style="margin-top:14px;">Version 1.0, August 19, 2026</p>
    <div style="margin-top:10px; display:flex; gap:22px; flex-wrap:wrap;">
      <a href="/faqs" style="text-decoration:underline; font-weight:700; font-size:0.92rem;">Read the FAQs &rarr;</a>
      <a href="{OPEN_COLLECTIVE_URL}" style="text-decoration:underline; font-weight:700; font-size:0.92rem;">Support our work &rarr;</a>
    </div>
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
      <a href="{SUBSTACK_URL or '#'}" class="btn btn-solid-orange" style="display:inline-block;">Sign up</a>
    </div>
  </div>
</section>'''

    WHO_CAN_SIGN_ROLES = [
        ("Operators and Keepers", "People who run, host, or tend public saunas that offer published public sessions anyone can attend."),
        ("Community Sauna Organisations and Networks", "Groups that connect, support, and speak for public and community saunas in their region."),
        ("Governments and Public Bodies", "Municipalities, Indigenous Nations, and public health and tourism organisations shaping planning, policy, and investment."),
        ("Designers, Builders and Suppliers", "Architects, builders, manufacturers, and suppliers helping create public saunas that are safe, accessible, and built to last."),
        ("Researchers and Educators", "People building the evidence, knowledge, and training that help public sauna grow well."),
        ("Funders and Investors", "Those who support public sauna as a public good and want their investment to reflect that."),
        ("Bathers and Advocates", "Individuals who believe public sauna should be welcoming, safe, and held for the common good."),
    ]
    role_cards_html = "".join(
        f'<div class="info-card"><h3>{title}</h3><p>{body}</p></div>' for title, body in WHO_CAN_SIGN_ROLES)

    who_can_sign = f'''<section class="section" id="who-can-sign" style="background:var(--light-blue); color:var(--green-dark);">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Who can sign</span>
      <h2>Built by, and for, everyone shaping public sauna</h2>
      <p class="lede muted">Anyone working to strengthen public sauna as a common good can sign. You don&rsquo;t need to run a sauna. You simply state what you will do, in your own role, to support the Charter&rsquo;s principles.</p>
    </div>
    <div class="card-grid-4">{role_cards_html}</div>
    <div class="callout" style="margin-top:28px;">
      <p style="margin:0 0 10px;"><strong>Two things to know before signing.</strong> A reference from an existing signatory is required. Operators also need to meet the Charter&rsquo;s definition of a public sauna-bath: public sessions people can attend on their own, without a membership, an overnight stay, or buying another product or service.</p>
      <div style="display:flex; gap:22px; flex-wrap:wrap; font-weight:700;">
        <a href="/signatories#list" style="text-decoration:underline;">Find a signatory &rarr;</a>
        <a href="/faqs" style="text-decoration:underline;">Read the full answer in the FAQs &rarr;</a>
      </div>
    </div>
    <p class="small" style="margin-top:20px;">The founding stewards and advisors are the Charter&rsquo;s first signatories. Meet them on the <a href="/about#stewards" style="text-decoration:underline; font-weight:700;">About page &rarr;</a></p>
  </div>
</section>'''

    HOW_SIGNING_STEPS = [
        ("Read the Charter", "Get to know the ten principles and talk them through with your team, board, or council."),
        ("Find a reference", "Ask an existing signatory, either an individual or an organisation, for a letter or brief statement of reference."),
        ("Complete the questionnaire", "The form has three parts: Commitment, Contribution, and Consent and Affirmation."),
        ("Review and welcome", "Applications are reviewed by the founding stewards in intake rounds, two to four times a year. Once confirmed, you join the list of signatories and the wider network, with check-ins on your commitments over time."),
    ]
    step_cards_html = "".join(
        f'<div class="info-card"><h3>{i+1}. {title}</h3><p>{body}</p></div>'
        for i, (title, body) in enumerate(HOW_SIGNING_STEPS))

    how_signing_works = f'''<section class="section bg-white" id="how-signing-works">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">How signing works</span>
      <h2>Signing is an application, and it asks for real commitments</h2>
      <p class="lede muted">Signing is free and takes about 15 to 30 minutes. You choose the principles most relevant to your work and say, in your own words, how you will put them into practice.</p>
    </div>
    <div class="card-grid-4">{step_cards_html}</div>
    <div class="hero-actions" style="margin-top:26px;">
      <a href="/signatories#sign" class="btn btn-primary">Sign the Charter</a>
      <a href="/signatories#list" class="btn btn-outline-dark">Find a signatory</a>
    </div>
    <p class="small muted" style="margin-top:14px;">The initial intake round is currently open. Join the movement!</p>
  </div>
</section>'''

    is_isnt = f'''<section class="section bg-cream" id="is-isnt">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--purple);">What the Charter is</span>
      <ul class="is-list" style="margin-top:18px;">
        <li>A shared set of principles for the responsible development and stewardship of public sauna.</li>
        <li>A common reference point for communities, operators, governments, funders, researchers, and industry.</li>
        <li>A guide for planning, governance, operations, investment, and policy.</li>
        <li>A commitment to public sauna that is safe, accessible, culturally respectful, and trustworthy.</li>
        <li>A foundation for shared guidance, resources, and learning across the movement.</li>
      </ul>
    </div>
    <div>
      <span class="eyebrow" style="color:var(--brown);">What the Charter isn&rsquo;t</span>
      <ul class="isnt-list" style="margin-top:18px;">
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
SIGNATORY_COUNTRY_COUNT = len({_country_of(s) for s in SIGNATORIES if _country_of(s)})

def page_signatories():
    signatories_header = f'''<section class="section bg-cream" style="padding-bottom:0;" id="signatories-header">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">Signatories</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px; max-width:24ch;">Sign the Charter, and meet those who already have</h1>
    <p class="lede muted" style="max-width:64ch;">Sauna for All is built by the people and organisations shaping public sauna today, from operators and community networks to governments, researchers, builders, and bathers. Explore who has committed, find a signatory to support your application, or apply to join them.</p>
    <div class="hero-actions" style="margin-top:22px;">
      <a href="#sign" class="btn btn-primary">Sign the Charter</a>
      <a href="/charter" class="btn btn-outline-dark">Read the Charter</a>
    </div>
  </div>
</section>'''

    BEFORE_YOU_BEGIN = [
        ("Build alignment.", "Talk it through with your team, board, or council first."),
        ("Get a reference.", 'You&rsquo;ll need a letter or statement from an existing signatory. <a href="#list" style="text-decoration:underline; font-weight:700;">Find a signatory &rarr;</a>'),
        ("Check eligibility.", "Operators need to offer published public sessions people can attend on their own."),
        ("Set aside 15 to 30 minutes.", "You can&rsquo;t save and return in Google Forms, so it helps to draft your commitments first."),
    ]
    before_you_begin_html = "".join(
        f'<li><strong>{lead}</strong> {rest}</li>' for lead, rest in BEFORE_YOU_BEGIN)

    QUESTIONNAIRE_PARTS = [
        ("Part A: Commitment.", "Who you are, why you&rsquo;re signing, and the principles and commitments you choose."),
        ("Part B: Contribution.", "Your stewardship, your part in the sector, research, and looking ahead."),
        ("Part C: Consent and Affirmation.", ""),
    ]
    questionnaire_parts_html = "".join(
        f'<li><strong>{lead}</strong>{" " + rest if rest else ""}</li>' for lead, rest in QUESTIONNAIRE_PARTS)

    sign = f'''<section class="section bg-white" id="sign">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Sign the Charter</span>
      <h2>Signing is an application, and it asks for real commitments</h2>
      <p class="lede muted">By signing, you commit to the Charter&rsquo;s principles and to showing how they guide your decisions, operations, and stewardship.</p>
    </div>
    <div class="two-col">
      <div>
        <h3>Before you begin</h3>
        <ul class="is-list" style="margin-top:14px;">{before_you_begin_html}</ul>
        <h3 style="margin-top:30px;">The questionnaire has three parts</h3>
        <ul class="is-list" style="margin-top:14px;">{questionnaire_parts_html}</ul>
        <a href="{GOOGLE_FORM_URL}" class="btn btn-solid-orange" target="_blank" rel="noopener" style="margin-top:10px; display:inline-block;">Open the questionnaire</a>
        <p class="small muted" style="margin-top:10px;">Opens in Google Forms.</p>
      </div>
      <div class="stack-20">
        <div class="info-card">
          <h3>What happens next</h3>
          <p>The founding stewards review applications together in intake rounds, two to four times a year. Once confirmed, you&rsquo;re listed among the signatories and welcomed into the network. Your commitments are revisited in future check-ins.</p>
        </div>
        <div class="info-card">
          <h3>Who can sign</h3>
          <p class="small">{" &middot; ".join(SIGNATORY_FILTERS)}</p>
          <a href="/charter#who-can-sign" style="display:inline-block; margin-top:10px; font-weight:700; text-decoration:underline; font-size:0.9rem;">Read who can sign in full &rarr;</a>
        </div>
      </div>
    </div>
  </div>
</section>'''

    def category_pills(cats):
        return "".join(f'<span class="category-pill">{c}</span>' for c in cats)

    def logo_tile(s):
        domain = s.get("logo_domain", "")
        if not domain:
            initials = "".join(w[0] for w in re.split(r"\s+", s["name"]) if w)[:3].upper()
            return f'<div class="logo-tile" style="width:80px; height:80px; border-radius:50%; border:none; background:var(--light-blue); font-size:0.85rem; font-weight:800; color:var(--green-dark);">{initials}</div>'
        # Pulled from the signatory's own website via Google's public favicon
        # service -- no key required. (Clearbit's free public logo API, used
        # here previously, was retired and now returns 503 for every domain.)
        # Falls back to the plain initials tile if the domain has no icon on
        # file or the request fails for any reason.
        logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
        return (f'<div class="logo-tile" style="width:80px; height:80px; padding:4px; overflow:hidden;">'
                f'<img src="{logo_url}" alt="{s["name"]} logo" loading="lazy" '
                f'style="max-width:100%; max-height:100%; object-fit:contain;" '
                f'onerror="this.parentElement.textContent=&#39;{s["name"][:3].upper()}&#39;; this.parentElement.style.padding=&#39;8px&#39;;">'
                f'</div>')

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
    <div class="signatories-grid" id="signatoriesGrid">{signatories_html}</div>
    <p class="filter-empty" id="signatoryEmpty">{empty_message}</p>'''
    else:
        list_html = '<p class="lede muted">Our first signatories will appear here soon.</p>'

    directory = f'''<section class="section bg-cream" id="list">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Signatories</span>
      <h2>Who has signed the Charter</h2>
      <p class="lede muted">Meet the people and organisations committed to public sauna as a common good. Filter by role, or search by name or country.</p>
      <p class="small muted" style="margin-top:10px;">New signatories are confirmed in intake rounds, two to four times a year. Sign up for news to hear when the next round opens.</p>
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
        f'<li><strong>{lead}</strong> {rest}</li>' for lead, rest in WAYS_TO_HELP)

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

    body = signatories_header + sign + directory + support + regional_partners
    write("signatories.html", layout(
        "Signatories",
        "Sign the Public Sauna-Bathing Charter, see who has already signed, and find out how to support the movement.",
        "signatories", body))

# ---------------------------------------------------------------------------
# ABOUT PAGE (mission + founding stewards, combined)
# ---------------------------------------------------------------------------
def page_about():
    STEWARDS = [
        ("Becky Pelkonen", "Kamu Sauna", "Canada"),
        ("Polly Wilson", "Community Sauna Baths", "United Kingdom"),
        ("Charlie Duckworth", "Community Sauna Baths", "United Kingdom"),
        ("Freddie Mehigan", "Community Sauna Network", "United Kingdom"),
        ("Ian Whelan", "Fád Saoil Saunas", "Ireland"),
        ("Steve Crosbie", "Fád Saoil Saunas", "Ireland"),
        ("Jason Wong", "Kotisauna", "Canada"),
        ("Azar Eskandarpour", "Humans Who Bathe", "Mexico"),
        ("Juho Pelkonen", "Kamu Sauna", "Canada"),
        ("Niamh Murphy", "Kamu Sauna", "Canada"),
    ]
    ADVISORS = [
        ("Mikkel Aaland", "author and sauna historian, United States"),
        ("Dalva Lamminmäki", "folklorist and sauna researcher, Finland"),
    ]

    def person(name, role):
        initials = "".join([p[0] for p in name.split()[:2]])
        return f'''<div class="person"><div class="avatar">{initials}</div><div class="name">{name}</div><div class="role">{role}</div></div>'''

    stewards_html = "".join(person(name, f"{org}, {country}") for name, org, country in STEWARDS)
    advisors_html = "".join(person(name, role) for name, role in ADVISORS)
    advisors_html += '''<div class="person"><div class="avatar" style="font-size:0.62rem; font-weight:700; text-align:center; padding:6px; line-height:1.15;">Sauna From Finland</div><div class="name">Sauna from Finland</div></div>'''

    body = f'''<section class="section bg-cream" style="padding-bottom:0;" id="story">
  <div class="container">
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 18px;">Public sauna as common good</h1>
    <p class="lede muted" style="max-width:64ch;">Around the world, people are rediscovering public sauna, both for their own wellbeing and for the life it brings to communities. Sauna for All is a grassroots movement guiding this resurgence through shared values, evidence, and collaboration. Our aim is for public sauna to grow as a trusted part of civic and cultural life, rooted in the common good.</p>
    <a href="#stewards" style="display:inline-block; margin-top:18px; text-decoration:underline; font-weight:700;">Meet the founding stewards &rarr;</a>
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
      <p class="lede muted">People across the sauna world have shared their knowledge, guidance, and encouragement as the Charter took shape. We thank Sauna from Finland for early support and advice, and for welcoming this work at the World Sauna Forum. We thank the organisers of the International Sauna Congress for making room for this conversation. And we thank the grassroots organisers in Finland and around the world who have stepped forward as early signatories.</p>
      <a href="/signatories" style="display:inline-block; margin-top:18px; text-decoration:underline; font-weight:700;">Meet the signatories and wider network &rarr;</a>
    </div>
    <div>
      <img src="/images/photos/sauna-for-all-2026-04.jpg" alt="Sauna networking and community gathering as part of the World Sauna Forum in Jyväskylä, Finland" style="border-radius:var(--radius-lg); width:100%; height:100%; object-fit:cover;">
    </div>
  </div>
</section>

<section class="section bg-white" id="get-involved">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Get involved</span>
      <h2>Want to help shape what comes next?</h2>
    </div>
    <div class="card-grid-4">
      <div class="info-card">
        <h3>1. Stay close on the bench</h3>
        <p>Follow the Charter as it grows, learn from operators and researchers, and get invitations to online meet-ups. You&rsquo;ll also hear first when we open new rounds for signatories.</p>
        <a href="{SUBSTACK_URL or '#'}" class="btn btn-outline-dark" style="margin-top:14px; display:inline-block;">Sign up</a>
      </div>
      <div class="info-card">
        <h3>2. Sign the Charter</h3>
        <p>Ready to commit? Signing means sharing how the Charter&rsquo;s principles show up in your work. The form takes about 15 to 30 minutes, and we&rsquo;re happy to help along the way.</p>
        <a href="/signatories#sign" class="btn btn-outline-dark" style="margin-top:14px; display:inline-block;">Sign the Charter</a>
      </div>
      <div class="info-card">
        <h3>3. Support our work</h3>
        <p>Sauna for All is run by volunteers at this time. Your contribution helps with Charter administration, our website, future gatherings, and initial research and case study development projects.</p>
        <a href="{OPEN_COLLECTIVE_URL}" class="btn btn-outline-dark" style="margin-top:14px; display:inline-block;">Make a donation</a>
      </div>
      <div class="info-card">
        <h3>4. Contact us</h3>
        <p>Have a question, an idea, or a story to share? We&rsquo;d love to hear from you.</p>
        <a href="/contact" class="btn btn-outline-dark" style="margin-top:14px; display:inline-block;">Get in touch</a>
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
    # SPEC.md 6.7 calls for the exact text of all 16 questions and answers
    # from /content/faqs.md ("The Public Sauna-Bathing Charter FAQs, V1,
    # August 19, 2026" -- see Section 5's asset list). That document has not
    # been supplied -- it is not in the Drive folders pulled for this build,
    # nor anywhere else in the project. Rather than leave the page empty or
    # invent nine more questions, this interim list carries over the seven
    # real questions and answers that were live on the previous site (see
    # pdf/06-faqs.pdf), so the page is genuinely useful and not fabricated.
    #
    # TODO once Becky supplies /content/faqs.md (V1, 16 Q&As):
    #   1. Replace FAQS below with all 16 questions/answers, verbatim.
    #   2. Anchors are already id="faq-{n}" in signing order -- keep going
    #      to faq-16.
    #   3. In FAQ 8, replace "[Donation link]" with OPEN_COLLECTIVE_URL and
    #      "[Contact link]" with "/contact".
    #   4. In FAQ 16, show the email as hei@saunaforall.org and link
    #      "www.saunaforall.org" to "/".
    #   5. Remove the FAQS_ARE_INTERIM callout and restore the spec's small
    #      line: "Version 1, August 19, 2026".
    FAQS_ARE_INTERIM = True
    FAQS = [
        ("What is the Public Sauna-Bathing Charter?",
         'A shared set of principles and norms for the responsible development and stewardship of public sauna, a common point of reference for communities, practitioners, operators, governments, funders, researchers, and industry. Read the full <a href="/charter" style="text-decoration:underline; font-weight:700;">Charter &rarr;</a>.'),
        ("Who can sign the Charter?",
         'Founding stewards, advisors and stewards, operators, governments and public bodies, designers, builders and developers, industry partners, and bathers and community members. See the full list on the <a href="/charter#who-can-sign" style="text-decoration:underline; font-weight:700;">Charter page &rarr;</a>.'),
        ("Is there a cost to sign?",
         "No. Signing is free. It is, however, a genuine application: it asks for real commitments, not just a signature."),
        ("What happens after I apply?",
         "Your responses go to the founding stewards for review. Once confirmed, you&rsquo;re listed among signatories and welcomed into network channels."),
        ("Is the Charter a certification or standard?",
         'No. It does not certify or rank public saunas, and it isn&rsquo;t a technical standard or rulebook. It sets out shared principles, not specifications. See <a href="/charter#is-isnt" style="text-decoration:underline; font-weight:700;">what the Charter is / isn&rsquo;t &rarr;</a>.'),
        ("How can I get involved if I&rsquo;m not ready to sign?",
         f'You can contribute time, funding, expertise, or space: see <a href="/signatories#support" style="text-decoration:underline; font-weight:700;">Support our work &rarr;</a>, or stay close to the movement through the newsletter on our homepage.'),
        ("Who governs and funds the Charter?",
         'Sauna for All is entirely volunteer-led by an international steering group of founding stewards. See <a href="/about#stewards" style="text-decoration:underline; font-weight:700;">Founding Stewards &rarr;</a>.'),
    ]

    def faq_item(n, q, a):
        return (f'<details class="faq-item" id="faq-{n}">'
                f'<summary>{q}<svg class="faq-caret" viewBox="0 0 12 8" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M1 1.5l5 5 5-5"/></svg></summary>'
                f'<div class="faq-answer"><p>{a}</p></div></details>')
    faqs_html = "".join(faq_item(i, q, a) for i, (q, a) in enumerate(FAQS, start=1))

    version_line = (
        '<p class="small muted" style="margin-top:14px;">Showing 7 of 16 planned questions. '
        'The complete FAQ list is on its way. Check back soon, or '
        '<a href="/contact" style="text-decoration:underline; font-weight:700;">ask us directly &rarr;</a>.</p>'
        if FAQS_ARE_INTERIM else
        '<p class="small muted" style="margin-top:14px;">Version 1, August 19, 2026</p>'
    )

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

    updates = f'''<section class="section bg-cream" id="updates">
  <div class="container">
    <div class="card-grid" id="newsGrid" data-feed-endpoint="{NEWS_FEED_ENDPOINT}"></div>
    <p class="lede muted" id="newsEmpty" style="text-align:center; padding:20px 0;">News is on its way. Sign up to hear first.</p>
    <div style="text-align:center; margin-top:10px;">
      <button type="button" id="newsLoadMore" class="btn btn-outline-dark" style="display:none;">Load more</button>
    </div>
  </div>
</section>'''

    news_newsletter = f'''<section class="section bg-white" id="news-newsletter">
  <div class="container" style="max-width:640px; text-align:center;">
    <p class="lede"><strong>Stay close on the bench.</strong> Get updates like these in your inbox.</p>
    <a href="{SUBSTACK_URL or '#'}" class="btn btn-solid-orange" style="margin-top:14px; display:inline-block;">Sign up</a>
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

    media = f'''<section class="section bg-white" id="media">
  <div class="container">
    <div class="section-head">
      <h2>For media</h2>
      <p class="lede muted">Writing about public sauna or the Charter? We&rsquo;re happy to help with background, key facts, logos, photos, and interviews with our founding stewards.</p>
      <a href="/contact?reason=media" class="btn btn-primary" style="margin-top:18px; display:inline-block;">Contact us</a>
      <p class="small muted" style="margin-top:12px;">Media enquiries: <a href="mailto:{CONTACT_EMAIL}" style="text-decoration:underline; font-weight:700;">{CONTACT_EMAIL}</a></p>
    </div>
  </div>
</section>'''

    body = news_header + updates + news_newsletter + featured + media
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
      <a href="{SUBSTACK_URL or '#'}" class="btn btn-solid-orange" style="display:inline-block;">Sign up</a>
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
<section class="section bg-cream">
  <div class="container" style="max-width:640px;">
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
