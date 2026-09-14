#!/usr/bin/env python3
"""Static multi-post blog generator (Medium-style light theme).

Layout:
    content/posts/<slug>.md   one Markdown file per post, with YAML front-matter:
                                ---
                                title: ...
                                date: YYYY-MM-DD
                                summary: ...            (shown on the home page card)
                                cover: image.png        (optional, relative to content/)
                                ---
    content/*.png             images referenced by posts (./name.png)

Output:
    site/index.html           home page: card grid of all posts, newest first
    site/<slug>/index.html    one page per post
    site/<image>              copied images
    site/.nojekyll

Behaviour:
- Cloudflare Web Analytics beacon injected on every page (token from
  CF_ANALYTICS_TOKEN env or config.json).
- [Video: Title] placeholders in a post become responsive YouTube iframes,
  mapped in document order to that post's `videos` front-matter list (list of
  {youtube_id, title}); a global videos.json still works as a fallback.

Add a new post: drop a new .md in content/posts/ and rebuild. No code edits.

Usage:
    python3 build.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import date
from pathlib import Path

import markdown  # from the local venv (see setup.sh)

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "content"
POSTS_DIR = CONTENT / "posts"
ASSETS_DIR = CONTENT / "assets"   # content/assets/<slug>/<image>
SITE = ROOT / "site"
CONFIG = ROOT / "config.json"
VIDEOS = ROOT / "videos.json"


def load_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.exists() else default


def render(tpl: str, **kw) -> str:
    """Token replace: substitutes [[key]] tokens. Leaves CSS braces untouched."""
    out = tpl
    for k, v in kw.items():
        out = out.replace(f"[[{k}]]", str(v))
    return out


# --- tiny front-matter parser (no external YAML dependency) ---------------
def parse_front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    meta: dict = {}
    current_list_key = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if line.startswith("  - ") and current_list_key:
            # inline "key: value" pairs on a list item, e.g. "- youtube_id: abc"
            item = {}
            for part in line.strip()[2:].split(","):
                if ":" in part:
                    k, v = part.split(":", 1)
                    item[k.strip()] = v.strip().strip('"').strip("'")
            meta[current_list_key].append(item if item else line.strip()[2:])
            continue
        if ":" in line and not line.startswith(" "):
            key, val = line.split(":", 1)
            key, val = key.strip(), val.strip()
            if val == "":
                meta[key] = []
                current_list_key = key
            else:
                meta[key] = val.strip('"').strip("'")
                current_list_key = None
    return meta, body


def video_iframe(youtube_id: str, title: str) -> str:
    if not youtube_id or youtube_id.startswith("REPLACE"):
        return (
            f'<div class="video-embed video-placeholder" role="note">'
            f"<strong>Video placeholder:</strong> {title}"
            f'<br><span class="muted">Add the YouTube ID to embed it.</span></div>'
        )
    return (
        f'<div class="video-embed"><iframe '
        f'src="https://www.youtube-nocookie.com/embed/{youtube_id}" title="{title}" '
        f'loading="lazy" frameborder="0" '
        f'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
        f"allowfullscreen></iframe></div>"
    )


def embed_videos(body: str, videos: list[dict]) -> str:
    it = iter(videos)

    def _sub(match: re.Match) -> str:
        title = match.group(1).strip()
        try:
            v = next(it)
        except StopIteration:
            v = {"youtube_id": "", "title": title}
        return video_iframe(v.get("youtube_id", ""), v.get("title", title))

    return re.sub(r"\[Video:\s*(.+?)\]", _sub, body)


def cf_beacon(token: str) -> str:
    if token:
        return (
            '<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
            f"data-cf-beacon='{{\"token\": \"{token}\"}}'></script>"
        )
    return "<!-- Cloudflare Web Analytics: set cf_analytics_token in config.json to enable -->"


def fmt_date(value: str) -> str:
    try:
        y, m, d = (int(x) for x in value.split("-"))
        return date(y, m, d).strftime("%b %-d, %Y")
    except Exception:
        return value


def copy_images(html: str, slug: str) -> str:
    """Copy each ./img.png the post references from content/assets/<slug>/ into
    site/<slug>/. Post pages live in site/<slug>/, so the ./ path stays correct
    and images are namespaced per post (no cross-post collisions)."""
    out_dir = SITE / slug
    for img in re.findall(r'src="\./([^"]+)"', html):
        src = ASSETS_DIR / slug / img
        if src.exists():
            (out_dir / img).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out_dir / img)
        else:
            print(f"  WARNING: {slug}: image not found: content/assets/{slug}/{img}")
    return html


def build_toc(html_body: str) -> str:
    """Build a nested Table of Contents from the post's <h2>/<h3> headings.
    Headings already carry `id` anchors from the markdown `toc` extension.
    Returns '' when there are fewer than two headings (a TOC would add noise)."""
    heads = re.findall(r'<h([23]) id="([^"]+)">(.*?)</h[23]>', html_body, re.DOTALL)
    if len(heads) < 2:
        return ""
    items = []
    for level, hid, text in heads:
        label = re.sub(r"<[^>]+>", "", text).strip()  # strip inline tags
        cls = "toc-h2" if level == "2" else "toc-h3"
        items.append(
            f'<li class="{cls}"><a href="#{hid}" data-toc="{hid}">{label}</a></li>'
        )
    return (
        '<nav class="toc" aria-label="Table of contents">'
        '<div class="toc-title">On this page</div>'
        "<ul>" + "".join(items) + "</ul></nav>"
    )


def wrap_figures(html: str) -> str:
    """Wrap a standalone image in a semantic <figure>, and if the image is
    immediately followed by a caption paragraph (authored in Markdown as an
    italic line starting with 'Caption:'), render that as a <figcaption>.

    Markdown produces:
        <p><img alt="..." src="..." /></p>
        <p><em>Caption: the text</em></p>
    An image with no following caption line becomes a plain <figure> (no
    <figcaption>), so alt text still carries the accessible description."""
    # image + caption in the SAME paragraph (image and caption on consecutive
    # Markdown lines with no blank line between -> one <p>)
    html = re.sub(
        r'<p>(<img\b[^>]*/?>)\s*<em>Caption:\s*(.*?)</em></p>',
        lambda m: f'<figure>{m.group(1)}<figcaption>{m.group(2).strip()}</figcaption></figure>',
        html,
        flags=re.DOTALL,
    )
    # image + caption in SEPARATE paragraphs (blank line between)
    html = re.sub(
        r'<p>(<img\b[^>]*/?>)</p>\s*<p><em>Caption:\s*(.*?)</em></p>',
        lambda m: f'<figure>{m.group(1)}<figcaption>{m.group(2).strip()}</figcaption></figure>',
        html,
        flags=re.DOTALL,
    )
    # remaining standalone images (no caption) -> bare <figure>
    html = re.sub(
        r'<p>(<img\b[^>]*/?>)</p>',
        lambda m: f'<figure>{m.group(1)}</figure>',
        html,
    )
    return html


def build() -> None:
    config = load_json(CONFIG, {})
    site_title = config.get("site_title", "Blog")
    site_tagline = config.get("site_tagline", "")
    token = os.environ.get("CF_ANALYTICS_TOKEN", config.get("cf_analytics_token", ""))
    global_videos = load_json(VIDEOS, {"videos": []}).get("videos", [])
    beacon = cf_beacon(token)

    SITE.mkdir(exist_ok=True)

    posts = []
    for md in sorted(POSTS_DIR.glob("*.md")):
        meta, body = parse_front_matter(md.read_text())
        slug = md.stem
        videos = meta.get("videos") or global_videos
        body = embed_videos(body, videos if isinstance(videos, list) else [])
        html_body = markdown.markdown(body, extensions=["extra", "sane_lists", "toc"])
        html_body = wrap_figures(html_body)
        posts.append(
            {
                "slug": slug,
                "title": meta.get("title", slug.replace("-", " ").title()),
                "date": meta.get("date", ""),
                "summary": meta.get("summary", ""),
                "cover": meta.get("cover", ""),
                "html_body": html_body,
            }
        )

    # newest first
    posts.sort(key=lambda p: p["date"], reverse=True)

    # --- per-post pages ---
    for p in posts:
        out_dir = SITE / p["slug"]
        out_dir.mkdir(exist_ok=True)
        page = render(
            POST_TEMPLATE,
            title=p["title"],
            site_title=site_title,
            date_display=fmt_date(p["date"]) if p["date"] else "",
            toc=build_toc(p["html_body"]),
            body=p["html_body"],
            cf_beacon=beacon,
        )
        page = copy_images(page, slug=p["slug"])
        (out_dir / "index.html").write_text(page)

    # --- home page ---
    cards = []
    for p in posts:
        cover_html = ""
        cover_src = ASSETS_DIR / p["slug"] / p["cover"] if p["cover"] else None
        if cover_src and cover_src.exists():
            dest = SITE / p["slug"] / p["cover"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cover_src, dest)
            cover_html = f'<div class="card-cover"><img src="./{p["slug"]}/{p["cover"]}" alt=""></div>'
        cards.append(
            render(
                CARD_TEMPLATE,
                slug=p["slug"],
                title=p["title"],
                date_display=fmt_date(p["date"]) if p["date"] else "",
                summary=p["summary"],
                cover_html=cover_html,
            )
        )
    home = render(
        HOME_TEMPLATE,
        site_title=site_title,
        site_tagline=site_tagline,
        cards="\n".join(cards),
        cf_beacon=beacon,
    )
    (SITE / "index.html").write_text(home)

    (SITE / ".nojekyll").write_text("")
    print(f"Built {len(posts)} post(s) + home page in {SITE}")
    for p in posts:
        print(f"  - /{p['slug']}/  {p['title']}")
    if not token:
        print("NOTE: Cloudflare Analytics token not set. Add it to config.json before deploy.")


# ---------------------------------------------------------------------------
BASE_CSS = """
  :root {
    --bg:#fff; --text:#242424; --muted:#6b6b6b; --link:#1a8917;
    --border:#e6e6e6; --code-bg:#f2f2f2; --panel:#fafafa; --maxw:680px;
    --serif:Charter,Georgia,Cambria,"Times New Roman",Times,serif;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; padding:0; }
  html { scroll-behavior:smooth; }
  body { background:var(--bg); color:var(--text); font-family:var(--serif);
         font-size:20px; line-height:1.58; -webkit-font-smoothing:antialiased;
         text-rendering:optimizeLegibility; }
  a { color:inherit; }
  .site-header { border-bottom:1px solid var(--border); }
  .site-header .inner { max-width:1100px; margin:0 auto; padding:22px 24px;
         display:flex; align-items:baseline; gap:14px; }
  .site-header .brand { font-family:var(--sans); font-weight:800; font-size:1.35rem;
         letter-spacing:-0.02em; color:#111; text-decoration:none; }
  .site-header .tagline { font-family:var(--sans); color:var(--muted); font-size:.95rem; }
  code { background:var(--code-bg); padding:.1em .4em; border-radius:4px; font-size:.82em;
         font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace; }
  .muted { color:var(--muted); font-family:var(--sans); }
  footer { color:var(--muted); font-size:.8rem; font-family:var(--sans); }
"""

HOME_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>[[site_title]]</title>
<style>""" + BASE_CSS + """
  .home { max-width:1100px; margin:0 auto; padding:44px 24px 90px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
           gap:28px; }
  .card { display:flex; flex-direction:column; border:1px solid var(--border);
           border-radius:10px; overflow:hidden; text-decoration:none; color:inherit;
           transition:box-shadow .15s ease, transform .15s ease; background:#fff; }
  .card:hover { box-shadow:0 6px 24px rgba(0,0,0,.08); transform:translateY(-2px); }
  .card-cover { aspect-ratio:16/9; background:var(--panel); overflow:hidden;
                 border-bottom:1px solid var(--border); }
  .card-cover img { width:100%; height:100%; object-fit:cover; display:block; }
  .card-body { padding:20px 22px 24px; display:flex; flex-direction:column; gap:8px; }
  .card-title { font-family:var(--sans); font-weight:700; font-size:1.25rem;
                 line-height:1.25; letter-spacing:-0.01em; color:#111; }
  .card-summary { color:#404040; font-size:1rem; line-height:1.5; }
  .card-date { font-family:var(--sans); color:var(--muted); font-size:.82rem;
                text-transform:uppercase; letter-spacing:.04em; }
</style>
[[cf_beacon]]
</head><body>
<header class="site-header"><div class="inner">
  <a class="brand" href="./">[[site_title]]</a>
  <span class="tagline">[[site_tagline]]</span>
</div></header>
<div class="home">
  <div class="grid">
[[cards]]
  </div>
</div>
<footer style="max-width:1100px;margin:0 auto;padding:0 24px 60px;border-top:1px solid var(--border);padding-top:28px;">
  Staging preview. Not an official Kiro publication.
</footer>
</body></html>
"""

CARD_TEMPLATE = """    <a class="card" href="./[[slug]]/">
      [[cover_html]]
      <div class="card-body">
        <span class="card-date">[[date_display]]</span>
        <span class="card-title">[[title]]</span>
        <span class="card-summary">[[summary]]</span>
      </div>
    </a>"""

POST_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>[[title]]</title>
<style>""" + BASE_CSS + """
  main { max-width:var(--maxw); margin:0 auto; padding:56px 24px 80px; }
  .post-date { font-family:var(--sans); color:var(--muted); font-size:.85rem;
                text-transform:uppercase; letter-spacing:.04em; margin-bottom:10px; }
  h1 { font-family:var(--sans); font-weight:700; font-size:2.4rem; line-height:1.18;
        letter-spacing:-0.022em; margin:0 0 .55em; color:#111; }
  h2 { font-family:var(--sans); font-weight:700; font-size:1.55rem; line-height:1.25;
        letter-spacing:-0.012em; margin:1.9em 0 .5em; color:#111; scroll-margin-top:24px; }
  h3 { font-family:var(--sans); font-weight:600; font-size:1.2rem; margin:1.5em 0 .4em; color:#111; scroll-margin-top:24px; }
  p { margin:0 0 1.2em; }
  main a { text-decoration:underline; text-decoration-color:#b9b9b9; text-underline-offset:2px; }
  main a:hover { text-decoration-color:var(--text); }
  strong { font-weight:700; color:#111; }
  ul,ol { padding-left:1.4em; margin:0 0 1.2em; }
  li { margin:.4em 0; }
  img { max-width:100%; height:auto; margin:2em 0 .6em; display:block; }
  figure { margin:2em 0; }
  figure img { margin:0 0 .5em; }
  figcaption { font-family:var(--sans); font-size:.82rem; line-height:1.4;
               color:var(--muted); text-align:center; }
  .video-embed { position:relative; padding-bottom:56.25%; height:0; margin:2em 0;
                  border-radius:6px; overflow:hidden; background:var(--panel);
                  border:1px solid var(--border); }
  .video-embed iframe { position:absolute; inset:0; width:100%; height:100%; border:0; }
  .video-placeholder { position:static; padding:22px; height:auto; font-family:var(--sans);
                        font-size:.95rem; color:var(--muted); }
  .video-placeholder strong { color:var(--text); }
  .back { font-family:var(--sans); font-size:.9rem; text-decoration:none;
           color:var(--muted); }
  .back:hover { color:var(--text); }

  /* Two-column layout: article centered, TOC fixed to the viewport so it
     stays in view for the whole scroll (sticky collapses in a short grid item). */
  .layout { max-width:680px; margin:0 auto; padding:56px 24px 80px; }
  .layout main { max-width:none; margin:0; padding:0; }
  .toc-desktop { position:fixed; top:96px; left:calc(50% + 380px); width:230px;
                 max-height:calc(100vh - 140px); overflow:auto; }
  .toc { font-family:var(--sans); font-size:.9rem;
         border-left:2px solid var(--border); padding-left:16px; }
  .toc-title { text-transform:uppercase; letter-spacing:.06em; font-size:.72rem;
               font-weight:700; color:var(--muted); margin-bottom:10px; }
  .toc ul { list-style:none; padding:0; margin:0; }
  .toc li { margin:.15em 0; }
  .toc-h3 { padding-left:14px; }
  .toc a { display:block; padding:4px 0; color:var(--muted); text-decoration:none;
           line-height:1.35; border-left:2px solid transparent; margin-left:-18px;
           padding-left:16px; }
  .toc a:hover { color:var(--text); }
  .toc a.active { color:var(--link); border-left-color:var(--link); font-weight:600; }
  /* Hide the fixed TOC when the viewport is too narrow to fit it beside the column */
  .toc-mobile { display:none; }
  @media (max-width:1180px) {
    .toc-desktop { display:none; }
    .toc-mobile { display:block; margin:0 0 2em; }
    .toc-mobile summary { font-family:var(--sans); font-weight:700; cursor:pointer;
                          font-size:.95rem; color:#111; padding:12px 0; }
    .toc-mobile .toc { position:static; border-left:none; padding-left:0; }
    .toc-mobile .toc-title { display:none; }
  }
</style>
[[cf_beacon]]
</head><body>
<header class="site-header"><div class="inner">
  <a class="brand" href="../">[[site_title]]</a>
</div></header>
<div class="layout">
<main>
  <a class="back" href="../">← All posts</a>
  <div class="post-date">[[date_display]]</div>
  <h1>[[title]]</h1>
  <details class="toc-mobile"><summary>On this page</summary>[[toc]]</details>
  [[body]]
</main>
<aside class="toc-desktop">[[toc]]</aside>
</div>
<footer style="max-width:1080px;margin:0 auto;padding:0 24px 60px;border-top:1px solid var(--border);padding-top:28px;">
  Staging preview. Not an official Kiro publication.
</footer>
<script>
(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll('.toc-desktop .toc a[data-toc]'));
  if (!links.length) return;
  var targets = links.map(function (a) {
    return { id: a.getAttribute('data-toc'),
             el: document.getElementById(a.getAttribute('data-toc')),
             link: a };
  }).filter(function (t) { return t.el; });
  var current = null;
  function setActive(id) {
    if (current === id) return;
    current = id;
    links.forEach(function (a) { a.classList.toggle('active', a.getAttribute('data-toc') === id); });
  }
  function onScroll() {
    // The reading line sits ~120px below the viewport top. Pick the last
    // heading whose top is above it; near the bottom, force the last one.
    var line = 120;
    var active = targets[0].id;
    for (var i = 0; i < targets.length; i++) {
      if (targets[i].el.getBoundingClientRect().top <= line) active = targets[i].id;
    }
    if ((window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 4)) {
      active = targets[targets.length - 1].id;  // reached the bottom
    }
    setActive(active);
  }
  var ticking = false;
  window.addEventListener('scroll', function () {
    if (!ticking) { window.requestAnimationFrame(function () { onScroll(); ticking = false; }); ticking = true; }
  }, { passive: true });
  onScroll();
})();
</script>
</body></html>
"""


if __name__ == "__main__":
    build()
