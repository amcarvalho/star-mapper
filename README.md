# Starmap Generator — README

Turn your Siril astrophotos into interactive webpages where hovering over
stars shows their names, object type, and links to Wikipedia and SIMBAD.
Generate an index page to browse all your projects in one place.

---

## Files

| File | Purpose |
|------|---------|
| `star_mapper.py` | Generates a starmap HTML from a plate-solved FITS file |
| `generate_index.py` | Scans your project folders and generates an index page |

---

## Requirements

Install once:
```
pip install astropy numpy Pillow tifffile requests
```

No other dependencies needed.

---

## Recommended Siril Workflow

The script requires a **plate-solved FITS file**. Here is the correct order
of operations in Siril to get one:

1. **Stack** your frames (Naztronomy script or manually)
2. **Process** your image: SPCC, background extraction, stretching, colour
   saturation, GraXpert denoising, etc.
3. **Crop** to your final composition
4. **Plate Solve** — in Siril, click the crosshair/astrometry icon in the
   toolbar, or go to the Image menu. Fill in:
   - Object name (e.g. `M101`)
   - Pixel size: `2.0 µm` (DWARF 3)
   - Focal length: `149.2 mm` (DWARF 3)
   - Click OK
5. **Save as FITS** (`File → Save`) — this embeds the WCS coordinates
6. **Save as TIFF** (optional) — your fully processed display image

> **Important:** Plate solve *after* cropping, not before. Cropping changes
> pixel coordinates, which would invalidate the WCS. Plate solving on the
> final cropped image gives exact results.

---

## Generating a Starmap

### FITS only (simplest)
```
python star_mapper.py my_image.fits
```
The image is read directly from the FITS file and auto-stretched.

### FITS + TIFF (best quality)
```
python star_mapper.py my_image.fits my_image.tif
```
Uses the FITS for coordinates and the TIFF for the display image — gives you
the fully processed, colour-corrected, denoised image in the webpage.

### FITS + PNG
```
python star_mapper.py my_image.fits my_image.png
```

Output is a single self-contained `my_image_starmap.html` — no server needed,
open in any browser.

---

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--mag-limit N` | `13.0` | Faintest V magnitude to include. Lower = fewer, brighter objects |
| `--title TEXT` | filename stem | Title shown in the webpage header |
| `--output FILE` | `<stem>_starmap.html` | Custom output HTML filename |

### Magnitude limit guide
- `--mag-limit 10` → only the brightest named stars and major objects
- `--mag-limit 13` → good balance (default)
- `--mag-limit 15` → many faint stars, can get crowded on wide fields

---

## What the Output HTML Contains

- Your astrophoto embedded as a JPEG (auto-resized to max 2048 px wide)
- **Coloured dot markers** on every identified object:
  - 🔵 Blue — Stars
  - 🟠 Orange — Galaxies
  - 🟢 Green — H II regions / Nebulae
  - 🔴 Red — Supernovae
  - 🟣 Purple — Clusters
- **Hover tooltip** showing name, object type, and two links:
  - → Wikipedia
  - → SIMBAD (guaranteed page for every catalogued object)
- **Filter chips** to show/hide objects by type
- **Show/hide markers** toggle button to compare the clean image
- **Legend** listing all objects with W (Wikipedia) and S (SIMBAD) buttons
- **Object count** that updates as you filter

---

## Workflow Internals

```
your_image.fits
    │
    ├─ WCS (plate-solve data) ──────────────────────────────────────┐
    │   CRPIX, CRVAL, PC matrix, SIP distortion coefficients        │
    │                                                                │
    └─ Image data (if no TIFF provided)                             │
                                                                     │
your_image.tif (optional, preferred for display)                    │
    │                                                                │
    ▼                                                                ▼
[1/4] Load WCS from FITS           [2/4] Load display image
    │                                                                │
    └────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
              [2/4] Query SIMBAD for named objects
                  (only M, NGC, IC, HD, TYC, SN names)
                                 │
                                 ▼
              [3/4] Project RA/Dec → pixel coords via WCS
                  (all_world2pix with SIP distortion)
                  (Y-axis flipped: Siril stores top-down)
                                 │
                                 ▼
              [4/4] Generate self-contained HTML
```

---

## DWARF 3 Notes

| Property | Value |
|----------|-------|
| Pixel size | 2.0 µm |
| Focal length | ~149.2 mm |
| Pixel scale | ~2.76 arcsec/px |
| Typical FOV (full frame) | ~132′ × 79′ |

The DWARF 3 exports 32-bit float TIFFs which standard PIL cannot open.
The script handles this automatically via `tifffile`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ERROR: FITS file has no plate-solve data` | Plate-solve in Siril first (see workflow above) |
| `WCS projection has 3 dimensions` | Fixed internally — script strips the colour axis before parsing WCS |
| SIMBAD query times out | Try `--mag-limit 11` to reduce result set |
| SIMBAD returns obscure catalog codes | Already filtered — only M, NGC, IC, HD, TYC, SN names are returned |
| Markers all in wrong positions | Check that FITS and TIFF are the same crop/size |
| Image appears upside down | Happens when loading from FITS directly; fixed with automatic vertical flip |
| Markers slightly off on H II regions / historical SNe | Expected — these are extended objects or faded transients with no visible point source |

---

## Generating the Index Page

Place `generate_index.py` in your root Astronomy folder (the parent of all
your project folders) and run:

```
cd C:\Users\alexa\Pictures\Astronomy
python generate_index.py --title "My Astrophotography"
```

This scans all subfolders for `*_starmap.html` files and generates
`index.html` with:
- A card grid with thumbnail, title, subtitle, object count and date
- A live search bar to filter by object name or constellation
- Same dark space aesthetic as the starmaps

### Expected folder structure
```
Astronomy\
  generate_index.py       ← index generator
  index.html              ← generated, open this in a browser
  M101\
    m101.fits
    m101.tif
    m101_starmap.html     ← generated by star_mapper.py
  Soul_Nebula\
    soul_nebula.fits
    soul_nebula.tif
    soul_nebula_starmap.html
  Andromeda\
    andromeda.fits
    andromeda_starmap.html
```

### To make regeneration easy, save this as `update_index.bat`:
```bat
@echo off
cd /d "%~dp0"
python generate_index.py --title "My Astrophotography"
pause
```
Double-click it after adding a new project.

---

## Full Example: M101 Pinwheel Galaxy

```
python star_mapper.py m101.fits m101.tif --title "M101 — Pinwheel Galaxy"
```

Output: `m101_starmap.html` — open in any browser, no server needed.

---

## Full Example: Soul Nebula (IC 1848)

```
python star_mapper.py soul_nebula.fits soul_nebula.tif --title "Soul Nebula — IC 1848"
```

Note: the Soul Nebula plate solve uses SIP distortion coefficients for
higher accuracy. The script handles this automatically.
