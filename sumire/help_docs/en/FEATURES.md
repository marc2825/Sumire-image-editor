# Sumīre features

Sumīre hides parts of images, shows and removes metadata, and helps you sort and export images. All image processing happens on your PC.

If you are new, start with [Getting started](USER_GUIDE.md).

## Open and organise

| What you want | Where |
| --- | --- |
| Open images or folders | The buttons on the start page, “File” at the top left, or drag and drop |
| View the images in a ZIP | “File → Open ZIP…” or drag and drop (not extracted, read only; “Export from ZIP…” takes chosen images out) |
| Work on several things at once | Tabs. They are restored at the next start. Double-click a tab to rename it |
| Open or create folders inside | The folder bar above the list |
| Move images to another folder | Drag them onto a folder in the bar, or right-click → “Move to folder” |
| Cut, copy and paste image files | Ctrl+X, Ctrl+C, Ctrl+V in the list, or right-click (works with Explorer too) |
| Search and sort | The search box (file names, notes and tags), the filter button (order, labels, tags, list / grid and thumbnail size), dragging in the list, typing a number into “4 / 111” above the image |
| Rename | Double-click the image name, or F2. For numbering, “Export and batch → Renumber in order” below the list, or right-click (zero-padded: 00, 01…) |
| Add a note | Right-click in the list → “Note” |
| Remove from the list | Right-click → “Remove from list” (the file is not deleted; Ctrl+R or ⟳ in the folder row brings it back) |
| Delete images | Right-click → “Delete images…” (after asking, moves them to the Recycle Bin) |
| Remove duplicates | “Export and batch → Remove duplicates” below the list. All but the one you keep go to the Recycle Bin |
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
| Crop or resize | “Crop and resize…” in “Adjust the image” in the right panel. Drag the corners or edges to set the area |
| Rotate or flip | “Adjust the image” in the right panel |
| Adjust colours | “Adjust colours…” in “Adjust the image” |
| Zoom | Type a number into the zoom box below the image, the Fit to window button (F), “100%”, or Ctrl+wheel |
| Enlarge | “More → Upscale” in “⋯” or the image's right-click menu (1.5–4×) |
| Reuse settings | Edit presets in the right panel |

## Sort

| What you want | Where |
| --- | --- |
| Label images | “Accept”, “Hold”, “Reject” below the image, or the 1, 2, 3 keys. Applies to every selected image |
| Tag images | Right-click → “Tags…” (several images at once) |
| Tag with a button | The custom tag buttons to the right of the labels (“Needs fixing” at first; keys 4–9). The tag icon to their right adds, renames, deletes and reorders them |
| Sort into label folders | “Export and batch → Export by label…” below the list (moves into a folder per label; can also copy, and renumber) |
| Sort as you label | Right-click → “Label → Sort into label folders automatically” (where Accept / Hold / Reject folders exist) |
| Gather label folders | “Export and batch → Gather the label folders…” below the list |
| Remove all labels | “Export and batch → Reset all sorting…” below the list |
| Return the list to its first state | “Export and batch → Reset the whole list” below the list (this session's overwrites, labels, notes, tags, order, filters) |
| Undo organising | “Undo organising” above the list (Ctrl+Alt+Z). Undoes labels, tags, order, names, notes and moves |

## Save and export

| What you want | Where |
| --- | --- |
| Change how images are saved | “Overwrite · auto-save ▾” at the top right |
| See the metadata | “Metadata: yes / none” above the image |
| Remove metadata | “Remove metadata” above the image, or “Export and batch → Remove metadata from all images…” below the list. It can also be removed on every save |
| Get removed metadata back | “⋯ → More → Save a copy with restored metadata” |
| Undo an overwrite | “Restore original” at the foot of the right panel, or “⋯ → Restore the original from before overwriting” (until the app closes) |
| Save under another name | “Save as” in “⋯” or the image's right-click menu |
| Change the format | Right-click → “Convert format” (for the whole list, “Export and batch” below the list) |
| Make files smaller | Right-click → “Reduce file size”. Shows how much smaller they get before writing. Images whose format stays the same can also overwrite the originals |
| Combine images | Select images, right-click → “Make a collage” (from one image). Grid or free layout; each image can be cropped |
| Copy the result or open a pasted image | Ctrl+C copies the result, Ctrl+V opens the clipboard image in a new tab |
| Continue editing later | “File → Save edit project with the original” |
| Hand images to NovelAI or other apps | The Share button above the image (NovelAI i2i, Copy image, Drag to share) |

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
