# 依存ライブラリーとライセンス

Sumīre 自身のソースコードは [MIT License](LICENSE)（Copyright (c) 2026 marc2825）です。改変・再配布・商用利用・販売ができます。

Windows版の配布物には、次のソフトウェアとフォントが入っています。それぞれのライセンスは、Sumīre の MIT License とは別に、そのまま適用されます。ライセンス文は配布物の `licenses` フォルダーにあります。

## Windows版に入っているもの（1.00.0）

| 名前 | 版 | ライセンス | ライセンス文・説明 |
| --- | --- | --- | --- |
| Python（ランタイム） | 3.12.10 | PSF License 2.0 | `licenses/Python/LICENSE.txt`（bzip2・libffi・OpenSSL の通知と、Microsoft の再頒布可能なファイルの条件を含む）、`licenses/Python/python-3.12.10-license.rst.txt`（expat・libmpdec・zlib など、Python に組み込まれたコードの通知） |
| Qt（Core・Gui・Widgets・Network・Svg、プラグイン、訳） | 6.12.0 | GNU LGPL v3 | `licenses/Qt/LGPL-3.0-only.txt`、`licenses/Qt/GPL-3.0-only.txt`、差し替え方法は [QT_REPLACEMENT.md](QT_REPLACEMENT.md) |
| Qt が含む第三者のコード | — | BSD・MIT・zlib・libpng・IJG・FreeType など | `licenses/Qt/THIRD_PARTY.md`、`licenses/Qt/third-party/` |
| PySide6・shiboken6 | 6.12.0 | GNU LGPL v3 | `licenses/Qt/`、[QT_REPLACEMENT.md](QT_REPLACEMENT.md) |
| Pillow | 12.3.0 | MIT-CMU | `licenses/Pillow/`（同梱の libjpeg-turbo・libpng・libwebp・libavif・libtiff・FreeType・zlib などの通知を含む） |
| PyInstaller のブートローダー | 6.22.3 | GPL v2 以降＋ブートローダーの例外 | `licenses/PyInstaller/`。例外により、作られた実行ファイルは任意のライセンスで配布できます |
| Noto Sans JP（Regular・Bold） | 2.004 | SIL Open Font License 1.1 | `licenses/NotoSansJP/OFL.txt`。© 2014-2021 Adobe。Noto is a trademark of Google Inc. |
| Microsoft Visual C++ ランタイム・Universal CRT（`VCRUNTIME140.dll`、`MSVCP140*.dll`、`ucrtbase.dll`、`api-ms-win-*.dll`） | — | Microsoft の再頒布可能なファイル | Python と PySide6 に付属して入っています。条件は `licenses/Python/LICENSE.txt` の「Additional Conditions for this Windows binary build」を参照 |

- Qt は商用ライセンスでも提供されていますが、Sumīre は LGPL v3 の条件で使っています。
- Qt と PySide6 の各ファイルは、PyPI の wheel に入っていたものを改変せずに入れています。対応するソースコードは `Sumire-v1.00.0-qt-pyside6-source.zip` として配布物と同じ場所から入手できます（[QT_REPLACEMENT.md](QT_REPLACEMENT.md)）。
- HEIC の読み書きに使う pillow-heif・pi-heif は、ライセンスの都合で配布物に入れていません。
- Noto Sans JP は、[Noto CJK の公式リポジトリ](https://github.com/notofonts/noto-cjk)の `Sans/SubsetOTF/JP` から取得したもので、改変していません。アプリが起動するときにだけ読み込み、Windows にはインストールしません。

## 文書への記載を求められている表示

同梱しているライブラリーのライセンスにより、次のとおり表示します。

- This software is based in part on the work of the FreeType Team (https://freetype.org/).（Pillow と Qt が含む FreeType）
- This software is based in part on the work of the Independent JPEG Group.（Pillow と Qt の JPEG プラグインが含む libjpeg-turbo）

## 開発・ビルドだけに使うもの（配布物には入りません）

| 名前 | ライセンス |
| --- | --- |
| PyInstaller（ブートローダー以外）、pyinstaller-hooks-contrib | GPL v2 以降（例外つき）、Apache-2.0／GPL v2 |
| pytest、pytest-qt、pluggy、iniconfig | MIT |
| Pygments | BSD-2-Clause |
| colorama | BSD-3-Clause |
| altgraph | MIT |
| pefile | MIT |
| pywin32-ctypes | BSD-3-Clause |
| packaging | Apache-2.0 または BSD-2-Clause |
| setuptools | MIT |

版は `scripts/windows-build-requirements.txt` で固定しています。

## 参照

- [Qt for Python のライセンス](https://doc.qt.io/qtforpython-6/licenses.html)、[Qt の LGPL の義務](https://www.qt.io/development/open-source-lgpl-obligations)
- [Pillow のライセンス](https://github.com/python-pillow/Pillow/blob/main/LICENSE)、[PyInstaller のライセンス](https://pyinstaller.org/en/stable/license.html)
- [SIL Open Font License 1.1](https://openfontlicense.org/)
