# Tauri icon set

`tauri.conf.json` references `icons/icon.png`, `icons/icon.ico`, and
`icons/icon.icns`. We ship only `icon.svg` (the source-of-truth Klaravex
mark from `/brand/logos/`). The build scripts generate the raster
formats:

```sh
cd shared
cargo tauri icon icons/icon.svg
```

This produces:
- `icons/icon.png` (1024×1024 master + sizes used by Tauri)
- `icons/icon.ico` (Windows icon, multi-size)
- `icons/icon.icns` (macOS icon, multi-size)
- 32x32.png, 128x128.png, 128x128@2x.png (Linux/Tauri runtime)

The generated files MUST NOT be committed; they're regenerated at build
time. Source SVG IS committed so the brand mark is auditable.

If you replace `icon.svg`, you must also update:
- `brand/logos/klaravex-icon.svg` (master)
- the support.klaravex.com download page favicon
- the marketing site (`website/public/icon.svg`)

These four files MUST stay in lockstep — one of the trust signals the
helper relies on is brand consistency between the email link, the
download page, the installer, and the running app.
