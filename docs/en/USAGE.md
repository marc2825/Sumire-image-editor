# Usage guide

Every feature in detail. To get going quickly, read the in-app help (F1) or [Getting started](../../sumire/help_docs/en/USER_GUIDE.md). Keys are listed in [Shortcuts](../../sumire/help_docs/en/SHORTCUTS.md).

## The window

| Area | Contents |
| --- | --- |
| Top | On the left, “Sumīre” and “File”, then the tabs. On the right, the save method (“Overwrite · auto-save ▾”), help and the gear (settings) |
| Left | List actions (export by label, bulk removal, reset sorting, undo organising, “⋯”), the folder bar (up, reload ⟳, new folder), search (names and notes), the image list |
| Centre | The image. Above it: undo / redo, the save state, whether there is metadata, “Remove metadata”, “Overwrite and next →”. Below it: crop, compare, mask. To the right of the name: “Share” (NovelAI i2i, Copy image, Drag to share) and “⋯” (overwrite, save as, remove and view metadata, upscale, restore the original from before overwriting, more) |
| Right | Editing tools, “More settings” (presets, area expansion, rotate, flip, colour), sorting |
| Bottom | Status messages, zoom (you can type a number), Fit, 100% |

The save state above the image is one of “Unedited”, “Unsaved”, “Saving…”, “Saved” or “Save failed”. Press “Metadata: yes / none” next to it to see the metadata. Each image in the list shows its edit and save state, label, and whether it has a note.
With two or more images selected, a “N selected” bar appears above the list for acting on them together.

## Opening

- **Folders**: lists the images directly inside, in natural name order (1, 2, 10). Folders inside are opened from the bar above the list.
- **Images**: lists only the chosen images. Other images in the same folder are not added.
- While working, you can add what you open to the current tab or open it in a new tab. Adding keeps the shown image and its edits.
- With “Pick up images added to the folder” (the list's “⋯”, on by default), images newly placed in the open folder are added to the list once they have been written completely.
- The ✕ next to a recent folder on the start page removes it from the list (the folder and images are not deleted).

### Moving around inside a folder

A tab that opened one folder shows a folder bar above the list. The tab starts at the folder it opened; moving inside does not change the tab's name.

- Click a folder name to show its images. “.. (up one folder)” or the arrow on the left goes back. You cannot go above the starting folder.
- The current place is shown like “works / variants”. Order, filters and the shown image are remembered per folder, and restoring the tab returns to the folder you were in.
- Opening another folder from “File” makes it the new starting folder.
- The button on the right of the bar creates a new folder in the current one.

### Moving images to a folder

Drag images from the list onto a folder in the bar, or right-click → “Move to folder” and choose the destination. Several images can be moved at once.

- The image data is moved unchanged. If the destination has an image with the same name, `_2` or similar is added; nothing is overwritten. To another drive, the file is copied and verified before the original is removed.
- Labels, notes, edit masks and metadata backups move too. Save records of separate-folder saves do not move, so moved images count as unsaved at the destination.
- If the shown image has unsaved edits, Sumīre asks whether to save before moving. Images with unsaved edits other than the shown one are not moved.
- “Undo the last organising step” (Ctrl+Alt+Z) puts them back where they were, with their old names.

## Tabs

Images and folders open in tabs. The list, edits and save method are separate for each tab.

- Ctrl+T opens a new tab, Ctrl+W closes it, Ctrl+Tab / Ctrl+Shift+Tab switch.
- Rename a tab by double-clicking or right-clicking it (up to 60 characters; leave it empty to use the folder name). The name is used again when the same folder is opened.
- Closing a tab with unsaved edits asks whether to save. If saving fails, the tab stays open.
- The tabs, order, filters, shown image and settings at quit are remembered and restored at the next start. Only the shown tab loads its images. If images or folders are given at start, only those are opened.

## Saving

Choose the save method at the first start; change it later with “Overwrite · auto-save ▾” at the top right. If you used Sumīre before 0.4.0, it stays on overwrite with auto-save. If you closed the first-start window without choosing, originals stay unchanged and images are auto-saved to a separate folder.

- **Overwrite the original**: replaces PNG, JPEG and WebP files in the same place, with the same name and format. Other formats cannot be overwritten; save them to a separate folder. The first overwrite after each start asks first (“Don't show this again” stops it).
- **Save to a separate folder**: saves into `Sumīre` inside the image's folder and leaves the original unchanged. The destination and format (PNG, JPEG, lossless WebP) can be changed.
- **Keep the original temporarily before overwriting** (on by default): the original, as it was before the first overwrite after starting, is kept in the system's temporary folder. “⋯ → Restore the original from before overwriting” puts the original file back, metadata included. Kept originals are deleted when the app closes (any left by a crash are deleted at a later start after 7 days).
- **Remove metadata when saving** (off by default): when off, the original's metadata is kept (except when saving in another format). When on, it is removed and checked on every save. “Remove metadata” and bulk removal always remove it, whatever this setting.
- With auto-save on, every edit is saved. With it off, Sumīre asks whether to save when you move to another image.
- Images you did not edit are not saved just by moving on. Enter (save and next) saves even unedited images.
- If saving fails, your edits stay. If you keep editing while saving, the latest state is saved after the first save finishes.
- Undoing back to the original state also shows “Unedited” in the list again.

How saving works and what is checked is described in [Saving and privacy](SAVING_AND_PRIVACY.md).

## Editing

| Tool | Notes |
| --- | --- |
| Mosaic | The strength is the block size. `,` and `.` change it in 2 px steps |
| Blur | The strength is the blur radius |
| Fill | Choose a colour and opacity (0–100%). At 100% the original pixels are replaced completely |
| Eraser | Returns traced areas to the original. Press it again (E) to go back to your tool |

- **Area shapes**: Brush, Rectangle, Ellipse, Polygon, Lasso. Hover over the shape list to see how each works.
  - Polygon: click to add points; Enter or double-click finishes, Backspace removes the last point, Esc cancels.
  - Lasso: drag around an area. The ends are not joined: the first closed region formed where the line crosses itself is shown briefly and then edited. If the line never crosses itself, nothing happens.
- **Apply outside**: turn on “⋯ → More → Invert selection” to edit outside the next enclosed area (not for the brush).
- **Area expansion**: widens traced or enclosed areas outwards by 0–3 px (default 1 px; in “More settings”). It prevents a thin unedited rim along the edge.
- **Typing numbers**: brush diameter, strength (opacity) and area expansion can also be typed into the box to the right of their name (Enter applies).
- **Eyedropper and straight lines**: Alt+click picks a colour; Shift+click draws a straight line from the last brush position.
- **Compare and mask**: hold “Compare” below the image or Tab to see the original. “Mask” (M) tints the edited areas blue. The tint is not saved.
- **Reset edits and mask**: removes all edits and returns to the original, after asking. Ctrl+Z undoes it. Edits already in the image when it was opened cannot be removed.
- **Edit presets**: name and save the tool, brush size, strength, colour, shape and area expansion, and switch to them later (in “More settings”).

Edited areas (the mask) are kept in the records when saving and come back when the image is opened again, unless another app changed the image. The mask can also be exported as a black-and-white PNG (“⋯ → More → Save edit mask as PNG”).

## Crop, rotate, colour and upscale

- **Crop**: “Crop” below the image. The frame starts around the whole image; drag the corners or edges to make it smaller and drag inside to move it. You can also type the left, top, width and height. With “Set the output size (enlarge or reduce)” on, the cropped area is scaled to the width × height given; “Keep width and height in proportion” changes one when you change the other.
- **Rotate and flip**: the buttons in “More settings” apply at once.
- **Colour**: “Adjust colours” in “More settings”. Brightness, contrast, saturation, hue, exposure, temperature and gamma, plus highlights, shadows, white level, black level, RGB balance and sharpness under “More adjustments”. The window has its own Undo and Redo, and double-clicking a slider resets it. Transparency and edited areas are kept.
- **Upscale**: “More → Upscale” in “⋯” or the image's right-click menu. Enlarges the shown image 1.5–4×. Scales that would exceed 32,768 px per side or 24 million pixels cannot be chosen. **Hidden areas are never recovered.**

All of these change the image and the mask together, and Undo reverts them, size included. When overwriting, Sumīre asks before cropping or upscaling. After overwriting and quitting, cropped-off parts cannot be brought back.

## Sorting

Label images with “Accept”, “Hold” and “Reject” at the bottom right (1, 2, 3). Pressing again keeps the label (so you can keep going); to remove it, use “Remove label” (Alt+0). With several images selected, all of them are labelled (Ctrl+click adds or removes one image, Shift+click selects a range).

- **Tags**: right-click → “Tags…” adds or removes free-form tags, separate from labels (for several images at once). Tick to add, untick to remove; a half tick leaves them as they are. Find them with “Filter by tag” and the search (names, notes and tags). Tags show on the second line of the list and move with renames and moves.
- **Gather the label folders**: the list's “⋯ → Gather the label folders…” collects the images of the Accept / Hold / Reject folders in the tab's folder into that folder (or a new one), with their labels, notes and tags; emptied folders can be removed. “Undo the last organising step” brings them back.

- Labels are saved at once and survive restarts, saving, renaming and moving between folders. They never change the image.
- The filter button shows images by label. Counts appear below the list.
- With “Next after labelling” on, Sumīre moves to the next image after each label.
- With “Sort into label folders automatically” on (right-click → “Label”, or Settings → Display and import → Sorting), a labelled image moves into its label folder at once wherever Accept / Hold / Reject folders exist: into the one inside the image's folder, or, when the image is in a label folder, into the one beside it (Accept inside “Hold” moves it to “Accept”). A missing label folder is created; removing a label never moves the image. “Undo the last organising step” moves it back.
- “Reset sorting” removes every label in the tab.
- The list's “⋯ → Reset the whole list” restores the originals of images overwritten in this session (when they were kept), clears the shown image's edits and mask, and clears labels, notes, order, filters and search. Edits saved before this session, and overwrites without a kept original, cannot be undone.
- “Export by label” sorts the images of Accept, Hold, Reject or all labels into folders named after the labels. By default it creates those folders in the open folder, renames the images 00, 01… in list order and **moves the original files** there (labels and notes move with them; “Undo the last organising step” moves them back; save unsaved edits first).
- With “Move the original files” off, the originals stay and the edited images are written as new files: unsaved edits are included, metadata is not, and the format can be chosen.
- The destination and numbering can be changed.

## Organising

- **Search**: type part of a file name into the search box (Ctrl+F).
- **Order**: by name or by modification time (ascending or descending). Dragging images in the list switches to a manual order.
- **Rename**: double-click the image name, or F2. The extension does not change.
- **Numbering**: the list's “⋯ → Renumber in order” (all) or right-click (selected). Numbers start at 0 in list order, with one more digit than the largest number (00–02 for 3 images, 000–010 for 11). The old and new names are shown before renaming.
- **Notes**: right-click → “Note”. Up to 4,000 characters; hover over an image in the list to read it.
- **Remove from list**: right-click. The file is not deleted; Ctrl+R brings it back.
- **Delete images**: right-click → “Delete images…”. After asking, the files go to the Recycle Bin (never deleted outright).
- **Remove duplicates**: the list's “⋯ → Remove duplicates”. For each group of identical images, choose one to keep; the rest go to the Recycle Bin.
- **Compare**: select 2–6 images, right-click → “Compare side by side”. Zoom is per image; “Link zoom and position” keeps them together.
- **Undo the last organising step**: the arrow above the list (Ctrl+Alt+Z). Undoes labels, order, names, notes and folder moves, newest first. A rename is not undone if the image changed after it.

Renaming never rewrites the image. If a file with the new name exists, renaming stops. If renaming is interrupted, the next time the folder is opened the old names are restored or the change is completed.

## Exporting

| Action | Where | What it does |
| --- | --- | --- |
| Save as | “⋯”, right-click | Saves a new file with the name and format you choose |
| Convert format | Right-click, the list's “⋯” | Converts to PNG, JPEG, WebP, AVIF, BMP, TIFF or GIF |
| Reduce file size | Right-click, the list's “⋯” | Makes files smaller, either keeping quality or allowing quality loss |
| Make a collage | Select 1 or more, right-click | Arranges 1–16 images in a grid (side by side, stacked, 2×2 and so on) or freely, into one image; “Add images…” and “Remove” change the number |

- Originals are never changed. Converting and reducing size create a “Converted” or “Compressed” folder in the open folder (the destination can be changed). Files with the same name are never overwritten.
- When you choose a method, the first image is actually converted to show the result, for example “Original 3.2 MB → Compressed 740 KB (77% smaller)”. On export, every image is converted and the total is checked before anything is written; cancelling leaves nothing behind. Shrinking the long side is also available.
- Methods that keep quality: PNG optimisation (images with 256 colours or fewer get a palette without losing colours) and lossless WebP. Methods that may lose quality: JPEG, WebP, AVIF and PNG colour reduction.
- JPEG and BMP turn transparent areas white; GIF has up to 256 colours. HEIC is not supported.
- In a collage, double-click an image to show a crop frame in place. Cropped-off parts are shown faded; click outside the frame to finish. With “Free layout”, drag images to move them, drag a corner to resize, and set the canvas size. The clicked image comes to the front. Crops apply only to the collage; the originals do not change.
- Exported files are read back to check the format, size and the absence of metadata. For methods that keep quality, the pixels are checked too.
- With “Keep removed metadata for restoring” on, the original's metadata is kept, linked to the exported file.

## Copy and paste

Ctrl+C copies the result; Ctrl+V (or “File → Open the image on the clipboard”) opens the clipboard image in a new tab. Neither includes metadata. With the list focused, Ctrl+C and Ctrl+X copy or cut the image files, and Ctrl+V pastes image files from the clipboard into the tab's folder (moving them when cut; works with Explorer too). While you type text, text copy and paste take priority.
Pasted images start with manual saving, and the first save asks where to save. To restore the tab, pasted images are kept in `clipboard-images` next to the settings. You can delete them after quitting.

## Edit projects

“File → Save edit project with the original” bundles the original, the edited image and the mask into a `.sumire` file. Even without the original, you can open it again and undo edits with the eraser.
**It also contains what you hid, before editing.** Share images made with a normal save instead. Edit history is not included.

## Sharing (NovelAI and other apps)

Choose from “Share” to the right of the image name. Each hands over the edited image (unsaved edits included) without metadata.

- **Copy image**: paste it into a post or a chat.
- **Drag to share**: shows the image in a small window; drag it into a browser post field or a chat app.
- **NovelAI i2i**: as follows.

1. Choose “Share → NovelAI i2i”. The image is copied to the clipboard and NovelAI opens in your browser.
2. Sign in to NovelAI and paste, or drag the image from Sumīre's window.
3. Choose “Image2Image”.

The original file name and prompts are not handed over. Under “Settings → NovelAI” you can turn on cropping and shrinking before handing over, and “Include the generation info (metadata) in images for NovelAI”, which lets NovelAI read the original's prompt and settings (images handed to other apps never carry it). The steps follow [NovelAI's documentation](https://docs.novelai.net/en/image/controltools).

## Settings

Open them with the gear at the top right and choose a topic on the left. “Reset settings” at the bottom left returns every setting (shortcuts and edit presets included) to its first state. Records, the Windows right-click entry, recent folders and the display language stay.

| Topic | Contents |
| --- | --- |
| Save | Auto-save, overwriting, metadata for restoring, format and destination for separate-folder saves, JPEG quality (1–100, default 95) |
| Records | Switching where the records are kept, and deleting them |
| Shortcuts | Changing keys |
| Display and import | Display language, navigator, picking up images added to the folder, next after labelling, sorting into label folders automatically, confirmation when quitting, full screen |
| NovelAI | Cropping and shrinking before handing over; including the generation info for NovelAI |
| Windows | Adding and removing the right-click entry |
| About | Version, licences, details of the last error |

The display language takes effect at the next start.

When you close the window, Sumīre asks whether to quit. Quitting loses the undo / redo history and the originals kept before overwriting. Unsaved edits are saved before quitting (tabs with auto-save off ask about each image). Turn the question off with “Don't show this again”, or under “Display and import” in the settings.

Settings are saved in `sumire-workspace.json` (the location can also be set with the `SUMIRE_SETTINGS_FILE` environment variable). It contains folder paths for resuming, but no images. Deleting it restores the defaults.

## Opening from the Windows right-click menu

“Settings → Windows → Add “Open with Sumīre” to the right-click menu” adds “Open with Sumīre” to the right-click menu of images (PNG, JPEG, WebP, BMP), folders and folder backgrounds. On Windows 11 it is under “Show more options”.

- It is registered only for the current Windows user and does not change default apps. “Remove the right-click entry” removes it.
- Register again after moving the exe, and remove it before deleting the exe.
- If Sumīre is running, the image opens there. If it is busy, the image opens when it finishes.
