import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
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
                files_to_process.extend(p.rglob(f"*{ext}"))
                files_to_process.extend(p.rglob(f"*{ext.upper()}"))
        else:
            typer.echo(f"错误: 目录不存在: {directory}", err=True)
            raise typer.Exit(1)

    if not files_to_process:
        typer.echo("没有找到支持的图片或视频文件。")
        raise typer.Exit(0)

    processor = PixProcessor(target_dir)

    with console.status("[bold green]正在扫描和解析文件...") as status:
        plan = processor.plan_moves(files_to_process)

    # 打印计划表格
    table = Table(title="文件处理计划")
    table.add_column("源文件", style="cyan", no_wrap=False)
    table.add_column("目标文件", style="magenta", no_wrap=False)
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

        table.add_row(str(item["source"]), target_str, status_str)

    console.print(table)

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件移动。[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        confirm = typer.confirm("确认执行以上文件操作？", abort=True)

    with console.status("[bold green]正在执行文件移动...") as status:
        processor.execute_plan(plan)

    console.print("[bold green]执行完成！[/bold green]")

def main():
    """主入口函数"""
    app()

if __name__ == "__main__":
    main()
