# Pixso (px)

Pixso 是一个基于 Python 开发的媒体文件（图片/视频）元数据处理与归档工具。它能够自动提取媒体文件的拍摄时间、设备型号等元数据，并将文件重命名并组织到规范的目录结构中。

## 核心功能

- **自动化归档**：根据元数据将文件整理至 `archive/YYYYMM/[p|v|misc]` 或 `snapshot/YYYYMM/`。
- **标准化命名**：将文件重命名为 `YYYYMMDDHHMMSS_设备名_原始名.扩展名`，确保文件名唯一且包含关键信息。
- **深度元数据提取**：
  - **图片**：解析 EXIF 数据（支持 JPG, RAW 等）。
  - **视频**：使用 FFmpeg 解析视频元数据（支持 MOV, MP4, MKV 等）。
  - **回退机制**：如果元数据缺失，尝试从文件名解析时间戳，或回退至文件创建时间。
- **智能去重**：通过 SHA-256 哈希值检测完全重复的文件，支持自动删除或跳过。
- **冲突处理**：如果目标路径存在同名但内容不同的文件，自动添加编号避免覆盖。
- **交互式体验**：基于 `rich` 提供美观的进度条、计划预览表和统计信息。
- **统计功能**：快速查看已归档文件的按月分布情况。

## 安装

项目推荐使用 [uv](https://github.com/astral-sh/uv) 进行管理。

```bash
# 克隆仓库
git clone <repository-url>
cd pixso

# 安装依赖并安装工具
uv pip install .
```

安装完成后，你可以使用 `px` 命令。

### 依赖项

- Python >= 3.12
- **FFmpeg**: 视频元数据提取依赖系统安装的 `ffmpeg`。

## 配置

Pixso 需要知道归档的目标目录。请设置 `PIXSO_TARGET_DIR` 环境变量：

```bash
export PIXSO_TARGET_DIR="/path/to/your/photo/archive"
```

## 使用方法

### 1. 处理并归档文件

使用 `process` 命令扫描目录或单个文件。

```bash
# 扫描并归档一个目录下的所有媒体文件
px process --dir ./my_photos

# 预览操作（Dry-run），不实际移动文件
px process --dir ./my_photos --dry-run

# 处理单个文件
px process --file photo.jpg

# 自动删除重复的源文件
px process --dir ./my_photos --delete-duplicates

# 跳过确认直接执行
px process --dir ./my_photos --yes
```

### 2. 查看归档统计

使用 `stats` 命令查看目标目录中的文件统计。

```bash
# 查看所有月份统计
px stats

# 查看指定月份统计
px stats 202405
```

## 目录结构说明

归档后的目录结构如下：

```text
TARGET_DIR/
├── archive/              # 包含准确拍摄时间的文件
│   └── YYYYMM/           # 按年月组织
│       ├── p/            # 图片 (Photos)
│       ├── v/            # 视频 (Videos)
│       └── misc/         # 其他文件
├── snapshot/             # 缺失拍摄时间、使用文件创建时间归档的文件
│   └── YYYYMM/
│       └── ...
└── .pixso_logs/          # 执行日志 (JSONL 格式)
```

## 开发

本项目使用 `typer` 构建 CLI，`rich` 负责 UI，`exifread` 和 `ffmpeg-python` 处理元数据。

```bash
# 运行 lint
uv run ruff check .

# 格式化代码
uv run ruff format .
```
