# Adjustments

All adjustments are banded LUT operations (premultiplication-aware) with
live, debounced previews from pristine copies — Cancel restores byte-exactly,
OK lands one undo step.

## The dialogs
- **Levels** (`Ctrl+L`): input black/white points + gamma, with **Auto**
  (0.1% luminance percentiles).
- **Curves** (`Ctrl+M`): monotone spline editor (Fritsch–Carlson) with master
  and per-channel curves.
- **Hue/Saturation** (`Ctrl+U`): hue rotation (−180..180), saturation and
  lightness (−100..100).
- **Point Color** (`Ctrl+Shift+U`): targeted hue-band HSL — click the
  thumbnail to sample the target color straight from the composite, then
  shift hue/saturation/lightness for just that band with a smooth cosine
  falloff. Near-grays are protected. **Uniformity** pulls in-band hues
  toward the centre (evens skin out); the **Skin Tones preset** loads the
  classic band (`hue=20`, `range=28`). CLI mirror: `--point-color`.
- **Color Balance** (`Ctrl+B`): shadows/midtones/highlights bands, each with
  cyan–red / magenta–green / yellow–blue axes.

## Scope: layer or whole image
Every dialog has **"Apply to all layers (full image)"** — live preview across
every visible layer, one undo macro for the whole image, exact cancel.

## The Adjust panel
Lightroom-style Basic sliders (exposure/contrast/highlights/shadows/whites/
blacks/temperature/tint/vibrance/saturation) applied as one LUT pass with
live preview. The **Apply to all layers (full image)** checkbox switches the
scope from the active layer to every visible layer — same toggle as the
adjustment dialogs; Apply is a single undo step either way. Headless, the
same pass is `photoslop-cli --adjust "exposure=1,contrast=10,..."`.

## Adjustment layers
For a non-destructive version of Levels, use Layer → New Adjustment Layer —
see [Layers](layers.md).

## Selections apply
With an active selection, destructive adjustments confine to it; feathered
selections blend at the edge (see [Selections](selections.md)).
