# Sumīre — image finishing

[![version](https://img.shields.io/badge/version-1.00.0-a7dfc2)](CHANGELOG.md) [![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE) [![platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)](README-Windows.en.txt)

[日本語](README.md) · English · [简体中文](README.zh-CN.md)

Sumīre is a Windows 11 app for hiding parts of images with mosaic or blur, and for viewing and removing their metadata. It also helps you sort and export large batches of images. All image processing happens on your PC.

## The basic flow

Open a folder, trace over what you want to hide, and press → for the next image. Edits are saved automatically; Enter saves and moves on.

On the first start, choose where to save: overwrite the originals, or save to a separate folder.

## Features

- **Hide**: mosaic, blur and fill, with a brush, rectangle, ellipse, polygon or lasso. Eraser, undo / redo and comparison with the original.
- **View and remove metadata**: see EXIF, PNG text, generation prompts and more as a list, and remove them one image at a time or in bulk. NovelAI's information embedded in transparency (Stealth PNGInfo) is removed too, and the saved file is checked. By default, metadata is kept when saving.
- **Restore later**: metadata removed from an image can be kept and restored into a separate copy.
- **Sort**: Reject / Hold / Accept labels, filters, tabs, moving between folders, numbered renaming, duplicate removal and side-by-side comparison.
- **Export**: convert to PNG, JPEG, WebP, AVIF, BMP, TIFF or GIF, reduce file size, export the accepted images, make collages.
- **Adjust**: crop, resize, rotate, flip, colour (brightness, contrast, saturation, hue, exposure, temperature and more), upscale.
- **Share**: hand images without metadata to NovelAI's Image2Image or to other apps.

The interface is available in Japanese, English and Simplified Chinese (at the bottom right of the start page, or Settings → Display and import → Language).

Sumīre makes no network requests. It only opens your default browser for NovelAI.

## Getting started

**Windows**: extract the whole distribution ZIP and run `sumire.exe`. Python is not needed. See [README-Windows.en.txt](README-Windows.en.txt).

**From source**: install Python 3.12 or later and run this in the project folder:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m sumire
```

Running on Linux, tests and building the exe are described in [Development and builds](docs/DEVELOPMENT.md) (Japanese).

## Before you share

- **An overwritten original cannot be brought back after the app closes.** Until then, “⋯ → Restore the original from before overwriting” brings it back. To keep originals, save to a separate folder.
- **Metadata kept for restoring is not encrypted.** Prompts and location data stay readable; they are stored in the app's own data folder. Installations from 0.4.0 or earlier keep them as `.sumire-index.sqlite3` in the image folder; leave that file out when sharing whole folders.
- **Mosaic and blur cannot hide completely.** Use fill at 100% opacity for anything that must stay hidden.
- **“Metadata: none” covers the kinds Sumīre checks.** It cannot detect unknown embedding methods or text drawn into the image.

See [Saving and privacy](docs/en/SAVING_AND_PRIVACY.md) for details.

## Documentation

Press “?” or F1 in the app to read the same help offline.

| Document | Contents |
| --- | --- |
| [Features](sumire/help_docs/en/FEATURES.md) | What Sumīre can do, and where |
| [Getting started](sumire/help_docs/en/USER_GUIDE.md) | Opening, hiding, saving and sorting, step by step |
| [Shortcuts](sumire/help_docs/en/SHORTCUTS.md) | Keyboard shortcuts |
| [Metadata and restoring](sumire/help_docs/en/METADATA.md) | Removing, keeping and restoring, and what to watch when sharing |
| [FAQ](sumire/help_docs/en/FAQ.md) | When something goes wrong |
| [Usage guide](docs/en/USAGE.md) | Every feature in detail |
| [Saving and privacy](docs/en/SAVING_AND_PRIVACY.md) | How saving works, what is checked, and the limits |
| [Security](docs/en/SECURITY.md) / [Reporting problems](docs/en/CONTRIBUTING.md) | How to report |

The change log, roadmap, development notes and technical explanations are in Japanese.

## License

Sumīre's code is under the [MIT License](LICENSE): you may modify, redistribute and use it commercially.

Python, Qt, PySide6, Pillow, Noto Sans JP and the other parts of the Windows version keep their own licences (LGPLv3 for Qt and PySide6, SIL Open Font License 1.1 for Noto Sans JP, and so on). See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (Japanese) for the list and [QT_REPLACEMENT.md](QT_REPLACEMENT.md) for replacing Qt and getting its source.
