# MadziHub brand

`source/` holds the master artwork (concept **A — Accounted Drop**) exactly as
delivered. Nothing in the app reads these files directly; the web assets in
`app/static/brand/` are generated from them:

```
pip install -r tools/brand/requirements.txt
python tools/brand/build_brand.py
```

The generator needs a Chromium binary for rasterising (set `CHROMIUM=` if it
is not auto-detected). Commit the regenerated `app/static/brand/*`.

| Asset | Used for |
|---|---|
| `favicon.svg` | Browser tab (Chrome, Edge, Firefox); turns its navy ink white under a dark browser theme |
| `favicon.ico`, `favicon-16/32/48.png` | Tab icon for Safari and legacy consumers, plus `/favicon.ico`; navy tile, legible on light and dark tab strips |
| `apple-touch-icon.png` | iOS home screen (180 px, full-bleed; iOS rounds the corners) |
| `icon-192/512.png`, `icon-maskable-512.png`, `site.webmanifest` | Android / desktop "Install app" |
| `madzihub-mark.svg` | Fallback organisation logo when a tenant has none (`/api/config/logo`) |
| `madzihub-wordmark-{light,dark}.svg` | Small placements, e.g. "Powered by" on the login screen |
| `madzihub-logo-{light,dark}.svg` | Full lockup with tagline, for large placements (splash, reports, docs) |
| `madzihub-icon.svg` | App icon, vector |

Light/dark in the page follows `data-theme="dark"` on `<html>`: elements with
`.brand-on-light` / `.brand-on-dark` swap automatically.

Lockup text is converted to outlines by the generator. The masters specify
DejaVu Sans, which Windows and macOS do not ship, and the substitute font would
push "Madzi" and "Hub" out of alignment.

Tenant logos (`tenants/<id>/logo.*`) are the utility's own brand and are
separate from the product brand.
