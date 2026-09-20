"""
Prepares a deploy-ready copy of the site for Cloudflare's manual
"Upload static files" flow (Workers & Pages > sauna-for-all > New deployment).

Why this exists: Cloudflare's browser-based static-file uploader trusts the
browser-supplied MIME type for each file instead of inferring it from the
extension. In this environment that resulted in style.css and main.js being
served as application/octet-stream (so the browser refused to apply them).
The reliable fix is to inline the CSS and JS directly into each HTML page,
so only .html files need to be uploaded (those get the correct text/html
type every time).

Also copies the local static assets the pages reference by absolute path
(currently the three /images/photos/*.jpg used on Home and About, and the
Charter PDF at /files/public-sauna-bathing-charter.pdf) into dist/ under the
same relative paths, so dist/ is a single complete, ready-to-upload folder --
no separate "don't forget the images" step.

Usage:
    python3 build.py            # regenerates index.html etc. from templates/data
    python3 prepare_deploy.py   # writes self-contained pages + assets into dist/

Then go to:
    https://dash.cloudflare.com/?to=/:account/workers/services/view/sauna-for-all/production
    -> "New deployment" -> drag in every file/folder from dist/ -> Deploy
"""
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

PAGES = [
    "index.html", "about.html", "charter.html",
    "signatories.html", "news.html", "faqs.html",
    "resources.html", "contact.html",
]

# Local static assets referenced by absolute path (src="/..." or href="/...")
# in the built HTML. Kept as an explicit list (rather than copying all of
# images/ and files/) so an unused asset added to those folders later doesn't
# silently bloat every deploy -- add to this list when a page starts
# referencing something new.
STATIC_ASSETS = [
    "images/photos/sauna-for-all-2026-04.jpg",
    "images/photos/sauna-for-all-2026-05.jpg",
    "images/photos/sauna-for-all-2026-13.jpg",
    "images/photos/sauna-for-all-2026-14.jpg",
    "images/photos/sauna-for-all-2026-12.jpg",
    "images/photos/sauna-for-all-2026-21.jpg",
    "images/photos/sauna-for-all-2026-23.jpg",
    "images/photos/sauna-for-all-signatories-hero.jpg",
    "files/public-sauna-bathing-charter.pdf",
    "images/headshots/becky-pelkonen.jpg",
    "images/headshots/polly-wilson.jpg",
    "images/headshots/charlie-duckworth.jpg",
    "images/headshots/freddie-mehigan.jpg",
    "images/headshots/ian-whelan.jpg",
    "images/headshots/jason-wong.jpg",
    "images/headshots/azar-eskandarpour.jpg",
    "images/headshots/juho-pelkonen.jpg",
    "images/headshots/niamh-murphy.jpg",
    "images/headshots/mikkel-aaland.jpg",
    "images/headshots/dalva-lamminmaki.jpg",
    "images/headshots/steve-crosbie.jpg",
    "images/headshots/carita-harju.jpg",
    "images/headshots/sauna-from-finland-logo.jpg",
    "images/logo/sauna-for-all-orange.png",
    "images/icons/network.png",
    "images/icons/heat.png",
    "images/icons/leaf.png",
    "images/icons/sun.png",
    "images/icons/place.png",
    "images/icons/lattice.png",
    "images/icons/weave.png",
    "images/icons/reciprocity.png",
    "images/icons/circulate.png",
    "images/icons/seal.png",
    "images/icons/thumbs-up.png",
]

def main():
    with open(os.path.join(ROOT, "css", "style.css")) as f:
        css = f.read()
    with open(os.path.join(ROOT, "js", "main.js")) as f:
        main_js = f.read()
    with open(os.path.join(ROOT, "js", "news-feed.js")) as f:
        news_feed_js = f.read()
    with open(os.path.join(ROOT, "js", "signatories-feed.js")) as f:
        signatories_feed_js = f.read()

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)

    for name in PAGES:
        with open(os.path.join(ROOT, name)) as f:
            html = f.read()
        html = html.replace(
            '<link rel="stylesheet" href="css/style.css">',
            f"<style>\n{css}\n</style>",
        )
        html = html.replace(
            '<script src="js/main.js"></script>\n<script src="js/news-feed.js"></script>\n<script src="js/signatories-feed.js"></script>',
            f"<script>\n{main_js}\n</script>\n<script>\n{news_feed_js}\n</script>\n<script>\n{signatories_feed_js}\n</script>",
        )
        if "<style>" not in html or "<script>" not in html:
            raise RuntimeError(
                f"{name}: expected href/src not found -- check build.py's "
                "asset tags haven't changed and update this script to match."
            )
        out_path = os.path.join(DIST, name)
        with open(out_path, "w") as f:
            f.write(html)
        print(f"wrote dist/{name}")

    for rel_path in STATIC_ASSETS:
        src_path = os.path.join(ROOT, rel_path)
        if not os.path.isfile(src_path):
            raise RuntimeError(
                f"static asset missing: {rel_path} -- update STATIC_ASSETS "
                "in this script if it moved or was renamed."
            )
        dest_path = os.path.join(DIST, rel_path)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        shutil.copyfile(src_path, dest_path)
        print(f"copied dist/{rel_path}")

    # Signatory logos are copied wholesale rather than listed one by one: a new
    # signatory's logo should ship just by being dropped into the folder, with
    # no second edit here to forget. Everything in there is referenced by
    # definition -- build.py only emits a tile for a file it found.
    logo_dir = os.path.join(ROOT, "images", "signatories")
    if os.path.isdir(logo_dir):
        for name in sorted(os.listdir(logo_dir)):
            src_path = os.path.join(logo_dir, name)
            if not os.path.isfile(src_path) or name.startswith("."):
                continue
            rel_path = f"images/signatories/{name}"
            dest_path = os.path.join(DIST, rel_path)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copyfile(src_path, dest_path)
            print(f"copied dist/{rel_path}")

    print(f"\nDone. Upload every file/folder in {DIST} to Cloudflare's 'New deployment' page.")

if __name__ == "__main__":
    main()
