# Removing, backing up and restoring metadata

## Check

Press “Metadata: yes / none” above the image (or “⋯ → View metadata”) to list what the image contains, by type.

- EXIF, GPS (location), generation info (prompts and settings), XMP, ICC profiles, Stealth PNGInfo and more are shown as “item: content”.
- Information that cannot be interpreted is listed as “Unknown”, with its size.
- “Copy text” copies everything shown.

## Remove

**By default, metadata is kept when you save edits.** To remove it, use one of these:

| For | Use |
| --- | --- |
| The shown image | “Remove metadata” above the image |
| Selected images | Right-click in the list → “Remove metadata and save” |
| Every image in the tab | “Remove all metadata” above the list |
| Every save | Turn on “Remove metadata when saving” in the save method |

Removing takes out EXIF, XMP, PNG text, ICC profiles and other extra information, as well as NovelAI's Stealth PNGInfo, and checks that none of it is left in the saved image. Files made with Save as, Convert format, Reduce file size or Make a collage never contain metadata, whatever the settings.

Even with metadata kept, it is not kept when saving in another format (for example a PNG saved as JPEG). Anything that would be a copy of the unedited image, such as EXIF thumbnails or images embedded in XMP, is never kept, so a mosaicked area cannot survive as a thumbnail. Dates, camera, location, prompts and the like are kept, so press “Metadata: yes” to check before sharing.

“Metadata: none” is the result of checking the supported kinds. Information embedded in unknown ways, or text drawn into the image, cannot be checked.
JPEG is recompressed on every save, so pixels may change slightly.

## Keep for restoring

When “Keep removed metadata for restoring” in the save method is on (the default), the metadata is saved in the records before the image is rewritten. If it cannot be saved, the image is not rewritten.

**Compression is not encryption. The records keep prompts, location data, embedded thumbnails and so on as they were.**
The records are kept in the app's own storage, not in the image folder. If you have used Sumīre since 0.4.0 or earlier, they are in `.sumire-index.sqlite3` (`.sumi-index.sqlite3` in older versions) inside the image folder. Windows shows files starting with “.”, so take care when sharing whole folders.

This is not a backup of the images. The original from before overwriting is kept until the app closes (“⋯ → Restore the original from before overwriting”). To keep unedited images after that, save to a separate folder or save an edit project.

## Restore

1. Show the image.
2. Choose “⋯ → More → Save a copy with restored metadata” to the right of the image name.
3. Enter a new file name. You get a copy of the current result with the removed metadata attached.

Originals and existing files are never overwritten. The copy contains the removed information again, so check it before sharing (anything that would be a copy of the unedited image, such as thumbnails, is not restored).
Files made with Convert format, Reduce file size or Save as can be restored too. The copy uses the original's format for PNG, JPEG and WebP, and PNG otherwise.
**Information that was not kept for restoring cannot be brought back.**

Orientation and colour are adjusted to match the edited image. The copy is not identical to the original file, and signatures on the original may no longer be valid.
Up to 16 MiB per image and 128 MiB in total can be kept for restoring.

## Location and deletion

“Settings (gear) → Records” switches where the records are kept (inside the image folder / app-only storage) and deletes them. Deleting also removes labels, notes, masks and metadata backups. Images and edit projects are kept.

[Getting started](USER_GUIDE.md) · [FAQ](FAQ.md)
