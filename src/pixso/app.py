import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from .config import config
from .exif import PixExif
from .processor import PixProcessor
from .utils import (
    Category,
    MediaType,
    ProcessStatus,
    console,
    get_files,
    get_progress,
    get_target_dir,
)

app = typer.Typer(help="图片/视频元数据处理与归档工具", no_args_is_help=True)


def print_plan_summary(plan: List[Dict[str, Any]], target_dir: Path):
    """打印执行计划摘要"""
    day_stats = defaultdict(
        lambda: {"archive": 0, "unknown": 0, "duplicate": 0, "p": 0, "v": 0, "misc": 0}
    )
    unknown_samples = []
    total_count = len(plan)

    for item in plan:
        exif = item.get("exif")
        status = item.get("status")

        if not exif:
            continue

        # 按天分组 (YYYY-MM-DD)
        ts = exif._meta.timestamp
        day = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"

        # 统计操作类型
        if status in (ProcessStatus.SKIP_DUPLICATE, ProcessStatus.DELETE_DUPLICATE):
            day_stats[day]["duplicate"] += 1
        elif exif.category == Category.UNKNOWN:
            day_stats[day]["unknown"] += 1
            if len(unknown_samples) < 10:
                unknown_samples.append(item)
        else:
            day_stats[day]["archive"] += 1

        # 统计媒体类型
        day_stats[day][exif.media_type] += 1

    # 1. 打印按天统计的表格
    table = Table(title="执行计划摘要 (按天统计)")
    table.add_column("日期", style="cyan")
    table.add_column("正常归档", style="green", justify="right")
    table.add_column("未知时间", style="yellow", justify="right")
    table.add_column("重复文件", style="red", justify="right")
    table.add_column("P/V/M", style="dim", justify="right")
    table.add_column("当日总计", style="bold", justify="right")

    for day in sorted(day_stats.keys()):
        stats = day_stats[day]
        p_v_m = (
            f"{stats[MediaType.PHOTO]}/{stats[MediaType.VIDEO]}/{stats[MediaType.MISC]}"
        )
        day_total = stats["archive"] + stats["unknown"] + stats["duplicate"]
        table.add_row(
            day,
            str(stats["archive"]) if stats["archive"] > 0 else "-",
            f"[yellow]{stats['unknown']}[/yellow]" if stats["unknown"] > 0 else "-",
            f"[red]{stats['duplicate']}[/red]" if stats["duplicate"] > 0 else "-",
            p_v_m,
            str(day_total),
        )

    console.print(table)

    # 2. 如果有未知文件，打印示例
    if unknown_samples:
        console.print("\n[yellow]▼ 未知时间文件示例 (前 10 个):[/yellow]")
        sample_table = Table(box=None)
        sample_table.add_column("源文件", style="dim", width=40)
        sample_table.add_column("➔", justify="center")
        sample_table.add_column("目标路径", style="yellow")

        for item in unknown_samples:
            source = item["source"]
            target = item["target"]
            try:
                src_display = str(source.relative_to(Path.cwd()))
            except ValueError:
                src_display = source.name

            try:
                tgt_display = str(target.relative_to(target_dir))
            except ValueError:
                tgt_display = str(target)

            sample_table.add_row(src_display, "→", tgt_display)
        console.print(sample_table)

    console.print(
        Panel(
            f"共计待处理文件: [bold cyan]{total_count}[/bold cyan] "
            f"(正常: [green]{sum(s['archive'] for s in day_stats.values())}[/green], "
            f"未知: [yellow]{sum(s['unknown'] for s in day_stats.values())}[/yellow], "
            f"重复: [red]{sum(s['duplicate'] for s in day_stats.values())}[/red])",
            expand=False,
        )
    )


def print_plan_table(
    plan: List[Dict[str, Any]], target_dir: Path, title: str = "执行计划"
):
    """优雅地打印同步/整理计划表格"""
    table = Table(title=title)
    table.add_column("源位置", style="cyan")
    table.add_column("目标位置", style="magenta")
    table.add_column("操作", style="green")

    # 只显示前 100 条，避免终端刷屏
    display_items = plan[:100]

    for item in display_items:
        source = item["source"]
        target = item["target"]
        status = item["status"]

        # 1. 计算源路径显示
        try:
            source_display = str(source.relative_to(target_dir))
        except ValueError:
            try:
                source_display = str(source.relative_to(Path.cwd()))
            except ValueError:
                source_display = str(source)

        # 2. 计算状态和目标路径显示
        if status == ProcessStatus.SKIP_DUPLICATE:
            status_str = "[yellow]Move to Duplicates[/yellow]"
            target_display = f"[yellow]duplicates/{source.name}[/yellow]"
        elif status == ProcessStatus.DELETE_DUPLICATE:
            status_str = "[bold red]Delete Duplicate[/bold red]"
            target_display = "[bold red]DELETE[/bold red]"
        elif target:
            try:
                target_display = str(target.relative_to(target_dir))
            except ValueError:
                target_display = str(target)
            status_str = (
                status.format_rich()
                if isinstance(status, ProcessStatus)
                else str(status)
            )
        else:
            target_display = "N/A"
            status_str = str(status)

        table.add_row(source_display, target_display, status_str)

    if len(plan) > 100:
        table.add_row("...", "...", f"还有 {len(plan) - 100} 个文件未列出")

    console.print(table)
    console.print(f"\n[bold]待处理文件: {len(plan)}[/bold]\n")


@app.command()
def sync(
    path: Optional[str] = typer.Argument(
        None,
        help="要同步或导入的文件/目录路径。可以是库外路径（导入）或库内路径（整理）",
    ),
    month: Optional[str] = typer.Option(
        None, "-m", "--month", help="指定归档库中的月份 (YYYYMM)"
    ),
    photo: bool = typer.Option(False, "-p", "--photo", help="仅处理照片"),
    video: bool = typer.Option(False, "-v", "--video", help="仅处理视频"),
    dry_run: bool = typer.Option(False, "--dry-run", help="预览操作，不实际执行"),
    yes: bool = typer.Option(False, "-y", "--yes", help="跳过确认，直接执行"),
    delete_duplicates: bool = typer.Option(
        False,
        "--delete-duplicates",
        "--dd",
        help="直接删除重复文件，而不是移入 duplicates 目录",
    ),
):
    """同步媒体文件：支持导入外部文件、整理库内文件、或按月份筛选"""
    target_dir = get_target_dir()
    files_to_process = []
    mode_desc = ""

    # 1. 确定处理范围
    if path:
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
        try:
            rel = p.relative_to(target_dir)
            mode_desc = f"整理目录: [cyan]{rel}[/cyan]"
        except ValueError:
            mode_desc = f"导入外部路径: [cyan]{p}[/cyan]"

    elif month:
        for sub_dir in [Category.ARCHIVE, Category.UNKNOWN]:
            m_path = target_dir / sub_dir / month
            if m_path.exists():
                files_to_process.extend(get_files(m_path))
        if not files_to_process:
            console.print(f"[yellow]在归档库中未找到月份为 {month} 的文件。[/yellow]")
            raise typer.Exit(0)
        mode_desc = f"同步月份: [cyan]{month}[/cyan]"
    else:
        console.print("[red]错误: 必须提供路径参数或 --month 选项[/red]")
        console.print(
            "用法举例:\n  px sync ~/Downloads\n  px sync unknown\n  px sync --month 202405"
        )
        raise typer.Exit(1)

    # 2. 过滤
    if photo or video:
        files_to_process = [
            f
            for f in files_to_process
            if (photo and f.suffix.lower() in config.IMAGES)
            or (video and f.suffix.lower() in config.VIDEOS)
        ]
        mode_desc += " (已过滤类型)"

    if not files_to_process:
        console.print("没有找到需要处理的文件。")
        raise typer.Exit(0)

    # 3. 分析与计划
    processor = PixProcessor(str(target_dir), delete_duplicates=delete_duplicates)
    console.print(f"[bold]模式 - {mode_desc}[/bold]")

    with get_progress("[bold green]正在分析文件: ", len(files_to_process)) as progress:
        task_id = progress.tasks[0].id
        plan = processor.plan_moves(
            files_to_process, progress_callback=lambda: progress.advance(task_id)
        )

    # 4. 过滤掉无需操作的文件
    active_plan = [
        item for item in plan if item["status"] != ProcessStatus.SKIP_ALREADY_ORGANIZED
    ]

    if not active_plan:
        console.print("[green]所有文件均已符合规范，无需操作。[/green]")
        raise typer.Exit(0)

    # 5. 预览与执行
    if len(active_plan) > 20:
        print_plan_summary(active_plan, target_dir)
    else:
        print_plan_table(active_plan, target_dir, title="同步执行计划")

    if dry_run:
        console.print("[bold yellow]Dry-run 模式: 未执行任何文件操作。[/bold yellow]")
        raise typer.Exit(0)

    if not yes and not Confirm.ask("确认执行上述操作？"):
        raise typer.Abort()

    with get_progress("[cyan]正在执行操作: ", len(active_plan)) as progress:
        task_id = progress.tasks[0].id
        for _ in processor.execute_plan(active_plan):
            progress.advance(task_id)

    console.print("\n[bold green]同步完成！[/bold green]")


@app.command()
def stats(
    month: Optional[str] = typer.Argument(None, help="要查看的特定月份 (格式: YYYYMM)"),
):
    """查看归档库统计信息"""
    target_dir = get_target_dir()

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
                stats_data[m] = {
                    MediaType.PHOTO: 0,
                    MediaType.VIDEO: 0,
                    MediaType.MISC: 0,
                }

            for root, _, files in os.walk(month_dir):
                for f in files:
                    if f.startswith((".", "._")):
                        continue

                    p = Path(root) / f
                    try:
                        exif = PixExif(p)
                        stats_data[m][exif.media_type] += 1
                    except Exception:
                        # 如果解析失败，简单通过后缀回退
                        ext = p.suffix.lower()
                        if ext in config.IMAGES:
                            stats_data[m][MediaType.PHOTO] += 1
                        elif ext in config.VIDEOS:
                            stats_data[m][MediaType.VIDEO] += 1
                        else:
                            stats_data[m][MediaType.MISC] += 1

    for cat in [Category.ARCHIVE, Category.UNKNOWN]:
        scan_dir(target_dir / cat)

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
        total = d[MediaType.PHOTO] + d[MediaType.VIDEO] + d[MediaType.MISC]
        table.add_row(
            m,
            str(d[MediaType.PHOTO]),
            str(d[MediaType.VIDEO]),
            str(d[MediaType.MISC]),
            str(total),
        )

    console.print(table)


@app.command()
def info(
    file: str = typer.Argument(..., help="要查看的文件路径"),
):
    """查看文件的元数据解析结果与预期归档路径"""
    p = Path(file)
    if not p.is_file():
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

        # 系统字段
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

        # 归档目录
        try:
            target_dir = get_target_dir()
            processor = PixProcessor(str(target_dir))
            target_path, _ = processor._compute_target(exif)
            rel_target_dir = target_path.parent.relative_to(target_dir)
            table.add_row(
                "[bold green]归档目录[/bold green]",
                f"[bold green]{rel_target_dir}[/bold green]",
            )
        except Exception:
            pass

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
