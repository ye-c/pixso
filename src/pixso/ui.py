from collections import defaultdict
from pathlib import Path
from typing import List

from rich.panel import Panel
from rich.table import Table

from .utils import (
    Category,
    MediaType,
    PlanItem,
    ProcessStatus,
    console,
    get_display_path,
)


def print_plan_summary(plan: List[PlanItem], target_dir: Path):
    """打印执行计划摘要"""
    day_stats = defaultdict(
        lambda: {
            "archive": 0,
            "unknown": 0,
            "duplicate": 0,
            MediaType.PHOTO: 0,
            MediaType.VIDEO: 0,
            MediaType.MISC: 0,
        }
    )
    unknown_samples = []
    total_count = len(plan)

    for item in plan:
        exif = item.exif
        status = item.status

        if not exif:
            continue

        # 按天分组 (YYYY-MM-DD)
        day = exif.formatted_date

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
            source = item.source
            target = item.target
            src_display = get_display_path(source)
            tgt_display = get_display_path(target, [target_dir])

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


def print_plan_table(plan: List[PlanItem], target_dir: Path, title: str = "执行计划"):
    """优雅地打印同步/整理计划表格"""
    table = Table(title=title)
    table.add_column("源位置", style="cyan")
    table.add_column("目标位置", style="magenta")
    table.add_column("操作", style="green")

    # 只显示前 100 条，避免终端刷屏
    display_items = plan[:100]

    for item in display_items:
        source = item.source
        target = item.target
        status = item.status

        # 1. 计算源路径显示
        source_display = get_display_path(source, [target_dir, Path.cwd()])

        # 2. 计算状态和目标路径显示
        if status == ProcessStatus.SKIP_DUPLICATE:
            status_str = "[yellow]Move to Duplicates[/yellow]"
            target_display = f"[yellow]duplicates/{source.name}[/yellow]"
        elif status == ProcessStatus.DELETE_DUPLICATE:
            status_str = "[bold red]Delete Duplicate[/bold red]"
            target_display = "[bold red]DELETE[/bold red]"
        elif target:
            target_display = get_display_path(target, [target_dir])
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


def print_stats_table(stats_data: dict):
    """打印统计信息表格"""
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
