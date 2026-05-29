# Pixso (px)

Pixso 是一个基于 Python 开发的媒体文件（图片/视频）元数据处理与归档工具。它能够自动提取媒体文件的拍摄时间、设备型号等元数据，并将文件重命名并组织到规范的目录结构中。

## 核心功能

- **自动化归档**：根据元数据将文件整理至 `archive/YYYYMM/[p|v|misc]`。
- **标准化命名**：将文件重命名为 `YYYYMMDDHHMMSS_设备简写_Hash8.扩展名`，确保文件名唯一且包含关键信息。
- **深度元数据提取**：
  - **图片**：解析 EXIF 数据（支持 JPG, PNG, HEIF, RAW 等）。
  - **视频**：使用 FFmpeg 解析视频元数据（支持 MOV, MP4, MKV 等）。
  - **回退机制**：如果元数据缺失，尝试从文件名解析时间戳，或回退至文件创建时间。
- **智能去重**：通过 **Hash8** (基于 BLAKE2b 的 8 位内容哈希) 检测完全重复的文件。
- **冲突处理**：如果目标路径存在同名但内容不同的文件，自动通过 Hash8 区分，避免覆盖。
- **归档库整理**：`sync` 命令可快速将现有归档库应用到最新的命名规范。
- **交互式体验**：基于 `rich` 提供美观的进度条、计划预览表和统计信息。

## 安装

项目推荐使用 [uv](https://github.com/astral-sh/uv) 进行管理。

```bash
# 克隆仓库
git clone <repository-url>
cd pixso

# 安装依赖
uv sync
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

你也可以通过环境变量自定义支持的扩展名或设备映射：
- `PIXSO_IMAGES`: 自定义图片扩展名（逗号分隔）
- `PIXSO_VIDEOS`: 自定义视频扩展名（逗号分隔）
- `PIXSO_DEVICE_MAP`: 设备型号到简写的映射 (JSON 或 `key:val,key:val` 格式)

## 使用方法

### 1. 导入或整理媒体文件

使用 `sync` 命令扫描目录或单个文件。它会自动判断是导入外部文件还是整理库内文件。

```bash
# 扫描并同步一个目录下的所有媒体文件
px sync ./my_photos

# 预览操作（Dry-run），不实际移动文件
px sync ./my_photos --dry-run

# 直接删除重复文件 (默认是移入 duplicates 目录)
px sync ./my_photos --delete-duplicates

# 跳过确认直接执行
px sync ./my_photos --yes
```

### 2. 按月份同步归档库

使用 `sync` 命令将归档库中的文件按最新规范重命名。

```bash
# 整理归档库中的特定目录
px sync archive/202405

# 整理特定月份的所有文件
px sync -m 202405

# 仅整理特定月份的照片
px sync -m 202405 -p

# 仅整理特定月份的视频
px sync -m 202405 -v
```

### 3. 查看文件信息

使用 `info` 命令查看文件的元数据解析结果与预期归档路径。

```bash
px info photo.jpg
```

### 4. 查看归档统计

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
├── duplicates/           # 导入过程中发现的重复文件
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
