#!/usr/bin/env python3
"""
Starmap Generator v2
====================
Takes a plate-solved FITS file (for WCS coordinates) and a TIFF file
(your processed image for display) and generates a self-contained HTML
webpage with interactive star/object annotations and a show/hide toggle.

Workflow in Siril:
  1. Stack your frames (Naztronomy script)
  2. Process: SPCC, stretch, background extraction, colour, GraXpert, etc.
  3. Crop to your final composition
  4. Plate Solve  (Image menu -> Plate Solving)
  5. Save as FITS  -> this is your <fits_file>
  6. Save as TIFF  -> this is your <tiff_file>

Usage:
    python starmap_generator.py <fits_file> <tiff_file> [options]

Examples:
    python starmap_generator.py final_M101.fits final_M101.tiff
    python starmap_generator.py final_M101.fits final_M101.tiff --mag-limit 12
    python starmap_generator.py final_M101.fits final_M101.tiff --title "M101 Pinwheel Galaxy"

Requirements:
    pip install astropy numpy scipy Pillow tifffile requests
"""

import argparse, base64, csv, json, math, os, sys, warnings
from io import BytesIO
from pathlib import Path

MISSING = []
try:
    import numpy as np
except ImportError:
    MISSING.append("numpy")
try:
    from astropy.io import fits as astropy_fits
    from astropy.wcs import WCS
    from astropy.coordinates import SkyCoord
    import astropy.units as u
except ImportError:
    MISSING.append("astropy")
try:
    from PIL import Image
except ImportError:
    MISSING.append("Pillow")
try:
    import tifffile
except ImportError:
    MISSING.append("tifffile")
try:
    import requests
except ImportError:
    MISSING.append("requests")

if MISSING:
    print(f"Missing dependencies: {', '.join(MISSING)}")
    print(f"Install with:  pip install {' '.join(MISSING)}")
    sys.exit(1)

warnings.filterwarnings("ignore")


# ── 1. WCS FROM FITS ──────────────────────────────────────────────────────────

def load_wcs(fits_path):
    print(f"[1/4] Reading WCS from {fits_path} ...")
    with astropy_fits.open(fits_path) as hdul:
        header = None
        for hdu in hdul:
            if hdu.data is not None and hdu.data.ndim >= 2:
                header = hdu.header
                break
        if header is None:
            header = hdul[0].header
    try:
        # Strip 3rd axis from header copy so WCS+SIP loads cleanly
        hdr2 = header.copy()
        for key in ['NAXIS3', 'CTYPE3', 'CRVAL3', 'CRPIX3', 'CDELT3',
                    'CUNIT3', 'PC3_1', 'PC3_2', 'PC1_3', 'PC2_3', 'PC3_3']:
            if key in hdr2:
                del hdr2[key]
        hdr2['NAXIS'] = 2
        wcs = WCS(hdr2)
        # Debug: print what WCS sees
        naxis1 = int(header.get("NAXIS1", 0))
        naxis2 = int(header.get("NAXIS2", 0))
        crpix1 = header.get("CRPIX1", "?")
        crpix2 = header.get("CRPIX2", "?")
        has_sip = wcs.sip is not None
        print(f"    FITS dims: {naxis1} x {naxis2}")
        print(f"    CRPIX: ({crpix1}, {crpix2})")
        print(f"    SIP distortion: {has_sip}")
        # Sanity check: project CRVAL, should land on CRPIX
        crval1 = float(header.get("CRVAL1", 0))
        crval2 = float(header.get("CRVAL2", 0))
        test_px = wcs.all_world2pix([[crval1, crval2]], 0)
        expected_px = (float(crpix1) - 1, float(crpix2) - 1)
        print(f"    Sanity check: CRVAL -> pixel {test_px[0][0]:.1f},{test_px[0][1]:.1f}  (expected {expected_px[0]:.1f},{expected_px[1]:.1f})")
        if not wcs.has_celestial:
            print("ERROR: FITS file has no plate-solve data.")
            print("In Siril: Image menu -> Plate Solving, then File -> Save as FITS.")
            sys.exit(1)
        naxis1 = int(header.get("NAXIS1", 0))
        naxis2 = int(header.get("NAXIS2", 0))
        if naxis1 and naxis2:
            c = wcs.pixel_to_world(naxis1/2, naxis2/2)
            print(f"    WCS OK - centre RA={c.ra.deg:.4f} Dec={c.dec.deg:+.4f}  FITS size={naxis1}x{naxis2}")
        return wcs, header
    except Exception as e:
        print(f"ERROR parsing WCS: {e}")
        sys.exit(1)


# ── 2. LOAD TIFF ──────────────────────────────────────────────────────────────

def load_tiff(tiff_path):
    print(f"[2/4] Loading display image from {tiff_path} ...")
    ext = Path(tiff_path).suffix.lower()
    if ext in (".tif", ".tiff"):
        try:
            raw = tifffile.imread(tiff_path)
            if raw.dtype in (np.float32, np.float64):
                arr8 = (np.clip(raw, 0, 1) * 255).astype(np.uint8)
            elif raw.dtype == np.uint16:
                arr8 = (raw >> 8).astype(np.uint8)
            else:
                arr8 = raw.astype(np.uint8)
            img = Image.fromarray(arr8, mode="L" if arr8.ndim == 2 else "RGB").convert("RGB")
            print(f"    Loaded via tifffile: {img.size[0]}x{img.size[1]}")
            return img
        except Exception as e:
            print(f"    tifffile failed ({e}), trying PIL...")
    img = Image.open(tiff_path).convert("RGB")
    print(f"    Loaded via PIL: {img.size[0]}x{img.size[1]}")
    return img


def load_image_from_fits(fits_path):
    """Extract and stretch the image data from a FITS file as an 8-bit PIL image."""
    import numpy as np
    print(f"    Reading image array from {fits_path} ...")
    with astropy_fits.open(fits_path) as hdul:
        data = None
        for hdu in hdul:
            if hdu.data is not None and hdu.data.ndim >= 2:
                data = hdu.data.copy()
                break
        if data is None:
            raise ValueError("No image data found in FITS file.")

    # Handle (3, H, W) colour cube -> (H, W, 3)
    if data.ndim == 3:
        if data.shape[0] in (1, 3, 4):
            data = np.moveaxis(data, 0, -1)
        if data.shape[2] == 1:
            data = data[:, :, 0]

    def stretch(arr):
        arr = arr.astype(np.float32)
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return np.zeros_like(arr, dtype=np.uint8)
        # If already 0-1 (Siril float FITS), use directly
        if finite.max() <= 1.0 and finite.min() >= 0.0:
            return (np.clip(arr, 0, 1) * 255).astype(np.uint8)
        # Otherwise percentile stretch
        lo, hi = np.percentile(finite, [0.5, 99.5])
        if hi == lo:
            return np.zeros_like(arr, dtype=np.uint8)
        arr = np.clip(arr, lo, hi)
        arr = (arr - lo) / (hi - lo)
        # Mild asinh stretch for better star/nebula balance
        arr = np.arcsinh(arr * 5) / np.arcsinh(5)
        return (arr * 255).astype(np.uint8)

    if data.ndim == 2:
        arr8 = stretch(data)
        img = Image.fromarray(arr8, mode="L").convert("RGB")
    else:
        arr8 = np.stack([stretch(data[:, :, c]) for c in range(3)], axis=-1)
        img = Image.fromarray(arr8, mode="RGB")

    # FITS stores rows bottom-up; flip vertically so row 0 = top (matches browser + WCS Y-flip)
    img = img.transpose(Image.FLIP_TOP_BOTTOM)

    print(f"    Loaded from FITS: {img.size[0]}x{img.size[1]}")
    return img



# ── 4. SIMBAD QUERY ───────────────────────────────────────────────────────────

def query_simbad(ra_deg, dec_deg, radius_deg, mag_limit):
    radius = min(radius_deg, 0.65)
    print(f"[2/4] Querying SIMBAD (radius {radius:.2f} deg, mag <= {mag_limit}) ...")

    HOSTS = ["simbad.u-strasbg.fr", "simbad.cds.unistra.fr"]

    def tap_csv(adql):
        for host in HOSTS:
            try:
                r = requests.get(
                    f"https://{host}/simbad/sim-tap/sync",
                    params={"REQUEST": "doQuery", "LANG": "ADQL",
                            "FORMAT": "csv", "QUERY": adql},
                    timeout=40)
                if r.status_code == 200:
                    lines = r.text.strip().splitlines()
                    if len(lines) >= 2:
                        rows = list(csv.DictReader(lines))
                        print(f"    {len(rows)} rows from {host}")
                        return rows
                    print(f"    {host}: empty response")
                else:
                    snippet = r.text[r.text.find("ERROR"):r.text.find("ERROR")+100] if "ERROR" in r.text else r.text[:80]
                    print(f"    {host}: HTTP {r.status_code} - {snippet.strip()}")
            except requests.exceptions.Timeout:
                print(f"    {host}: timed out")
            except Exception as e:
                print(f"    {host}: {e}")
        return []

    # Only return objects with recognisable names:
    # Messier (M ), NGC, IC, HD, HIP, common names, supernovae.
    # This excludes obscure catalog codes like [VSH98] or CXO J...
    # We match on main_id prefix patterns using LIKE.
    adql = (
        f"SELECT TOP 500 main_id, ra, dec, otype_txt "
        f"FROM basic WHERE CONTAINS(POINT('ICRS',ra,dec),"
        f"CIRCLE('ICRS',{ra_deg},{dec_deg},{radius}))=1 "
        f"AND (main_id LIKE 'M %' "
        f"OR main_id LIKE 'NGC %' "
        f"OR main_id LIKE 'IC %' "
        f"OR main_id LIKE 'HD %' "
        f"OR main_id LIKE 'HIP %' "
        f"OR main_id LIKE 'TYC %' "
        f"OR main_id LIKE 'SN %' "
        f"OR main_id LIKE 'V* %' "
        f"OR main_id LIKE 'NAME %')"
    )

    rows = tap_csv(adql)
    if not rows:
        print("WARNING: SIMBAD returned no objects.")
        return []

    # Magnitude lookup
    mag_rows = tap_csv(
        f"SELECT b.main_id, f.V FROM basic AS b "
        f"JOIN allfluxes AS f ON f.oidref = b.oid "
        f"WHERE CONTAINS(POINT('ICRS',b.ra,b.dec),"
        f"CIRCLE('ICRS',{ra_deg},{dec_deg},{radius}))=1 AND f.V IS NOT NULL "
        f"AND (b.main_id LIKE 'M %' OR b.main_id LIKE 'NGC %' "
        f"OR b.main_id LIKE 'IC %' OR b.main_id LIKE 'HD %' "
        f"OR b.main_id LIKE 'HIP %' OR b.main_id LIKE 'TYC %' "
        f"OR b.main_id LIKE 'SN %' OR b.main_id LIKE 'NAME %')"
    )
    mag_map = {}
    for row in mag_rows:
        name = row.get("main_id", "").strip()
        try:
            mag_map[name] = float(row.get("V") or "")
        except (ValueError, TypeError):
            pass
    print(f"    Magnitude data for {len(mag_map)} objects.")

    results, seen = [], set()
    for row in rows:
        name = row.get("main_id", "").strip()
        if not name or name in seen:
            continue
        try:
            ra_o  = float(row.get("ra") or 0)
            dec_o = float(row.get("dec") or 0)
        except ValueError:
            continue
        mag = mag_map.get(name)
        if mag is not None and mag > mag_limit:
            continue
        seen.add(name)
        # Wikipedia URL — Messier objects use "Messier_101" style
        import re as _re
        m_match = _re.match(r'^M\s+(\d+)$', name.strip())
        if m_match:
            wiki_url = f"https://en.wikipedia.org/wiki/Messier_{m_match.group(1)}"
        else:
            wiki_url = "https://en.wikipedia.org/wiki/" + name.replace(" ", "_")
        # SIMBAD URL — guaranteed to have a page for every object
        simbad_url = "https://simbad.u-strasbg.fr/simbad/sim-id?Ident=" + name.replace(" ", "+")
        results.append({
            "ra": ra_o, "dec": dec_o, "name": name,
            "type": row.get("otype_txt") or "Star", "mag": mag,
            "wikipedia_url": wiki_url,
            "simbad_url": simbad_url,
        })

    print(f"    {len(results)} objects after magnitude filter.")
    return results


# ── 5. PROJECT CATALOG ONTO PIXELS ───────────────────────────────────────────

def project_catalog(catalog, wcs, img_w, img_h, fits_w, fits_h):
    scale_x = img_w / fits_w if fits_w else 1.0
    scale_y = img_h / fits_h if fits_h else 1.0
    annotations = []
    total = len(catalog)
    for obj in catalog:
        try:
            # all_world2pix handles SIP distortion correctly (world_to_pixel ignores it)
            result = wcs.all_world2pix([[obj["ra"], obj["dec"]]], 0)
            fits_px = float(result[0][0])
            # Siril stores images top-down but FITS/astropy convention is bottom-up.
            # Flip Y so pixel 0 = top of image (matches PIL/numpy and the display TIFF).
            fits_py = (fits_h - 1) - float(result[0][1])
        except Exception:
            continue



        px = fits_px * scale_x
        py = fits_py * scale_y
        if not (-30 <= px <= img_w + 30 and -30 <= py <= img_h + 30):
            continue
        px = max(3.0, min(img_w - 3.0, px))
        py = max(3.0, min(img_h - 3.0, py))

        ax, ay = px, py

        mag_str = f" · mag {obj['mag']:.1f}" if obj.get("mag") is not None else ""
        annotations.append({
            "x": round(ax, 1), "y": round(ay, 1),
            "name": obj["name"], "type": obj["type"],
            "label": f"{obj['name']}{mag_str}",
            "wikipedia_url": obj["wikipedia_url"],
            "simbad_url": obj.get("simbad_url", ""),
        })

    return annotations


# ── 6. HTML ───────────────────────────────────────────────────────────────────

def build_html(pil_image, annotations, title, subtitle):
    # Keep original dimensions for coordinate mapping
    ORIG_W, ORIG_H = pil_image.size
    # Resize for web if needed
    scale = min(1.0, 2048 / max(ORIG_W, ORIG_H))
    if scale < 1.0:
        display = pil_image.resize((int(ORIG_W*scale), int(ORIG_H*scale)), Image.LANCZOS)
    else:
        display = pil_image
    W, H = display.size
    buf = BytesIO()
    display.save(buf, format="JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    # Dot coordinates are in original FITS pixel space — tell JS to use original dims
    ann_json = json.dumps(annotations, ensure_ascii=False)
    n = len(annotations)

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
  --bg:#060a12;--border:#192848;
  --c-star:#5bc4ff;--c-galaxy:#ffb347;--c-hii:#7fff90;--c-sn:#ff5555;--c-cluster:#d4a0ff;--c-other:#c5d8f0;
  --accent:#5bc4ff;--accent2:#ffb347;--text:#c5d8f0;--muted:#4a5a7a;
  --glow:0 0 10px 3px rgba(91,196,255,0.35);
}}
body{{background:var(--bg);background-image:radial-gradient(ellipse at 50% 0%,#0d1a35 0%,var(--bg) 70%);color:var(--text);font-family:'Lora',Georgia,serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:2rem 1rem 5rem}}
header{{width:100%;max-width:1100px;margin-bottom:1.5rem;display:flex;align-items:flex-end;justify-content:space-between;border-bottom:1px solid var(--border);padding-bottom:1rem;gap:1rem;flex-wrap:wrap}}
.title-block h1{{font-family:'Space Mono',monospace;font-size:clamp(1rem,3vw,1.45rem);color:var(--accent);letter-spacing:.1em;text-transform:uppercase}}
.title-block p{{font-size:.8rem;color:var(--muted);font-style:italic;margin-top:.3rem}}
.controls{{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap}}
/* ── toggle markers button ── */
#toggle-btn{{font-family:'Space Mono',monospace;font-size:.7rem;background:#0c1628;border:1px solid var(--accent);color:var(--accent);border-radius:4px;padding:.38rem .85rem;cursor:pointer;transition:background .15s,color .15s,border-color .15s;letter-spacing:.05em;white-space:nowrap}}
#toggle-btn:hover{{background:var(--accent);color:#060a12}}
#toggle-btn.off{{border-color:var(--muted);color:var(--muted)}}
#toggle-btn.off:hover{{background:var(--muted);color:#060a12}}
/* ── image ── */
#wrap{{position:relative;display:inline-block;line-height:0;border:1px solid var(--border);box-shadow:0 0 80px rgba(5,15,40,.9);max-width:100%;cursor:crosshair}}
#astro-img{{display:block;max-width:100%;height:auto;width:{W}px;user-select:none}}
/* ── dots ── */
.dot{{position:absolute;width:22px;height:22px;transform:translate(-50%,-50%);cursor:pointer;border-radius:50%;border:1.5px solid rgba(91,196,255,.12);transition:border-color .15s,box-shadow .15s,transform .15s;z-index:10}}
.dot::after{{content:'';position:absolute;top:50%;left:50%;width:5px;height:5px;border-radius:50%;background:var(--c-star);opacity:.75;transform:translate(-50%,-50%);box-shadow:0 0 4px 1px rgba(91,196,255,.45);transition:opacity .15s}}
.dot.galaxy::after{{background:var(--c-galaxy);box-shadow:0 0 5px 2px rgba(255,179,71,.5);width:8px;height:8px}}
.dot.hii::after{{background:var(--c-hii);box-shadow:0 0 4px 1px rgba(127,255,144,.4);width:8px;height:8px;border-radius:2px}}
.dot.supernova::after{{background:var(--c-sn);box-shadow:0 0 7px 3px rgba(255,85,85,.65);width:10px;height:10px}}
.dot.cluster::after{{background:var(--c-cluster);box-shadow:0 0 5px 2px rgba(212,160,255,.45);width:8px;height:8px}}
.dot.other::after{{background:var(--c-other);opacity:.55}}
.dot:hover,.dot.active{{border-color:var(--accent);box-shadow:var(--glow);transform:translate(-50%,-50%) scale(1.65)}}
.dot:hover::after,.dot.active::after{{opacity:1}}
.dots-hidden .dot{{display:none!important}}
/* ── tooltip ── */
.tip{{position:absolute;background:rgba(5,10,22,.97);border:1px solid var(--accent);border-radius:5px;padding:.6rem .85rem;pointer-events:none;opacity:0;transition:opacity .18s;z-index:200;width:240px;box-shadow:0 4px 24px rgba(0,0,0,.8),var(--glow)}}
.tip.show{{opacity:1;pointer-events:auto}}
.tip .t-name{{font-family:'Space Mono',monospace;font-size:.74rem;color:var(--accent);letter-spacing:.06em;line-height:1.3}}
.tip .t-type{{font-size:.71rem;color:var(--muted);margin-top:3px;font-style:italic}}
.tip .t-links{{display:flex;gap:.6rem;margin-top:7px;flex-wrap:wrap}}
.tip a{{font-size:.68rem;font-family:'Space Mono',monospace;color:var(--accent2);text-decoration:underline;text-decoration-style:dotted;text-underline-offset:3px;pointer-events:auto}}
.tip a:hover{{color:#fff;border-color:#fff}}
/* ── legend section ── */
#legend-wrap{{width:100%;max-width:1100px;margin-top:2rem}}
/* ── type filter chips ── */
#type-filters{{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:1.1rem}}
.chip{{font-family:'Space Mono',monospace;font-size:.68rem;padding:.32rem .75rem;border-radius:20px;border:1.5px solid;cursor:pointer;transition:background .15s,color .15s,opacity .15s;display:flex;align-items:center;gap:.45rem;letter-spacing:.04em;user-select:none}}
.chip .chip-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
.chip.star  {{border-color:var(--c-star);   color:var(--c-star)}}
.chip.galaxy{{border-color:var(--c-galaxy); color:var(--c-galaxy)}}
.chip.hii   {{border-color:var(--c-hii);    color:var(--c-hii)}}
.chip.sn    {{border-color:var(--c-sn);      color:var(--c-sn)}}
.chip.cluster{{border-color:var(--c-cluster);color:var(--c-cluster)}}
.chip.other {{border-color:var(--c-other);  color:var(--c-other)}}
.chip.reset {{border-color:var(--muted);    color:var(--muted)}}
.chip.active{{color:#060a12!important}}
.chip.star.active  {{background:var(--c-star)}}
.chip.galaxy.active{{background:var(--c-galaxy)}}
.chip.hii.active   {{background:var(--c-hii)}}
.chip.sn.active    {{background:var(--c-sn)}}
.chip.cluster.active{{background:var(--c-cluster)}}
.chip.other.active {{background:var(--c-other)}}
.chip.reset.active {{background:var(--muted)}}
.chip:not(.active){{opacity:.55}}
.chip:hover{{opacity:1}}
/* ── object list ── */
#legend-count{{font-family:'Space Mono',monospace;font-size:.68rem;color:var(--muted);margin-bottom:.6rem}}
#legend{{display:grid;grid-template-columns:repeat(auto-fill,minmax(265px,1fr));gap:.3rem .8rem}}
.leg{{display:flex;align-items:center;gap:.55rem;padding:.3rem .4rem;border-radius:4px;cursor:pointer;font-size:.8rem;transition:background .12s}}
.leg:hover{{background:#0c1830}}
.leg-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.leg-dot.star{{background:var(--c-star)}}
.leg-dot.galaxy{{background:var(--c-galaxy)}}
.leg-dot.hii{{background:var(--c-hii);border-radius:1px}}
.leg-dot.supernova{{background:var(--c-sn)}}
.leg-dot.cluster{{background:var(--c-cluster)}}
.leg-dot.other{{background:var(--c-other)}}
.leg-name{{flex:1;color:var(--text)}}
.leg-type{{font-size:.67rem;color:var(--muted);font-style:italic;margin-right:.3rem}}
.leg a{{color:var(--accent2);font-size:.67rem;font-family:'Space Mono',monospace;text-decoration:none;opacity:.7;white-space:nowrap;border:1px solid currentColor;border-radius:3px;padding:0 .3rem;margin-left:.2rem}}
.leg a:hover{{opacity:1}}
.leg.hidden{{display:none}}
footer{{margin-top:3.5rem;font-size:.65rem;color:var(--muted);font-family:'Space Mono',monospace;text-align:center;letter-spacing:.05em;line-height:2}}
</style>
</head>
<body>
<header>
  <div class="title-block">
    <h1>{title}</h1>
    <p>{subtitle}</p>
  </div>
  <div class="controls">
    <button id="toggle-btn">&#11044; Hide markers</button>
  </div>
</header>
<div id="wrap">
  <img id="astro-img" src="data:image/jpeg;base64,{b64}" alt="{title}" draggable="false">
</div>
<div id="legend-wrap">
  <div id="type-filters"><!-- chips injected by JS --></div>
  <div id="legend-count"></div>
  <div id="legend"></div>
</div>
<footer>
  Coordinates via plate-solving (Siril) &nbsp;&#183;&nbsp; Objects from SIMBAD astronomical database<br>
  Hover a marker to see details &nbsp;&#183;&nbsp; Click &#8599; to open Wikipedia
</footer>
<script>
const NATIVE_W={ORIG_W},NATIVE_H={ORIG_H};
const ANN={ann_json};

const wrap    = document.getElementById('wrap');
const img     = document.getElementById('astro-img');
const legend  = document.getElementById('legend');
const filters = document.getElementById('type-filters');
const counter = document.getElementById('legend-count');
const btn     = document.getElementById('toggle-btn');

// ── tooltip ──────────────────────────────────────────────────────────────────
const tip = document.createElement('div');
tip.className = 'tip';
wrap.appendChild(tip);
let activeDot = null, markersOn = true;

// ── classify ─────────────────────────────────────────────────────────────────
function typeKey(t) {{
  if (!t) return 'other';
  const s = t.toLowerCase();
  const raw = t.trim();
  // SIMBAD short codes for galaxies: G, GiG, GiP, BiC, SyG, Sy1, Sy2, AGN, QSO, rG, EmG, LSB, IG, PaG, ClG
  const galaxyCodes = ['G','GiG','GiP','BiC','SyG','Sy1','Sy2','AGN','QSO','rG','EmG','LSB','IG','PaG','ClG','CGG','PoG'];
  if (galaxyCodes.includes(raw) || s.includes('galaxy') || s.includes('spiral') || s.includes('lenticular') || s.includes('seyfert')) return 'galaxy';
  // Nebulae and HII regions
  const nebCodes = ['HII','RNe','MoC','DNe','GNe','SNR','PN','SFR','HVC','Cld'];
  if (nebCodes.includes(raw) || s.includes('hii') || s.includes('h ii') || s.includes('region') || s.includes('nebul') || s.includes('remnant')) return 'hii';
  // Supernovae
  if (raw.startsWith('SN') || s.includes('supernova')) return 'sn';
  // Clusters
  const clCodes = ['OpC','GlC','Cl*','As*'];
  if (clCodes.includes(raw) || s.includes('cluster') || s.includes('association')) return 'cluster';
  // Stars (default for anything with * or star-related)
  if (s.includes('star') || raw.includes('*') || ['V*','RR*','Ce*','WR*','Be*','HB*','sg*','s*b','s*r','s*y','No*','LP*','Mi*','pA*','pe*','Ae*','RS*','bL*','SB*','El*','Ro*'].includes(raw)) return 'star';
  return 'other';
}}
const TYPE_LABEL = {{star:'Star', galaxy:'Galaxy', hii:'H\u202fII\u00a0/ Nebula', sn:'Supernova', cluster:'Cluster', other:'Other'}};
const TYPE_DOT_CLASS = {{star:'star', galaxy:'galaxy', hii:'hii', sn:'supernova', cluster:'cluster', other:'other'}};

// ── active filter state ───────────────────────────────────────────────────────
const activeFilters = new Set(['star','galaxy','hii','sn','cluster','other']);

// ── build type filter chips ───────────────────────────────────────────────────
const presentTypes = [...new Set(ANN.map(a => typeKey(a.type)))];
const CHIP_ORDER = ['star','galaxy','hii','sn','cluster','other'];

CHIP_ORDER.filter(k => presentTypes.includes(k)).forEach(key => {{
  const count = ANN.filter(a => typeKey(a.type) === key).length;
  const chip = document.createElement('div');
  chip.className = `chip ${{key}} active`;
  chip.dataset.key = key;
  chip.innerHTML = `<span class="chip-dot" style="background:var(--c-${{key === 'sn' ? 'sn' : key}})"></span>${{TYPE_LABEL[key]}} <span style="opacity:.6">(${{count}})</span>`;
  chip.addEventListener('click', () => toggleFilter(key));
  filters.appendChild(chip);
}});

// reset button
const resetBtn = document.createElement('div');
resetBtn.className = 'chip reset';
resetBtn.innerHTML = '&#8635; Show all';
resetBtn.addEventListener('click', resetFilters);
filters.appendChild(resetBtn);

function toggleFilter(key) {{
  if (activeFilters.has(key)) {{
    activeFilters.delete(key);
    filters.querySelector(`.chip.${{key}}`).classList.remove('active');
  }} else {{
    activeFilters.add(key);
    filters.querySelector(`.chip.${{key}}`).classList.add('active');
  }}
  applyFilter();
}}

function resetFilters() {{
  presentTypes.forEach(k => {{
    activeFilters.add(k);
    const c = filters.querySelector(`.chip.${{k}}`);
    if (c) c.classList.add('active');
  }});
  applyFilter();
}}

function applyFilter() {{
  let shown = 0;
  legend.querySelectorAll('.leg').forEach(item => {{
    const key = item.dataset.typekey;
    const visible = activeFilters.has(key);
    item.classList.toggle('hidden', !visible);
    if (visible) shown++;
  }});
  // show/hide dots on image too
  wrap.querySelectorAll('.dot').forEach(dot => {{
    const key = dot.dataset.typekey;
    dot.style.display = (markersOn && activeFilters.has(key)) ? '' : 'none';
  }});
  counter.textContent = shown + ' of {n} objects shown';
  hideTip();
}}

// ── dots ─────────────────────────────────────────────────────────────────────
function sc() {{ return img.offsetWidth / NATIVE_W; }}

function buildDots() {{
  wrap.querySelectorAll('.dot').forEach(d => d.remove());
  const s = sc();
  ANN.forEach((a, idx) => {{
    const key = typeKey(a.type);
    const dot = document.createElement('div');
    dot.className = 'dot ' + TYPE_DOT_CLASS[key];
    dot.style.left = (a.x * s) + 'px';
    dot.style.top  = (a.y * s) + 'px';
    dot.dataset.idx = idx;
    dot.dataset.typekey = key;
    if (!activeFilters.has(key)) dot.style.display = 'none';
    wrap.appendChild(dot);
    dot.addEventListener('mouseenter', () => showTip(dot, a));
    dot.addEventListener('mouseleave', e => {{ if (!tip.contains(e.relatedTarget)) hideTip(); }});
  }});
}}

function showTip(dot, a) {{
  if (activeDot && activeDot !== dot) activeDot.classList.remove('active');
  activeDot = dot; dot.classList.add('active');
  const col = `var(--c-${{typeKey(a.type) === 'sn' ? 'sn' : typeKey(a.type)}})`;
  const wikiLink = '<a href="'+a.wikipedia_url+'" target="_blank" rel="noopener">&#8594; Wikipedia</a>';
  const simbadLink = a.simbad_url
    ? '<a href="'+a.simbad_url+'" target="_blank" rel="noopener">&#8594; SIMBAD</a>'
    : '';
  tip.innerHTML = '<div class="t-name" style="color:'+col+'">'+a.name+'</div>'
    + '<div class="t-type">'+a.type+'</div>'
    + '<div class="t-links">'+wikiLink+simbadLink+'</div>';
  tip.classList.add('show');
  const s=sc(), wW=wrap.offsetWidth, wH=wrap.offsetHeight;
  let tx=a.x*s+14, ty=a.y*s-14;
  if (tx+244>wW) tx=a.x*s-244;
  if (ty<0)      ty=a.y*s+14;
  if (ty+110>wH) ty=wH-115;
  tip.style.left=tx+'px'; tip.style.top=ty+'px';
}}

function hideTip() {{
  tip.classList.remove('show');
  if (activeDot) {{ activeDot.classList.remove('active'); activeDot=null; }}
}}
tip.addEventListener('mouseleave', hideTip);
wrap.addEventListener('mouseleave', hideTip);

// ── show/hide toggle ──────────────────────────────────────────────────────────
btn.addEventListener('click', () => {{
  markersOn = !markersOn;
  if (markersOn) {{
    btn.innerHTML = '&#11044; Hide markers';
    btn.classList.remove('off');
    wrap.classList.remove('dots-hidden');
    applyFilter();
  }} else {{
    btn.innerHTML = '&#9711; Show markers';
    btn.classList.add('off');
    wrap.classList.add('dots-hidden');
    hideTip();
  }}
}});

// ── legend list ───────────────────────────────────────────────────────────────
ANN.forEach((a, idx) => {{
  const key = typeKey(a.type);
  const item = document.createElement('div');
  item.className = 'leg';
  item.dataset.typekey = key;
  const dc = TYPE_DOT_CLASS[key];
  const legSimbad = a.simbad_url
    ? '<a href="'+a.simbad_url+'" target="_blank" rel="noopener" title="SIMBAD database">S</a>'
    : '';
  item.innerHTML = '<div class="leg-dot '+dc+'"></div>'
    + '<span class="leg-name">'+a.name+'</span>'
    + '<span class="leg-type">'+a.type+'</span>'
    + legSimbad
    + '<a href="'+a.wikipedia_url+'" target="_blank" rel="noopener" title="Wikipedia">W</a>';
  item.addEventListener('click', e => {{
    if (e.target.tagName==='A') return;
    if (!markersOn) btn.click();
    wrap.scrollIntoView({{behavior:'smooth',block:'nearest'}});
    const dot = wrap.querySelector('.dot[data-idx="'+idx+'"]');
    if (dot) {{ showTip(dot,a); setTimeout(hideTip,3500); }}
  }});
  legend.appendChild(item);
}});

counter.textContent = '{n} of {n} objects shown';
buildDots();
window.addEventListener('resize', buildDots);
</script>
</body>
</html>"""



# ── 7. MAIN ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate an interactive star-map HTML from a plate-solved FITS + display TIFF.")
    parser.add_argument("fits",  help="Plate-solved FITS file (WCS coordinates + image data)")
    parser.add_argument("tiff",  nargs="?", default=None,
                        help="Optional TIFF/PNG display image. If omitted, image is read from the FITS file.")
    parser.add_argument("--mag-limit", type=float, default=13.0,
                        help="Faintest V magnitude to include (default: 13)")
    parser.add_argument("--title",  default=None, help="Title shown in the webpage")
    parser.add_argument("--output", default=None, help="Output HTML filename")
    args = parser.parse_args()

    for p in filter(None, (args.fits, args.tiff)):
        if not os.path.isfile(p):
            print(f"File not found: {p}")
            sys.exit(1)

    wcs, header = load_wcs(args.fits)
    fits_w = int(header.get("NAXIS1", 0))
    fits_h = int(header.get("NAXIS2", 0))

    if args.tiff:
        pil_image = load_tiff(args.tiff)
    else:
        print("[2/4] Reading image data from FITS file ...")
        pil_image = load_image_from_fits(args.fits)
    img_w, img_h = pil_image.size

    if fits_w and fits_h and (fits_w, fits_h) != (img_w, img_h):
        print(f"Note: FITS size ({fits_w}x{fits_h}) != TIFF size ({img_w}x{img_h}) - scaling pixel coords.")
    if not (fits_w and fits_h):
        fits_w, fits_h = img_w, img_h

    cx = fits_w / 2.0
    cy = fits_h / 2.0
    # Use all_world2pix inverse: all_pix2world handles SIP distortion correctly
    centre_radec = wcs.all_pix2world([[cx, cy]], 0)[0]
    ra_c  = float(centre_radec[0])
    dec_c = float(centre_radec[1])
    centre = SkyCoord(ra=ra_c * u.deg, dec=dec_c * u.deg)

    corner_radec = wcs.all_pix2world(
        [[0,0],[fits_w,0],[0,fits_h],[fits_w,fits_h]], 0)
    corners = SkyCoord(ra=[r[0] for r in corner_radec]*u.deg,
                       dec=[r[1] for r in corner_radec]*u.deg)
    radius_deg = float(centre.separation(corners).max().deg) * 1.05

    subtitle = (f"RA {ra_c:.3f}  Dec {dec_c:+.3f}  |  "
                f"FOV ~{radius_deg*120:.0f}' diagonal  |  mag <= {args.mag_limit}")

    catalog = query_simbad(ra_c, dec_c, radius_deg, args.mag_limit)

    annotations = []
    if catalog:
        annotations = project_catalog(
            catalog, wcs, img_w, img_h, fits_w, fits_h)
        print(f"{len(annotations)} objects projected onto image.")
    else:
        print("WARNING: No catalog data - HTML will have no markers.")

    stem  = Path(args.tiff).stem if args.tiff else Path(args.fits).stem
    title = args.title or stem.replace("_", " ").replace("-", " ")
    out   = args.output or (stem + "_starmap.html")

    print(f"[4/4] Generating HTML ...")
    html = build_html(pil_image, annotations, title, subtitle)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Done! -> {os.path.abspath(out)}  ({os.path.getsize(out)//1024} KB)")
    print("Open in any browser - no server needed.")


if __name__ == "__main__":
    main()
