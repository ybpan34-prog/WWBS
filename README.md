# wwbs

## Remote Updates

The packaged application can check the latest GitHub Release from:

`https://github.com/ybpan34-prog/WWBS`

Each Release must include an asset named `wwbs-exe.zip`. Users can click `检查更新` in the application; when a newer tag is available, wwbs downloads the asset, replaces the current packaged files, and restarts.

Recommended release flow:

1. Increase `APP_VERSION` in `app.py`.
2. Rebuild `wwbs-exe.zip` with PyInstaller.
3. Create a GitHub Release whose tag is the new version, such as `v1.4`.
4. Upload the rebuilt `wwbs-exe.zip` as a Release asset.

wwbs 是一个 Windows 桌面自动点击工具，面向鸣潮 PC 客户端窗口。它通过模板图像识别按钮位置，并按配置自动点击。

当前默认任务会先点击 `menu1.png`，然后从 `menu2.png` 到 `menu99.png` 按顺序循环识别点击，直到你手动停止。

## 功能

- 识别鸣潮 PC 客户端窗口。
- 根据 `templates/` 里的模板图片自动找按钮。
- 支持循环任务，手动开始、手动停止。
- 支持每个模板单独设置点击偏移。
- 支持制作、刷新、删除模板。
- 可显示游戏窗口预览和运行日志。

## 环境要求

- Windows
- Python 3.10 或更高版本

安装依赖：

```powershell
pip install -r requirements.txt
```

## 启动

双击：

```text
启动 wwbs.bat
```

或在项目目录运行：

```powershell
python app.py
```

## 使用流程

1. 打开鸣潮 PC 客户端，并停在任务开始画面。
2. 打开 wwbs。
3. 点 `检测游戏窗口`。
4. 点 `开始执行`。
5. 需要结束时点 `停止当前任务`。

`先预演一次` 只识别、不点击；真实点击请点 `开始执行`。

## 默认循环逻辑

默认任务名为 `菜单模板循环点击`：

1. 先识别并点击 `menu1.png`。
2. 然后进入循环：
   `menu2.png -> menu3.png -> ... -> menu99.png`
3. 到 `menu99.png` 后回到 `menu2.png`。
4. 一直循环，直到手动停止。

当前每步点击后的等待时间在 `weekly_tasks.json` 里配置为 `0.15` 秒。

## 模板文件

模板放在：

```text
templates/
```

模板命名示例：

```text
menu1.png
menu2.png
menu3.png
...
menu99.png
```

模板制作建议：

- 尽量包含按钮文字、图标、边框等明显特征。
- 不要只截纯色背景。
- 如果识别错位置，重新截更有辨识度的区域。

## 配置

主要配置文件：

```text
weekly_tasks.json
```

常用字段：

- `template`：单个模板名。
- `templates`：循环模板列表。
- `seconds`：点击后等待秒数。
- `threshold`：识别阈值。
- `offset_x` / `offset_y`：点击点偏移。
- `template_offsets`：给某个模板单独设置偏移。

## 发布给朋友

最简单的方式：发送 `wwbs-exe.zip`。

朋友使用方式：

1. 解压 `wwbs-exe.zip`。
2. 打开解压后的文件夹。
3. 双击 `wwbs.exe`。

如果发送源码版，则需要把以下内容一起发给朋友：

- `app.py`
- `windows_client.py`
- `image_matcher.py`
- `weekly_tasks.json`
- `requirements.txt`
- `templates/`
- `wwbs.ico`
- `wwbs_icon.png`
- `启动 wwbs.bat`

运行缓存、调试图、截图缓存不需要发送。

## GitHub 上传建议

本项目已包含 `.gitignore`，会自动忽略：

- `debug/`
- `__pycache__/`
- `_runtime_screenshot.png`
- `_target_preview.png`
- `_template_source.png`

如果电脑已安装 Git，可执行：

```powershell
git init
git add .
git commit -m "Initial release"
git branch -M main
git remote add origin https://github.com/<你的用户名>/wwbs.git
git push -u origin main
```
