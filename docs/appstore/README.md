# App Store GA package (#257)

Everything App Store Connect asks for between TestFlight and **Submit for
Review**, ready to paste. The final Submit is the maintainer's to press.

## App information

| Field | Value |
|---|---|
| Name | Photoslop |
| Subtitle (30 chars max) | Layered raster image editor |
| Category | Graphics & Design |
| Price | **Free** |
| Bundle ID | `io.ronin48.photoslop.ipad` |
| Support URL | <https://github.com/CryptoJones/Photoslop/issues> |
| Marketing URL | <https://github.com/CryptoJones/Photoslop> |
| Copyright | © 2026 Aaron K. Clark |
| License note | The app is open source under Apache-2.0 |

## Promotional text (170 chars max)

> A layered raster image editor for iPad and iPhone. Apple Pencil, layers,
> selections, live effects and filters. Free, open source, and nothing ever
> leaves your device.

## Description

> Photoslop is a layered raster image editor built for iPad and iPhone.
>
> Draw with Apple Pencil — pressure-aware, with pen and pencil tools, brush
> width, colour and stroke opacity. Or turn on finger drawing and paint with a
> fingertip.
>
> Work in layers: add, duplicate, reorder, rename, hide, merge down, and blend
> them with per-layer opacity — plus fill opacity, which fades a layer's
> artwork while leaving its effects at full strength. Place text that stays
> editable. Import pictures from Photos or Files into their own layers,
> position them with a draggable placement box, and resize them after the fact.
>
> Select what you want to change: magic wand, rectangle and lasso, with
> feathering, and Cut, Copy, Paste and Delete one tap away while a selection
> is up. Brushes, the paint bucket and every filter stay inside it.
>
> Give any layer live effects that are never baked in: drop and inner shadow,
> outer and inner glow, outline, colour and gradient overlay, bevel and
> emboss, Gaussian blur and feather. They are re-drawn every time the layer
> changes, and stay editable for as long as the document lives.
>
> Reach for the tools you expect: pen, pencil, marker, eraser, paint bucket
> with adjustable tolerance, and an eyedropper that picks up whatever colour
> you can actually see rather than only the layer you happen to be on.
>
> Run any of eight filters — Sepia, Pixelate, Denoise, Retro Console, Pixel
> Sort, Datamosh, Film Negative, and Beam Dither, a one-bit renderer with
> error-diffusion and CRT beam modes.
>
> Shape the document: crop to a region you draw, pad or trim with Canvas
> Size, or resample the whole picture with Resize Document. Pan with two
> fingers, pinch to zoom.
>
> When it's done, export a flattened image to Photos or Files, or keep the
> layered .photoslop document — it's a plain, documented package format, and
> the same documents open in the free desktop edition.
>
> No account. No ads. No tracking — nothing ever leaves your device.
> Photoslop is free and open source (Apache-2.0):
> https://github.com/CryptoJones/Photoslop

## Keywords (100 chars max, comma-separated)

```
image editor,layers,drawing,apple pencil,paint,raster,photo editor,dither,art,sketch
```

## Age rating

Answer **None / No** to every content question (violence, mature themes,
gambling, contests, unrestricted web access, user-generated content…):
the app has no content of its own and no network features. Result: **4+**.

## Privacy label ("App Privacy" in App Store Connect)

**Data Not Collected.** The app makes no network requests, has no analytics,
no accounts, and no third-party SDKs. Photos access is add/select only and
images never leave the device. Answer "No, we do not collect data from this
app" and the label is done.

## Screenshots

Required sizes, both in `screenshots/`:

| File | Device | Pixels |
|---|---|---|
| `iphone-69-launch.png`, `iphone-69-editor.png` | iPhone 6.9" (16 Pro Max) | 1320×2868 |
| `ipad-13-launch.png`, `ipad-13-editor.png` | iPad 13" (Pro 13-inch M4) | 2064×2752 |

To retake them (e.g. with nicer artwork), stage a document on a booted
simulator and photograph it:

```sh
cd ipados
TEST_RUNNER_PHOTOSLOP_STAGE_SCREENSHOTS=1 xcodebuild \
  -project Photoslop-iPadOS.xcodeproj -scheme PhotoslopIPad \
  -configuration Debug -destination 'platform=iOS Simulator,id=<UDID>' \
  -only-testing:PhotoslopIPadUITests/StoreScreenshotStagingUITests \
  -resultBundlePath /tmp/stage.xcresult CODE_SIGNING_ALLOWED=NO test
xcrun xcresulttool export attachments --path /tmp/stage.xcresult --output-path /tmp/shots
```

The editor screenshot is the exported attachment; the launch scene is a plain
`xcrun simctl io <UDID> screenshot` after launching the app.

## What remains manual

1. **Clear any pending agreement** in App Store Connect under *Business*
   (the section formerly called "Agreements, Tax, and Banking"). A submission
   is refused while one is outstanding, and the banner names the one it wants.
   Correction to an earlier draft of this file: a free app with no in-app
   purchases is covered by the Apple Developer Program License Agreement and
   does **not** normally need the Paid Applications agreement. Accept whatever
   that page actually lists as pending rather than hunting for that one.
2. Create the App Store version from the current TestFlight build, paste the
   fields above, upload the screenshots.
3. Press **Submit for Review**.

---

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
