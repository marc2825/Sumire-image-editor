# FAQ

## The previous tabs opened at start

Sumīre starts with the same tabs and images as last time. If you close every tab before quitting, the next start shows the start page. Undo and redo history is not carried over.

## Does “Remove from list” delete the file?

No. It only removes the image from that tab's list. “File → Reload the list” (Ctrl+R) brings it back.

## I want to remove every edit

Use “Reset edits and mask” in the right panel. Ctrl+Z undoes it. Edits that were already in the image when you opened it cannot be removed.

## An image does not appear in the list

Check that no search or filter is active. The button to the right of the search box clears them.
The list shows only the images directly in the current folder. Images in folders inside it appear when you open that folder from the bar above the list.

## I want to change where images are saved

Use “Overwrite · auto-save ▾” at the top right. With overwriting off, originals are kept and images are saved to a separate folder.

## I overwrote an image by mistake

You can get it back before quitting the app.

- Ctrl+Z undoes the edits. With auto-save on, the image is saved again as it was. It is not the original file itself, though (JPEG is recompressed).
- To get the original file itself back, use “⋯ → Restore the original from before overwriting”. It works when “Keep the original temporarily before overwriting” is on (the default).

Neither works after quitting.

## Metadata is still there after saving

By default, metadata is kept when you save edits. To remove it, use “Remove metadata” above the image, or turn on “Remove metadata when saving”. Press “Metadata: yes” above the image to see what is left.

## I only want to remove metadata

Use “Remove metadata” above the image for the shown image, “Remove all metadata” above the list for every image in the tab, or right-click → “Remove metadata and save” for selected images. No tracing needed.

## I want smaller files or another format

Right-click → “Reduce file size” or “Convert format” (for the whole list, the list's “⋯”). Originals stay; new files go into a new folder.
The JPEG quality used for normal saves is under “Settings (gear) → Save” (1–100, default 95).

## HEIC images do not open

For licensing reasons, the component that opens HEIC is not bundled. Convert iPhone photos and the like to JPEG first.

## I want images back that “Remove duplicates” removed

Restore them from the Recycle Bin. Where there is no Recycle Bin (some network drives, for example), images are left where they are.

## Removed metadata cannot be restored

Only images whose metadata was kept for restoring can be restored. It cannot be restored if “Keep removed metadata for restoring” was off, or if the records were deleted. See [Metadata and restoring](METADATA.md).

## The eraser does not bring the image back

The eraser returns to the unedited image Sumīre remembers. After an image is overwritten and the app is closed, the unedited state no longer exists, so it cannot be brought back.
To be able to fix things later, save to a separate folder or save an edit project.

## Saving or renaming fails

Check for a file with the same name, characters that cannot be used, write permission, free space, and whether another app has the file open. Your edits stay even if it fails.

## “Open with Sumīre” is not in the right-click menu

Register it in “Settings (gear) → Windows”. On Windows 11 it is under “Show more options”. Register again after moving the exe.

## The image is not imported into NovelAI automatically

Sumīre prepares the image and opens the browser. Importing, choosing Image2Image and generating are done in the browser.

## I want to report a problem

“Settings (gear) → About → Details of the last error” copies the version and the error. Send it with the steps to reproduce to the contact listed where you got Sumīre. Do not attach private images or records.

[Getting started](USER_GUIDE.md) · [Features](FEATURES.md) · [Shortcuts](SHORTCUTS.md)
