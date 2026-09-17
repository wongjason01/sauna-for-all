# Giving Becky a CMS to edit content without touching code

The site is a Python static-site generator (`build.py`) that writes plain HTML files,
committed to GitHub, and deployed to Cloudflare Workers by uploading the built files.
Right now every content change (a new FAQ, a resource, a press logo) means editing Python
and re-running the build -- fine for a developer, not something to hand Becky directly.

The plan discussed earlier in this project was **Sveltia CMS** (a lightweight,
git-backed, open-source CMS with no server of its own to run) plus **Cloudflare Workers
Builds** (git-integration auto-deploy, so a commit to `main` rebuilds and redeploys
automatically instead of needing the manual `prepare_deploy.py` + dashboard-upload step
used throughout this project). This file lays out the concrete steps and the decisions
that need making first -- it isn't done yet, because both require access this project
doesn't have (a Cloudflare account, and a product decision from Becky).

## Step 0: decide what Becky actually needs to edit

This matters before writing any config, because Sveltia CMS edits **files**, and
`build.py` currently keeps almost all copy as Python string literals inside functions,
not as separate files. Rewiring *everything* into CMS-editable files would be a large,
risky rewrite of a site that mostly holds finished, spec-approved, word-for-word copy
that isn't meant to change casually.

The pieces of this site that are genuinely meant to change over time, and are already
structured as their own data (not prose woven into a page layout), are the best
candidates:

| Content | Current state | CMS-ready? |
|---|---|---|
| Signatories | Already editable -- via the live Google Sheet, not code | No CMS needed |
| FAQs | 7 interim Q&As hardcoded in `page_faqs()`, 16 planned | Good candidate |
| Resources | Empty list (`RESOURCES = []`), category cards hardcoded | Good candidate |
| News/press logos | Empty list (`PRESS_LOGOS = []`) | Good candidate |
| Regional partners | Empty list (`REGIONAL_PARTNERS = []`) | Good candidate |
| Home/About/Charter body copy | Spec-verbatim prose woven into HTML layout | Not worth it yet |

Recommended first phase: move just the four "Good candidate" lists into their own YAML
files under a new `content/` directory, and have `build.py` read them instead of
defining them inline. Everything else stays code-managed until there's a real need to
change it more often than the codebase itself changes.

## Step 1: restructure that content into files

For each candidate, create a YAML file, e.g. `content/faqs.yml`:

```yaml
- question: "What is the Public Sauna-Bathing Charter?"
  answer: "A shared set of principles..."
- question: "Who can sign the Charter?"
  answer: "Founding stewards, advisors..."
```

`content/resources.yml`, `content/press_logos.yml`, `content/regional_partners.yml`
following the same shape as their existing Python list-of-dicts equivalents. `build.py`
then loads each with `yaml.safe_load(open(path))` at the top of the relevant `page_*()`
function instead of a hardcoded list. This is a small, mechanical change once the file
format is agreed, and it's the only code change this step needs.

## Step 2: add the Sveltia CMS admin panel

Sveltia CMS is just a static JS app pointed at a config file -- no build step of its own.

1. Create `admin/index.html`:
   ```html
   <!DOCTYPE html>
   <html><head><meta charset="utf-8" /><title>Content Manager</title></head>
   <body>
   <script src="https://unpkg.com/@sveltia/cms/dist/sveltia-cms.js" type="module"></script>
   </body></html>
   ```
2. Create `admin/config.yml` describing each editable collection, e.g.:
   ```yaml
   backend:
     name: github
     repo: wongjason01/sauna-for-all
     branch: main
     base_url: https://sveltia-cms-auth.<your-subdomain>.workers.dev

   media_folder: "images/uploads"
   public_folder: "/images/uploads"

   collections:
     - name: faqs
       label: FAQs
       files:
         - name: faqs
           label: FAQ list
           file: content/faqs.yml
           fields:
             - { name: questions, label: Questions, widget: list, fields: [
                 { name: question, label: Question, widget: string },
                 { name: answer, label: Answer, widget: text } ] }
     - name: resources
       label: Resources
       files:
         - name: resources
           label: Resource list
           file: content/resources.yml
           fields: [...]
   ```
   (Repeat a `files` entry per content type from Step 1.)

## Step 3: deploy the sveltia-cms-auth Worker

GitHub's OAuth flow needs a small server-side piece to exchange the auth code for a
token; Sveltia's own `sveltia-cms-auth` Worker does exactly this and nothing more.

1. Register a GitHub OAuth App (GitHub Settings -> Developer settings -> OAuth Apps) for
   this repo, noting the Client ID and Client Secret.
2. `npx wrangler deploy` the `sveltia-cms-auth` Worker (source at
   github.com/sveltia/sveltia-cms-auth) to Cloudflare, with `GITHUB_CLIENT_ID` and
   `GITHUB_CLIENT_SECRET` set as Worker secrets (`wrangler secret put ...`).
3. Set that Worker's deployed URL as `backend.base_url` in `admin/config.yml` (Step 2).
4. In the GitHub OAuth App's settings, set the callback URL to
   `https://sveltia-cms-auth.<your-subdomain>.workers.dev/callback`.

## Step 4: connect Cloudflare Workers Builds

This replaces the manual `prepare_deploy.py` + dashboard-upload flow used throughout
this project with automatic deploys on every push to `main`:

1. In the Cloudflare dashboard, open the `sauna-for-all` Worker -> Settings -> Builds.
2. Connect the GitHub repo and branch (`main`).
3. Set the build command to run both build steps in sequence:
   `python3 build.py && python3 prepare_deploy.py`
4. Set the deploy/output directory to `dist/` (what `prepare_deploy.py` already
   produces -- self-contained HTML with CSS/JS inlined, which is what made the Cloudflare
   static-upload MIME-type issue go away earlier in this project; Workers Builds should
   respect the same output rather than trying to serve `css/style.css` and `js/*.js` as
   separate files again).
5. Once this is verified working, the manual "upload via GitHub's web UI, then upload via
   Cloudflare's dashboard" workflow used throughout this project is no longer needed --
   pushing to `main` (from this sandbox, from Becky's CMS edits, or from a normal `git
   push`) deploys automatically.

## What's already done vs. still open

Done in this project: the CSV-based signatories pipeline (a form of "content management"
that doesn't need Sveltia at all, since Becky/the stewards already just fill in a Google
Form).

Still open, and blocking real Sveltia setup: Step 0's decision (confirm which content
Becky wants to self-edit), a Cloudflare account with permission to deploy Workers and
enable Workers Builds, and a GitHub OAuth App under an account with admin rights on this
repo. None of these are things this project can do unattended -- they need a person with
the right access to follow the steps above.
