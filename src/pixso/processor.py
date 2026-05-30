import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .exif import PixExif
from .utils import (
    Category,
    MediaType,
    PlanItem,
    ProcessStatus,
    log_action,
    safe_resolve,
)


class PixProcessor:
    def __init__(self, target_dir: str, delete_duplicates: bool = False):
        self.target_dir = Path(target_dir)
        self.log_dir = self.target_dir / ".pixso_logs"
        self.delete_duplicates = delete_duplicates

        # 为当前运行创建一个带时间戳的日志文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.log_dir / f"px_{timestamp}.log"

    def plan_moves(self, files: List[Path], progress_callback=None) -> List[PlanItem]:
        """为文件列表生成移动计划 (Lock-free 并发设计)"""

        # 1. 预处理：按绝对路径去重
        unique_files = {safe_resolve(f): f for f in files}
        files_to_process = list(unique_files.values())

        # 2. 并发生成初步计划 (不处理冲突)
        proposed_plans: List[PlanItem] = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            for item in executor.map(self._process_one, files_to_process):
                proposed_plans.append(item)
                if progress_callback:
                    progress_callback()

        # 3. 单线程解决冲突并生成最终计划
        final_plan: List[PlanItem] = []
        planned_targets: Dict[Path, Path] = {}  # target_path -> source_path

        for item in proposed_plans:
            if item.status == ProcessStatus.MOVE and item.target:
                target = item.target
                source = item.source
                if target in planned_targets:
                    # 冲突：已经有文件要移动到这个目标
                    if safe_resolve(planned_targets[target]) == safe_resolve(source):
                        item.status = ProcessStatus.SKIP_ALREADY_ORGANIZED
                    else:
                        item.status = (
                            ProcessStatus.DELETE_DUPLICATE
                            if self.delete_duplicates
                            else ProcessStatus.SKIP_DUPLICATE
                        )
                else:
                    planned_targets[target] = source
            final_plan.append(item)

        return final_plan

    def _process_one(self, file_path: Path) -> PlanItem:
        """处理单个文件，生成初步计划"""
        try:
            exif = PixExif(file_path)
            target_path, status = self._compute_target(exif)
            return PlanItem(
                source=file_path, target=target_path, status=status, exif=exif
            )
        except Exception as e:
            return PlanItem(
                source=file_path,
                target=None,
                status=ProcessStatus.ERROR,
                error_msg=str(e),
            )

    def _compute_target(self, exif: PixExif) -> tuple[Path, str]:
        """计算目标路径并处理已有文件的冲突"""
        source_path = exif._path

        # 基础目标路径
        base_dir = self.target_dir / exif.category / exif.month / exif.media_type

        # 获取带 Hash8 的文件名
        target_name = exif.rename()
        target_path = base_dir / target_name

        # 检查是否已经是归档好的文件
        if source_path.name == target_path.name and safe_resolve(
            source_path.parent
        ) == safe_resolve(target_path.parent):
            return target_path, ProcessStatus.SKIP_ALREADY_ORGANIZED

        # 冲突处理：由于文件名带 Hash8，同名即代表内容相同（碰撞概率极低）
        if target_path.exists():
            # 特殊处理：如果源文件就在目标位置（比如只是大小写不同，或者inode相同）
            if safe_resolve(source_path) == safe_resolve(target_path):
                return target_path, ProcessStatus.SKIP_ALREADY_ORGANIZED

            status = (
                ProcessStatus.DELETE_DUPLICATE
                if self.delete_duplicates
                else ProcessStatus.SKIP_DUPLICATE
            )
            return target_path, status

        return target_path, ProcessStatus.MOVE

    def execute_plan(self, plan: List[PlanItem]):
        """执行移动计划"""
        created_dirs = set()

        # 预先检查目标目录（如果是外接硬盘等）是否存在并且可写
        try:
            if not self.target_dir.exists():
                # 尝试创建，如果失败说明挂载点不存在或没有权限
                self.target_dir.mkdir(parents=True, exist_ok=True)

            # 尝试在目标目录写入一个临时文件来测试写入权限
            test_file = self.target_dir / ".pixso_write_test"
            try:
                test_file.touch()
                test_file.unlink()
            except OSError as e:
                raise OSError(f"Target directory is not writable: {e}")

        except OSError as e:
            for item in plan:
                item.set_status(item.status, f"Target directory unavailable: {e}")
                yield item
            return

        for item in plan:
            source = item.source
            target = item.target
            status = item.status

            # 安全前置检查：源文件是否还存在
            if not source.exists():
                item.set_status(status, "Source file no longer exists")
                yield item
                continue

            if status == ProcessStatus.MOVE and target is not None:
                self._handle_move(item, created_dirs)
            elif status == ProcessStatus.DELETE_DUPLICATE:
                self._handle_delete(item)
            elif status == ProcessStatus.SKIP_DUPLICATE:
                self._handle_duplicate(item, created_dirs)
            elif status == ProcessStatus.SKIP_ALREADY_ORGANIZED:
                log_action(self.log_dir, self.log_file, source, target, str(status))

            yield item

    def _handle_move(self, item: PlanItem, created_dirs: set):
        try:
            parent = item.target.parent
            if parent not in created_dirs:
                try:
                    parent.mkdir(parents=True, exist_ok=True)
                    created_dirs.add(parent)
                except OSError as e:
                    # 捕获由于目标驱动器未挂载等导致的权限或只读错误
                    raise RuntimeError(f"Cannot create target directory {parent}: {e}")

            shutil.move(str(item.source), str(item.target))
            log_action(
                self.log_dir, self.log_file, item.source, item.target, str(item.status)
            )
            item.set_status(item.status, error=None)  # Mark success implicitly
            item.status = f"{item.status} (Success)"
        except Exception as e:
            item.set_status(item.status, str(e))

    def _handle_delete(self, item: PlanItem):
        try:
            if not item.target.exists():
                item.set_status(
                    item.status,
                    "Target file missing, aborting deletion to prevent data loss",
                )
            else:
                item.source.unlink()
                log_action(
                    self.log_dir,
                    self.log_file,
                    item.source,
                    item.target,
                    str(item.status),
                )
                item.status = f"{item.status} (Success)"
        except Exception as e:
            item.set_status(item.status, str(e))

    def _handle_duplicate(self, item: PlanItem, created_dirs: set):
        try:
            dup_dir = self.target_dir / "duplicates"
            if dup_dir not in created_dirs:
                dup_dir.mkdir(parents=True, exist_ok=True)
                created_dirs.add(dup_dir)

            # 保持源文件名
            dest = dup_dir / item.source.name
            if dest.exists():
                dest = (
                    dup_dir
                    / f"{item.source.stem}_{datetime.now().strftime('%H%M%S')}{item.source.suffix}"
                )

            shutil.move(str(item.source), str(dest))
            log_action(
                self.log_dir, self.log_file, item.source, dest, "Move (Duplicate)"
            )
            item.status = "Move (Duplicate Success)"
        except Exception as e:
            item.status = f"Move (Duplicate Failed: {e})"

    def get_stats(self, specific_month: Optional[str] = None) -> dict:
        """扫描归档库并返回统计信息"""
        stats_data = {}

        def scan_dir(base_dir: Path):
            if not base_dir.exists():
                return
            for month_dir in base_dir.iterdir():
                if not month_dir.is_dir() or not month_dir.name.isdigit():
                    continue

                m = month_dir.name
                if specific_month and m != specific_month:
                    continue

                if m not in stats_data:
                    stats_data[m] = {
                        MediaType.PHOTO: 0,
                        MediaType.VIDEO: 0,
                        MediaType.MISC: 0,
                    }

                for root, _, files in os.walk(month_dir):
                    # 优化：通过目录名直接确定媒体类型
                    rel_path = Path(root).relative_to(month_dir)
                    parts = rel_path.parts
                    media_type = MediaType.MISC
                    if MediaType.PHOTO in parts:
                        media_type = MediaType.PHOTO
                    elif MediaType.VIDEO in parts:
                        media_type = MediaType.VIDEO

                    for f in files:
                        if f.startswith((".", "._")):
                            continue
                        stats_data[m][media_type] += 1

        for cat in [Category.ARCHIVE, Category.UNKNOWN]:
            scan_dir(self.target_dir / cat)

        return stats_data
