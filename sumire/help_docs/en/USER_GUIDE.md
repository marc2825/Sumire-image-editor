# Getting started

The basic flow is: open → trace to hide → save → next image.

## 1. Open

Use “Open folder” or “Open images” on the start page, or drag and drop. While working, open more from “File” at the top left (Alt+F). Next time, Sumīre starts where you left off: the same tabs and images.

- Opening a folder lists the images directly inside it. Folders inside it can be opened from the bar above the list (see [Moving between folders](#moving-between-folders)).
- Opening images lists only those images.
- While working, you can add what you open to the current tab or open it in a new tab.

## 2. Choose how to save

At the first start, choose “Overwrite the original” or “Save to a separate folder and keep the original”. You can change it any time with “Overwrite · auto-save ▾” at the top right. If you close the window without choosing, it is set to overwrite with auto-save. Sumīre asks before the first overwrite.

- Keep originals: turn off “Overwrite the original”.
- Be able to undo an overwrite: turn on “Keep the original temporarily before overwriting” (on by default). “⋯ → Restore the original from before overwriting” brings back the original from before the first overwrite in this session. **Kept originals are deleted when the app closes.**
- Save by hand: turn off “Auto-save” and save with Ctrl+S.
- Remove metadata on every save: turn on “Remove metadata when saving” (off by default, so metadata is kept).
- Be able to restore removed metadata: turn on “Keep removed metadata for restoring” (on by default).

If saving fails, your edits stay. Check the reason shown and save again.

## 3. Hide

Choose Mosaic, Blur or Fill in the right panel and trace over what you want to hide. Besides the brush, you can use a rectangle, ellipse, polygon or lasso.

- Undo: Ctrl+Z. Redo: Ctrl+Y.
- Eraser: returns traced areas to the original. Press it again (E) to go back to your tool.
- Compare: hold “Compare” below the image, or Tab, to see the original.
- Mask: tints the edited areas. The tint is not saved.
- Reset edits and mask: removes all edits and returns to the original, after asking. Ctrl+Z undoes it.

## 4. Next image

The ← → keys move between images. Images you did not edit are not saved just by moving on.
Enter saves the image, even if unedited, and moves to the next one.
With auto-save off, Sumīre asks whether to save when you move on.

## 5. Check and remove metadata

Press “Metadata: yes / none” above the image to see what it contains, by type (“[type] item: content”; anything that cannot be interpreted is shown as “Unknown”).

By default, metadata is kept when you save. To remove it:

- The shown image: “Remove metadata” above the image
- Every image in the tab: “Remove all metadata” above the list. Sumīre shows the number of images and the save method first.
- Selected images: right-click in the list → “Remove metadata and save”

To remove it on every save, turn on “Remove metadata when saving”. See also [Metadata and restoring](METADATA.md).

## 6. Sort

Label images with “Reject”, “Hold” and “Accept” at the bottom right (keys 1, 2, 3). Labels never delete images. Select several with Ctrl or Shift to label them together.

- Collect the accepted images: “Export accepted” above the list. It creates an “Accept” folder in the open folder and writes the images renumbered 00, 01…. The destination and numbering can be changed.
- Remove all labels: “Reset sorting” above the list.
- Undo the last organising step: the arrow above the list (Ctrl+Alt+Z). Undoes labels, order, names, notes and folder moves.
- Reorder: drag images in the list. The order can be changed with the button to the right of the search box.
- Rename: double-click the image name, or F2. Enter confirms, Esc cancels.
- Numbering: the list's “⋯ → Renumber in order”, or right-click. Numbers follow the list order, with one more digit than the largest number (00–02 for three images).
- Remove duplicates: the list's “⋯ → Remove duplicates”. Of identical images, all but the one you keep go to the Recycle Bin.
- Remove from the list: right-click → “Remove from list”. The file is not deleted; Ctrl+R brings it back.

## Moving between folders

In a tab that opened a folder, a folder bar appears above the list.

- Click a folder name to show its images. “.. (up one folder)” or the arrow on the left goes back. You cannot go above the folder the tab opened.
- The button on the right of the bar creates a new folder.
- Drag images onto a folder in the bar, or right-click → “Move to folder”. If an image with the same name exists, `_2` or similar is added; nothing is overwritten. Labels and notes move with the images.

## Tabs

Ctrl+T opens a new tab, Ctrl+W closes it, Ctrl+Tab / Ctrl+Shift+Tab switch. Closing every tab returns to the start page.
Double-click a tab to rename it. Leave the name empty to use the folder name again.

## Continue editing later

“File → Save edit project with the original” saves the original, the edited image and the mask together.
**It contains the unedited image, so do not share it with your finished images.** Edit history is not saved.

## Crop, rotate and colour

- Crop: “Crop” below the image. The frame starts around the whole image. Drag the corners or edges to adjust it, and drag inside to move it. You can also type numbers. “Set the output size” enlarges or reduces the result.
- Rotate and flip: the buttons in “More settings” in the right panel apply at once.
- Colour: “Adjust colours” in the same place. Change brightness, contrast, saturation, hue, exposure, temperature and gamma; “More adjustments” adds highlights, shadows, white / black level, RGB balance and sharpness. The window has its own Undo and Redo (Ctrl+Z / Ctrl+Y).

All of these can be undone. When overwriting, Sumīre asks before cropping.

## Save as, convert, reduce size, upscale

“⋯” to the right of the image name and the image's right-click menu hold the common actions.

- Overwrite: saves with the current save method (Ctrl+S). When saving to a separate folder, it says “Save”.
- Save as: saves a new file with the name and format you choose.
- Remove metadata and save: removes the metadata and saves with the current save method.
- View metadata: shows what the image contains, by type.
- Upscale: enlarges the shown image 1.5–4×. Hidden areas are never recovered.
- Restore the original from before overwriting: returns to the state before the first overwrite in this session.

Converting and reducing file size are in the right-click menu (for the whole list, the list's “⋯”). The originals stay; new files go into a new folder. Before writing, the size change is shown, for example “Original 3.2 MB → Compressed 740 KB (77% smaller)”.

With two or more images selected, the right-click menu offers “Compare side by side” (up to 6) and “Make a collage”. A collage can be a grid or a free layout; double-click an image to crop it in place.

## Copy and paste

Ctrl+C copies the result; Ctrl+V opens the clipboard image in a new tab. Neither includes metadata.
Pasted images are kept in `clipboard-images`, next to the settings, so their tabs can be restored. You can delete them after quitting the app.

## Hand images to NovelAI or other apps

Use “Share” to the right of the image name. Nothing handed over contains metadata.

- NovelAI i2i: copies the image and opens NovelAI in your browser. Paste or drag it in, then choose “Image2Image”.
- Copy image / Drag to share: hand the image to a social site or a chat app.

## Settings

The gear at the top right opens the settings. “Reset settings” at the bottom left returns every setting to its first state. JPEG quality is under “Save”, key assignments under “Shortcuts”, and the navigator, full screen (F11) and the display language under “Display and import”.

[Features](FEATURES.md) · [Shortcuts](SHORTCUTS.md) · [FAQ](FAQ.md)
