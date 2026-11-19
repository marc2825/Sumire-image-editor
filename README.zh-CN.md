# Sumīre — 图像修整

[![version](https://img.shields.io/badge/version-1.4.0-a7dfc2)](CHANGELOG.md) [![tests](https://github.com/marc2825/Sumire-image-editor/actions/workflows/tests.yml/badge.svg)](https://github.com/marc2825/Sumire-image-editor/actions/workflows/tests.yml) [![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE) [![platform](https://img.shields.io/badge/platform-Windows%2011-lightgrey)](README-Windows.zh-CN.txt)

[日本語](README.md) · [English](README.en.md) · 简体中文

<p align="center"><img src="docs/images/teaser.png" alt="Sumīre 界面" width="820"></p>
<p align="center"><sub>（※ 这些是由 AI 生成的虚构照片。）</sub></p>

Sumīre 是一款适用于 Windows 11 的应用，可以用马赛克或模糊隐藏图像的一部分，并查看、删除图像的元数据。也可用于大量图像的分拣和导出。所有图像处理都在本机进行。

主要用于对在活动或旅游景点大量拍摄的照片、以及用 AI 批量生成的插画进行筛选和打马赛克。

## 基本流程

1. 打开文件夹
2. 涂抹要隐藏的部分（自动保存）
3. 按 → 键前往下一张图像（按 Enter 保存并前往下一张）

覆盖原图还是保存到其他文件夹，在首次启动时选择。

## 功能

- 用马赛克、模糊、填充隐藏（画笔、矩形、椭圆、多边形、套索）
- 添加文字（可选择字体、大小和颜色；添加后也可移动、旋转、缩放和重写）
- 查看、删除、恢复元数据（也支持 NovelAI 的 Stealth PNGInfo 和 ChatGPT 等添加的 C2PA）
- 用采用、待定、不采用标签和标记分拣（“需修正”等常用标记可用按钮添加），按标签分入文件夹
- 工作标签页、文件夹间移动、编号重命名、删除重复、多张比较
- 转换格式、压缩体积、拼贴
- 裁剪、旋转、调整色调、超分辨率放大
- 将不含元数据的图像交给 NovelAI 或其他应用

界面支持日语、英语和简体中文。本应用不进行网络通信，仅在使用 NovelAI 时打开默认浏览器。

## 开始使用

### Windows 版

解压完整的发行 ZIP，运行 `sumire.exe`。无需 Python。详见 [README-Windows.zh-CN.txt](README-Windows.zh-CN.txt)。

### 从源代码运行

安装 Python 3.12 或更高版本，在项目文件夹中执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m sumire
```

### WSL（Ubuntu 24.04）

先安装 Qt 所需的库，再执行：

```bash
sudo apt install python3-venv libegl1 libgl1 libfontconfig1 libdbus-1-3 libglib2.0-0 \
  libxkbcommon0 libwayland-client0 libwayland-cursor0 libwayland-egl1 \
  libx11-xcb1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-glx0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m sumire
```

- Windows 的文件夹可通过 `/mnt/c/Users/<name>/Pictures` 打开（读写比 WSL 内慢）。
- 要把“用 Sumīre 打开”加入右键菜单，还需安装 Windows 版 Python。

测试的运行和 exe 的制作方法见[开发与构建](docs/DEVELOPMENT.md)（日语）。

## 注意事项

- 覆盖保存的原图在应用退出后无法恢复。如需保留原图，请保存到其他文件夹。
- 默认情况下，保存时会保留元数据。如需删除，请使用“删除元数据”。
- 为恢复而保留的元数据没有加密（提示词和位置信息仍可读取）。
- 马赛克和模糊无法完全隐藏。需要确实隐藏的部分，请使用不透明度 100% 的填充。
- “元数据：无”是对所支持类型的检查结果。以未知方式嵌入的信息或图像中绘制的文字无法检查。
- Sumīre 无意推动或助长利用 AI 生成插画侵犯著作权的行为。使用或发布图像时，请遵守著作权等权利以及发布平台的规定。

详见[保存与隐私](docs/zh-CN/SAVING_AND_PRIVACY.md)。

## 文档

在应用中按“？”或 F1，可离线阅读以下帮助：

- [功能一览](sumire/help_docs/zh_CN/FEATURES.md)
- [入门操作](sumire/help_docs/zh_CN/USER_GUIDE.md)
- [快捷键](sumire/help_docs/zh_CN/SHORTCUTS.md)
- [元数据与恢复](sumire/help_docs/zh_CN/METADATA.md)
- [常见问题](sumire/help_docs/zh_CN/FAQ.md)

更多资料：

- [操作指南](docs/zh-CN/USAGE.md)：各功能的详细说明
- [保存与隐私](docs/zh-CN/SAVING_AND_PRIVACY.md)：保存的机制、检查的内容和限制
- [问题报告与需求](docs/zh-CN/CONTRIBUTING.md) · [安全](docs/zh-CN/SECURITY.md)

更新记录、开发计划、开发说明和原理说明为日语。

## 许可证

Sumīre 的代码采用 [MIT License](LICENSE)，可以修改、再发布和商业使用。

Windows 版中的 Python、Qt、PySide6、Pillow、Noto Sans JP 等遵循各自的许可证（Qt 和 PySide6 为 LGPLv3，Noto Sans JP 为 SIL Open Font License 1.1 等）。

- 列表：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)（日语）
- Qt 的替换方法和源代码获取方法：[QT_REPLACEMENT.md](QT_REPLACEMENT.md)

※ 包括本 README 在内，大部分文档以 AI 生成的文字为基础。
