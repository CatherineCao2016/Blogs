# Blog / guides — staging site

Medium-style clean static blog for a personal GitHub Pages preview, with
**Cloudflare Web Analytics** for view tracking. A home page lists every post as a
card grid; each post gets its own page. This is a pre-launch staging preview, not
an official Kiro publication.

## Add a new post (no code edits)

1. Drop a new Markdown file in `content/posts/<slug>.md`. The file name is the URL
   slug (`content/posts/my-post.md` → `/my-post/`).
2. Start it with a front-matter block:

   ```
   ---
   title: My post title
   date: 2026-10-01
   summary: One or two sentences shown on the home page card.
   cover: my-image.png        # optional; put the image in content/
   ---

   Body starts here…
   ```

3. Put images for the post in `content/assets/<slug>/` (a folder named after the
   post's slug) and reference them from the body as `./image.png`. Each post owns
   its own image folder, so two posts can reuse the same file name without
   clashing. The `cover:` image is resolved from the same folder. To add a visible
   caption under an image, put an italic `Caption:` line right after it:

   ```markdown
   ![alt text](./image.png)
   _Caption: The text shown under the image._
   ```

   Images render as semantic `<figure>` elements; with a `Caption:` line the text
   becomes a `<figcaption>`. Alt text is always required for accessibility; the
   caption is optional.
4. Embed videos with `[Video: A title]` in the body, and add a `videos:` list to
   the front-matter mapping them in order:

   ```
   videos:
     - youtube_id: dQw4w9WgXcQ, title: A title
   ```

5. Rebuild. The home page card grid and the post page are regenerated. Posts sort
   newest-first by `date`.

## Table of contents (automatic)

Each post gets a table of contents built from its `##` and `###` headings — no
front-matter needed. On wide screens it is a sticky sidebar on the right that
highlights the section you are reading (scroll-spy); on mobile it collapses into
an "On this page" toggle above the article. A post with fewer than two headings
gets no TOC. Write good `##` section headings and the TOC follows.

## Build locally

```bash
./setup.sh                       # one-time: creates .venv, installs markdown
./.venv/bin/python build.py      # renders site/
open site/index.html             # preview the home page
```

## Track views (Cloudflare Web Analytics)

Cloudflare Web Analytics is cookieless and free, so it needs no cookie banner.

1. Sign in at https://dash.cloudflare.com/ and open **Analytics & Logs → Web Analytics**.
2. **Add a site** and enter the URL your Pages site will serve at
   (e.g. `https://<you>.github.io/<repo>/` or your custom domain).
3. Cloudflare shows a JS snippet containing a **token**. Copy just the token value.
4. Put it in `config.json` (`"cf_analytics_token": "<token>"`), **or** set the
   `CF_ANALYTICS_TOKEN` repository secret so it is injected only at deploy time
   and never committed. The secret takes precedence over `config.json`.
5. Rebuild / redeploy. The beacon loads on the live site and views appear in the
   Cloudflare dashboard within a minute.

The beacon only fires on the deployed origin, so local `file://` previews record
nothing — that is expected.

## Embed the videos

Each `[Video: A title]` placeholder in a post body maps, in document order, to an
entry in that post's `videos:` front-matter list. Upload the walkthrough(s) to
YouTube (unlisted is fine for staging), then add the IDs:

```
videos:
  - youtube_id: dQw4w9WgXcQ, title: Running a task in a cloud session
```

Until an ID is set the page builds with a labelled placeholder card, and the
written walkthrough in the post stays inline as the text fallback.

## Deploy to GitHub Pages

1. Create a repo (private is fine for staging) and push this folder to `main`.
2. In **Settings → Pages**, set **Source: GitHub Actions**.
3. (Optional) add the `CF_ANALYTICS_TOKEN` secret under
   **Settings → Secrets and variables → Actions**.
4. Every push to `main` runs `.github/workflows/deploy.yml`, which builds and
   publishes `site/` to Pages.

## Files

| File | Purpose |
|------|---------|
| `content/posts/*.md` | One Markdown file per post, with front-matter |
| `content/assets/<slug>/` | Images for that post (body images + `cover`) |
| `build.py` | Scans posts → home page + per-post pages, injects analytics + video embeds |
| `config.json` | Site title, tagline, Cloudflare token (fallback) |
| `videos.json` | Global video fallback (per-post `videos:` front-matter preferred) |
| `.github/workflows/deploy.yml` | Build + deploy to GitHub Pages |
