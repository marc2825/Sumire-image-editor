# Reporting problems and requests

Sumīre is developed by one person. Not everything can get a reply or a fix, but reports are handled as follows.

| Topic | Where | Priority |
| --- | --- | --- |
| Information leaks and security | [SECURITY.md](SECURITY.md) (report privately) | Highest |
| Bugs in saving, metadata removal, renaming, or lost files | GitHub issues | High |
| Display and usability bugs | GitHub issues | In turn |
| Feature requests | GitHub issues | Considered case by case |
| Questions about use | Please read the help (F1) and the [FAQ](../../sumire/help_docs/en/FAQ.md) first | Used to improve the documentation |

## When reporting a bug

- Sumīre and Windows versions (copy them from Settings → About → Details of the last error)
- Steps to reproduce, what you expected, and what happened
- The image format (PNG, JPEG, WebP and so on) and its approximate size
- The save method (overwrite / separate folder, auto / manual)

**Do not attach private images or records.** Reproduce the problem with synthetic images or images that may be made public.

## Features that will not be added

Accounts, cloud sync and features that use online services' APIs will not be added. All image processing happens on your PC.

## Sending code

Please discuss it in an issue first. How to run the tests and how the code is organised are described in [Development and builds](../DEVELOPMENT.md) (Japanese). Before sending, make sure `python -m pytest -q` passes. Code you send is published under the same [MIT License](../../LICENSE) as this repository.
