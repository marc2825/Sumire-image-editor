# 開発・ビルド

ソースからの実行、テスト、Windows版の作り方、コードの構成です。

## 名前

表示名は **Sumīre**、Pythonのパッケージ名やコマンドは **sumire** です。旧名（Sumi）の設定・`.sumi-index.sqlite3`・`.sumi` プロジェクト・`Sumi` フォルダーも、そのまま読み込めます。設定ファイルの場所は環境変数 `SUMIRE_SETTINGS_FILE`（旧 `SUMI_SETTINGS_FILE`）で指定できます。

## 実行

Python 3.12以降を入れ、プロジェクトのフォルダーで次を実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m sumire
```

画像やフォルダーを引数に渡すと、それを開いて起動します。

```powershell
.\.venv\Scripts\python.exe -m sumire "C:\Pictures\illustrations"
```

Linuxでは `python3 -m venv .venv`、`.venv/bin/python -m pip install -e '.[dev]'`、`.venv/bin/python -m sumire` です。画面の表示には、Qtの動作に必要なライブラリーと日本語フォントが要ります。
ネットワークのない環境では、wheelを用意して `pip install --no-index --find-links wheels -e ".[dev]"` で入れられます。

## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

lint と型検査（GitHub Actions と同じ。道具の版は `scripts/ci-requirements.txt`）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts\ci-requirements.txt
.\.venv\Scripts\python.exe -m ruff check sumire scripts tests run_sumire.py
.\.venv\Scripts\python.exe -m mypy
```

画面のテストは画面を表示せずに動きます。Windowsの実際の画面で動かすときは、`QT_QPA_PLATFORM=windows` を設定してください。

GitHub Actions（`.github/workflows/tests.yml`）が、push と pull request のたびに、Windows と Linux で訳の点検（`scripts.i18n_check`）と全テストを実行します。パッケージの版は `scripts/windows-build-requirements.txt` のとおりです。

保存した画像にメタデータが残っていないかは、次のコマンドでも確かめられます。ExifToolが入っていれば、それでも確認します（ExifToolだけでは画素に埋め込まれた情報は見つけられないため、アプリ側でも検査します）。

```powershell
.\.venv\Scripts\python.exe -m scripts.verify_metadata "C:\Pictures\Sumīre\image.png"
```

`python -m scripts.smoke_gui` で、合成画像を使った一連の操作とスクリーンショットの作成を再現できます。

## Windows版を作る

Windows 11 と Python 3.12（64ビット）で実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

1. 専用の仮想環境 `.venv-windows` を作り、[`scripts/windows-build-requirements.txt`](../scripts/windows-build-requirements.txt) の版どおりにパッケージを入れます（配布物と同じ PySide6・Pillow・PyInstaller）。
2. テストを実行します（`-SkipTests` で省略）。
3. PyInstaller でフォルダー形式（onedir）の `dist\sumire\` を作ります。Qt・PySide6 は `_internal\PySide6\` に別のファイルとして残り、差し替えられます（[QT_REPLACEMENT.md](../QT_REPLACEMENT.md)）。
4. `scripts.package_windows` が、版の一致（pyproject.toml・exe のバージョン情報・Windows 説明書）、必要なファイル（Qt・訳・フォント・AVIF）と入れないもの（HEIF・WebEngine）を確かめ、説明書とライセンス文を加えて `dist\Sumire-v<版>-win64.zip` と、その SHA-256（ZIP の外の `.zip.sha256`）を作ります。

- 使う Python は `-PythonExecutable` で指定できます（`py -3.12` がない PC など）。
- 説明書だけを直した場合は、同じ環境で `.venv-windows\Scripts\python.exe -m scripts.package_windows` を実行するとZIPだけを作り直せます。
- Linux上のPythonからWindows版は作れません。
- コード署名、インストーラー、自動更新はありません。

版の表記：画面・説明書・ZIP の名前（`sumire.DISPLAY_VERSION`）と、pyproject.toml・`sumire.__version__` は同じ `1.2.0` です（1.00.0 だけは表示が2桁、パッケージは PEP 440 の形の 1.0.0）。exe のバージョン情報は、数値が 1.2.0.0、文字列が `1.2.0` です。

### Qt・PySide6 のソースとライセンス文

```sh
python -m scripts.fetch_qt_sources
```

Qt 6.12.0（qtbase・qtsvg・qtimageformats・qttranslations）と pyside-setup 6.12.0 の公式のソースを download.qt.io から取得し、スクリプトに記載した SHA-256 と照合して `dist/Sumire-v<版>-qt-pyside6-source.zip` にまとめます。あわせて、ソース内の `qt_attribution.json` から `licenses/Qt/THIRD_PARTY.md` を作り直します。

### 配布物の確認

配布物の exe には、画面を表示せずに確かめる機能があります。設定・記録・一時ファイルは指定したフォルダーの中だけに作り、右クリックメニューは登録しません。

```powershell
.\dist\Sumire-v1.2.0-win64\sumire.exe --self-test "$env:TEMP\sumire-self-test"
```

フォントの読み込み、PNG・JPEG・WebP・AVIF・BMP・TIFF・GIF の書き出しと読み直し、メタデータと Stealth PNGInfo の削除、Qt の訳、ヘルプ、右クリックメニューに登録するコマンド、読み込んだ Qt の DLL の場所と SHA-256、日本語・英語・簡体字中国語の画面と 125%・150% 相当（`QT_SCALE_FACTOR`）の画面を確かめ、`self-test.json` と画面の画像を書き出します。終了コードが 0 なら、すべて通っています。

実際のマウス・キーボード操作での確認には、Windowsの検証用Pythonに `Pillow pywinauto psutil pywin32` を入れて実行します。マウスとキーボードを自動で動かすため、終わるまでPCを操作しないでください。

```powershell
python -m scripts.smoke_windows_exe dist\Sumire-v1.2.0-win64 --artifacts test-artifacts\windows-exe --shell-verbs
```

`--artifacts` には新しいフォルダーを指定します。`--shell-verbs` を付けると、右クリックの登録と、そこからの起動も確かめます（終わったら元に戻します）。

Windows Sandboxが使えるPCでは、次のコマンドでネットワークのない確認環境を開けます。

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create_windows_sandbox.ps1 -Launch
```

### 公開前の検査

```sh
python -m scripts.export_public --audit --destination .
```

このリポジトリで公開される（Git が追跡する、または無視されない新しい）ファイルを検査します。秘密鍵・トークン・個人のパス・メールアドレス（`licenses/` の上流のライセンス文を除く）、開発用の記録、SQLite・ログ・画像・キャッシュがあれば、終了コード 1 で知らせます。`--private-term` で、自分のメールアドレスなど特定の文字列も検査できます（値は記録しません）。

`python -m scripts.export_public --destination <フォルダー>` は、許可リストのファイルだけを Git の履歴なしで書き出します（既定は `build/source/Sumire-image-editor`）。Windows でビルドするときに、作業中のファイルを含まない写しを作るのに使えます。

### アンインストールの補助

`sumire.exe --unregister` は、右クリックの「Sumīreで開く」を解除して終了します。配布物の `unregister-context-menu.cmd` はこれを実行するだけのファイルです。

## 表示言語

画面の文字は日本語で書き、`tr("…")` で包みます（`sumire/i18n.py`）。日本語の文がそのまま鍵になり、英語・簡体字中国語の訳は `sumire/locales/en.json`・`zh_CN.json` にあります。値を差し込む文は `tr("保存 {count}枚").format(count=n)` のように名前付きの欄にし、訳でも同じ欄を使います。

- 文を足したり変えたりしたら、`python -m scripts.i18n_check` で訳のない文を確かめ、両方の訳を足します。`--prune` で、使われなくなった訳を消せます。テスト（`tests/test_i18n.py`）も、訳の不足と欄の食い違いを確かめます。
- 一覧の保存の状態（「未編集 · 保存済み」など）は日本語のまま持ち、表示するときに `tr_state` で区切りごとに訳します。プリセットの既定の名前も、設定には日本語で残します。
- 言語は起動時に一度だけ決まります（設定の `language`、なければ日本語）。画面のモジュールは言語を決めてから読み込みます（`__main__.window_class`）。
- ヘルプは `sumire/help_docs/`（日本語）、`help_docs/en/`、`help_docs/zh_CN/` にあり、訳がないページは日本語で表示します。利用者向けの文書の訳は `docs/en/`・`docs/zh-CN/` と、`README.en.md`・`README.zh-CN.md`・`README-Windows.*.txt` です。

## コードの構成

超解像・モザイク・Stealth PNGInfo・重複の判定などの処理の仕組みは、[仕組みの解説](technical/README.md)にまとめています。

| ファイル | 役割 |
| --- | --- |
| `sumire/window.py` | 画面と操作の流れ |
| `sumire/workspace_tabs.py` | 作業タブ |
| `sumire/workbench.py` | 一覧・仕分け・一括操作 |
| `sumire/folders.py`、`sumire/folder_features.py` | タブ内のフォルダーと画像の移動 |
| `sumire/library.py` | 一覧・絞り込み・サムネイル |
| `sumire/canvas.py` | 画像の表示と描画 |
| `sumire/imaging.py` | 画像処理と編集の履歴 |
| `sumire/editing.py`、`sumire/editor_dialogs.py`、`sumire/editor_features.py` | 切り抜き・回転・色調・超解像 |
| `sumire/export.py` | 確認つきの保存 |
| `sumire/backups.py` | 上書き前の元画像の一時保存と復元 |
| `sumire/stealth.py` | Stealth PNGInfoの検出と除去 |
| `sumire/metadata.py` | メタデータの確認・復元用の保存・復元 |
| `sumire/convert.py`、`sumire/collage.py`、`sumire/collage_canvas.py` | 形式変換・容量削減・コラージュ（配置と切り抜きの画面） |
| `sumire/output_dialogs.py`、`sumire/output_features.py` | 書き出しの画面と処理 |
| `sumire/session.py`、`sumire/labels.py`、`sumire/masks.py`、`sumire/storage.py` | 管理記録 |
| `sumire/organize.py`、`sumire/locking.py` | 名前の変更・中断からの復旧・Sumīre同士の排他 |
| `sumire/analysis.py`、`sumire/compare.py` | 重複の検出と比較 |
| `sumire/monitor.py`、`sumire/workers.py` | フォルダーの監視と、バックグラウンドの処理 |
| `sumire/novelai.py` | NovelAIへ渡す画像の用意 |
| `sumire/settings_dialog.py`、`sumire/preferences.py`、`sumire/shortcuts.py` | 設定 |
| `sumire/help.py`、`sumire/help_docs/` | 同梱のヘルプ（言語ごとのフォルダー） |
| `sumire/i18n.py`、`sumire/locales/` | 表示言語と訳 |
| `sumire/ui.py`、`sumire/theme.py`、`sumire/icons.py` | 画面の部品・配色・アイコン |

レイヤー、編集履歴の保存、アニメーションには対応していません。
