#!/usr/bin/env python3
"""
Starmap Index Generator
=======================
Scans subfolders for *_starmap.html files and generates a beautiful
index.html in the current directory linking to each one.

Usage:
    cd C:\\Users\\alexa\\Pictures\\Astronomy
    python generate_index.py

    # Custom title:
    python generate_index.py --title "My Astrophotography"

    # Preview what it would find without writing:
    python generate_index.py --dry-run
"""

import argparse
import base64
import glob
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path


def find_starmaps(root: Path) -> list[dict]:
    """
    Walk immediate subdirectories looking for *_starmap.html files.
    Returns list of dicts with metadata extracted from each HTML.
    """
    entries = []

    for subdir in sorted(root.iterdir()):
        if not subdir.is_dir():
            continue

        # Find *_starmap.html in this folder (not recursive — one level only)
        htmls = sorted(subdir.glob("*_starmap.html"))
        if not htmls:
            continue

        # Use the first (or only) starmap found
        html_path = htmls[0]
        rel_path  = html_path.relative_to(root)

        # Extract metadata from the HTML
        meta = extract_metadata(html_path)
        meta["path"]    = str(rel_path).replace("\\", "/")  # forward slashes for web
        meta["folder"]  = subdir.name
        meta["html_name"] = html_path.name
        meta["mtime"]   = datetime.fromtimestamp(html_path.stat().st_mtime)

        # If multiple starmaps in folder, note them
        if len(htmls) > 1:
            meta["extras"] = [
                {"name": h.name,
                 "path": str(h.relative_to(root)).replace("\\", "/")}
                for h in htmls[1:]
            ]
        else:
            meta["extras"] = []

        entries.append(meta)

    return entries


def extract_metadata(html_path: Path) -> dict:
    """Parse a starmap HTML file to extract title, subtitle, object count, and thumbnail."""
    meta = {
        "title":    html_path.stem.replace("_starmap", "").replace("_", " ").replace("-", " "),
        "subtitle": "",
        "n_objects": 0,
        "thumbnail": None,
    }

    try:
        with open(html_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Title from <h1>
        m = re.search(r'<h1[^>]*>(.*?)</h1>', content, re.IGNORECASE)
        if m:
            meta["title"] = re.sub(r'&[a-z]+;', ' ', m.group(1)).strip()
            meta["title"] = re.sub(r'\s+', ' ', meta["title"])

        # Subtitle from <p> in title-block
        m = re.search(r'<p>(.*?)</p>', content, re.IGNORECASE)
        if m:
            sub = re.sub(r'&[a-z#0-9]+;', ' ', m.group(1)).strip()
            meta["subtitle"] = re.sub(r'\s+', ' ', sub)[:120]

        # Object count
        m = re.search(r'(\d+)\s+objects identified', content)
        if m:
            meta["n_objects"] = int(m.group(1))
        else:
            m = re.search(r'const ANN=(\[.*?\]);', content, re.DOTALL)
            if m:
                try:
                    meta["n_objects"] = len(json.loads(m.group(1)))
                except Exception:
                    pass

        # Thumbnail: grab first ~6KB of the base64 image and make a tiny preview
        m = re.search(r'src="data:image/jpeg;base64,([^"]{100,})"', content)
        if m:
            # Take just the first portion of the base64 to create a thumbnail reference
            # We store the full src but will use CSS to clip it
            meta["thumbnail"] = "data:image/jpeg;base64," + m.group(1)

    except Exception as e:
        print(f"    Warning: could not parse {html_path.name}: {e}")

    return meta


def build_html(entries: list[dict], title: str, root: Path) -> str:
    """Build the index HTML."""

    cards_html = ""
    for e in entries:
        thumb_style = ""
        if e["thumbnail"]:
            cards_html += f"""
    <a class="card" href="{e['path']}">
      <div class="card-thumb">
        <img src="{e['thumbnail']}" alt="{e['title']}" loading="lazy">
      </div>
      <div class="card-body">
        <div class="card-title">{e['title']}</div>
        <div class="card-sub">{e['subtitle']}</div>
        <div class="card-meta">
          <span class="pill">{e['n_objects']} objects</span>
          <span class="pill muted">{e['mtime'].strftime('%Y-%m-%d')}</span>
        </div>
      </div>
    </a>"""
        else:
            cards_html += f"""
    <a class="card no-thumb" href="{e['path']}">
      <div class="card-body">
        <div class="card-title">{e['title']}</div>
        <div class="card-sub">{e['subtitle']}</div>
        <div class="card-meta">
          <span class="pill">{e['n_objects']} objects</span>
          <span class="pill muted">{e['mtime'].strftime('%Y-%m-%d')}</span>
        </div>
      </div>
    </a>"""

    n = len(entries)
    now = datetime.now().strftime("%Y-%m-%d")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Lora:ital,wght@0,400;0,600;1,400&display=swap" rel="stylesheet">
<style>
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  :root{{
    --bg:#060a12;--surface:#0b1221;--border:#192848;
    --accent:#5bc4ff;--accent2:#ffb347;
    --text:#c5d8f0;--muted:#4a5a7a;
    --glow:0 0 18px 2px rgba(91,196,255,0.2);
    --card-w:320px;
  }}
  html{{scroll-behavior:smooth}}
  body{{
    background:var(--bg);
    background-image:
      radial-gradient(ellipse at 20% 20%, #0d1a35 0%, transparent 60%),
      radial-gradient(ellipse at 80% 80%, #0a1428 0%, transparent 60%);
    color:var(--text);font-family:'Lora',Georgia,serif;
    min-height:100vh;display:flex;flex-direction:column;align-items:center;
    padding:3rem 1.5rem 6rem;
  }}

  /* ── header ── */
  header{{
    width:100%;max-width:1200px;
    margin-bottom:3rem;
    text-align:center;
  }}
  header h1{{
    font-family:'Space Mono',monospace;
    font-size:clamp(1.2rem,4vw,2rem);
    color:var(--accent);
    letter-spacing:.15em;text-transform:uppercase;
    margin-bottom:.6rem;
  }}
  header p{{
    font-size:.85rem;color:var(--muted);font-style:italic;
  }}
  .header-rule{{
    width:60px;height:1px;
    background:linear-gradient(90deg,transparent,var(--accent),transparent);
    margin:.8rem auto 0;
  }}

  /* ── search ── */
  #search-wrap{{
    width:100%;max-width:500px;
    margin:0 auto 2.5rem;
    position:relative;
  }}
  #search{{
    width:100%;
    background:#0c1628;
    border:1px solid var(--border);
    border-radius:6px;
    color:var(--text);
    font-family:'Space Mono',monospace;
    font-size:.78rem;
    padding:.55rem 1rem .55rem 2.4rem;
    outline:none;
    transition:border-color .2s;
  }}
  #search:focus{{border-color:var(--accent)}}
  #search::placeholder{{color:var(--muted)}}
  .search-icon{{
    position:absolute;left:.8rem;top:50%;
    transform:translateY(-50%);
    color:var(--muted);font-size:.8rem;
    pointer-events:none;
  }}

  /* ── stats bar ── */
  .stats{{
    font-family:'Space Mono',monospace;font-size:.68rem;
    color:var(--muted);letter-spacing:.08em;
    margin-bottom:2rem;text-align:center;
  }}

  /* ── grid ── */
  #grid{{
    display:grid;
    grid-template-columns:repeat(auto-fill,minmax(var(--card-w),1fr));
    gap:1.5rem;
    width:100%;max-width:1200px;
  }}

  /* ── card ── */
  .card{{
    background:var(--surface);
    border:1px solid var(--border);
    border-radius:8px;
    overflow:hidden;
    text-decoration:none;
    color:inherit;
    display:flex;flex-direction:column;
    transition:border-color .2s,box-shadow .2s,transform .2s;
    position:relative;
  }}
  .card:hover{{
    border-color:var(--accent);
    box-shadow:var(--glow);
    transform:translateY(-3px);
  }}
  .card::after{{
    content:'→';
    position:absolute;bottom:.9rem;right:1rem;
    font-family:'Space Mono',monospace;
    font-size:.75rem;color:var(--accent);
    opacity:0;transition:opacity .2s;
  }}
  .card:hover::after{{opacity:1}}

  /* thumbnail */
  .card-thumb{{
    width:100%;height:180px;overflow:hidden;
    background:#060a12;
    position:relative;
  }}
  .card-thumb img{{
    width:100%;height:100%;
    object-fit:cover;
    object-position:center;
    transition:transform .4s;
    filter:brightness(.9);
  }}
  .card:hover .card-thumb img{{transform:scale(1.04);filter:brightness(1)}}

  /* body */
  .card-body{{padding:1rem 1.1rem 1rem}}
  .card.no-thumb .card-body{{padding:1.4rem 1.1rem}}

  .card-title{{
    font-family:'Space Mono',monospace;
    font-size:.85rem;
    color:var(--accent);
    letter-spacing:.06em;
    text-transform:uppercase;
    margin-bottom:.35rem;
  }}
  .card-sub{{
    font-size:.78rem;color:var(--muted);
    font-style:italic;
    line-height:1.5;
    margin-bottom:.7rem;
    min-height:2.4em;
    /* clamp to 2 lines */
    display:-webkit-box;
    -webkit-line-clamp:2;
    -webkit-box-orient:vertical;
    overflow:hidden;
  }}
  .card-meta{{display:flex;gap:.4rem;flex-wrap:wrap;align-items:center}}
  .pill{{
    font-family:'Space Mono',monospace;font-size:.62rem;
    border:1px solid var(--border);border-radius:20px;
    padding:.18rem .55rem;color:var(--text);
    background:#0c1628;
  }}
  .pill.muted{{color:var(--muted)}}

  /* hidden during search */
  .card.hidden{{display:none}}

  /* no results */
  #no-results{{
    display:none;
    font-family:'Space Mono',monospace;font-size:.8rem;
    color:var(--muted);text-align:center;
    padding:3rem 0;grid-column:1/-1;
  }}

  footer{{
    margin-top:4rem;font-size:.65rem;color:var(--muted);
    font-family:'Space Mono',monospace;
    text-align:center;letter-spacing:.06em;line-height:2;
  }}
</style>
</head>
<body>

<header>
  <h1>{title}</h1>
  <p>Interactive annotated astrophotography — hover over stars for names and links</p>
  <div class="header-rule"></div>
</header>

<div id="search-wrap">
  <span class="search-icon">&#9906;</span>
  <input id="search" type="text" placeholder="Search objects, constellations, NGC…" autocomplete="off">
</div>

<div class="stats" id="stats">{n} image{'' if n == 1 else 's'} &nbsp;&#183;&nbsp; generated {now}</div>

<div id="grid">
{cards_html}
  <div id="no-results">No matching images found</div>
</div>

<footer>
  Generated by starmap_generator.py &nbsp;&#183;&nbsp; Coordinates via Siril plate-solving<br>
  Objects from SIMBAD astronomical database
</footer>

<script>
const search = document.getElementById('search');
const cards  = document.querySelectorAll('.card');
const noRes  = document.getElementById('no-results');
const stats  = document.getElementById('stats');

search.addEventListener('input', () => {{
  const q = search.value.toLowerCase().trim();
  let shown = 0;
  cards.forEach(card => {{
    const text = card.textContent.toLowerCase();
    const match = !q || text.includes(q);
    card.classList.toggle('hidden', !match);
    if (match) shown++;
  }});
  noRes.style.display = shown === 0 ? 'block' : 'none';
  stats.textContent = shown + ' of {n} image{'' if n == 1 else 's'} shown';
}});

// Clear search on Escape
search.addEventListener('keydown', e => {{
  if (e.key === 'Escape') {{ search.value = ''; search.dispatchEvent(new Event('input')); }}
}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Generate an index page for all starmap HTMLs in subfolders.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--title",   default="My Astrophotography",
                        help="Title shown on the index page (default: 'My Astrophotography')")
    parser.add_argument("--output",  default="index.html",
                        help="Output filename (default: index.html)")
    parser.add_argument("--root",    default=".",
                        help="Root folder to scan (default: current directory)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be found without writing anything")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    print(f"Scanning {root} for *_starmap.html files...")

    entries = find_starmaps(root)

    if not entries:
        print("No *_starmap.html files found in any subfolders.")
        print("Make sure you run this from the parent folder containing your project folders.")
        sys.exit(0)

    print(f"Found {len(entries)} starmap(s):")
    for e in entries:
        extras = f" (+{len(e['extras'])} more)" if e["extras"] else ""
        print(f"  {e['folder']:30s} → {e['html_name']}  [{e['n_objects']} objects]{extras}")

    if args.dry_run:
        print("\n--dry-run: not writing index.html")
        return

    html = build_html(entries, args.title, root)
    out  = root / args.output
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(out) // 1024
    print(f"\nDone! → {out}  ({size_kb} KB)")
    print("Open index.html in any browser, or serve the folder with any web server.")


if __name__ == "__main__":
    main()
