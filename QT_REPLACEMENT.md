# Qt・PySide6 の差し替えとソースコード

Windows版の Sumīre は、Qt と PySide6 を GNU LGPL version 3 の条件で使っています。
ここでは、配布物に入っている Qt・PySide6 の場所、そのソースコードの入手方法、利用者が自分で用意した Qt・PySide6 に差し替える方法を説明します。

An English summary is at the end.

## 配布物に入っているもの

`Sumire-v1.5.0-win64.zip` を展開したフォルダーの `_internal` に、次のファイルがそのまま（改変・圧縮せずに）入っています。どれも PyPI の wheel（PySide6-Essentials 6.12.0・shiboken6 6.12.0）に含まれていたものです。

| 種類 | 版 | 場所（`_internal\` から） |
| --- | --- | --- |
| Qt のライブラリー | 6.12.0 | `PySide6\Qt6Core.dll`、`Qt6Gui.dll`、`Qt6Widgets.dll`、`Qt6Network.dll`、`Qt6Svg.dll` |
| Qt のプラグイン | 6.12.0 | `PySide6\plugins\`（`platforms`・`styles`・`imageformats`・`iconengines`） |
| Qt の訳 | 6.12.0 | `PySide6\translations\*.qm` |
| PySide6 | 6.12.0 | `PySide6\QtCore.pyd`、`QtGui.pyd`、`QtWidgets.pyd`、`QtNetwork.pyd`、`pyside6.abi3.dll` |
| shiboken6 | 6.12.0 | `shiboken6\` |

- PySide6 の Python のファイル（`PySide6\__init__.py` など）は、ほかの Python のコードと一緒に `sumire.exe` の中にまとめられています。
- Sumīre が使わない Qt のプラグイン（TLS 通信・ネットワーク状態・TUIO 入力）と、ソフトウェア描画用の `opengl32sw.dll` は配布物から除いています。
- Qt と PySide6 のライセンス文は `licenses\Qt\`（LGPLv3・GPLv3）に、Qt が含む第三者のコードの一覧は `licenses\Qt\THIRD_PARTY.md` にあります。

## ソースコード

- **Qt・PySide6・shiboken6**：同じ版の公式のソース一式を `Sumire-v1.5.0-qt-pyside6-source.zip` にまとめ、配布 ZIP と同じ場所から配布します。中身は download.qt.io で公開されている次のアーカイブで、Qt が公開している SHA-256 と照合しています。
  - `qtbase-everywhere-src-6.12.0.tar.xz`
  - `qtsvg-everywhere-src-6.12.0.tar.xz`
  - `qtimageformats-everywhere-src-6.12.0.tar.xz`
  - `qttranslations-everywhere-src-6.12.0.tar.xz`
  - `pyside-setup-everywhere-src-6.12.0.tar.xz`

  同じものは `python -m scripts.fetch_qt_sources` で取得・照合できます（入手先と SHA-256 はスクリプトに記載）。
- **Sumīre**：MIT License で公開しているソース一式（GitHub の `Sumire-image-editor`）に、配布物を作るスクリプトと、使ったパッケージの版を固定した一覧（`scripts/windows-build-requirements.txt`）が入っています。

## 差し替える方法

Qt 6.12 と互換性のある Qt（MSVC 2022・64 ビットでビルドしたもの）を用意してください。Qt の版は、同じ 6.12 系であれば差し替えられる見込みです。PySide6 を差し替える場合は、Qt と PySide6 の版をそろえてください。

### A. ライブラリーのファイルを置き換える

1. 配布 ZIP を展開したフォルダーで、Sumīre を終了します。
2. `_internal\PySide6\` の `Qt6*.dll` と、`_internal\PySide6\plugins\` のプラグインを、用意したファイルに置き換えます。ファイル名とフォルダーの構成は変えません。
3. PySide6 自体を置き換える場合は、`_internal\PySide6\*.pyd`・`pyside6.abi3.dll` と `_internal\shiboken6\` も置き換えます。PySide6 の Python のファイルを変える場合は、下の B の方法で作り直してください。
4. 次のコマンドで確認します。画面は表示されず、利用者の設定や画像には触れません。

   ```powershell
   .\sumire.exe --self-test "$env:TEMP\sumire-self-test"
   ```

   終了コードが 0 なら、すべての確認に通っています。`self-test.json` の `loaded_libraries` に、実際に読み込んだ Qt のファイルとその SHA-256 が記録されるので、置き換えたファイルが使われたことを確かめられます。

### B. ソースから作り直す

公開しているソースから、配布物と同じ構成で作り直せます（Windows 11、Python 3.12 64 ビット）。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

改変した PySide6・Qt を使う場合は、`scripts/windows-build-requirements.txt` の `PySide6-Essentials`・`shiboken6` を自分の wheel に変えるか、作られた `.venv-windows` にその wheel を入れてから、スクリプトの PyInstaller 以降を実行します。詳しくは [開発・ビルド](docs/DEVELOPMENT.md) を参照してください。

## 確かめたこと

1.2.0 の配布物で、Windows 11 上で次を確かめました。結果は配布物の作成時の記録に残しています。

- `_internal\PySide6\` の Qt のファイルが、wheel に含まれていたものと同じ（SHA-256 が一致）であること。
- 起動した Sumīre が、Qt のライブラリーを `_internal\PySide6\` から読み込むこと（`--self-test` の `loaded_libraries`）。
- Qt が別に配布している Qt 6.12.0 の MSVC 2022 版（download.qt.io のオンラインインストーラー用リポジトリの `qtbase`。wheel のものとは SHA-256 が異なる）の `Qt6Core.dll`・`Qt6Gui.dll`・`Qt6Widgets.dll`・`Qt6Network.dll`・`qwindows.dll` に置き換えても、`--self-test` のすべての確認に通り、置き換えたファイルが読み込まれること。

自分で改変・ビルドした Qt での差し替えは試していません。

## English summary

Sumīre for Windows uses Qt 6.12.0 and PySide6/shiboken6 6.12.0 under the GNU LGPL version 3. The libraries are unmodified files from the PySide6-Essentials and shiboken6 wheels and are stored as separate files in `_internal\PySide6\` and `_internal\shiboken6\` (PySide6's Python modules are inside `sumire.exe`).

- **Source code**: `Sumire-v1.5.0-qt-pyside6-source.zip` is offered next to the distribution ZIP. It contains the official source archives of qtbase, qtsvg, qtimageformats, qttranslations and pyside-setup 6.12.0 from download.qt.io, checked against Qt's published SHA-256 values. `python -m scripts.fetch_qt_sources` downloads and checks the same files. Sumīre's own source (MIT) includes the build scripts and the pinned package versions.
- **Replacing the libraries**: quit Sumīre, replace the `Qt6*.dll` files and plugins in `_internal\PySide6\` (and, for PySide6 itself, the `.pyd` files, `pyside6.abi3.dll` and `_internal\shiboken6\`) with compatible builds (Qt 6.12, MSVC 2022, x64), keeping the names. Then run `sumire.exe --self-test <folder>`; it exits with 0 when every check passes, and `self-test.json` lists the Qt files that were loaded with their SHA-256. To change PySide6's Python modules, rebuild with `scripts\build_windows.ps1` after installing your wheels.
- **Tested**: replacing Qt6Core, Qt6Gui, Qt6Widgets, Qt6Network and qwindows with Qt's separately distributed official 6.12.0 MSVC 2022 build passed the self-test, and the replaced files were the ones loaded. A self-built, modified Qt has not been tried.
