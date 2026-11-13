# Sumīre features

Sumīre hides parts of images, shows and removes metadata, and helps you sort and export images. All image processing happens on your PC.
If you are new, start with [Getting started](USER_GUIDE.md).

## Open and organise

| What you want | Where |
| --- | --- |
| Open images or folders | The buttons on the start page, “File” at the top left, or drag and drop |
| Work on several things at once | Tabs. They are restored at the next start. Double-click a tab to rename it |
| Open or create folders inside | The folder bar above the list |
| Move images to another folder | Drag them onto a folder in the bar, or right-click → “Move to folder” |
| Search and sort | The search box (file names and notes), the filter button (order, labels, list / grid and thumbnail size), dragging in the list, typing a number into “4 / 111” above the image |
| Rename | Double-click the image name, or F2. For numbering, the list's “⋯ → Renumber in order” or right-click (zero-padded: 00, 01…) |
| Add a note | Right-click in the list → “Note” |
| Remove from the list | Right-click → “Remove from list” (the file is not deleted; Ctrl+R or ⟳ in the folder row brings it back) |
| Remove duplicates | The list's “⋯ → Remove duplicates”. All but the one you keep go to the Recycle Bin |

## Hide and adjust

| What you want | Where |
| --- | --- |
| Hide part of an image | Mosaic, Blur or Fill in the right panel. Areas: Brush, Rectangle, Ellipse, Polygon, Lasso |
| Undo edits | Undo / Redo, the Eraser, “Reset edits and mask” |
| See what was edited | “Mask” below the image. It can also be saved as a black-and-white PNG (“⋯ → More”) |
| Compare with the original | Hold “Compare” below the image, or hold Tab |
| Pick a colour / draw a straight line | Alt+click for the eyedropper, Shift+click for a straight line |
| Crop or resize | “Crop” below the image. Drag the corners or edges to set the area |
| Rotate or flip | “More settings” in the right panel |
| Adjust colours | “Adjust colours” in “More settings”. Brightness, contrast, saturation, hue, exposure, temperature and gamma, plus More adjustments (highlights, shadows, white / black level, RGB, sharpness) |
| Zoom | Type a number into the zoom box at the bottom right, “Fit”, “100%”, or Ctrl+wheel |
| Enlarge | “More → Upscale” in “⋯” or the image's right-click menu (1.5–4×) |
| Reuse settings | Edit presets in “More settings” |

## Sort

| What you want | Where |
| --- | --- |
| Label images | “Accept”, “Hold”, “Reject” at the bottom right, or the 1, 2, 3 keys. Applies to every selected image |
| Sort into label folders | “Export by label” above the list (moves into a folder per label; can also copy, and renumber) |
| Remove all labels | “Reset sorting” above the list |
| Return the list to its first state | The list's “⋯ → Reset the whole list” (this session's overwrites, labels, notes, order, filters) |
| Undo organising | The arrow above the list (Ctrl+Alt+Z). Undoes labels, order, names, notes and moves |
| Compare | Select 2–6 images, right-click → “Compare side by side” |

## Save and export

| What you want | Where |
| --- | --- |
| Change how images are saved | “Overwrite · auto-save ▾” at the top right |
| See the metadata | Press “Metadata: yes / none” above the image (contents shown by type) |
| Remove metadata | “Remove metadata” above the image, or “Remove all metadata” above the list. It can also be removed on every save |
| Undo an overwrite | “Restore original” above the image, or “⋯ → Restore the original from before overwriting” (until the app closes) |
| Save under another name | “Save as” in “⋯” or the image's right-click menu |
| Change the format | Right-click → “Convert format” (for the whole list, the list's “⋯”) |
| Make files smaller | Right-click → “Reduce file size”. Shows how much smaller they get before writing. Can also overwrite the originals (same format only) |
| Combine images | Select 2 or more, right-click → “Make a collage”. Grid or free layout; each image can be cropped |
| Get removed metadata back | “⋯ → More → Save a copy with restored metadata” |
| Copy and paste | Ctrl+C copies the result, Ctrl+V opens the clipboard image in a new tab |
| Continue editing later | “File → Save edit project with the original” |
| Hand images to NovelAI or other apps | “Share” to the right of the image name (NovelAI i2i, Copy image, Drag to share) |

## Settings

The gear at the top right opens the settings: Save, Records, Shortcuts, Display and import, NovelAI, Windows. JPEG quality (1–100, default 95), the display language and the Windows right-click entry are here too.

## Please note

- **An overwritten original cannot be brought back after the app closes.** To keep originals, save to a separate folder.
- By default, metadata is kept when saving. To remove it, use “Remove metadata”, or turn on “Remove metadata when saving”.
- Mosaic and blur cannot hide completely. For anything that must stay hidden, use fill at 100% opacity.
- Metadata kept for restoring is not encrypted. See [Metadata and restoring](METADATA.md).

## Supported images

- Opens still PNG, JPEG, WebP, AVIF, BMP, TIFF and GIF images. HEIC is not supported.
- Only PNG, JPEG and WebP can be overwritten. Save other formats to a separate folder.
- Animations, layers and keeping edit history after quitting are not supported.
- Text drawn into an image, or information embedded in unknown ways, cannot be removed.

[Getting started](USER_GUIDE.md) · [Shortcuts](SHORTCUTS.md) · [FAQ](FAQ.md)
