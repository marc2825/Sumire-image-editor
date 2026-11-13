# Qt・PySide6 のライセンス文書

Windows版は PySide6-Essentials・shiboken6 6.12.0（Qt 6.12.0）を GNU LGPL version 3 の条件で使っています。
wheel にはライセンス文として商用ライセンスの参照文書しか入っていないため、次の本文を Qt for Python の公式リポジトリの同じ版のタグから取得して入れています（本文は変更していません）。

- [LGPL-3.0-only.txt](https://github.com/pyside/pyside-setup/blob/v6.12.0/LICENSES/LGPL-3.0-only.txt)
- [GPL-3.0-only.txt](https://github.com/pyside/pyside-setup/blob/v6.12.0/LICENSES/GPL-3.0-only.txt)（LGPL v3 は GPL v3 を前提にしているため同梱）

`THIRD_PARTY.md` と `third-party/` は、Qt 6.12.0 と pyside-setup 6.12.0 の公式ソースにある `qt_attribution.json` から `python -m scripts.fetch_qt_sources --notices-only` で作った、第三者のコードの一覧とライセンス文です。

ソースコードの入手方法と、Qt・PySide6 を差し替える方法は [QT_REPLACEMENT.md](../../QT_REPLACEMENT.md) にあります。
