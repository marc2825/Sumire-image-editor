Sumīre 1.5.0 / Windows 11 x64

Getting started
Extract the whole ZIP and double-click sumire.exe. Python is not needed.
sumire.exe uses the _internal folder next to it: keep the folder together and do not move the exe on its own.
On the first start, choose “Overwrite the original” or “Save to a separate folder and keep the original”. If you close it without choosing, originals stay unchanged and images are saved to a separate folder. You can change it later with “Overwrite · auto-save ▾” at the top right.
Images and folders can also be opened by dropping them on the window. Next time, Sumīre starts with the same tabs and images.
To switch the language, use the box at the bottom right of the start page, or open the gear at the top right → “Display and import” → “Language” (applies from the next start).

Basic use
Trace over what you want to hide; it is saved automatically. Enter saves and moves to the next image; ← → move between images.
The list is on the left, the image in the centre, and the editing tools and sorting (Accept / Hold / Reject, keys 1, 2, 3) on the right.
If you get stuck, open the help with “?” at the top right or F1 (it works offline).

Main features
- Tabs: Ctrl+T opens a new tab, Ctrl+W closes it. Double-click a tab to rename it.
- Folders: open or create folders inside from the bar above the list. Drag images onto a folder to move them.
- Right-click an image: Save as, Convert format, Reduce file size, Upscale, Compare, Make a collage, numbering, Tags, Remove from list, Delete images (to the Recycle Bin).
- Crop, Compare and Mask are below the image; rotate, flip and colour are in “More settings” in the right panel.
- Text: choose “Text” (T) in the right panel and click the image to add text. Afterwards, move, rotate and resize it with its box, and double-click to rewrite.
- ZIP: “File → Open ZIP…” or drag and drop shows and sorts the images in a ZIP without extracting it (read only; “Export from ZIP…” takes chosen images out).
- Custom tags: tags you use often, such as “Needs fixing”, are added and removed with the buttons in “Custom tags” above the labels (keys 4–9).
- Ctrl+C copies the result; Ctrl+V opens the clipboard image in a new tab. With the list focused, they cut, copy and paste the image files instead (Ctrl+X, Ctrl+C, Ctrl+V).

Metadata
By default, metadata is kept when saving. To remove it, use “Remove metadata” above the image or “Remove all metadata” above the list. It can also be removed on every save.
Press “Metadata: yes” above the image to see what it contains.
Removed information can be restored with “⋯ → More → Save a copy with restored metadata”. It is not encrypted, so prompts and location data stay readable. It is kept in the app's own storage, not in the image folder (if you have used Sumīre since 0.4.0 or earlier, in .sumire-index.sqlite3 inside the image folder).
“Metadata: none” is the result of checking the supported kinds. Information embedded in unknown ways cannot be checked.

Opening from the right-click menu
After deciding where to keep the extracted folder, choose the gear at the top right → “Windows” → “Add “Open with Sumīre” to the right-click menu”. Then right-click an image or folder → “Show more options” → “Open with Sumīre”.
Register again after moving the folder, and remove the entry before deleting it.

Updating
Extract the new ZIP into another folder, quit the old app, then start the new one. Settings, records and edit projects carry over. Deleting the extracted folder leaves images, settings and records in place. Change or delete where records are kept under “Records” in the settings. If you added the right-click entry, register it again from the new folder.

Uninstalling
1. If you added the right-click entry, double-click unregister-context-menu.cmd in the extracted folder to remove it (or use the gear → “Windows” → “Remove the right-click entry”).
2. To remove settings and records too, delete the records under “Records” in the settings, then delete the %LOCALAPPDATA%\Sumīre folder (and, if you have used Sumīre since 0.4.0 or earlier, .sumire-index.sqlite3 in the image folders).
3. Delete the extracted folder. Your images are not touched.

Detailed instructions are in the docs folder (English in docs/en), changes in CHANGELOG.md (Japanese), and tested environments in docs/VALIDATION_SUMMARY.md (Japanese).
For reporting problems see docs/en/SECURITY.md; licences are in LICENSE, THIRD_PARTY_NOTICES.md and the licenses folder, and how to replace Qt and get its source is in QT_REPLACEMENT.md.
