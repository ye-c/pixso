import os
from pathlib import Path
from typing import Optional, List

import typer
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
from rich.table import Table
from rich.prompt import Confirm

from .exif import PixExif
from .processor import PixProcessor

app = typer.Typer(help="图片/视频元数据处理与归档工具", no_args_is_help=True)
console = Console()


def get_files(path: Path) -> List[Path]:
    """递归获取目录下所有支持的文件"""
    files = []
    if path.is_file():
        if not path.name.startswith("._") and not path.name.startswith("."):
            files.append(path)
    elif path.is_dir():
        extensions = PixExif._IMAGES | PixExif._VIDEOS
        for ext in extensions:
            # 同时支持大小写后缀
            for f in path.rglob(f"*{ext}"):
                if not f.name.startswith("._") and not f.name.startswith(".") and "duplicates" not in f.parts:
                    files.append(f)
            for f in path.rglob(f"*{ext.upper()}"):
                if not f.name.startswith("._") and not f.name.startswith(".") and "duplicates" not in f.parts:
                    files.append(f)
    return files


@app.command(name="import")
def import_cmd(
    path: str = typer.Argument(..., help="要导入的文件或目录路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览操作，不实际执行"),
    yes: bool = typer.Option(False, "-y", "--yes", help="跳过确认，直接执行"),
    delete_source: bool = typer.Option(
        False, "--delete-source", help="如果是重复文件，直接从源位置删除而不是移入 duplicates 目录"
    ),
):
    """导入并归档媒体文件"""
    target_dir = os.environ.get("PIXSO_TARGET_DIR")
    if not target_dir:
        console.print("[red]错误: 必须设置 PIXSO_TARGET_DIR 环境变量[/red]")
        raise typer.Exit(1)

    p = Path(path)
    if not p.exists():
        console.print(f"[red]错误: 路径不存在: {path}[/red]")
        raise typer.Exit(1)

    files_to_process = get_files(p)

    if not files_to_process:
        console.print("没有找到支持的图片或视频文件。")
        raise typer.Exit(0)

    processor = PixProcessor(target_dir, delete_duplicates=delete_source)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[bold green]正在扫描和解析文件: ", total=len(files_to_process)
        )
        plan = processor.plan_moves(
            files_to_process, progress_callback=lambda: progress.advance(task)
        )

    # 打印计划表格
    table = Table(title="文件处理计划")
    table.add_column("源文件", style="cyan", no_wrap=False, overflow="fold")
    table.add_column("目标文件", style="magenta", no_wrap=False, overflow="fold")
    table.add_column("状态/操作", style="green")

    for item in plan:
        target_str = str(item["target"]) if item["target"] else "N/A"
        status_str = item["status"]
        if "Error" in status_str:
            status_str = f"[red]{status_str}[/red]"
        elif "Skip" in status_str:
            status_str = f"[yellow]{status_str}[/yellow]"
        elif "Delete" in status_str:
            status_str = f"[bold red]{status_str}[/bold red]"

        table.add_row(str(item["source"]), target_str, status_str)

    console.print(table)

    # 统计
    duplicates = sum(1 for item in plan if "Duplicate" in item["status"])
    errors = sum(1 for item in plan if "Error" in item["status"])
    moves = sum(1 for item in plan if item["status"] == "Move")

    console.print(
        f"\n[bold]统计信息:[/bold] 待归档: {moves} | 重复: {duplicates} | 错误: {errors}\n"
    )

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件操作。[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        if not Confirm.ask("确认执行以上文件操作？"):
            raise typer.Abort()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]正在执行文件操作: ", total=len(plan))
        for _ in processor.execute_plan(plan):
            progress.advance(task)

    console.print("\n[bold green]执行完成！[/bold green]")


@app.command()
def sync(
    path: Optional[str] = typer.Argument(None, help="要整理的特定目录路径。如果不提供，则整理整个 PIXSO_TARGET_DIR"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览操作，不实际执行"),
    yes: bool = typer.Option(False, "-y", "--yes", help="跳过确认，直接执行"),
):
    """整理并重建归档库（应用新命名规范并清理重复文件）"""
    target_dir = os.environ.get("PIXSO_TARGET_DIR")
    if not target_dir:
        console.print("[red]错误: 必须设置 PIXSO_TARGET_DIR 环境变量[/red]")
        raise typer.Exit(1)

    scan_path = Path(path) if path else Path(target_dir)
    if not scan_path.exists():
        console.print(f"[red]错误: 路径不存在: {scan_path}[/red]")
        raise typer.Exit(1)

    if not path and not yes:
        if not Confirm.ask(f"[bold red]警告: 将重新整理整个归档库 ({target_dir})，是否继续？[/bold red]"):
            raise typer.Abort()

    files_to_process = get_files(scan_path)
    if not files_to_process:
        console.print("没有找到需要整理的文件。")
        raise typer.Exit(0)

    # sync 模式下，重复文件默认移入 duplicates
    processor = PixProcessor(target_dir, delete_duplicates=False)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[bold green]正在分析归档库: ", total=len(files_to_process))
        plan = processor.plan_moves(
            files_to_process, progress_callback=lambda: progress.advance(task)
        )

    # 过滤掉不需要操作的文件 (Already Organized)
    active_plan = [item for item in plan if item["status"] != "Skip (Already Organized)"]

    if not active_plan:
        console.print("[green]归档库已经是最新规范，无需整理。[/green]")
        raise typer.Exit(0)

    # 打印计划
    table = Table(title="归档库整理计划")
    table.add_column("当前路径", style="cyan")
    table.add_column("新路径", style="magenta")
    table.add_column("操作", style="green")

    for item in active_plan[:100]:  # 最多显示100行
        table.add_row(str(item["source"].relative_to(target_dir)),
                      str(item["target"].relative_to(target_dir)) if item["target"] else "N/A",
                      item["status"])

    if len(active_plan) > 100:
        table.add_row("...", "...", f"还有 {len(active_plan)-100} 个文件未列出")

    console.print(table)
    console.print(f"\n[bold]共发现 {len(active_plan)} 个文件需要整理。[/bold]")

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件操作。[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        if not Confirm.ask("确认执行整理操作？"):
            raise typer.Abort()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        MofNCompleteColumn(),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]正在重构归档库: ", total=len(active_plan))
        for _ in processor.execute_plan(active_plan):
            progress.advance(task)

    console.print("\n[bold green]整理完成！[/bold green]")


@app.command()
def info(
    file: str = typer.Argument(..., help="要查看的文件路径"),
    raw: bool = typer.Option(False, "--raw", help="显示完整的原始元数据"),
):
    """查看文件的元数据解析结果与预期归档路径"""
    p = Path(file)
    if not p.is_file():
        console.print(f"[red]错误: 文件不存在: {file}[/red]")
        raise typer.Exit(1)

    try:
        exif = PixExif(p)
        from .utils import get_hash8

        table = Table(title=f"文件信息: {p.name}")
        table.add_column("属性", style="cyan")
        table.add_column("值", style="magenta")

        table.add_row("时间戳", exif._meta.timestamp)
        table.add_row("设备 (原始)", exif._meta.device)
        table.add_row("设备 (简短)", exif.get_device_short())
        table.add_row("Hash8", get_hash8(p))
        table.add_row("是否未知时间", str(exif._meta.is_unknown_time))
        table.add_row("最终文件名", exif.rename())

        console.print(table)

        if raw and exif.raw_tags:
            raw_table = Table(title="原始元数据")
            raw_table.add_column("Tag", style="blue")
            raw_table.add_column("Value", style="white")
            for k in sorted(exif.raw_tags.keys()):
                val = str(exif.raw_tags[k])
                if len(val) > 80: val = val[:77] + "..."
                raw_table.add_row(k, val)
            console.print(raw_table)

    except Exception as e:
        console.print(f"[red]解析失败: {e}[/red]")
        raise typer.Exit(1)


def main():
    app()


if __name__ == "__main__":
    main()
