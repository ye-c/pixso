import os
from pathlib import Path
from typing import Optional

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

from .exif import PixExif
from .processor import PixProcessor

app = typer.Typer(help="图片/视频元数据处理与归档工具")
console = Console()


@app.command()
def process(
    file: Optional[str] = typer.Option(None, "-f", "--file", help="扫描单个文件"),
    directory: Optional[str] = typer.Option(None, "-d", "--dir", help="扫描目录"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览操作，不实际移动文件"),
    yes: bool = typer.Option(False, "-y", "--yes", help="跳过确认，直接执行"),
    delete_duplicates: bool = typer.Option(
        False, "--delete-duplicates", help="删除完全重复的源文件"
    ),
):
    """处理并归档媒体文件"""
    if not file and not directory:
        typer.echo("错误: 必须提供 -f/--file 或 -d/--dir 参数", err=True)
        raise typer.Exit(1)

    if file and directory:
        typer.echo("错误: 不能同时提供 -f/--file 和 -d/--dir 参数", err=True)
        raise typer.Exit(1)

    target_dir = os.environ.get("PIXSO_TARGET_DIR")
    if not target_dir:
        typer.echo("错误: 必须设置 PIXSO_TARGET_DIR 环境变量", err=True)
        raise typer.Exit(1)

    files_to_process = []
    if file:
        p = Path(file)
        if p.is_file():
            files_to_process.append(p)
        else:
            typer.echo(f"错误: 文件不存在: {file}", err=True)
            raise typer.Exit(1)
    elif directory:
        p = Path(directory)
        if p.is_dir():
            # 收集支持的图片和视频文件
            extensions = PixExif._IMAGES | PixExif._VIDEOS
            for ext in extensions:
                for f in p.rglob(f"*{ext}"):
                    if not f.name.startswith("._") and not f.name.startswith("."):
                        files_to_process.append(f)
                for f in p.rglob(f"*{ext.upper()}"):
                    if not f.name.startswith("._") and not f.name.startswith("."):
                        files_to_process.append(f)
        else:
            typer.echo(f"错误: 目录不存在: {directory}", err=True)
            raise typer.Exit(1)

    if not files_to_process:
        typer.echo("没有找到支持的图片或视频文件。")
        raise typer.Exit(0)

    processor = PixProcessor(target_dir, delete_duplicates=delete_duplicates)

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
        elif "Rename" in status_str:
            status_str = f"[blue]{status_str}[/blue]"
        elif "Delete" in status_str:
            status_str = f"[bold red]{status_str}[/bold red]"

        table.add_row(str(item["source"]), target_str, status_str)

    console.print(table)

    # 打印统计数据
    photos = sum(1 for item in plan if item.get("exif") and item["exif"].is_image)
    videos = sum(1 for item in plan if item.get("exif") and item["exif"].is_video)
    duplicates = sum(1 for item in plan if "Duplicate" in item["status"])
    errors = sum(1 for item in plan if "Error" in item["status"])

    console.print(
        f"\n[bold]统计信息:[/bold] 照片: {photos} | 视频: {videos} | 重复文件: {duplicates} | 错误: {errors}\n"
    )

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件操作。[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        typer.confirm("确认执行以上文件操作？", abort=True)

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
def exif(file: str = typer.Argument(..., help="要查看的文件路径")):
    """查看文件的元数据解析结果"""
    p = Path(file)
    if not p.is_file():
        typer.echo(f"错误: 文件不存在: {file}", err=True)
        raise typer.Exit(1)

    try:
        exif = PixExif(p)
        table = Table(title=f"元数据解析结果: {p.name}")
        table.add_column("属性", style="cyan")
        table.add_column("值", style="magenta")

        table.add_row("原始名称", exif._meta.original_name)
        table.add_row("后缀", exif._meta.suffix)
        table.add_row("时间戳 (YYYYMMDDHHMMSS)", exif._meta.timestamp)
        table.add_row("设备型号", exif._meta.device)
        table.add_row("是否回退时间", str(exif._meta.is_fallback_time))
        table.add_row("图片", str(exif.is_image))
        table.add_row("视频", str(exif.is_video))
        table.add_row("最终文件名", exif.rename())

        console.print(table)
    except Exception as e:
        typer.echo(f"解析失败: {e}", err=True)
        raise typer.Exit(1)


def main():
    """主入口函数"""
    app()


if __name__ == "__main__":
    main()
