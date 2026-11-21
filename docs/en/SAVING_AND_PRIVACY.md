# Saving and privacy

How saving works, how metadata is removed and restored, how records are handled, and what this app cannot prevent. The steps are in the [Usage guide](USAGE.md).

## Save methods

- Overwrite the original: replaces PNG, JPEG and WebP files in the same place, with the same name and format. Other formats cannot be overwritten.
- Save to a separate folder: saves into `Sumīre` (changeable) inside the image's folder, as PNG (default), JPEG or lossless WebP. If the name exists, `_2` or similar is added.

### Safeguards when overwriting

- The image is first written to a temporary file and checked; only then is it swapped with the original. If anything fails or is cancelled, the original is unchanged.
- The original's SHA-256 from when it was opened is compared just before saving. If another app changed or deleted it, overwriting stops.
- “Keep the original temporarily before overwriting” (on by default): the original from just before the first overwrite after starting is copied to `sumire-backup-*` in the system's temporary folder. “⋯ → Restore the original from before overwriting” checks it and puts it back.
- Kept originals are deleted when the app closes. Copies left by a crash are deleted at a later start after 7 days.
- Crop, resize and upscale follow the save method. When overwriting, Sumīre asks before applying them. After overwriting and quitting, cropped-off parts cannot be brought back.

### Actions that create new files

Save as, Convert format, Reduce file size, Make a collage and Export by label (copying) only create new files; they change neither the originals nor the image being edited. The two exceptions:

- “Overwrite the originals” in Reduce file size: replaces images whose format stays the same.
- “Move the original files” in Export by label: moves the files as they are.

Images in a separate folder are updated automatically only if Sumīre wrote them and they have not changed since.

### JPEG

JPEG is saved at quality 95 (changeable, 1–100) without chroma subsampling, with transparent areas made white. It is recompressed on every save, so even unedited areas change slightly.

## Saving with metadata kept

By default, metadata is kept when you save edits. Just before saving, the original's metadata is read and attached to the image rebuilt from the edited pixels.

- It is attached only when saving in the original's format. In another format, the image is saved without metadata.
- Orientation is applied to the pixels and set to “1”, and the ICC profile is replaced with sRGB.
- NovelAI's Stealth PNGInfo is embedded again into the edited pixels (except in JPEG).
- Only kinds of information that are understood are kept: EXIF, GPS, XMP, PNG text, comments, IPTC, resolution and the like. Unknown segments (such as private PNG chunks) are not kept.
- C2PA (Content Credentials) is kept as it is, unless it contains a picture such as a thumbnail or an imported ingredient. Editing breaks its signature, so verifiers report a change.

### What is not kept

Nothing that would be a copy of the unedited image is kept:

- EXIF thumbnails and maker notes (MakerNote, which may contain previews)
- Photoshop thumbnails and JFIF thumbnails
- Images embedded in XMP or text (such as the original image Google's camera puts into XMP)
- MPF, FlashPix and extended XMP segments

EXIF is rewritten without only the thumbnail and MakerNote; date, camera, location and so on are kept.

## Removing metadata

These rebuild a new image from the pixels alone:

- “Remove metadata”, “Remove all metadata”, “Remove metadata and save”
- Saving with “Remove metadata when saving” on

The original's EXIF, GPS, XMP, IPTC, comments, PNG text (`tEXt`, `zTXt`, `iTXt`, `eXIf`), generation prompts, software names, authors, copyright notices, ICC profiles, embedded thumbnails and C2PA are not carried over. The same goes for information added by NovelAI, Stable Diffusion, ComfyUI and others.

### Stealth PNGInfo

The prompt information NovelAI embeds in the pixels is removed too. When the `stealth_pngcomp` signature of [NovelAI's implementation](https://github.com/NovelAI/novelai-image-metadata), or `stealth_pnginfo`, `stealth_rgbcomp` or `stealth_rgbinfo` of [a related method](https://github.com/neggles/sd-webui-stealth-pnginfo), is found, the whole least-significant-bit area is cleared (its contents are not read).

- It is removed when the image is opened (before rotation or colour conversion), and its absence is checked again when saving.
- For NovelAI's opaque images, only the transparency is set back to 255 (colours and size do not change). For images with transparency, or the RGB variants, the affected colours change by at most one level.
- Images saved with earlier versions should be processed again with “Remove metadata” or “Remove all metadata”.

### Checks after saving

The saved image is read back to check its size, format and single frame, and that no metadata or Stealth PNGInfo remains. Its file structure is checked too, and only these parts are allowed. If anything is wrong, saving is abandoned.

- PNG: `IHDR`, `IDAT`, `IEND`
- JPEG: what is needed for decoding, plus `JFIF`
- WebP: `VP8`, `VP8L`, `VP8X`, `ALPH`

New files are created in a way that never overwrites existing files (hard links). On Windows, a local NTFS folder is recommended. Destinations that do not support hard links fail to save, and no incomplete file is left.

### What cannot be checked

- “Metadata: none” means these checks found nothing. It does not guarantee that no unknown embedding method was used.
- Watermarks hidden in the pixels themselves (such as SynthID) are not metadata and cannot be removed.

## Metadata kept for restoring

With “Keep removed metadata for restoring” (on by default), the original metadata is compressed with zlib and saved in the records before the image is rewritten. If it cannot be saved, the image is not rewritten.

- “⋯ → More → Save a copy with restored metadata” makes a copy of the current result with the metadata attached. Originals and existing files are never overwritten.
- The copy uses the same format if the original was PNG, JPEG or WebP, and PNG for BMP, AVIF, TIFF or GIF.
- Files made with Convert format, Reduce file size or Save as can be restored too. After renaming or re-saving, restoring still works by matching the image's SHA-256.
- Anything that would be a copy of the unedited image, such as thumbnails, is not restored (it remains in the records).
- Orientation is set to “1” and colour to sRGB. For Stealth PNGInfo, the header and body are restored, but the trailing error-correction data is not. The result is not identical to the original file.
- Up to 16 MiB per image after decompression, and 128 MiB in total, can be kept.
- Information removed before this feature was used, or not kept for restoring, cannot be brought back.

**Compression is not encryption.** The records keep removed prompts, location data and embedded thumbnails as they were. When sharing images, do not include the records (`.sumire-index.sqlite3` and its temporary files).

## Images in a ZIP

Images in a ZIP are read from the ZIP each time they are shown; nothing is written to the ZIP.

- Before reading, the ZIP's size and modification time from when it was opened, and the entry's size and CRC-32, are compared. If they differ, the image is not read and you are told so.
- The ZIP is never held open, so it can be moved or deleted while it is shown.
- Labels, tags and notes are kept in the records of the ZIP's folder, under an identifier made from the ZIP's location, the name inside it and its content (CRC-32 and size). They never attach to another ZIP or to an image whose content changed.
- “Export from ZIP” writes the chosen images' data unchanged as new files. Existing files are never overwritten, and nothing is written outside the chosen folder.

## Records

Save records, labels, notes, tags, edit masks and metadata kept for restoring are stored in SQLite records.

- They are kept in the app's own storage (`records/<an identifier per folder>/` next to the settings). They are not created in image folders, so sharing a whole folder does not pass on removed metadata.
- If you have used Sumīre since 0.4.0 or earlier, they stay in `.sumire-index.sqlite3` inside the image folder. Windows shows files starting with “.”, so take care when sharing.
- Switching the location in “Settings → Records” moves the records (if that fails, everything is put back). The same window can delete the records of the current list.

The records contain an identifier made from the file path, output file names, formats and SHA-256, whether images were edited, labels, notes, tags, black-and-white masks, transformation steps and metadata kept for restoring. They contain no images, no plain-text original paths and no edit history.

The settings file (`sumire-workspace.json`) contains paths for resuming, recent folders and presets.

## Supported images

- Still PNG, JPEG, WebP, AVIF, BMP, TIFF and GIF can be opened.
- Animations, multi-page TIFF, SVG, RAW and HEIC are not supported (HEIC needs a component that is not bundled for licensing reasons).
- Images over 24 million pixels, 32,768 px per side or 256 MiB, damaged images, and images whose colours cannot be converted cannot be opened.
- 16-bit images become 8-bit.
- When opening, the EXIF orientation is applied to the pixels and any ICC profile is converted to sRGB. The original profile is not kept, so colours may look different on some displays.

## Many images

“Remove all metadata” saves every image in the tab again (saved ones included), one by one.

- Before it starts, it shows the number of images, the save method and the destination.
- Failed images are skipped and listed at the end.
- If you stop it, the images already saved stay saved.

Memory limits:

- Images being edited: up to the 2 most recent per tab (256 MiB), and about 512 MiB for the whole app. The shown image and unsaved edits are never released.
- Undo history is trimmed from the oldest, at about 80 steps or 48 MiB per image (the last step is always kept).
- List thumbnails are only for display and are never used for saving.

## What this app cannot prevent

- There is no guarantee that mosaic or blur hides completely. For anything that must stay hidden, fill it at 100% opacity and check at actual size ([how they are calculated and what remains](../technical/HIDING.md), Japanese).
- Text drawn into the image, visible watermarks, unknown embedding methods, file and folder names, operating-system history and cloud sync are out of scope. Complete anonymisation is not possible.
- Edit projects (`.sumire`) contain the unedited image.

## Temporary files

Sumīre never writes images or metadata to logs. While working it creates the following temporary files and deletes them when done. If any remain after a crash or power cut, you can delete them after quitting the app.

- `.sumire-*.tmp`: the edited image while saving
- `.sumire-project-*`: data of an edit project while saving (including the original)
- `.sumire-restore-*.tmp`: an image with metadata while restoring
- `.sumire-staging-*`: images converted or reduced, before they are written
- `sumire-backup-*` (system temporary folder): originals from before overwriting (deleted when the app closes)
- `.sumire-rename-*.tmp`, `.json`: links that protect originals during a rename, and the recovery record

If a rename was interrupted, the next time that folder is opened the old names are restored or the rename is completed. If a file was replaced by something else, the recovery files are kept and recovery stops.

To keep two Sumīre windows from rewriting the same image at once, lock files are placed in `sumire-locks-*` in the system's temporary folder. Changes by other apps cannot be prevented this way, so content hashes are compared as well.
