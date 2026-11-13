# Reporting security and privacy problems

Sumīre exists to remove information from images. Bugs that leave such information behind are handled first.

## What to report

- Metadata or generation prompts remain in a saved image (including when “Metadata: none” is shown)
- The original pixels of an area hidden with mosaic, blur or fill can be recovered
- Records, temporary files or the settings file contain information they should not
- Originals or existing files are overwritten or deleted without asking
- The right-click launch or similar can be abused to open or act on files unexpectedly

Known limits, such as mosaic and blur not hiding completely, are described in [Saving and privacy](SAVING_AND_PRIVACY.md).

## How to report

**Do not post it in a public issue.** Report privately with “Report a vulnerability” on the GitHub repository's “Security” tab. If you got Sumīre from a distribution site, use the contact on that page.

Helpful details:

- Sumīre version (Settings → About) and operating system
- Steps to reproduce, and what you expected and what happened
- The kind of information left behind (EXIF, PNG text, Stealth PNGInfo and so on)

**Do not attach private images or records (`.sumire-index.sqlite3` and the like).** Reproduce the problem with synthetic images or images that may be made public.

## Versions

Fixes are made for the latest release. If you use an older version, check whether the problem also happens in the latest one.
