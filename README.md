# Pixso (px)

Pixso 是一个基于 Python 开发的媒体文件（图片/视频）元数据处理与归档工具。它能够自动提取媒体文件的拍摄时间、设备型号等元数据，并将文件重命名并组织到规范的目录结构中。

## 核心功能

- **全能同步 (Sync)**：一个命令搞定所有场景。既能从外部目录**导入**新照片，也能对现有归档库进行**重命名整理**或**迁移**。
- **标准化命名**：将文件重命名为 `YYYYMMDDHHMMSS_设备简写_Hash8.扩展名`，确保文件名唯一且包含关键信息。
- **双重归档体系**：
  - `archive/YYYYMM/`：基于准确拍摄时间（EXIF/视频元数据）组织。
  - `unknown/YYYYMM/`：对于缺失元数据的文件，基于文件系统时间组织，确保库内无杂物。
- **深度元数据提取**：
  - **图片**：解析 EXIF 数据（支持 JPG, PNG, HEIF, RAW 等），支持复杂的本地化时间格式。
  - **视频**：使用 FFmpeg 解析视频元数据（支持 MOV, MP4, MKV 等）。
  - **回退机制**：如果元数据缺失，尝试从文件名解析时间戳，或回退至文件修改时间。
- **智能去重与安全**：
  - 通过 **Hash8** (基于 BLAKE2b 的内容哈希) 精确识别重复。
  - 重复文件默认移至 `duplicates/` 目录，支持 `--delete-duplicates` 直接删除。
  - 自动处理同名但内容不同的冲突，通过 Hash8 后缀区分，绝不覆盖。
- **交互式体验**：基于 `rich` 提供美观的执行计划预览、进度条和分类统计。

## 安装

项目推荐使用 [uv](https://github.com/astral-sh/uv) 进行管理。

```bash
# 克隆仓库
git clone <repository-url>
cd pixso

# 安装依赖
uv sync
```

安装完成后，你可以使用 `px` 命令（如果已将 uv bin 目录加入 PATH）。

### 依赖项

- **Python >= 3.12**
- **FFmpeg**: 视频元数据提取依赖系统安装的 `ffmpeg` 命令行工具。

## 配置

Pixso 必须知道归档的目标目录。请设置 `PIXSO_TARGET_DIR` 环境变量：

```bash
export PIXSO_TARGET_DIR="/path/to/your/photo/archive"
```

可选自定义配置：
- `PIXSO_DEVICE_MAP`: 设备型号到简写的映射 (例如 `{"iPhone 15 Pro": "IP15P"}`)。
- `PIXSO_IMAGES` / `PIXSO_VIDEOS`: 自定义支持的扩展名。

## 使用方法

### 1. 同步与导入 (sync)

`sync` 是最常用的命令。它会自动识别路径是在库内还是库外。

```bash
# 导入外部照片到归档库
px sync ~/Downloads/trip_photos

# 整理归档库中的某个特定月份（修复命名规范或重新组织）
px sync archive/202405

# 仅处理视频，并跳过交互确认
px sync ~/Downloads --video --yes

# 预览模式：只看计划，不移动任何文件
px sync ~/Downloads --dry-run

# 发现重复文件直接删除，不移动到 duplicates 目录
px sync ~/Downloads --delete-duplicates
```

### 2. 按月份快速整理

```bash
# 整理归档库中 2024年5月 的所有文件（包括 archive 和 unknown）
px sync --month 202405
```

### 3. 查看文件信息 (info)

查看 Pixso 如何解析某个文件，以及它预期的归档路径。

```bash
px info test.jpg
```

### 4. 统计信息 (stats)

查看归档库的整体规模和各月份分布。

```bash
px stats
```

## 目录结构说明

归档后的目录结构如下：

```text
TARGET_DIR/
├── archive/              # 包含准确拍摄时间的文件
│   └── YYYYMM/           # 按年月组织 (例如 202405)
│       ├── p/            # 图片 (Photos)
│       ├── v/            # 视频 (Videos)
│       └── misc/         # 其他识别出的媒体
├── unknown/              # 缺失拍摄时间，按文件修改时间组织
│   └── YYYYMM/           # 结构与 archive 一致
│       ├── p/
│       ├── v/
│       └── misc/
├── duplicates/           # 同步过程中识别出的重复文件
└── .pixso_logs/          # 执行日志
```

## 开发

```bash
# 运行 lint 与格式化
uv run ruff check .
uv run ruff format .
```
