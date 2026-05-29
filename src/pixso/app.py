import os
from pathlib import Path
from typing import List, Optional

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
from rich.prompt import Confirm
from rich.table import Table

from .config import config
from .exif import PixExif
from .processor import PixProcessor
from .utils import ProcessStatus

app = typer.Typer(help="图片/视频元数据处理与归档工具", no_args_is_help=True)
console = Console()


def get_target_dir() -> Path:
    """获取并验证归档根目录"""
    target_dir = os.environ.get("PIXSO_TARGET_DIR")
    if not target_dir:
        console.print("[red]错误: 必须设置 PIXSO_TARGET_DIR 环境变量[/red]")
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


def get_files(path: Path) -> List[Path]:
    """递归获取目录下所有支持的文件 (单次遍历)"""
    files = []
    if path.is_file():
        if not path.name.startswith((".", "._")):
            files.append(path)
    elif path.is_dir():
        for f in path.rglob("*"):
            if (
                f.is_file()
                and f.suffix.lower() in config.ALL_EXTENSIONS
                and not f.name.startswith((".", "._"))
                and "duplicates" not in f.parts
            ):
                files.append(f)
    return files


@app.command(name="import")
def import_cmd(
    path: str = typer.Argument(..., help="要导入的文件或目录路径"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览操作，不实际执行"),
    yes: bool = typer.Option(False, "-y", "--yes", help="跳过确认，直接执行"),
    delete_source: bool = typer.Option(
        False,
        "--delete-source",
        help="如果是重复文件，直接从源位置删除而不是移入 duplicates 目录",
    ),
):
    """导入并归档媒体文件"""
    target_dir = get_target_dir()

    p = Path(path)
    if not p.exists():
        # 尝试相对于 target_dir
        alt_p = target_dir / path
        if alt_p.exists():
            p = alt_p
        else:
            console.print(f"[red]错误: 路径不存在: {path}[/red]")
            raise typer.Exit(1)

    files_to_process = get_files(p)

    if not files_to_process:
        console.print("没有找到支持的图片或视频文件。")
        raise typer.Exit(0)

    processor = PixProcessor(str(target_dir), delete_duplicates=delete_source)

    with get_progress(
        "[bold green]正在扫描和解析文件: ", len(files_to_process)
    ) as progress:
        task_id = progress.tasks[0].id
        plan = processor.plan_moves(
            files_to_process, progress_callback=lambda: progress.advance(task_id)
        )

    # 打印计划表格
    table = Table(title="文件处理计划")
    table.add_column("源文件", style="cyan", no_wrap=False, overflow="fold")
    table.add_column("目标文件", style="magenta", no_wrap=False, overflow="fold")
    table.add_column("状态/操作", style="green")

    for item in plan:
        target_str = str(item["target"]) if item["target"] else "N/A"
        status = item["status"]

        # 优化重复文件的显示
        if status == ProcessStatus.SKIP_DUPLICATE:
            status_str = "[yellow]Move to Duplicates[/yellow]"
            target_str = f"[yellow]duplicates/{item['source'].name}[/yellow]"
        elif status == ProcessStatus.DELETE_DUPLICATE:
            status_str = "[bold red]Delete Duplicate[/bold red]"
            target_str = "[bold red]DELETE[/bold red]"
        elif isinstance(status, ProcessStatus):
            status_str = status.format_rich()
        else:
            # 处理带错误信息的字符串
            status_str = str(status)
            if "Error" in status_str:
                status_str = f"[red]{status_str}[/red]"
            elif "Move" in status_str:
                status_str = f"[green]{status_str}[/green]"

        table.add_row(str(item["source"]), target_str, status_str)

    console.print(table)

    # 统计
    duplicates = sum(1 for item in plan if "Duplicate" in str(item["status"]))
    errors = sum(1 for item in plan if "Error" in str(item["status"]))
    moves = sum(1 for item in plan if item["status"] == ProcessStatus.MOVE)

    console.print(
        f"\n[bold]统计信息:[/bold] 待归档: {moves} | 重复: {duplicates} | 错误: {errors}\n"
    )

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件操作。[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        if not Confirm.ask("确认执行以上文件操作？"):
            raise typer.Abort()

    with get_progress("[cyan]正在执行文件操作: ", len(plan)) as progress:
        task_id = progress.tasks[0].id
        for _ in processor.execute_plan(plan):
            progress.advance(task_id)

    console.print("\n[bold green]执行完成！[/bold green]")


@app.command()
def sync(
    path: Optional[str] = typer.Argument(
        None, help="要整理的特定目录路径。如果不提供，则整理整个 PIXSO_TARGET_DIR"
    ),
    month: Optional[str] = typer.Option(
        None, "-m", "--month", help="指定月份 (YYYYMM)"
    ),
    photo: bool = typer.Option(False, "-p", "--photo", help="仅处理照片"),
    video: bool = typer.Option(False, "-v", "--video", help="仅处理视频"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览操作，不实际执行"),
    yes: bool = typer.Option(False, "-y", "--yes", help="跳过确认，直接执行"),
    delete_duplicates: bool = typer.Option(
        False, "--delete-duplicates", help="直接删除重复文件，而不是移入 duplicates 目录"
    ),
):
    """整理并重建归档库（应用新命名规范并清理重复文件）"""
    target_dir = get_target_dir()

    files_to_process = []
    if path:
        scan_path = Path(path)
        if not scan_path.exists():
            # 尝试相对于 target_dir
            alt_path = target_dir / path
            if alt_path.exists():
                scan_path = alt_path
            else:
                console.print(f"[red]错误: 路径不存在: {path}[/red]")
                raise typer.Exit(1)
        files_to_process = get_files(scan_path)
    elif month:
        # 同时检查 archive 和 snapshot 目录下的对应月份
        for sub_dir in ["archive", "snapshot"]:
            m_path = target_dir / sub_dir / month
            if m_path.exists():
                files_to_process.extend(get_files(m_path))
        if not files_to_process:
            console.print(f"[yellow]在归档库中未找到月份为 {month} 的文件。[/yellow]")
            raise typer.Exit(0)
    else:
        if not yes:
            if not Confirm.ask(
                f"[bold red]警告: 将重新整理整个归档库 ({target_dir})，是否继续？[/bold red]"
            ):
                raise typer.Abort()
        files_to_process = get_files(target_dir)

    if not files_to_process:
        console.print("没有找到需要整理的文件。")
        raise typer.Exit(0)

    # 根据类型过滤
    if photo or video:
        filtered = []
        for f in files_to_process:
            ext = f.suffix.lower()
            if photo and ext in config.IMAGES:
                filtered.append(f)
            elif video and ext in config.VIDEOS:
                filtered.append(f)
        files_to_process = filtered

    if not files_to_process:
        console.print("经过类型过滤后，没有找到需要整理的文件。")
        raise typer.Exit(0)

    # sync 模式下，重复文件默认移入 duplicates
    processor = PixProcessor(str(target_dir), delete_duplicates=delete_duplicates)

    with get_progress(
        "[bold green]正在分析归档库: ", len(files_to_process)
    ) as progress:
        task_id = progress.tasks[0].id
        plan = processor.plan_moves(
            files_to_process, progress_callback=lambda: progress.advance(task_id)
        )

    # 过滤掉不需要操作的文件 (Already Organized)
    active_plan = [
        item for item in plan if item["status"] != ProcessStatus.SKIP_ALREADY_ORGANIZED
    ]

    if not active_plan:
        console.print("[green]归档库已经是最新规范，无需整理。[/green]")
        raise typer.Exit(0)

    # 打印计划
    table = Table(title="归档库整理计划")
    table.add_column("当前路径", style="cyan")
    table.add_column("新路径", style="magenta")
    table.add_column("操作", style="green")

    for item in active_plan[:100]:  # 最多显示100行
        status = item["status"]
        source_rel = str(item["source"].relative_to(target_dir))
        target_rel = (
            str(item["target"].relative_to(target_dir)) if item["target"] else "N/A"
        )

        if status == ProcessStatus.SKIP_DUPLICATE:
            status_str = "[yellow]Move to Duplicates[/yellow]"
            target_rel = f"[yellow]duplicates/{item['source'].name}[/yellow]"
        elif status == ProcessStatus.DELETE_DUPLICATE:
            status_str = "[bold red]Delete Duplicate[/bold red]"
            target_rel = "[bold red]DELETE[/bold red]"
        elif isinstance(status, ProcessStatus):
            status_str = status.format_rich()
        else:
            status_str = str(status)

        table.add_row(
            source_rel,
            target_rel,
            status_str,
        )

    if len(active_plan) > 100:
        table.add_row("...", "...", f"还有 {len(active_plan) - 100} 个文件未列出")

    console.print(table)
    console.print(f"\n[bold]共发现 {len(active_plan)} 个文件需要整理。[/bold]")

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件操作。[/bold yellow]")
        raise typer.Exit(0)

    if not yes:
        if not Confirm.ask("确认执行整理操作？"):
            raise typer.Abort()

    with get_progress("[cyan]正在重构归档库: ", len(active_plan)) as progress:
        task_id = progress.tasks[0].id
        for _ in processor.execute_plan(active_plan):
            progress.advance(task_id)

    console.print("\n[bold green]整理完成！[/bold green]")


@app.command()
def stats(
    month: Optional[str] = typer.Argument(None, help="要查看的特定月份 (格式: YYYYMM)"),
):
    """查看归档库统计信息"""
    target_dir = get_target_dir()
    archive_dir = target_dir / "archive"
    snapshot_dir = target_dir / "snapshot"

    stats_data = {}

    def scan_dir(base_dir: Path):
        if not base_dir.exists():
            return
        for month_dir in base_dir.iterdir():
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue

            m = month_dir.name
            if month and m != month:
                continue

            if m not in stats_data:
                stats_data[m] = {"p": 0, "v": 0, "misc": 0}

            for root, _, files in os.walk(month_dir):
                for f in files:
                    if f.startswith((".", "._")):
                        continue
                    ext = Path(f).suffix.lower()
                    if ext in config.IMAGES:
                        stats_data[m]["p"] += 1
                    elif ext in config.VIDEOS:
                        stats_data[m]["v"] += 1
                    else:
                        stats_data[m]["misc"] += 1

    scan_dir(archive_dir)
    scan_dir(snapshot_dir)

    if not stats_data:
        console.print("[yellow]没有找到归档数据。[/yellow]")
        return

    table = Table(title="归档统计信息")
    table.add_column("月份", style="cyan")
    table.add_column("图片 (p)", style="green", justify="right")
    table.add_column("视频 (v)", style="magenta", justify="right")
    table.add_column("其他", style="white", justify="right")
    table.add_column("总计", style="bold blue", justify="right")

    for m in sorted(stats_data.keys(), reverse=True):
        d = stats_data[m]
        total = d["p"] + d["v"] + d["misc"]
        table.add_row(m, str(d["p"]), str(d["v"]), str(d["misc"]), str(total))

    console.print(table)


@app.command()
def info(
    file: str = typer.Argument(..., help="要查看的文件路径"),
):
    """查看文件的元数据解析结果与预期归档路径"""
    p = Path(file)
    if not p.is_file():
        # 尝试相对于 target_dir
        try:
            target_dir = get_target_dir()
            alt_p = target_dir / file
            if alt_p.is_file():
                p = alt_p
            else:
                console.print(f"[red]错误: 文件不存在: {file}[/red]")
                raise typer.Exit(1)
        except Exception:
            console.print(f"[red]错误: 文件不存在: {file}[/red]")
            raise typer.Exit(1)

    try:
        exif = PixExif(p)

        table = Table(title=f"文件信息: {p.name}")
        table.add_column("属性", style="cyan")
        table.add_column("值", style="magenta")

        # 系统字段 (高亮显示)
        table.add_row(
            "[bold yellow]时间戳[/bold yellow]",
            f"[bold yellow]{exif._meta.timestamp}[/bold yellow]",
        )
        table.add_row(
            "[bold yellow]设备 (原始)[/bold yellow]",
            f"[bold yellow]{exif._meta.device}[/bold yellow]",
        )
        table.add_row(
            "[bold yellow]设备 (简短)[/bold yellow]",
            f"[bold yellow]{exif.get_device_short()}[/bold yellow]",
        )
        table.add_row(
            "[bold yellow]Hash8[/bold yellow]",
            f"[bold yellow]{exif.get_hash8()}[/bold yellow]",
        )
        table.add_row(
            "[bold yellow]是否未知时间[/bold yellow]",
            f"[bold yellow]{exif._meta.is_unknown_time}[/bold yellow]",
        )
        table.add_row(
            "[bold yellow]最终文件名[/bold yellow]",
            f"[bold yellow]{exif.rename()}[/bold yellow]",
        )

        if exif.raw_tags:
            table.add_section()
            for k in sorted(exif.raw_tags.keys()):
                val = str(exif.raw_tags[k])
                if len(val) > 80:
                    val = val[:77] + "..."
                table.add_row(k, val)

        console.print(table)

    except Exception as e:
        console.print(f"[red]解析失败: {e}[/red]")
        raise typer.Exit(1)
