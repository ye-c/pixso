import hashlib
import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from .config import config

console = Console()


class Category(str, Enum):
    ARCHIVE = "archive"
    UNKNOWN = "unknown"


class MediaType(str, Enum):
    PHOTO = "p"
    VIDEO = "v"
    MISC = "misc"


class ProcessStatus(str, Enum):
    MOVE = "Move"
    SKIP_ALREADY_ORGANIZED = "Skip (Already Organized)"
    SKIP_DUPLICATE = "Skip (Duplicate)"
    DELETE_DUPLICATE = "Delete (Duplicate)"
    ERROR = "Error"
    RENAME = "Rename"  # 虽然目前不再使用数字重命名，但保留作为状态扩展

    def __str__(self):
        return self.value

    def format_rich(self, extra: str = "") -> str:
        """返回带 Rich 颜色格式的字符串"""
        status_str = self.value
        if extra:
            status_str = f"{status_str} ({extra})"

        if self == ProcessStatus.ERROR:
            return f"[red]{status_str}[/red]"
        if "Skip" in self.value:
            return f"[yellow]{status_str}[/yellow]"
        if self == ProcessStatus.DELETE_DUPLICATE:
            return f"[bold red]{status_str}[/bold red]"
        if self == ProcessStatus.MOVE or "Move" in status_str:
            return f"[green]{status_str}[/green]"
        return status_str


def get_target_dir() -> Path:
    """获取并验证归档根目录"""
    target_dir = os.environ.get("PIXSO_TARGET_DIR")
    if not target_dir:
        console.print("[red]错误: 必须设置 PIXSO_TARGET_DIR 环境变量[/red]")
        import typer

        raise typer.Exit(1)
    return Path(target_dir)


def get_progress(description: str, total: int) -> Progress:
    """统一的进度条配置"""
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    progress.add_task(description, total=total)
    return progress


def get_display_path(path: Path, base_dirs: List[Path] = None) -> str:
    """获取美化的显示路径，尝试使其相对于 base_dirs 或当前目录"""
    if base_dirs is None:
        base_dirs = [Path.cwd()]

    for base in base_dirs:
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def safe_resolve(path: Path) -> Path:
    """安全地解析路径，防止因权限或符号链接问题抛出异常"""
    try:
        return path.resolve()
    except Exception:
        return path.absolute()


def get_files(path: Path) -> List[Path]:
    """递归获取目录下所有支持的文件 (单次遍历)"""
    files = []
    if path.is_file():
        if not path.name.startswith((".", "._")):
            files.append(path)
    elif path.is_dir():
        for f in path.rglob("*"):
            # 只有当 duplicates 是相对于搜索根路径的子目录时才过滤
            # 这样如果用户显式指定了 duplicates 目录，则可以正常处理其中的文件
            try:
                rel_parts = f.relative_to(path).parts
            except ValueError:
                rel_parts = f.parts

            if (
                f.is_file()
                and f.suffix.lower() in config.ALL_EXTENSIONS
                and not f.name.startswith((".", "._"))
                and "duplicates" not in rel_parts
            ):
                files.append(f)
    return files


def get_file_hash(path: Path, chunk_size: int = 8192) -> str:
    """计算文件的 SHA-256 哈希值（分块读取以节省内存）"""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def get_hash8(path: Path) -> str:
    """计算文件的 SHA-256 哈希值并返回前 8 位"""
    return get_file_hash(path)[:8]


def log_action(log_dir: Path, log_file: Path, source: Path, target: Path, status: str):
    """将执行记录追加到日志文件"""
    log_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now().isoformat(),
        "source": str(source),
        "target": str(target),
        "status": status,
    }

    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
