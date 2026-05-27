import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

from .utils import get_clean_name, parse_filename_stem

console = Console()


class Deduper:
    def __init__(self, target_dir: str, dry_run: bool = False):
        self.target_dir = Path(target_dir)
        self.dry_run = dry_run
        self.duplicates_dir = self.target_dir / "duplicates"

    def scan(self) -> Dict[str, List[Path]]:
        """扫描目录，按时间戳分组"""
        groups = defaultdict(list)

        # 遍历 archive 和 unknown 目录下的所有文件
        for p in self.target_dir.rglob("*"):
            if p.is_file() and not p.name.startswith('.'):
                # 跳过 duplicates 目录
                if "duplicates" in p.parts:
                    continue

                timestamp, _ = parse_filename_stem(p.stem)
                if timestamp:
                    groups[timestamp].append(p)

        # 只保留有多个文件的组
        return {ts: files for ts, files in groups.items() if len(files) > 1}

    def _is_generic(self, name: str) -> bool:
        """判断是否为通用文件名（如 IMG, IMAGE, PHOTO 等）"""
        name = name.upper()

        # 剥离设备名前缀（如果存在）
        # 比如 ILCE7CM2IMG 变成 IMG
        # 因为 get_clean_name 会把设备名和文件名连在一起
        # 这里我们简单处理：如果包含这些通用词，就认为是通用的

        generic_patterns = ['IMG', 'IMAGE', 'PHOTO', 'PICTURE', 'PIC']
        for p in generic_patterns:
            if p in name:
                return True

        # 匹配 DSC, P 等前缀，但不能带长数字
        if re.search(r'(DSC|P)\d{4,}', name):
            return False

        if re.search(r'(DSC|P)\d*$', name):
            return True

        return False

    def _analyze_group(self, files: List[Path]) -> Tuple[Path, List[Path]]:
        """分析一组文件，返回 (要保留的文件, 要删除/移动的文件列表)"""
        if len(files) <= 1:
            return files[0], []

        # 优先保留：1. 具有具体名称的(非通用名) 2. 文件更大的
        def sort_key(f: Path):
            size = f.stat().st_size
            _, name_part = parse_filename_stem(f.stem)

            try:
                from .exif import PixExif
                exif = PixExif(f)
                clean_name = get_clean_name(exif._meta.original_name)
            except Exception:
                clean_name = get_clean_name(name_part)

            is_generic = self._is_generic(clean_name)

            # 返回元组：(是否非通用名(True排前面), 文件大小)
            return (not is_generic, size)

        files.sort(key=sort_key, reverse=True)

        # 最大的/最具体的文件作为基准
        base_file = files[0]
        base_size = base_file.stat().st_size
        _, base_name_part = parse_filename_stem(base_file.stem)

        # 提取真正的后缀部分（尝试去掉设备名）
        from .exif import PixExif
        try:
            base_exif = PixExif(base_file)
            base_clean = get_clean_name(base_exif._meta.original_name)
        except Exception:
            base_clean = get_clean_name(base_name_part)

        to_remove = []

        for f in files[1:]:
            f_size = f.stat().st_size
            _, f_name_part = parse_filename_stem(f.stem)
            try:
                f_exif = PixExif(f)
                f_clean = get_clean_name(f_exif._meta.original_name)
            except Exception:
                f_clean = get_clean_name(f_name_part)

            is_duplicate = False

            # 1. 大小完全一致 -> 判定为重复
            if f_size == base_size:
                is_duplicate = True

            # 2. 大小非常接近 (差异 < 1% 且 < 50KB)
            elif abs(f_size - base_size) < max(base_size * 0.01, 50 * 1024):
                # 如果名称包含 -> 重复
                if (f_clean in base_clean and len(f_clean) >= 3) or (
                    base_clean in f_clean and len(base_clean) >= 3
                ):
                    is_duplicate = True
                # 如果一个是通用名称，另一个是具体名称 -> 重复
                elif self._is_generic(f_clean) or self._is_generic(base_clean):
                    is_duplicate = True
                # 连拍保护：如果两个都是具体的不同名称 (如 DSC01986 vs DSC01987) -> 不是重复
                else:
                    is_duplicate = False

            if is_duplicate:
                to_remove.append(f)

        return base_file, to_remove

    def _get_optimal_name(self, timestamp: str, files: List[Path]) -> str:
        """从一组重复文件中，找出最符合规范的名称"""
        # 直接使用 PixExif 生成标准名称。由于 files[0] 是最大的文件，
        # 我们信任它的元数据和它生成的标准名称。
        from .exif import PixExif
        try:
            return PixExif(files[0]).rename()
        except Exception:
            # 回退方案
            return files[0].name

    def run(self):
        console.print(
            f"[bold blue]Scanning {self.target_dir} for duplicates...[/bold blue]"
        )
        groups = self.scan()

        if not groups:
            console.print("[green]No potential duplicates found.[/green]")
            return

        total_duplicates = 0
        actions = []

        table = Table(title="Potential Duplicates Found")
        table.add_column("Timestamp", style="cyan")
        table.add_column("Action", style="yellow")
        table.add_column("Files", style="white")

        for ts, files in groups.items():
            base_file, to_remove = self._analyze_group(files)

            if not to_remove:
                continue

            total_duplicates += len(to_remove)

            # 确定最佳名称
            all_related_files = [base_file] + to_remove
            optimal_stem = self._get_optimal_name(ts, all_related_files)

            # 修复双后缀问题：如果 optimal_stem 已经包含了后缀，就不再添加
            if optimal_stem.lower().endswith(base_file.suffix.lower()):
                optimal_name = optimal_stem
            else:
                optimal_name = f"{optimal_stem}{base_file.suffix}"

            file_details = []
            file_details.append(
                f"[green]Keep:[/green] {base_file.name} ({base_file.stat().st_size / 1024 / 1024:.2f} MB)"
            )
            for f in to_remove:
                file_details.append(
                    f"[red]Remove:[/red] {f.name} ({f.stat().st_size / 1024 / 1024:.2f} MB)"
                )

            action_desc = "Remove Duplicates"
            if base_file.name != optimal_name:
                action_desc += f"\nRename Keep -> {optimal_name}"

            table.add_row(ts, action_desc, "\n".join(file_details))

            actions.append({
                'base_file': base_file,
                'to_remove': to_remove,
                'optimal_name': optimal_name,
            })

        if not actions:
            console.print(
                "[green]No actual duplicates identified after analysis.[/green]"
            )
            return

        console.print(table)
        console.print(
            f"\nFound [bold red]{total_duplicates}[/bold red] duplicates in [bold cyan]{len(actions)}[/bold cyan] groups."
        )

        if self.dry_run:
            console.print(
                "[yellow]Dry run mode enabled. No files will be modified.[/yellow]"
            )
            return

        if not Confirm.ask("Do you want to proceed with cleanup?"):
            console.print("Operation cancelled.")
            return

        # 执行清理
        if not self.duplicates_dir.exists():
            self.duplicates_dir.mkdir(parents=True)

        for action in actions:
            base_file = action['base_file']
            optimal_name = action['optimal_name']

            # 1. 移动重复文件
            for f in action['to_remove']:
                dest = self.duplicates_dir / f.name
                # 处理 duplicates 目录下的重名冲突
                if dest.exists():
                    dest = self.duplicates_dir / f"{f.stem}_dup{f.suffix}"
                shutil.move(str(f), str(dest))
                console.print(f"Moved [red]{f.name}[/red] to duplicates/")

            # 2. 重命名保留的文件（如果需要）
            if base_file.name != optimal_name:
                new_path = base_file.parent / optimal_name
                if not new_path.exists():
                    base_file.rename(new_path)
                    console.print(
                        f"Renamed [green]{base_file.name}[/green] -> [green]{optimal_name}[/green]"
                    )

        console.print("[bold green]Cleanup complete![/bold green]")
