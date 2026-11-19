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
| Cut, copy and paste image files | Ctrl+X, Ctrl+C, Ctrl+V in the list, or right-click (works with Explorer too) |
| Search and sort | The search box (file names, notes and tags), the filter button (order, labels, tags, list / grid and thumbnail size), dragging in the list, typing a number into “4 / 111” above the image |
| Rename | Double-click the image name, or F2. For numbering, the list's “⋯ → Renumber in order” or right-click (zero-padded: 00, 01…) |
| Add a note | Right-click in the list → “Note” |
| Remove from the list | Right-click → “Remove from list” (the file is not deleted; Ctrl+R or ⟳ in the folder row brings it back) |
| Delete images | Right-click → “Delete images…” (after asking, moves them to the Recycle Bin) |
| Remove duplicates | The list's “⋯ → Remove duplicates”. All but the one you keep go to the Recycle Bin |
| Compare | Select 2–6 images, right-click → “Compare side by side” |

## Hide and adjust

| What you want | Where |
| --- | --- |
| Hide part of an image | Mosaic, Blur or Fill in the right panel. Areas: Brush, Rectangle, Ellipse, Polygon, Lasso |
| Add text | Choose “Text” (T) in the right panel and click the image. Font, size, colour and bold can be chosen. Afterwards, move, rotate and resize it with its box, and double-click to rewrite |
| Undo edits | Undo / Redo, the Eraser, “Reset edits and mask” |
| See what was edited | “Mask” below the image. It can also be saved as a black-and-white PNG (“⋯ → More”) |
| Compare with the original | Hold “Compare” below the image, or hold Tab |
| Pick a colour / draw a straight line | Alt+click for the eyedropper, Shift+click for a straight line |
| Crop or resize | “Crop” below the image. Drag the corners or edges to set the area |
| Rotate or flip | “More settings” in the right panel |
| Adjust colours | “Adjust colours” in “More settings” |
| Zoom | Type a number into the zoom box at the bottom right, “Fit”, “100%”, or Ctrl+wheel |
| Enlarge | “More → Upscale” in “⋯” or the image's right-click menu (1.5–4×) |
| Reuse settings | Edit presets in “More settings” |

## Sort

| What you want | Where |
| --- | --- |
| Label images | “Accept”, “Hold”, “Reject” at the bottom right, or the 1, 2, 3 keys. Applies to every selected image |
| Tag images | Right-click → “Tags…” (several images at once) |
| Tag with a button | “Custom tags” above the labels (open it from its heading; “Needs fixing” at first; keys 4–9). “Edit” adds, renames, deletes and reorders them |
| Sort into label folders | “Export by label” above the list (moves into a folder per label; can also copy, and renumber) |
| Sort as you label | Right-click → “Label → Sort into label folders automatically” (where Accept / Hold / Reject folders exist) |
| Gather label folders | The list's “⋯ → Gather the label folders…” |
| Remove all labels | “Reset sorting” above the list |
| Return the list to its first state | The list's “⋯ → Reset the whole list” (this session's overwrites, labels, notes, tags, order, filters) |
| Undo organising | The arrow above the list (Ctrl+Alt+Z). Undoes labels, tags, order, names, notes and moves |

## Save and export

| What you want | Where |
| --- | --- |
| Change how images are saved | “Overwrite · auto-save ▾” at the top right |
| See the metadata | “Metadata: yes / none” above the image |
| Remove metadata | “Remove metadata” above the image, or “Remove all metadata” above the list. It can also be removed on every save |
| Get removed metadata back | “⋯ → More → Save a copy with restored metadata” |
| Undo an overwrite | “Restore original” above the image, or “⋯ → Restore the original from before overwriting” (until the app closes) |
| Save under another name | “Save as” in “⋯” or the image's right-click menu |
| Change the format | Right-click → “Convert format” (for the whole list, the list's “⋯”) |
| Make files smaller | Right-click → “Reduce file size”. Shows how much smaller they get before writing. Images whose format stays the same can also overwrite the originals |
| Combine images | Select images, right-click → “Make a collage” (from one image). Grid or free layout; each image can be cropped |
| Copy the result or open a pasted image | Ctrl+C copies the result, Ctrl+V opens the clipboard image in a new tab |
| Continue editing later | “File → Save edit project with the original” |
| Hand images to NovelAI or other apps | “Share” to the right of the image name (NovelAI i2i, Copy image, Drag to share) |

## Settings

The gear at the top right opens the settings: Save, Records, Shortcuts, Display and import, NovelAI, Windows. JPEG quality (1–100, default 95), the display language and the Windows right-click entry are here too.

## Please note

- An overwritten original cannot be brought back after the app closes. To keep originals, save to a separate folder.
- By default, metadata is kept when saving. To remove it, use “Remove metadata”, or turn on “Remove metadata when saving”.
- Mosaic and blur cannot hide completely. For anything that must stay hidden, use fill at 100% opacity.
- Metadata kept for restoring is not encrypted. See [Metadata and restoring](METADATA.md).

## Supported images

- Opens still PNG, JPEG, WebP, AVIF, BMP, TIFF and GIF images. HEIC is not supported.
- Only PNG, JPEG and WebP can be overwritten. Save other formats to a separate folder.
- Animations, layers and keeping edit history after quitting are not supported.
- Text drawn into an image, or information embedded in unknown ways, cannot be removed.

[Getting started](USER_GUIDE.md) · [Shortcuts](SHORTCUTS.md) · [FAQ](FAQ.md)
