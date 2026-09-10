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

Usage:
    python3 build.py            # regenerates index.html etc. from templates/data
    python3 prepare_deploy.py   # writes self-contained pages into dist/

Then go to:
    https://dash.cloudflare.com/?to=/:account/workers/services/view/sauna-for-all/production
    -> "New deployment" -> drag in every .html file from dist/ -> Deploy
"""
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")

PAGES = [
    "index.html", "about.html", "overview.html",
    "signatories.html", "news.html", "faqs.html",
]

def main():
    with open(os.path.join(ROOT, "css", "style.css")) as f:
        css = f.read()
    with open(os.path.join(ROOT, "js", "main.js")) as f:
        js = f.read()

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)

    for name in PAGES:
        with open(os.path.join(ROOT, name)) as f:
            html = f.read()
        html = html.replace(
            '<link rel="stylesheet" href="style.css">',
            f"<style>\n{css}\n</style>",
        )
        html = html.replace(
            '<script src="main.js"></script>',
            f"<script>\n{js}\n</script>",
        )
        out_path = os.path.join(DIST, name)
        with open(out_path, "w") as f:
            f.write(html)
        print(f"wrote dist/{name}")

    print(f"\nDone. Upload every file in {DIST} to Cloudflare's 'New deployment' page.")

if __name__ == "__main__":
    main()
