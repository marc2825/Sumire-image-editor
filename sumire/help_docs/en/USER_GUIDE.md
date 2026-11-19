# Getting started

The basic flow is: open → trace to hide → save → next image.

## 1. Open

Use “Open folder” or “Open images” on the start page, or drag and drop. While working, open more from “File” at the top left (Alt+F).

- Opening a folder lists the images directly inside it. Folders inside it can be opened from the bar above the list (see [Moving between folders](#moving-between-folders)).
- Opening images lists only those images.
- While working, you can add what you open to the current tab or open it in a new tab.

Next time, Sumīre starts where you left off: the same tabs and images.

## 2. Choose how to save

At the first start, choose “Overwrite the original” or “Save to a separate folder and keep the original”. If you close the window without choosing, images are saved to a separate folder.

Later, “Overwrite · auto-save ▾” at the top right changes these options:

- Overwrite the original: turn it off to keep originals and save to a separate folder.
- Keep the original temporarily before overwriting (on by default): “Restore original” above the image brings back the original from before the first overwrite. Kept originals are deleted when the app closes.
- Auto-save: turn it off to save by hand with Ctrl+S.
- Remove metadata when saving (off by default): turn it on to remove metadata on every save.
- Keep removed metadata for restoring (on by default): keeps removed metadata so it can be restored later.

If saving fails, your edits stay. Check the reason shown and save again.

## 3. Hide

Choose Mosaic, Blur or Fill in the right panel and trace over what you want to hide. Besides the brush, you can use a rectangle, ellipse, polygon or lasso.

- Ctrl+Z / Ctrl+Y: undo / redo
- Eraser (E): returns traced areas to the original. Press it again to go back to your tool.
- Compare: hold “Compare” below the image, or Tab, to see the original.
- Mask: tints the edited areas (the tint is not saved).
- Reset edits and mask: removes all edits. Ctrl+Z undoes it.

To add text, choose “Text” (T) and click the image. In the window that opens, choose the text, font, size, colour and bold, and see the result on the image. The point you click becomes the top left of the text.

The text gets a box: drag inside it to move, a corner to resize, the circle above to rotate; double-click to rewrite and press Delete to remove. Undo goes back one step each time.

## 4. Next image

- The ← → keys move between images. Images you did not edit are not saved just by moving on.
- Enter saves the image, even if unedited, and moves to the next one.
- With auto-save off, Sumīre asks whether to save before moving on.

## 5. Check and remove metadata

Press “Metadata: yes / none” above the image to see what it contains, by type.

By default, metadata is kept when you save. To remove it:

- The shown image: “Remove metadata” above the image
- Every image in the tab: “Remove all metadata” above the list (the number of images and the save method are shown first)
- Selected images: right-click in the list → “Remove metadata and save”
- Every save: turn on “Remove metadata when saving”

See also [Metadata and restoring](METADATA.md).

## 6. Sort

### Labels and tags

- Label images with “Accept”, “Hold” and “Reject” at the bottom right (keys 1, 2, 3). Alt+0 removes a label.
- With “Next after labelling” (on by default), labelling moves on to the next image.
- Select several with Ctrl or Shift to label them together.
- Right-click → “Tags…” adds free-form tags, separate from labels.
- Tags you use often can be added and removed with the buttons in “Custom tags” above the labels (open it from its heading; “Needs fixing” at first; keys 4–9 from the top). “Edit” adds, renames, deletes and reorders them.

Labels never delete images.

### Label folders

- Export by label (above the list): moves the images of the chosen labels into folders named after the labels, renumbered 00, 01…. With “Move the original files” off, the originals stay and the edited images are written without metadata.
- Sort automatically: turn on in right-click → “Label”, or Settings → Display and import → Sorting. Wherever Accept / Hold / Reject folders exist, a labelled image moves into its folder at once (hover over the option for the full rule).

### Organising the list

- Reset sorting (above the list): removes all labels.
- The arrow above the list (Ctrl+Alt+Z): undoes labels, tags, order, names, notes and moves.
- Reorder: drag images in the list. The order can be changed with the button to the right of the search box.
- Rename: double-click the image name, or F2 (Enter confirms, Esc cancels).
- Numbering: the list's “⋯ → Renumber in order”, or right-click. Numbers follow the list order: 00, 01….
- Remove duplicates: the list's “⋯ → Remove duplicates”. Keeps one of each identical image; the rest go to the Recycle Bin.
- Remove from list: right-click. The file is not deleted; Ctrl+R (or ⟳ in the folder row) brings it back.
- Delete images: right-click → “Delete images…”. The files go to the Recycle Bin (restore them from there).
- Find: type part of a file name, note or tag in the search box. Change the number in “4 / 111” above the image and press Enter to go to that image.

## Moving between folders

In a tab that opened a folder, a folder bar appears above the list.

- Click a folder name to go into it. “.. (up one folder)” or the arrow on the left goes back (you cannot go above the folder the tab opened).
- The button on the right of the bar creates a new folder.
- Drag images onto a folder in the bar, or right-click → “Move to folder”. If the name is taken, `_2` or similar is added; nothing is overwritten. Labels, notes and tags move too.

## Tabs

- Ctrl+T: new tab / Ctrl+W: close / Ctrl+Tab, Ctrl+Shift+Tab: switch
- Double-click a tab to rename it (empty uses the folder name).
- Closing every tab returns to the start page.

## Continue editing later

“File → Save edit project with the original” saves the original, the edited image and the mask together (edit history is not included).

It contains the unedited image, so do not share it with your finished images.

## Crop, rotate and colour

- Crop: “Crop” below the image. Drag the corners or edges to set the area and drag inside to move it. You can also type numbers, and “Set the output size” enlarges or reduces the result.
- Rotate and flip: the buttons in “More settings” in the right panel apply at once.
- Colour: “Adjust colours” in the same place. “More adjustments” adds highlights, shadows, white / black level, RGB balance and sharpness.

All of these can be undone. When overwriting, Sumīre asks before cropping.

## Save as, convert, reduce size, upscale

“⋯” to the right of the image name and the image's right-click menu hold the common actions.

- Overwrite (Ctrl+S): saves with the current save method (it says “Save” when saving to a separate folder).
- Save as: saves a new file with the name and format you choose.
- Remove metadata and save / View metadata
- More → Upscale: enlarges 1.5–4×. Hidden areas are never recovered.
- Restore the original from before overwriting: returns to the state before the first overwrite in this session.

Converting and reducing file size are in the right-click menu (for the whole list, the list's “⋯”).

- The originals stay; new files go into a new folder.
- Reducing size shows the result first, for example “Original 3.2 MB → Compressed 740 KB (77% smaller)”.
- With “Overwrite the originals” in Reduce file size, only images whose format stays the same are replaced (the originals are kept until the app closes).

With two or more images selected, the right-click menu offers “Compare side by side” (up to 6). “Make a collage” works from one image; arrange images in a grid or freely, and double-click one to crop it.

## Copy and paste

- Ctrl+C: copy the result (without metadata)
- Ctrl+V: open the clipboard image in a new tab
- With the list focused: Ctrl+X, Ctrl+C and Ctrl+V cut, copy and paste the image files themselves (works with Explorer too)

Pasted images are kept in `clipboard-images`, next to the settings (you can delete them after quitting).

## Hand images to NovelAI or other apps

Use “Share” to the right of the image name.

- Copy image / Drag to share: hand an image without metadata to a social site or a chat app.
- NovelAI i2i: copies the image and opens NovelAI in your browser. Paste or drag it in, then choose “Image2Image”.

Images for NovelAI carry no metadata by default either. With the generation info option on (Settings → NovelAI), it is attached when the original is a PNG.

## Settings

The gear at the top right opens the settings.

- JPEG quality: “Save”
- Key assignments: “Shortcuts”
- Navigator, full screen (F11), display language: “Display and import”

“Reset settings” at the bottom left returns every setting to its first state.

[Features](FEATURES.md) · [Shortcuts](SHORTCUTS.md) · [FAQ](FAQ.md)
