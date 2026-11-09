# 墨签 InkSign

墨签是一款 Windows 桌面 PDF 批注工具。可以在 PDF 上手写、用荧光笔标记、擦除笔迹，以及保存并重复使用手写签名和签名缩写。编辑完成后，可以另存为新的 PDF。

导出时，批注与手写签名作为图像叠加到页面上。手写签名用于显示笔迹，证书数字签名需使用支持该功能的 PDF 工具。

## 从源码运行

在 Windows 上安装 Python 3.12，然后在项目根目录运行以下 PowerShell 命令。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

程序内可以打开 PDF，也可以把文件路径作为参数传给 `main.py`。保存的手写签名存放在 `%APPDATA%\PDFAnnotator\signatures`。

## 测试和打包

现有冒烟测试会生成示例 PDF，检查页面渲染、笔迹、签名、撤销和导出等功能。

```powershell
.\.venv\Scripts\python.exe tests\headless_check.py
```

在 Windows 上打包单文件程序。

```powershell
.\.venv\Scripts\python.exe -m pip install PyInstaller==6.21.0
.\.venv\Scripts\python.exe -m PyInstaller '墨签InkSign.spec'
```

生成的程序位于 `dist\墨签InkSign.exe`。仓库已包含打包所需的图标。若要重新生成图标，可以安装 Pillow 并运行 `assets\make_logo.py`，脚本使用 Windows 上的 Arial Black 字体。

## 许可证

墨签源码采用 [GNU Affero General Public License v3.0](LICENSE)。PDF 处理使用 [PyMuPDF](https://github.com/pymupdf/PyMuPDF)，界面使用 [PySide6](https://doc.qt.io/qtforpython-6/)。这些依赖各自适用其上游许可证。
