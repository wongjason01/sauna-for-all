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
# Known raw answers seen so far are mapped onto the site's existing filter
# categories; anything unrecognized falls through unchanged and is logged
# at build time so it can be added here rather than silently mislabeled.
CATEGORY_MAP = {
    "public or community sauna operator, bricks and mortar": "Operators",
    "researcher or educator": "Advisors and Stewards",
    "sauna organisation or network": "Industry Partners",
}


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

    rows = []
    unmapped_categories = set()
    for raw_row in reader:
        if not any(raw_row):
            continue
        name = _cell(raw_row, _COL["name"])
        if not name:
            continue

        consent = _cell(raw_row, _COL["consent"]).lower()
        if _PUBLIC_LISTING_PHRASE not in consent:
            continue  # no consent to be listed publicly at all -- skip entirely

        raw_category = _cell(raw_row, _COL["category"])
        category = CATEGORY_MAP.get(raw_category.lower(), raw_category)
        if raw_category and raw_category.lower() not in CATEGORY_MAP:
            unmapped_categories.add(raw_category)

        commitment = _cell(raw_row, _COL["commitment"]) if _COMMITMENT_SHARE_PHRASE in consent else ""

        rows.append({
            "name": name,
            "url": _normalize_url(_cell(raw_row, _COL["website"])),
            "country": _cell(raw_row, _COL["country"]),
            "categories": [category] if category else ["Operators"],
            "commitment": commitment,
        })

    if unmapped_categories:
        print(f"  ! signatories sheet: unrecognized category answer(s), shown as-is: {sorted(unmapped_categories)}")
        print(f"    (add them to CATEGORY_MAP in build.py to match the site's filter categories)")

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
ICON_STROKE = 'stroke="#0f4d3b" stroke-width="1.6" fill="none" stroke-linecap="round" stroke-linejoin="round"'

# radial tick marks used for the two "coin edge" badge icons (sun, reciprocity),
# echoing the dial/rosette rims in the updated icon sheet
ICON_TICKS = "M27.30 16.00L29.30 16.00 M26.18 20.90L27.98 21.77 M23.05 24.83L24.29 26.40 M18.51 27.02L18.96 28.97 M13.49 27.02L13.04 28.97 M8.95 24.83L7.71 26.40 M5.82 20.90L4.02 21.77 M4.70 16.00L2.70 16.00 M5.82 11.10L4.02 10.23 M8.95 7.17L7.71 5.60 M13.49 4.98L13.04 3.03 M18.51 4.98L18.96 3.03 M23.05 7.17L24.29 5.60 M26.18 11.10L27.98 10.23"

ICONS = {
"network": f'<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="2.6" {ICON_STROKE}/><circle cx="16" cy="5" r="2.2" {ICON_STROKE}/><circle cx="27" cy="16" r="2.2" {ICON_STROKE}/><circle cx="16" cy="27" r="2.2" {ICON_STROKE}/><circle cx="5" cy="16" r="2.2" {ICON_STROKE}/><circle cx="23.5" cy="8.5" r="2.2" {ICON_STROKE}/><circle cx="23.5" cy="23.5" r="2.2" {ICON_STROKE}/><circle cx="8.5" cy="23.5" r="2.2" {ICON_STROKE}/><circle cx="8.5" cy="8.5" r="2.2" {ICON_STROKE}/><path d="M16 16L16 7M16 16L25 16M16 16L16 25M16 16L7 16M16 16L21.8 10.2M16 16L21.8 21.8M16 16L10.2 21.8M16 16L10.2 10.2" {ICON_STROKE}/></svg>',
"heat": f'<svg viewBox="0 0 32 32"><rect x="5" y="5" width="22" height="22" rx="2" {ICON_STROKE}/><path d="M9 10c1.5 2 1.5 3-0 5s-1.5 3 0 5M15.3 10c1.5 2 1.5 3 0 5s-1.5 3 0 5M21.6 10c1.5 2 1.5 3 0 5s-1.5 3 0 5" {ICON_STROKE}/></svg>',
"leaf": f'<svg viewBox="0 0 32 32"><path d="M16 27V13" {ICON_STROKE}/><path d="M16 13c0-5 3.5-8.5 8.5-8.5C24.5 9.5 21 13 16 13Z" {ICON_STROKE}/><path d="M16 18c0-4-3-7-7.5-7C8.5 15 12 18 16 18Z" {ICON_STROKE}/></svg>',
# redesigned: smiling face inside a coin/dial-edged circle (was a literal sun)
"sun": f'<svg viewBox="0 0 32 32"><circle cx="16" cy="16" r="11" {ICON_STROKE}/><path d="{ICON_TICKS}" {ICON_STROKE}/><circle cx="12" cy="14" r="1" fill="#0f4d3b"/><circle cx="20" cy="14" r="1" fill="#0f4d3b"/><path d="M11 19c1.4 2 3.2 3 5 3s3.6-1 5-3" {ICON_STROKE}/></svg>',
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
NAV_ITEMS = [
    ("about.html", "About"),
    ("overview.html", "Overview"),
    ("signatories.html", "Signatories"),
    ("news.html", "News"),
    ("faqs.html", "FAQs"),
]

def nav(active):
    active_cls = ' class="active"'
    links = "\n".join(
        f'<a href="{href}"{active_cls if href==active else ""}>{label}</a>'
        for href, label in NAV_ITEMS
    )
    return f'''<header class="site-header">
  <div class="nav">
    <a href="index.html" class="nav-logo" aria-label="Sauna For All — home">{logo_svg("#df804f", 34)}</a>
    <nav class="nav-links" id="navLinks">
      {links}
    </nav>
    <div class="nav-cta">
      <a href="signatories.html#sign" class="btn btn-primary">Sign the Charter</a>
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
        <a href="index.html" aria-label="Sauna For All — home">{logo_svg("#e7c196", 36)}</a>
        <p class="small" style="margin-top:16px; opacity:0.75;">A grassroots global movement guiding public sauna-bathing as common good.</p>
      </div>
      <div class="footer-links">
        <div class="footer-col">
          <h4>Movement</h4>
          <a href="overview.html">Overview &amp; Charter</a>
          <a href="signatories.html">Signatories</a>
          <a href="faqs.html">FAQs</a>
        </div>
        <div class="footer-col">
          <h4>About</h4>
          <a href="about.html">About &amp; Founding Stewards</a>
          <a href="news.html">News</a>
        </div>
        <div class="footer-col">
          <h4>Connect</h4>
          <a href="signatories.html#commit">Contribute</a>
          <a href="mailto:pelkoreb@uef.fi">pelkoreb@uef.fi</a>
        </div>
      </div>
    </div>
    <div class="footer-bottom">
      <span>&copy; 2026 Sauna For All. Public Sauna. Common Good.</span>
      <span>Site draft — v0.1</span>
    </div>
  </div>
</footer>
<script src="js/main.js"></script>'''

HEAD_EXTRA = ""

def layout(title, description, active, body, body_class=""):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} — Sauna For All</title>
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

def closing_cta():
    return f'''<section class="section bg-white">
  <div class="container">
    <div class="closing-grid">
      <div class="closing-card tan">
        <h3>Sauna is a common good.<br><em>We intend to keep it that way, together.</em></h3>
        <a href="signatories.html#sign" class="btn btn-outline-dark" style="align-self:flex-start;">Sign the Charter</a>
      </div>
      <div class="closing-card cream">
        <h3 style="font-size:1.15rem;">Stay close to the movement.</h3>
        <form class="field-row" onsubmit="return false;">
          <input type="email" placeholder="email address" required>
          <button class="btn btn-solid-orange" type="submit">Sign up</button>
        </form>
        <p class="small muted">Occasional updates on the Charter, signatories, and events. No spam.</p>
      </div>
    </div>
  </div>
</section>'''

# ---------------------------------------------------------------------------
# HOME PAGE
# ---------------------------------------------------------------------------
def page_home():
    hero = f'''<section class="hero">
  <div class="container hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">A grassroots global movement</span>
      <h1>Sauna for All.</h1>
      <p class="lede">Guiding public sauna-bathing as common good. A charter of ten principles, one global commitment: sauna that evolves with shared values, evidence, and effective collaboration.</p>
      <div class="hero-actions">
        <a href="signatories.html#sign" class="btn btn-primary">Sign the Charter</a>
        <a href="overview.html" class="btn btn-outline-light">Read the Principles</a>
      </div>
    </div>
    <div class="hero-media placeholder-img">
      <span>Hero photography — people bathing together, documentary style (not lifestyle/stock). Add final image here.</span>
    </div>
  </div>
</section>
{wave("#b3d3f0", backdrop="#0f4d3b")}
<section class="stat-strip">
  <div class="container stat-grid">
    <div class="stat-item"><div class="num">{len(SIGNATORIES)}</div><div class="label">Signatories</div></div>
    <div class="stat-item"><div class="num">{SIGNATORY_COUNTRY_COUNT}</div><div class="label">Countries</div></div>
    <div class="stat-item"><div class="num">10</div><div class="label">Principles</div></div>
    <div class="stat-item"><div class="num">&rsquo;26</div><div class="label">Introduced at World Sauna Forum</div></div>
  </div>
</section>
<section class="photo-band">
  <div class="placeholder-img photo-band-img">
    <span>Hero photography — people bathing together, documentary style (not lifestyle/stock). Add final image here.</span>
    {wave_mask("#f7f4e9", edge="bottom")}
  </div>
</section>'''

    def band_item(num, name, icon_name):
        return f'''<a href="overview.html#p{num}" class="principle-item">
          <span class="icon-plain">{ICONS[icon_name]}</span>
          <span class="principle-item-text"><span class="num">{num}</span><span class="name">{name}</span></span>
        </a>'''

    def movement_band(tag, sub, items_html):
        return f'''<div class="principle-band">
      <div class="principle-band-head"><span class="tag">{tag}</span><span class="dash">&mdash;</span><span class="sub">{sub}</span></div>
      <div class="principle-band-grid">
        {items_html}
      </div>
    </div>'''

    principles_preview = f'''<section class="section bg-cream" id="principles">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">The Public Sauna-Bathing Charter</span>
      <h2>Ten principles in four movements</h2>
      <p class="lede muted">Sauna is a common good, if done right. The Charter sets out shared principles for the responsible development and stewardship of public sauna &mdash; not a rulebook, a certification, or a standard, but a common reference point.</p>
    </div>

    <div class="principle-band-list">
      {movement_band("Practice", "Foundational Values",
        band_item("01","Access for All","network") +
        band_item("02","Shared Heat, Shared Space","heat") +
        band_item("03","Honour Tradition","leaf"))}
      {movement_band("Keeping", "Run for Public Good",
        band_item("04","Public Good Before Private Gain","sun") +
        band_item("05","A Sense of Place","place") +
        band_item("06","Community First","lattice"))}
      {movement_band("Tending", "Ongoing Care",
        band_item("07","Tended with Care","weave") +
        band_item("08","Reciprocity with the Natural World","reciprocity"))}
      {movement_band("Stewardship", "Shared Future",
        band_item("09","Wellbeing that Circulates","circulate") +
        band_item("10","Worth Public Support","seal"))}
    </div>

    <a href="overview.html" class="btn btn-outline-dark" style="margin-top:34px;">Read the full Charter</a>
  </div>
</section>'''

    why_now = f'''<section class="section bg-white">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Why now</span>
      <h2>The decisions being made today will shape public sauna for decades to come</h2>
    </div>
    <div class="card-grid">
      <div class="info-card"><h3>Policy and investment are emerging now</h3><p>Municipalities, health systems, tourism organizations, insurers, and regulators are beginning to decide what public sauna is, what outcomes it delivers, and how it should be governed.</p></div>
      <div class="info-card"><h3>Wellbeing emerges from the whole experience</h3><p>Environment, governance, norms, accessibility, and safety work together. Sauna is more than an amenity or wellness modality.</p></div>
      <div class="info-card"><h3>Trust must be earned</h3><p>A shared framework lets communities and policymakers recognize responsible practice &mdash; grounded in governance, cultural stewardship, safety, and care, not branding.</p></div>
    </div>
  </div>
</section>'''

    evidence = f'''<section class="section bg-mist">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">The evidence</span>
      <h2>Real, growing benefits from bathing together</h2>
    </div>
    <div class="card-grid-5">
      <div class="info-card"><h3>Physical health</h3><p>Regular sauna use is linked to lower cardiovascular mortality and stronger heart health, with the effect growing the more often people go.<sup>1</sup></p></div>
      <div class="info-card"><h3>Mental health</h3><p>Frequent sauna bathing is associated with better long-term mental health, including lower rates of serious psychiatric illness.<sup>2</sup></p></div>
      <div class="info-card"><h3>Belonging</h3><p>Shared sauna rituals build real emotional bonds &mdash; people feel a deeper sense of belonging through sauna than through many other group activities.<sup>3</sup></p></div>
      <div class="info-card"><h3>Community connection</h3><p>Public sauna brings strangers into regular contact across ages and backgrounds, turning brief encounters into lasting community ties.<sup>3</sup></p></div>
      <div class="info-card"><h3>Local &amp; economic value</h3><p><em>Emerging evidence &mdash; case studies to follow.</em> Public saunas anchor local economies and civic life, drawing footfall, tourism, and shared investment into the neighbourhoods that host them.</p></div>
    </div>
    <p class="small muted" style="margin-top:16px;">Sources: (1) Laukkanen et al., <em>BMC Medicine</em>, 2018. (2) Laukkanen et al., <em>Medical Principles and Practice</em>, 2018. (3) University of Greenwich, Oxford, Kent, London Interdisciplinary School &amp; British Sauna Society, <em>Social Science &amp; Medicine</em>, 2026. &middot; <a href="about.html" style="text-decoration:underline;">Learn more about our approach &rarr;</a></p>
  </div>
</section>'''

    why_evidence_block = why_now + evidence

    who_we_are = f'''<section class="section bg-white">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--gold);">Who we are</span>
      <h2 style="margin:14px 0 18px;">Guided by an international steering group of founding stewards</h2>
      <p class="lede muted">Practitioners, researchers, community leaders, and organizations committed to strengthening public sauna through knowledge sharing, cultural stewardship, and collective action.</p>
      <a href="about.html#stewards" style="display:inline-block; margin-top:18px; text-decoration:underline; font-weight:700;">Meet the founding stewards &rarr;</a>
    </div>
    <div class="logo-row">
      <div class="logo-tile">Kamu Sauna</div>
      <div class="logo-tile">Kotisauna</div>
      <div class="logo-tile">Community Sauna Baths</div>
      <div class="logo-tile">Community Sauna Network</div>
      <div class="logo-tile">F&aacute;d Saoil Saunas</div>
    </div>
  </div>
</section>'''

    body = hero + principles_preview + why_evidence_block + who_we_are + closing_cta()
    write("index.html", layout(
        "Home",
        "Sauna for All is a grassroots global movement guiding public sauna-bathing as common good, through the Public Sauna-Bathing Charter.",
        "index.html", body))

# ---------------------------------------------------------------------------
# OVERVIEW PAGE (the Charter, in full — formerly charter.html)
# ---------------------------------------------------------------------------
def page_overview():
    page_hero = f'''<section class="section bg-cream" style="padding-bottom:0;">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--gold);">The Public Sauna-Bathing Charter</span>
      <h1 style="font-size:clamp(2rem,4vw,2.9rem); margin:14px 0 20px;">Ten principles for public sauna as common good</h1>
      <p class="lede muted">A shared set of principles and norms for the responsible development and stewardship of public sauna &mdash; a common point of reference for communities, practitioners, operators, governments, funders, researchers, and industry. A living document that evolves through research, lived experience, and international dialogue.</p>
      <div class="hero-actions" style="margin-top:26px;">
        <a href="#" class="btn btn-outline-dark">Download PDF</a>
        <span class="small muted" style="align-self:center;">Version 1.0 &mdash; dated 2026</span>
      </div>
      <div style="margin-top:18px; display:flex; gap:22px; flex-wrap:wrap;">
        <a href="faqs.html" style="text-decoration:underline; font-weight:700; font-size:0.92rem;">Read the FAQs &rarr;</a>
        <a href="signatories.html#commit" style="text-decoration:underline; font-weight:700; font-size:0.92rem;">Contribute to the movement &rarr;</a>
      </div>
    </div>
    <div class="placeholder-img" style="aspect-ratio:4/3;"><span>Image: sauna bucket / detail photography</span></div>
  </div>
</section>'''

    def pdetail(num, title, icon_name, css, body, in_practice, draft=False):
        draft_tag = '<span class="draft-tag">Draft &mdash; pending final Charter language</span>' if draft else ''
        icon_html = icon(icon_name, css)
        return f'''<div class="principle-detail" id="p{num}">
      <div class="principle-detail-icon">{icon_html}<span class="num">{num}</span></div>
      <div class="principle-detail-body">
        <h3>{title}</h3>
        {draft_tag}
        <p>{body}</p>
      </div>
      <div class="principle-detail-practice">
        <span class="label">In practice</span>
        <p>{in_practice}</p>
      </div>
    </div>'''

    def movement_head(bar_color, range_label, name, sub, desc):
        return f'''<div class="movement-title"><span class="bar" style="background:{bar_color};"></span><span class="tag">{range_label} &middot; {name}</span><span class="sub">&mdash; {sub}</span></div>
      <p class="movement-desc">{desc}</p>'''

    movements = f'''<section class="section bg-cream">
  <div class="container">

    <div class="movement">
      {movement_head("var(--orange)", "01&ndash;03", "Practice", "Foundational values",
        "The starting posture for anyone building or supporting public sauna: who it&rsquo;s for, how it&rsquo;s used, and the traditions it draws from.")}
      <div class="principle-detail-list">
        {pdetail("01","Access for All","network","ic-tan",
          "Access means proximity, affordability, accessibility, and belonging &mdash; ensuring public sauna is close enough to reach, affordable enough to use, accessible to every body, and welcoming to all.",
          "location, pricing, and physical accessibility are evaluated together, not treated as separate decisions made late in a project.")}
        {pdetail("02","Shared Heat, Shared Space","heat","ic-orange",
          "Public sauna is built for collective use: heat, steam, and space held in common, designed and governed for bathing together rather than private consumption.",
          "layouts, session norms, and scheduling are designed around shared use from day one, not retrofitted onto a private model.", draft=True)}
        {pdetail("03","Honour Tradition","leaf","ic-gold",
          "Sauna is a living culture, sustained by people, not products. The traditions, values, and practices we inherit deserve to be honoured, shared with care, and stewarded for future generations.",
          "operators credit the cultural lineages their practice draws from, and involve knowledge holders rather than borrowing aesthetics alone.")}
      </div>
    </div>

    <div class="movement">
      {movement_head("var(--gold)", "04&ndash;06", "Keeping", "Run for public good",
        "How public sauna is governed and operated day to day, so the mission comes first even as it grows.")}
      <div class="principle-detail-list">
        {pdetail("04","Public Good Before Private Gain","sun","ic-yellow",
          "Profit can support the mission. It shouldn&rsquo;t replace it.",
          "surplus is reinvested in access, safety, and community programming before it is distributed as profit.")}
        {pdetail("05","A Sense of Place","place","ic-lightgreen",
          "Sauna should strengthen the community it&rsquo;s rooted in, not extract from it.",
          "hiring, sourcing, and programming favour the local community, and the space reflects the place it stands in.")}
        {pdetail("06","Community First","lattice","ic-olive",
          "In a loneliness epidemic, public sauna is one of the few remaining spaces where strangers become regulars, and regulars become community &mdash; that belonging comes before commercial interest.",
          "pricing and access rules are stress-tested against whether they exclude the regulars a space depends on to feel like community.", draft=True)}
      </div>
    </div>

    <div class="movement">
      {movement_head("var(--blue)", "07&ndash;08", "Tending", "Ongoing care",
        "The duty of care that keeps a sauna safe, well-run, and in right relationship with the world around it.")}
      <div class="principle-detail-list">
        {pdetail("07","Tended with Care","weave","ic-lightblue",
          "Every public sauna carries a duty of care &mdash; to the people who gather there, the cultures it draws from, and the places that sustain it. This responsibility demands spaces that are safe, well-run, and built to last.",
          "trained hosts or stewards are present, maintenance is scheduled rather than reactive, and incidents have a clear response process.")}
        {pdetail("08","Reciprocity with the Natural World","reciprocity","ic-blue",
          "Wood, water, and fire are finite. Public sauna should give back to the land and resources it depends on, not simply draw from them.",
          "fuel, water use, and waste are actively managed, and the operation gives back to the ecosystem it draws heat and materials from.", draft=True)}
      </div>
    </div>

    <div class="movement">
      {movement_head("var(--purple)", "09&ndash;10", "Stewardship", "Shared future",
        "What public sauna owes back to the people and places it serves, over the long term.")}
      <div class="principle-detail-list">
        {pdetail("09","Wellbeing that Circulates","circulate","ic-lavender",
          "Wellbeing is not created in isolation. Public sauna strengthens the relationships, trust, and resilience that enable communities to adapt, recover, and flourish.",
          "a space measures success partly by the relationships and resilience it builds, not only by visits or revenue.")}
        {pdetail("10","Worth Public Support","seal","ic-purple",
          "Community sauna is real social infrastructure, and it should be funded and recognized like it.",
          "operators make the public-good case for funding and recognition alongside pools, rinks, and other civic infrastructure.")}
      </div>
    </div>

    <div class="callout" style="margin-top:8px;">Principles 2, 6, and 8 are draft placeholder copy written from the founding stewards&rsquo; &ldquo;What We Believe&rdquo; values, with an illustrative &ldquo;in practice&rdquo; line added for every principle &mdash; swap in the authoritative Charter text once finalized.</div>
  </div>
</section>'''

    who_can_sign = f'''<section class="section bg-white">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Who can sign</span>
      <h2>Built by, and for, everyone shaping public sauna</h2>
    </div>
    <div class="chip-grid">
      <div class="chip">Founding Stewards</div>
      <div class="chip">Advisors and Stewards</div>
      <div class="chip">Operators</div>
      <div class="chip">Governments and Public Bodies</div>
      <div class="chip">Designers, Builders and Developers</div>
      <div class="chip">Industry Partners</div>
      <div class="chip">Bathers and Community Members</div>
    </div>
  </div>
</section>'''

    how_signing_works = f'''<section class="section bg-green">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">How signing works</span>
      <h2>Signing is an application, and it asks for real commitments</h2>
      <p class="lede" style="opacity:0.85;">Takes about 25&ndash;30 minutes. Free, but real &mdash; you apply, and you commit.</p>
    </div>
    <div class="step-grid">
      <div class="step-card"><div class="step-num">1</div><h3>Discover the Charter</h3><p>Read the ten principles.</p></div>
      <div class="step-card"><div class="step-num">2</div><h3>Apply to sign</h3><p>Short form: who you are, which category.</p></div>
      <div class="step-card"><div class="step-num">3</div><h3>Make your commitments</h3><p>How the principles show up in your practice.</p></div>
      <div class="step-card"><div class="step-num">4</div><h3>Join the list</h3><p>Appear among signatories; connect to the network.</p></div>
    </div>
    <div style="margin-top:28px;">
      <a href="signatories.html#sign" class="btn btn-primary">Sign the Charter</a>
    </div>
  </div>
</section>'''

    is_isnt = f'''<section class="section bg-white">
  <div class="container">
    <div class="two-col">
      <div>
        <span class="eyebrow" style="color:var(--gold);">What the Charter is</span>
        <ul class="checklist" style="margin-top:18px;">
          <li><span class="box" style="border-color:var(--light-green); background:var(--light-green);"></span><p>A shared set of principles and norms for the responsible development and stewardship of public sauna.</p></li>
          <li><span class="box" style="border-color:var(--light-green); background:var(--light-green);"></span><p>A common point of reference for communities, practitioners, operators, governments, funders, researchers, and industry.</p></li>
          <li><span class="box" style="border-color:var(--light-green); background:var(--light-green);"></span><p>A guide for planning, governance, operations, investment, and policy.</p></li>
          <li><span class="box" style="border-color:var(--light-green); background:var(--light-green);"></span><p>A commitment to public sauna that is safe, accessible, culturally respectful, and trustworthy.</p></li>
          <li><span class="box" style="border-color:var(--light-green); background:var(--light-green);"></span><p>A living document that evolves through research, lived experience, and international dialogue.</p></li>
        </ul>
      </div>
      <div>
        <span class="eyebrow" style="color:var(--orange);">What the Charter isn&rsquo;t</span>
        <ul class="checklist" style="margin-top:18px;">
          <li><span class="box" style="border-color:var(--orange);"></span><p><strong>Not a certification</strong> &mdash; it does not certify or rank public saunas.</p></li>
          <li><span class="box" style="border-color:var(--orange);"></span><p><strong>Not a rulebook or technical standard</strong> &mdash; it defines shared principles, not technical specifications.</p></li>
          <li><span class="box" style="border-color:var(--orange);"></span><p><strong>Not a replacement for regulation</strong> &mdash; it complements existing laws and safety requirements.</p></li>
          <li><span class="box" style="border-color:var(--orange);"></span><p><strong>Not about standardization</strong> &mdash; it respects diverse cultures, traditions, and local contexts.</p></li>
          <li><span class="box" style="border-color:var(--orange);"></span><p><strong>Not static</strong> &mdash; it is collaboratively stewarded and openly developed with humility.</p></li>
        </ul>
      </div>
    </div>
  </div>
</section>'''

    body = page_hero + movements + who_can_sign + how_signing_works + is_isnt + closing_cta()
    write("overview.html", layout(
        "Overview",
        "The Public Sauna-Bathing Charter: ten principles in four movements, who can sign, and how signing works.",
        "overview.html", body))

# ---------------------------------------------------------------------------
# PARTNERS PAGE (merged Sign the Charter + Signatories)
# ---------------------------------------------------------------------------
_PLACEHOLDER_SIGNATORIES = [
    {"name": "Name TBD", "url": "#", "country": "City, Canada",
     "categories": ["Operators"],
     "commitment": "Placeholder commitment &mdash; how this signatory reflects the Charter&rsquo;s principles in day-to-day practice."},
    {"name": "Name TBD", "url": "#", "country": "City, Finland",
     "categories": ["Advisors and Stewards", "Bathers and Community Members"],
     "commitment": "Placeholder commitment &mdash; how this signatory reflects the Charter&rsquo;s principles in day-to-day practice."},
    {"name": "Name TBD", "url": "#", "country": "City, Ireland",
     "categories": ["Operators"],
     "commitment": "Placeholder commitment &mdash; how this signatory reflects the Charter&rsquo;s principles in day-to-day practice."},
    {"name": "Name TBD", "url": "#", "country": "City, England",
     "categories": ["Governments and Public Bodies"],
     "commitment": "Placeholder commitment &mdash; how this signatory reflects the Charter&rsquo;s principles in day-to-day practice."},
    {"name": "Name TBD", "url": "#", "country": "City, Canada",
     "categories": ["Designers, Builders and Developers"],
     "commitment": "Placeholder commitment &mdash; how this signatory reflects the Charter&rsquo;s principles in day-to-day practice."},
    {"name": "Name TBD", "url": "#", "country": "City, Finland",
     "categories": ["Industry Partners"],
     "commitment": "Placeholder commitment &mdash; how this signatory reflects the Charter&rsquo;s principles in day-to-day practice."},
]

SIGNATORIES = load_signatories(SIGNATORIES_SHEET_CSV_URL, _PLACEHOLDER_SIGNATORIES)
SIGNATORY_COUNTRY_COUNT = len({_country_of(s) for s in SIGNATORIES if _country_of(s)})

QUOTES = [
    {"quote": "Placeholder quote about why this signatory signed and what the Charter means for their work.", "name": "Name TBD", "country": "Canada"},
    {"quote": "Placeholder quote about why this signatory signed and what the Charter means for their work.", "name": "Name TBD", "country": "Finland"},
    {"quote": "Placeholder quote about why this signatory signed and what the Charter means for their work.", "name": "Name TBD", "country": "Ireland"},
]

SIGNATORY_CATEGORIES = [
    "Founding Stewards", "Advisors and Stewards", "Operators", "Governments and Public Bodies",
    "Designers, Builders and Developers", "Industry Partners", "Bathers and Community Members",
]

def page_signatories():
    hero = f'''<section class="section bg-cream" style="padding-bottom:0;">
  <div class="container two-col">
    <div>
      <span class="eyebrow" style="color:var(--gold);">Signatories</span>
      <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px;">Sign the Charter, and meet those who already have</h1>
      <p class="lede muted">Sauna for All is built by the people and organizations shaping public sauna today &mdash; operators, governments, designers, researchers, industry partners, and bathers. Sign the Charter to add your name, or explore who has already committed.</p>
    </div>
    <div class="placeholder-img" style="aspect-ratio:4/3;"><span>Image: sauna bucket / detail photography</span></div>
  </div>
</section>'''

    commit = f'''<section class="section bg-green" id="commit">
  <div class="container">
    <div class="two-col">
      <div>
        <span class="eyebrow">Contribute</span>
        <h2 style="margin:14px 0 18px; color:var(--white);">Commit to the movement</h2>
        <p class="lede" style="opacity:0.9;">Sauna for All is entirely volunteer-led. This work &mdash; drafting the Charter, building the network, hosting workshops, and keeping this site running &mdash; cannot happen without support like yours and our partners&rsquo;. If you can contribute time, funding, expertise, or space, we want to hear from you.</p>
      </div>
      <div class="stack-20">
        <div class="info-card on-green">
          <h3 style="color:var(--white);">Ways to support</h3>
          <p style="color:var(--cream); opacity:0.85;">In-kind space &amp; hosting &middot; funding &amp; grants &middot; research &amp; evaluation &middot; design &amp; build expertise &middot; translation &amp; local coordination.</p>
        </div>
        <a href="mailto:pelkoreb@uef.fi" class="btn btn-primary">Get in touch to contribute</a>
      </div>
    </div>
  </div>
</section>'''

    regional_partners = f'''<section class="section bg-cream">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Regional partners</span>
      <h2>Independent partners coordinating locally</h2>
      <p class="lede muted">Like Swimmable Cities, independent contacts for certain regions &mdash; for example, the Community Sauna Network. Logos and links to come.</p>
    </div>
    <div class="logo-row">
      <div class="logo-tile">Community Sauna Network</div>
      <div class="logo-tile">Regional partner</div>
    </div>
  </div>
</section>'''

    sign = f'''<section class="section bg-white" id="sign">
  <div class="container">
    <div class="badge-note">Signing is an application process &mdash; it asks for real commitments and takes about 30 minutes.</div>
    <div class="two-col">
      <div>
        <h2 style="font-size:clamp(1.7rem,3.4vw,2.2rem); margin-bottom:18px;">Sign the Charter</h2>
        <p class="lede muted">By signing, you commit to the Charter&rsquo;s principles and to demonstrating how they are reflected in your decisions, operations, and stewardship.</p>

        <ul class="checklist">
          <li><span class="box"></span><p><strong>Part A &mdash; Commitment:</strong> who you are, why you&rsquo;re signing, your principles and commitments.</p></li>
          <li><span class="box"></span><p><strong>Part B &mdash; Contribution:</strong> stewardship, the sector, research, looking forward.</p></li>
          <li><span class="box"></span><p><strong>Part C &mdash; Consent and affirmation.</strong></p></li>
          <li><span class="box"></span><p>About 25&ndash;30 minutes.</p></li>
          <li><span class="box"></span><p>Responses go to the founding stewards for review.</p></li>
        </ul>

        <a href="#" class="btn btn-solid-orange">Open the Questionnaire</a>
        <p class="small muted" style="margin-top:12px;">Opens in Google Forms.</p>
      </div>

      <div class="stack-20">
        <div class="info-card">
          <h3>What happens next</h3>
          <p>Review by the stewards &rarr; confirmation &rarr; listed among signatories &rarr; welcomed to network channels.</p>
        </div>
        <div class="callout">The questionnaire is hosted on Google Forms. This page sets expectations before you begin.</div>
        <div class="info-card">
          <h3>Who can sign</h3>
          <p class="small">Operators, hosts &amp; stewards &middot; Governments &amp; municipalities &middot; Designers, builders &amp; developers &middot; Researchers &amp; knowledge holders &middot; Industry partners &middot; Bathers &amp; community members.</p>
          <a href="overview.html" style="display:inline-block; margin-top:10px; font-weight:700; text-decoration:underline; font-size:0.9rem;">Read who can sign in full &rarr;</a>
        </div>
      </div>
    </div>
  </div>
</section>'''

    def category_pills(cats):
        return "".join(f'<span class="category-pill">{c}</span>' for c in cats)

    def signatory_card(s):
        cats_attr = "|".join(s["categories"])
        commitment_html = (f'<p class="signatory-commitment">&ldquo;{s["commitment"]}&rdquo;</p>'
                            if s["commitment"] else "")
        return f'''<div class="signatory-card" data-categories="{cats_attr}" data-name="{s["name"]}" data-country="{s["country"]}">
      <div class="signatory-card-top">
        <div class="logo-tile" style="width:64px; height:64px; font-size:0.6rem;">Logo</div>
        <div class="category-pills">{category_pills(s["categories"])}</div>
      </div>
      <a href="{s["url"]}" class="signatory-name-link" target="_blank" rel="noopener">{s["name"]}</a>
      <div class="signatory-country">{s["country"]}</div>
      {commitment_html}
    </div>'''

    signatories_html = "".join(signatory_card(s) for s in SIGNATORIES)
    category_chips_html = "".join(
        f'<button type="button" class="filter-chip" data-category="{c}">{c}</button>' for c in SIGNATORY_CATEGORIES
    )

    directory = f'''<section class="section bg-cream">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Signatories</span>
      <h2>Who has signed the Charter</h2>
      <p class="lede muted">Category, logo, country, and commitment are pulled live from the signatory database once connected &mdash; shown here as placeholder fields. Category is multi-select in the backend &mdash; filter by one or more below, or search by name or country.</p>
    </div>
    <div class="badge-note">This is a placeholder list &mdash; connect a live data source (spreadsheet or CMS) so it updates automatically as applications are approved.</div>
    <div class="filter-bar">
      <div class="filter-chips" id="signatoryFilters">
        <button type="button" class="filter-chip active" data-category="">All</button>
        {category_chips_html}
      </div>
      <input type="search" id="signatorySearch" class="filter-search" placeholder="Search by name or country&hellip;" aria-label="Search signatories">
    </div>
    <div class="signatories-grid" id="signatoriesGrid">{signatories_html}</div>
    <p class="filter-empty" id="signatoryEmpty">No signatories match your filters yet.</p>
  </div>
</section>'''

    def quote_card(q):
        return f'''<div class="quote-card">
      <blockquote>&ldquo;{q["quote"]}&rdquo;</blockquote>
      <div class="quote-attribution">{q["name"]}</div>
      <div class="small muted">{q["country"]}</div>
    </div>'''

    quotes_html = "".join(quote_card(q) for q in QUOTES)

    commitments = f'''<section class="section bg-white">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Commitments</span>
      <h2>In their own words</h2>
    </div>
    <div class="commitments-grid">{quotes_html}</div>
  </div>
</section>'''

    body = hero + sign + directory + commitments + commit + regional_partners + closing_cta()
    write("signatories.html", layout(
        "Signatories",
        "Sign the Public Sauna-Bathing Charter, see who has already signed, and find out how to contribute to the movement.",
        "signatories.html", body))

# ---------------------------------------------------------------------------
# ABOUT PAGE (mission + founding stewards, combined)
# ---------------------------------------------------------------------------
def page_about():
    stewards = ["Becky Pelkonen","Charlie Duckworth","Polly Wilson","Freddie Mehigan","Steve Crosbie",
                "Ian Whelan","Niamh Murphy","Juho Pelkonen","Jason Wong","Azar Eskandarpour"]
    def person(name):
        initials = "".join([p[0] for p in name.split()[:2]])
        return f'''<div class="person"><div class="avatar">{initials}</div><div class="name">{name}</div><div class="role">Founding Steward</div></div>'''

    people_html = "".join(person(s) for s in stewards)

    body = f'''<section class="section bg-cream" style="padding-bottom:0;">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">About the movement</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 18px;">Public sauna as common good</h1>
    <p class="lede muted" style="max-width:64ch;">Around the world, people are rediscovering the value of public sauna &mdash; not only for individual wellbeing, but for community life. <em>Sauna for All</em> is a grassroots movement guiding this resurgence through shared values, evidence, and effective collaboration, so that public sauna continues to evolve as trusted civic and cultural infrastructure rooted in the common good.</p>
    <a href="#stewards" style="display:inline-block; margin-top:18px; text-decoration:underline; font-weight:700;">Meet the founding stewards &rarr;</a>
  </div>
</section>

<section class="section bg-cream">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">What we do</span>
      <h2>A charter, a network, and a shared voice</h2>
    </div>
    <div class="card-grid">
      <div class="info-card"><h3>1. A charter</h3><p>Shared principles shaped by the people doing the work, not any one group&rsquo;s rules.</p></div>
      <div class="info-card"><h3>2. A network</h3><p>Operators, hosts, trainers, researchers, and stewards, so no one builds alone. In development &mdash; WhatsApp group for now.</p></div>
      <div class="info-card"><h3>3. A shared voice</h3><p>Strong enough for funders, cities, and policymakers to hear, and to recognize community sauna as worth investing in.</p></div>
    </div>
  </div>
</section>

<section class="section bg-white" id="stewards">
  <div class="container">
    <div class="section-head">
      <span class="eyebrow">Founding Stewards</span>
      <h2>Guided by an international steering group</h2>
      <p class="lede muted">Practitioners, researchers, community leaders, and organizations committed to strengthening public sauna through knowledge sharing, cultural stewardship, and collective action.</p>
    </div>
    <div class="people-grid">{people_html}</div>
  </div>
</section>

<section class="section bg-cream">
  <div class="container">
    <div class="card-grid">
      <div class="info-card">
        <h3>Advisors</h3>
        <p>With gratitude to those who generously shared knowledge, guidance, and encouragement throughout the Charter&rsquo;s development: Sauna From Finland, Dalva Lamminm&auml;ki, Mikkel Aaland, Lorna Little, Alan Jalasjaa, and Glen Auerbach.</p>
      </div>
      <div class="info-card">
        <h3>Founding organizations</h3>
        <div class="logo-row" style="margin-top:6px;">
          <div class="logo-tile" style="width:96px; height:56px; font-size:0.65rem;">Kamu Sauna</div>
          <div class="logo-tile" style="width:96px; height:56px; font-size:0.65rem;">Kotisauna</div>
          <div class="logo-tile" style="width:96px; height:56px; font-size:0.65rem;">Community Sauna Baths</div>
        </div>
      </div>
      <div class="info-card">
        <h3>Meet the wider network</h3>
        <p>See partner organizations and signatories on the <a href="signatories.html" style="text-decoration:underline; font-weight:700;">Signatories page &rarr;</a>.</p>
      </div>
    </div>
  </div>
</section>

<section class="section bg-white">
  <div class="container">
    <div class="two-col">
      <div class="info-card">
        <h3>Action plan</h3>
        <p>Finalize Charter and gain initial signatories &middot; run online workshops for identified signatories &middot; develop and launch this website &middot; roll out case studies, a research database, and socials &middot; UK-based conference (November 2026, led by CSB and CSN) &middot; develop a Report on Public Sauna &middot; work toward measurement tools and an &ldquo;Index&rdquo; for best practice.</p>
      </div>
      <div class="info-card">
        <h3>Get in touch</h3>
        <p>Becky Pelkonen and the Community Sauna Network, founding stewards.</p>
        <a href="mailto:pelkoreb@uef.fi" style="display:inline-block; margin-top:10px; font-weight:700; text-decoration:underline;">pelkoreb@uef.fi</a>
        <p class="small muted" style="margin-top:8px;">No contact form at launch &mdash; email directly.</p>
      </div>
    </div>
  </div>
</section>'''
    write("about.html", layout(
        "About",
        "About Sauna for All — a grassroots movement guiding public sauna-bathing as common good, and the founding stewards behind it.",
        "about.html", body))

# ---------------------------------------------------------------------------
# FAQS PAGE
# ---------------------------------------------------------------------------
def page_faqs():
    faqs = [
        ("What is the Public Sauna-Bathing Charter?",
         'A shared set of principles and norms for the responsible development and stewardship of public sauna &mdash; a common point of reference for communities, practitioners, operators, governments, funders, researchers, and industry. Read the full <a href="overview.html" style="text-decoration:underline; font-weight:700;">Overview &amp; Charter &rarr;</a>.'),
        ("Who can sign the Charter?",
         'Founding stewards, advisors and stewards, operators, governments and public bodies, designers, builders and developers, industry partners, and bathers and community members &mdash; see the full list on the <a href="overview.html" style="text-decoration:underline; font-weight:700;">Overview page &rarr;</a>.'),
        ("Is there a cost to sign?",
         "No. Signing is free. It is, however, a genuine application &mdash; it asks for real commitments, not just a signature."),
        ("What happens after I apply?",
         "Your responses go to the founding stewards for review. Once confirmed, you&rsquo;re listed among signatories and welcomed into network channels."),
        ("Is the Charter a certification or standard?",
         'No. It does not certify or rank public saunas, and it isn&rsquo;t a technical standard or rulebook. It sets out shared principles, not specifications &mdash; see <a href="overview.html" style="text-decoration:underline; font-weight:700;">what the Charter is / isn&rsquo;t &rarr;</a>.'),
        ("How can I get involved if I&rsquo;m not ready to sign?",
         'You can contribute time, funding, expertise, or space &mdash; see <a href="signatories.html#commit" style="text-decoration:underline; font-weight:700;">Commit to the Movement &rarr;</a>, or stay close to the movement through the newsletter on our homepage.'),
        ("Who governs and funds the Charter?",
         'Sauna for All is entirely volunteer-led by an international steering group of founding stewards. See <a href="about.html#stewards" style="text-decoration:underline; font-weight:700;">Founding Stewards &rarr;</a>.'),
    ]
    def faq_item(q, a):
        return f'<div class="faq-item"><h3>{q}</h3><p>{a}</p></div>'
    faqs_html = "".join(faq_item(q, a) for q, a in faqs)

    body = f'''<section class="section bg-cream" style="padding-bottom:0;">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">FAQs</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 16px;">Frequently asked questions</h1>
    <p class="lede muted" style="max-width:64ch;">Answers to common questions about signing, the Charter&rsquo;s scope, and governance.</p>
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
        "faqs.html", body))

# ---------------------------------------------------------------------------
# NEWS PAGE
# ---------------------------------------------------------------------------
def page_news():
    def card():
        return f'''<div class="news-card">
      <div class="placeholder-img"><span>Image</span></div>
      <div class="news-card-body">
        <h3>Post or press item title</h3>
        <div class="meta">Date &middot; Source or author</div>
        <p class="small muted">One-line summary of the piece, linking out to the original source.</p>
      </div>
    </div>'''

    body = f'''<section class="section bg-cream" style="padding-bottom:0;">
  <div class="container">
    <span class="eyebrow" style="color:var(--gold);">News</span>
    <h1 style="font-size:clamp(2rem,4vw,2.6rem); margin:14px 0 8px;">About the movement, in the press</h1>
  </div>
</section>
<section class="section bg-cream">
  <div class="container">
    <div class="card-grid">
      {card()}{card()}{card()}
    </div>
    <div class="info-card" style="margin-top:32px;">
      <h3>Press kit</h3>
      <p>Boilerplate paragraph, logos, and key facts for media &mdash; plus a direct contact. Lives in Google Drive; link it here once available.</p>
    </div>
  </div>
</section>'''
    write("news.html", layout(
        "News",
        "News and press coverage of the Sauna for All movement and the Public Sauna-Bathing Charter.",
        "news.html", body))

print("Helpers loaded.")

if __name__ == "__main__":
    page_home()
    page_overview()
    page_signatories()
    page_about()
    page_faqs()
    page_news()
    print("Build complete.")
