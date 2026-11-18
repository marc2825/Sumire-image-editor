# Usage guide

Every feature in detail. To get going quickly, read the in-app help (F1) or [Getting started](../../sumire/help_docs/en/USER_GUIDE.md). Keys are listed in [Shortcuts](../../sumire/help_docs/en/SHORTCUTS.md).

## The window

- Top: “Sumīre”, “File” and the tabs. On the right, the save method (“Overwrite · auto-save ▾”), help and the gear (settings)
- Left: list actions (export by label, bulk removal, reset sorting, undo organising, “⋯”), the folder bar, the search box and the images
- Centre: the image. Above it, undo / redo, the save state, whether there is metadata, “Remove metadata” and “Overwrite and next →”; below it, crop, compare and mask
- Right of the image name: “Share” (NovelAI i2i, Copy image, Drag to share) and “⋯” (overwrite, save as, metadata, upscale, restore the original from before overwriting and more)
- Right: editing tools, “More settings” (presets, area expansion, rotate, flip, colour), sorting
- Bottom: status messages, zoom (you can type a number), Fit, 100%

The save state is one of “Unedited”, “Unsaved”, “Saving…”, “Saved” or “Save failed”. Press “Metadata: yes / none” to see the metadata.

Each image in the list shows its edit and save state, label, tags and whether it has a note. With two or more images selected, an “N selected” bar appears above the list for acting on them together.

## Opening

- Folders: lists the images directly inside, in natural name order (1, 2, 10).
- Images: lists only the chosen images (other images in the same folder are not added).
- While working, you can add what you open to the current tab or open it in a new tab.
- The list's “⋯ → Pick up images added to the folder” (on by default): images newly placed in the open folder are added once they have been written completely.
- The ✕ next to a recent folder on the start page removes it from the list (the folder is not deleted).

### Moving around inside a folder

A tab that opened one folder shows a folder bar above the list.

- Click a folder name to go into it. “.. (up one folder)” or the arrow on the left goes back.
- The folder the tab opened is the starting point; you cannot go above it. Opening another folder from “File” makes it the new starting point.
- The current place is shown like “works / variants”. Order, filters and the shown image are remembered per folder, and restoring the tab returns to the folder you were in.
- The button on the right of the bar creates a new folder.

### Moving images to a folder

Drag images from the list onto a folder in the bar, or right-click → “Move to folder”.

- The image data is moved unchanged. If the name is taken, `_2` or similar is added; nothing is overwritten.
- To another drive, the file is copied and verified before the original is removed.
- Labels, notes, tags, edit masks and metadata backups move too. Save records of separate-folder saves do not, so moved images count as unsaved at the destination.
- If the shown image has unsaved edits, Sumīre asks whether to save. Images with unsaved edits other than the shown one are not moved.
- “Undo the last organising step” (Ctrl+Alt+Z) puts them back.

## Tabs

The list, edits and save method are separate for each tab.

- Ctrl+T: new tab / Ctrl+W: close / Ctrl+Tab, Ctrl+Shift+Tab: switch
- Rename a tab by double-clicking or right-clicking it (up to 60 characters; empty uses the folder name)
- Closing a tab with unsaved edits asks whether to save (if saving fails, the tab stays open).
- The tabs, order, filters and shown image at quit are restored at the next start. Only the shown tab loads its images. If images or folders are given at start, only those are opened.

## Saving

Choose the save method at the first start; change it later with “Overwrite · auto-save ▾” at the top right. If you close the first-start window without choosing, images are saved to a separate folder (installations from 0.4.0 or earlier stay on overwrite with auto-save).

### Where images are saved

- Overwrite the original: replaces PNG, JPEG and WebP files in the same place, with the same name and format. Other formats cannot be overwritten. The first overwrite after each start asks first.
- Save to a separate folder: saves into `Sumīre` inside the image's folder. The destination and format (PNG, JPEG, lossless WebP) can be changed.

### Save method options

- Keep the original temporarily before overwriting (on by default): keeps the original from before the first overwrite until the app closes. “⋯ → Restore the original from before overwriting” puts it back, metadata included.
- Remove metadata when saving (off by default): while off, the original's metadata is kept (except when saving in another format). “Remove metadata” and bulk removal always remove it.
- Auto-save: when on, every edit is saved. When off, Sumīre asks whether to save when you move to another image.

### When images are saved

- Images you did not edit are not saved just by moving on. Enter (save and next) saves them.
- If saving fails, your edits stay.
- If you keep editing while saving, the latest state is saved after the first save finishes.

How saving works and what is checked is described in [Saving and privacy](SAVING_AND_PRIVACY.md).

## Editing

### Tools

- Mosaic: the strength is the block size. `,` and `.` change it in 2 px steps.
- Blur: the strength is the blur radius.
- Fill: choose a colour and opacity (0–100%). At 100% the original pixels are replaced completely.
- Eraser: returns traced areas to the original. Press it again (E) to go back to your tool.
- Text: writes text into the image. Press it again (T) to go back to your tool (see “Text” below).

### Choosing the area

- Shapes: Brush, Rectangle, Ellipse, Polygon, Lasso. Hover over the list to see how each works.
- Polygon: click to add points; Enter or double-click finishes. Backspace removes the last point, Esc cancels.
- Lasso: drag around an area. The first closed region formed where the line crosses itself is edited (nothing happens if it never crosses).
- Apply outside: turn on “⋯ → More → Invert selection” to edit outside the next enclosed area (not for the brush).
- Area expansion: widens areas outwards by 0–3 px (default 1 px), so no thin unedited rim is left along the edge.
- Brush diameter, strength and area expansion can also be typed into the box to the right of their name.

### Other actions

- Alt+click: eyedropper / Shift+click: straight line from the last brush position
- Hold “Compare” or Tab: show the original
- “Mask” (M): tints the edited areas blue (the tint is not saved)
- “Reset edits and mask”: removes all edits. Ctrl+Z undoes it.
- Edit presets: save the tool, size, strength, colour, shape and area expansion under a name (in “More settings”).

### Text

Choose “Text” (T) and click the image to open the text window.

- Choose the text (line breaks allowed), font, size (pixels of the original image), colour and bold. While you type, the result is shown on the image.
- The point you click becomes the top left of the first line.
- “Add” writes it into the image. Like other edits, it can be undone, erased, shown in the mask and saved.
- The font, size, colour and bold you chose are used for the next text too.
- Text cannot be saved as an edit preset.

Edited areas (the mask) are kept in the records and come back when the image is opened again, unless another app changed the image. “⋯ → More → Save edit mask as PNG” exports it as a black-and-white PNG.

## Crop, rotate, colour and upscale

- Crop: “Crop” below the image. Drag the corners or edges to make the frame smaller and drag inside to move it. You can also type numbers, and “Set the output size” enlarges or reduces the result.
- Rotate and flip: the buttons in “More settings” apply at once.
- Colour: “Adjust colours” in “More settings”. Brightness, contrast, saturation, hue, exposure, temperature and gamma, plus highlights, shadows, white / black level, RGB balance and sharpness under “More adjustments”. Double-click a slider to reset it.
- Upscale: “⋯ → More → Upscale”. Enlarges 1.5–4× (up to 32,768 px per side and 24 million pixels). Hidden areas are never recovered.

All of these change the image and the mask together, and Undo reverts them. When overwriting, Sumīre asks before cropping or upscaling. After overwriting and quitting, cropped-off parts cannot be brought back.

## Sorting

### Labels

- Label images with “Accept”, “Hold” and “Reject” at the bottom right (1, 2, 3). Pressing again keeps the label; Alt+0 removes it.
- With several images selected, all are labelled (Ctrl+click adds or removes one, Shift+click selects a range).
- With “Next after labelling” (on by default), Sumīre moves to the next image after each label.
- The filter button shows images by label. “Reset sorting” removes every label in the tab.

Labels are saved at once and survive restarts, renaming and moving. They never change the image.

### Tags

- Right-click → “Tags…” adds or removes free-form tags (for several images at once).
- Tick to add, untick to remove; a half tick leaves them as they are.
- Tags show on the second line of the list. Find them with “Filter by tag” and the search.

### Custom tags

Tags you use often can be shown as buttons below the labels. The first one is “Needs fixing”.

- Pressing a button adds its tag to the shown (or selected) images; when they all have it, it is removed.
- The keys 4–9 do the same, from the top (change them in the shortcut settings).
- “Edit” adds, renames, deletes and reorders them (up to 9). Renaming also renames the same tag on the images in this tab (this can be turned off).
- Deleting only removes the button; tags already on images stay.
- “Undo the last organising step” undoes adding and removing. The buttons are the same in every tab.

### Label folders

- Sort automatically: turn on in right-click → “Label”, or Settings → Display and import → Sorting. Wherever Accept / Hold / Reject folders exist, a labelled image moves into its folder at once (Accept inside “Hold” moves it to the “Accept” beside it).
- Export by label: moves the images of the chosen labels into folders named after the labels, renumbered 00, 01…. With “Move the original files” off, the originals stay and the edited images are written without metadata. The destination, numbering and format can be changed.
- Gather the label folders: from the list's “⋯”. Collects the images of the Accept / Hold / Reject folders into one folder; emptied folders can be removed.

Labels, notes and tags move with the images, and “Undo the last organising step” moves them back. Save unsaved edits before moving originals.

### Resetting the whole list

The list's “⋯ → Reset the whole list” resets:

- images overwritten in this session whose originals were kept
- the shown image's edits and mask
- labels, notes, tags, order, filters and search

Edits saved before this session, and overwrites without a kept original, cannot be undone.

## Organising

- Search (Ctrl+F): part of a file name, note or tag.
- Order: by name or by modification time. Dragging images switches to a manual order; the list scrolls near its edges.
- Rename: double-click the image name, or F2. The extension does not change.
- Numbering: the list's “⋯ → Renumber in order” or right-click. Numbers start at 0 in list order, with one more digit than the largest number (00–02 for 3 images).
- Notes: right-click → “Note” (up to 4,000 characters). Hover over an image in the list to read it.
- Remove from list: right-click. The file is not deleted; Ctrl+R brings it back.
- Delete images: right-click → “Delete images…”. The files go to the Recycle Bin.
- Remove duplicates: the list's “⋯ → Remove duplicates”. Keeps one image of each identical group; the rest go to the Recycle Bin.
- Compare: select 2–6 images, right-click → “Compare side by side”. “Link zoom and position” keeps the views together.

The arrow above the list (“Undo the last organising step”, Ctrl+Alt+Z) undoes labels, tags, order, names, notes and moves, newest first.

Renaming never rewrites the image.

- If a file with the new name exists, renaming stops.
- The records (save records, labels, notes, tags, masks) are updated in the same step. If they cannot be updated, the whole rename is cancelled.
- If renaming is interrupted, the next time the folder is opened the old names are restored or the change is completed.

## Exporting

- Save as: “⋯” or right-click. Saves a new file with the name and format you choose.
- Convert format: right-click or the list's “⋯”. To PNG, JPEG, WebP, AVIF, BMP, TIFF or GIF.
- Reduce file size: right-click or the list's “⋯”. Makes files smaller.
- Make a collage: select images, right-click → “Make a collage”.

Converting and reducing size never change the originals; they write into a “Converted” or “Compressed” folder (the destination can be changed). Files with the same name are never overwritten.

### Reducing file size

- Keeps quality: PNG optimisation (images with 256 colours or fewer get a palette) and lossless WebP
- May lose quality: JPEG, WebP, AVIF and PNG colour reduction
- Choosing a method converts the first image to show the result, for example “Original 3.2 MB → Compressed 740 KB (77% smaller)”.
- Shrinking the long side is also available. Cancelling leaves nothing behind.
- “Overwrite the originals”: replaces only images whose format stays the same (the originals are kept until the app closes).

JPEG and BMP turn transparent areas white; GIF has up to 256 colours. HEIC is not supported.

Exported files are read back to check the format, size and the absence of metadata. With “Keep removed metadata for restoring” on, the original's metadata is kept, linked to the exported file.

### Collages

- Arrange 1–16 images in a grid (side by side, stacked, 2×2 and so on) or freely. “Add images…” and “Remove” change the number.
- Double-click an image to show a crop frame; click outside it to finish (the originals do not change).
- With “Free layout”, drag to move, drag a corner to resize, and set the canvas size.

## Copy and paste

- Ctrl+C: copy the result (without metadata)
- Ctrl+V (“File → Open the image on the clipboard”): open the clipboard image in a new tab
- With the list focused, Ctrl+X, Ctrl+C and Ctrl+V cut, copy and paste the image files (into the tab's folder; works with Explorer too).
- While you type text, text copy and paste take priority.

Pasted images start with manual saving, and the first save asks where to save. To restore the tab, they are kept in `clipboard-images` next to the settings (delete them after quitting if you like).

## Edit projects

“File → Save edit project with the original” bundles the original, the edited image and the mask into a `.sumire` file. Opening it again lets you undo edits with the eraser (edit history is not included).

It also contains what you hid, before editing, so share images made with a normal save instead.

## Sharing

“Share” to the right of the image name hands over the edited image (unsaved edits included).

- Copy image: paste it into a post or a chat.
- Drag to share: drag the image from the small window into a browser or a chat app.
- NovelAI i2i: see the steps below.

Copy and drag never include metadata.

### NovelAI i2i

1. Choose “Share → NovelAI i2i”. The image is copied to the clipboard and NovelAI opens in your browser.
2. Sign in to NovelAI and paste, or drag the image from Sumīre's window.
3. Choose “Image2Image”.

“Settings → NovelAI” offers cropping and shrinking before handing over.

With “Include the generation info (metadata) in images for NovelAI” (off by default) on, the generation info (PNG text and Stealth PNGInfo) is attached only when the original is a PNG. Whether NovelAI actually reads it in its window has not been checked yet.

The original file name is not handed over. The steps follow [NovelAI's documentation](https://docs.novelai.net/en/image/controltools).

## Settings

Open them with the gear at the top right.

- Save: auto-save, overwriting, metadata for restoring, format and destination for separate-folder saves, JPEG quality (1–100, default 95)
- Records: switching where the records are kept, and deleting them
- Shortcuts: changing keys
- Display and import: display language (from the next start), navigator, picking up added images, next after labelling, sorting into label folders automatically, confirmation when quitting, full screen
- NovelAI: cropping and shrinking before handing over; including the generation info
- Windows: adding and removing the right-click entry
- About: version, licences, details of the last error

“Reset settings” at the bottom left returns every setting (shortcuts and edit presets included) to its first state. Records, the right-click entry, recent folders and the display language stay.

### When quitting

- Closing the window asks whether to quit (turn this off with “Don't show this again”, or under “Display and import”).
- Unsaved edits are saved before quitting (tabs with auto-save off ask about each image).
- Quitting loses the undo / redo history and the originals kept before overwriting.

Settings are saved in `sumire-workspace.json` (the location can be set with the `SUMIRE_SETTINGS_FILE` environment variable). It contains folder paths but no images. Deleting it restores the defaults.

## Opening from the Windows right-click menu

“Settings → Windows → Add “Open with Sumīre” to the right-click menu” adds “Open with Sumīre” to the right-click menu of images (PNG, JPEG, WebP, BMP), folders and folder backgrounds. On Windows 11 it is under “Show more options”.

- It is registered only for the current Windows user and does not change default apps.
- Register again after moving the exe, and remove it with “Remove the right-click entry” before deleting the exe.
- If Sumīre is running, the image opens there.
