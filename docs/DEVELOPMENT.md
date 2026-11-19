# 開発・ビルド

ソースからの実行、テスト、Windows版の作り方、コードの構成です。

## 名前

表示名は Sumīre、Pythonのパッケージ名やコマンドは `sumire` です。旧名（Sumi）の設定・`.sumi-index.sqlite3`・`.sumi` プロジェクト・`Sumi` フォルダーも、そのまま読み込めます。設定ファイルの場所は環境変数 `SUMIRE_SETTINGS_FILE`（旧 `SUMI_SETTINGS_FILE`）で指定できます。

## 実行

Windows・WSL（Ubuntu 24.04）での手順は[README](../README.md#使い始める)にあります。

- Linuxでは `python3 -m venv .venv`、`.venv/bin/python -m pip install -e '.[dev]'`、`.venv/bin/python -m sumire` で動きます。画面の表示には、Qtの動作に必要なライブラリーと日本語フォントが要ります。
- ネットワークのない環境では、wheelを用意して `pip install --no-index --find-links wheels -e ".[dev]"` で入れられます。

画像やフォルダーを引数に渡すと、それを開いて起動します。

```powershell
.\.venv\Scripts\python.exe -m sumire "C:\Pictures\illustrations"
```


## テスト

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

画面のテストは画面を表示せずに動きます。Windowsの実際の画面で動かすときは、`QT_QPA_PLATFORM=windows` を設定してください。

lint と型検査の道具の版は `scripts/ci-requirements.txt` に固定しています。

```powershell
.\.venv\Scripts\python.exe -m pip install -r scripts\ci-requirements.txt
.\.venv\Scripts\python.exe -m ruff check sumire scripts tests run_sumire.py
.\.venv\Scripts\python.exe -m mypy
```

GitHub Actions（`.github/workflows/tests.yml`）は、push と pull request のたびに、Windows と Linux で次を実行します。パッケージの版は `scripts/windows-build-requirements.txt` のとおりです。

- 訳の点検（`scripts.i18n_check`）
- 公開前の検査（`scripts.export_public --audit`）
- 全テスト（Linuxではカバレッジも計測）
- ruff と mypy（Linuxのみ）

保存した画像にメタデータが残っていないかは、次のコマンドでも確かめられます。ExifToolが入っていれば、それでも確認します。ExifToolだけでは画素に埋め込まれた情報を見つけられないため、アプリ側でも検査します。

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

画面・説明書・ZIP の名前に使う版（`sumire.DISPLAY_VERSION`）と、pyproject.toml・`sumire.__version__` は同じ `1.4.0` です（1.00.0 だけは表示が2桁、パッケージは PEP 440 の形の 1.0.0）。exe のバージョン情報は、数値が 1.4.0.0、文字列が `1.4.0` です。

### Qt・PySide6 のソースとライセンス文

```sh
python -m scripts.fetch_qt_sources
```

Qt 6.12.0（qtbase・qtsvg・qtimageformats・qttranslations）と pyside-setup 6.12.0 の公式のソースを download.qt.io から取得し、スクリプトに記載した SHA-256 と照合して `dist/Sumire-v<版>-qt-pyside6-source.zip` にまとめます。あわせて、ソース内の `qt_attribution.json` から `licenses/Qt/THIRD_PARTY.md` を作り直します。

### 配布物の確認

ビルドに使った環境で次を実行すると、利用者が受け取るのと同じ形で ZIP を確かめます。

- ZIP の外の `.sha256` と、中の `SHA256SUMS.txt` との照合
- 必要な説明書とライセンス文があること、私的なファイルが入っていないこと
- Qt・PySide6 のファイルが、インストールした wheel と同じであること
- 日本語と空白を含むパスに展開しての自己検査
- `--replace-qt` に Qt 6.12（MSVC 2022 x64）の公式ビルドのフォルダーを渡すと、Qt の DLL を置き換えて自己検査をやり直し、置き換えた DLL が読み込まれたことも確かめます。

```powershell
python -m scripts.verify_distribution dist\Sumire-v1.4.0-win64.zip --report test-artifacts\distribution.json
```

配布物の exe だけで確かめるときは、自己検査を直接実行します。設定・記録・一時ファイルは指定したフォルダーの中だけに作り、右クリックメニューは登録しません。

```powershell
.\dist\Sumire-v1.4.0-win64\sumire.exe --self-test "$env:TEMP\sumire-self-test"
```

自己検査で確かめること：

- フォントの読み込み、Qt の訳、ヘルプ
- PNG・JPEG・WebP・AVIF・BMP・TIFF・GIF の書き出しと読み直し
- メタデータと Stealth PNGInfo の削除
- 右クリックメニューに登録するコマンド
- 読み込んだ Qt の DLL の場所と SHA-256
- 日本語・英語・簡体字中国語の画面と、125%・150% 相当（`QT_SCALE_FACTOR`）の画面

結果は `self-test.json` と画面の画像に書き出します。終了コードが 0 なら、すべて通っています。

実際のマウス・キーボード操作で確かめるときは、Windowsの検証用Pythonに `Pillow pywinauto psutil pywin32` を入れて次を実行します。マウスとキーボードを自動で動かすため、終わるまでPCを操作しないでください。

```powershell
python -m scripts.smoke_windows_exe dist\Sumire-v1.4.0-win64 --artifacts test-artifacts\windows-exe --shell-verbs
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

このリポジトリで公開される（Git が追跡する、または無視されない新しい）ファイルを検査します。秘密鍵・トークン・個人のパス・メールアドレス（`licenses/` の上流のライセンス文を除く）、開発用の記録、SQLite・ログ・画像・キャッシュがあれば、終了コード 1 で知らせます。`--private-term` を使うと、自分のメールアドレスなど特定の文字列も検査できます（値は記録しません）。

`python -m scripts.export_public --destination <フォルダー>` は、許可リストのファイルだけを Git の履歴なしで書き出します（既定は `build/source/Sumire-image-editor`）。Windows でビルドするときに、作業中のファイルを含まない写しを作るのに使えます。

### アンインストールの補助

`sumire.exe --unregister` は、右クリックの「Sumīreで開く」を解除して終了します。配布物の `unregister-context-menu.cmd` はこれを実行するだけのファイルです。

## 表示言語

画面の文字は日本語で書き、`tr("…")` で包みます（`sumire/i18n.py`）。日本語の文がそのまま鍵になり、英語・簡体字中国語の訳は `sumire/locales/en.json`・`zh_CN.json` にあります。値を差し込む文は `tr("保存 {count}枚").format(count=n)` のように名前付きの欄にし、訳でも同じ欄を使います。

- 文を足したり変えたりしたら、`python -m scripts.i18n_check` で訳のない文を確かめ、両方の訳を足します。`--prune` で、使われなくなった訳を消せます。テスト（`tests/test_i18n.py`）も、訳の不足と欄の食い違いを確かめます。
- 一覧の保存の状態（「未編集 · 保存済み」など）は日本語のまま持ち、表示するときに `tr_state` で区切りごとに訳します。プリセットの既定の名前も、設定には日本語で残します。
- 言語は起動時に一度だけ決まります（設定の `language`、なければ日本語）。画面のモジュールは言語を決めてから読み込みます（`__main__.window_class`）。

ヘルプは `sumire/help_docs/`（日本語）、`help_docs/en/`、`help_docs/zh_CN/` にあり、訳がないページは日本語で表示します。利用者向けの文書の訳は `docs/en/`・`docs/zh-CN/` と、`README.en.md`・`README.zh-CN.md`・`README-Windows.*.txt` です。

## コードの構成

超解像・モザイク・Stealth PNGInfo・重複の判定などの処理の仕組みは、[仕組みの解説](technical/README.md)にまとめています。

画面（`sumire/window.py`）は、機能ごとの mixin を組み合わせて作っています。

- `window.py`：画面と操作の流れ
- `workspace_tabs.py`：作業タブ
- `workbench.py`：一覧・仕分け・タグ・整理の取り消し
- `folders.py`、`folder_features.py`：タブ内のフォルダーと、画像の移動
- `rename_features.py`、`organize.py`、`rename_records.py`：名前の変更（記録の更新も含め、中断から復旧できる手順で行う）
- `batch_features.py`：一覧全体のメタデータ削除とまとめての書き出し
- `file_clipboard.py`：画像ファイルの切り取り・コピー・貼り付け
- `library.py`：一覧・絞り込み・サムネイル
- `canvas.py`：画像の表示と描画
- `imaging.py`：画像の読み込み、隠す処理、編集の履歴
- `editing.py`、`editor_dialogs.py`、`editor_features.py`：切り抜き・回転・色調・超解像
- `export.py`：確認つきの保存
- `backups.py`：上書き前の元画像の一時保存と復元
- `stealth.py`：Stealth PNGInfoの検出と除去
- `metadata.py`、`provenance.py`：メタデータの確認・復元用の保存・復元と、C2PAの読み取り
- `convert.py`、`collage.py`、`collage_canvas.py`：形式変換・容量削減・コラージュ（配置と切り抜きの画面）
- `output_dialogs.py`、`output_features.py`：書き出しの画面と処理
- `projects.py`：編集プロジェクト
- `session.py`、`labels.py`、`masks.py`、`storage.py`、`legacy.py`：管理記録（保存の記録・ラベル・メモ・タグ・マスク）と、旧名のデータの読み込み
- `locking.py`：Sumīre同士の排他
- `analysis.py`、`compare.py`：重複の検出と比較
- `monitor.py`、`workers.py`：フォルダーの監視と、バックグラウンドの処理
- `novelai.py`：NovelAIへ渡す画像の用意
- `onboarding.py`：初回の保存方法の選択
- `settings_dialog.py`、`preferences.py`、`shortcuts.py`、`tag_dialog.py`：設定とタグ（オリジナルタグを含む）の画面
- `text_tool.py`：テキストの配置・描画・書き換え（1回の編集として置き換える）と入力画面
- `app_features.py`：編集プロジェクト・プリセット・管理記録の設定・ヘルプの呼び出し
- `instance.py`、`explorer.py`：多重起動の防止と起動中の画面への受け渡し、Windowsの右クリックへの登録
- `help.py`、`help_docs/`：同梱のヘルプ（言語ごとのフォルダー）
- `i18n.py`、`locales/`：表示言語と訳
- `ui.py`、`theme.py`、`icons.py`：画面の部品・配色・アイコン
- `selftest.py`：配布物の自己検査（`--self-test`）

ファイルはすべて `sumire/` の下にあります。レイヤー、編集履歴の保存、アニメーションには対応していません。
