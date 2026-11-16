# Sumīre — 画像の仕上げ

[![version](https://img.shields.io/badge/version-1.2.0-a7dfc2)](CHANGELOG.md) [![tests](https://github.com/marc2825/Sumire-image-editor/actions/workflows/tests.yml/badge.svg)](https://github.com/marc2825/Sumire-image-editor/actions/workflows/tests.yml) [![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE) [![platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)](README-Windows.txt)


[English](README.en.md) · [简体中文](README.zh-CN.md)

<p align="center"><img src="docs/images/teaser.png" alt="Sumīreの画面" width="820"></p>
<p align="center"><sub>（※ これらはAIによって生成された架空の写真です。）</sub></p>


画像の一部をモザイクやぼかしで隠したり、メタデータを確認・削除したりできる、Windows 11向けのアプリです。大量の画像の仕分けや書き出しにも使えます。画像の処理はすべてPC内で行います。

主にイベントや観光地で大量に撮影した写真や、AIで大量生成したイラストの選別・モザイク入れに使用することを想定しております。

## 基本の流れ

フォルダーを開き、隠したい部分をなぞって、→キーで次の画像へ進みます。加工は自動で保存されます。Enterで、保存して次へ進むこともできます。

保存先（元画像に上書きするか、別フォルダーに保存するか）は、初回の起動時に選びます。

## できること

- **隠す**：モザイク・ぼかし・塗りつぶし。ブラシのほか、長方形・楕円・多角形・投げ縄で範囲を指定できます。消しゴム、元に戻す／やり直す、元画像との比較つき。
- **メタデータを見る・消す**：EXIF・PNGのテキスト・生成プロンプトなどを一覧で確認し、1枚ずつ、またはまとめて削除できます。NovelAIが透明度に埋め込む情報（Stealth PNGInfo）や、ChatGPTなどの画像生成AIが付けるC2PA（コンテンツ認証情報）も消し、残っていないことを確かめます。初期設定では、保存してもメタデータは残ります。
- **あとから戻す**：削除する前のメタデータを残しておき、別名のコピーに戻せます。
- **仕分ける**：採用・保留・不採用のラベル（ラベルごとのフォルダーへの振り分け。付けたときに自動で移すことも可）、自由なタグ、絞り込み、作業タブ、フォルダー間の移動、連番での名前変更、重複の削除、複数枚の比較。
- **書き出す**：形式の変換（PNG・JPEG・WebP・AVIF・BMP・TIFF・GIF）、容量削減、コラージュ。
- **整える**：切り抜き・リサイズ・回転・反転、色調（明るさ・コントラスト・彩度・色相・露出・色温度など）、超解像。
- **共有**：メタデータを除いた画像を、NovelAIのImage2Imageや、ほかのアプリへ渡せます。

表示言語は、日本語・英語・簡体字中国語から選べます（初期画面の右下、または設定 → 表示・取り込み → 表示言語）。

通信はしません。NovelAIを開くときだけ、既定のブラウザーを使います。

## 使い始める

**Windows版**：配布ZIPをすべて展開して `sumire.exe` を起動します。Pythonは要りません。詳しくは[README-Windows.txt](README-Windows.txt)をご覧ください。

**ソースから**：Python 3.12以降を導入し、プロジェクトのフォルダーで以下を実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m sumire
```

**WSL（Ubuntu 24.04）から**：Qtが使用するライブラリーを導入してから、プロジェクトのフォルダーで以下を実行します。

```bash
sudo apt install python3-venv libegl1 libgl1 libfontconfig1 libdbus-1-3 libglib2.0-0 \
  libxkbcommon0 libwayland-client0 libwayland-cursor0 libwayland-egl1 \
  libx11-xcb1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-glx0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m sumire
```

Windowsのフォルダーは `/mnt/c/Users/<name>/Pictures` のように開けます（WSL内のフォルダーより読み書きが遅くなります）。また、設定の「Windows連携」で右クリックに「Sumīreで開く」を加えるには、Windows版のPythonもインストールしておく必要がございます。

Linuxでの実行、テスト、exeの作り方は[開発・ビルド](docs/DEVELOPMENT.md)にあります。

## 注意

- **上書きした元画像は、アプリを終了すると戻せません。** 終了するまでは「⋯ → 上書き前の元画像に戻す」で戻せます。元画像を残したいときは、別フォルダーに保存してください。
- **復元用に残したメタデータは暗号化していません。** プロンプトや位置情報も読める状態で、アプリ専用の場所に保存します。0.4.0以前から使っている場合は画像フォルダー内の `.sumire-index.sqlite3` にあるので、フォルダーごと共有するときは除いてください。
- **モザイクやぼかしでは完全には隠せません。** 確実に隠す部分は、不透明度100%で塗りつぶしてください。
- **「メタデータ：無し」は、対応している種類を調べた結果です。** 未知の方法で埋め込まれた情報や、画像に描かれた文字は調べられません。
- **Sumīreは、AI生成イラストによる著作権の侵害を推進・助長するものではありません。** 画像を使う・公開するときは、**著作権などの権利と、投稿先の規約を守ってください。**

詳しくは[保存とプライバシー](docs/SAVING_AND_PRIVACY.md)をご覧ください。

## 説明書

アプリの「？」かF1で、同じ内容のヘルプをオフラインで読めます。

| 文書 | 内容 |
| --- | --- |
| [機能一覧](sumire/help_docs/FEATURES.md) | できることと、その操作の場所 |
| [はじめての操作](sumire/help_docs/USER_GUIDE.md) | 開く・隠す・保存・仕分けの手順 |
| [ショートカット](sumire/help_docs/SHORTCUTS.md) | キー操作 |
| [メタデータ・復元](sumire/help_docs/METADATA.md) | 削除・保存・復元と、共有時の注意 |
| [よくある質問](sumire/help_docs/FAQ.md) | 困ったときに |
| [操作ガイド](docs/USAGE.md) | 各機能の詳しい説明 |
| [保存とプライバシー](docs/SAVING_AND_PRIVACY.md) | 保存の仕組み、確認していること、限界 |
| [仕組みの解説](docs/technical/README.md) | 超解像・モザイク・Stealth PNGInfo・重複の判定の仕組みと参考資料 |
| [開発・ビルド](docs/DEVELOPMENT.md) | ソースからの実行、テスト、exeの作成 |
| [動作確認](docs/VALIDATION_SUMMARY.md) | 確認済みの環境と未確認の項目 |
| [変更履歴](CHANGELOG.md) / [開発計画](ROADMAP.md) | 版ごとの変更と今後の予定 |
| [セキュリティ](SECURITY.md) / [不具合の報告](CONTRIBUTING.md) | 報告の方法 |

## ライセンス

Sumīreのコードは[MIT License](LICENSE)です。改変・再配布・商用利用ができます。

Windows版に入っているPython・Qt・PySide6・Pillow・Noto Sans JPなどは、それぞれのライセンス（QtとPySide6はLGPLv3、Noto Sans JPはSIL Open Font License 1.1など）に従います。一覧は[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)、Qtの差し替え方法とソースの入手方法は[QT_REPLACEMENT.md](QT_REPLACEMENT.md)にあります。


※ このREADMEを含め、ドキュメントの大半はAIが生成した文章をもとにしています。
