import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .exif import PixExif
from .utils import ProcessStatus, log_action, safe_resolve


class PixProcessor:
    def __init__(self, target_dir: str, delete_duplicates: bool = False):
        self.target_dir = Path(target_dir)
        self.log_dir = self.target_dir / ".pixso_logs"
        self.delete_duplicates = delete_duplicates

        # 为当前运行创建一个带时间戳的日志文件
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.log_dir / f"px_{timestamp}.log"

    def plan_moves(
        self, files: List[Path], progress_callback=None
    ) -> List[Dict[str, Any]]:
        """为文件列表生成移动计划"""

        # 1. 预处理：按绝对路径去重，防止同一个文件被处理两次
        unique_files = {}
        for f in files:
            unique_files[safe_resolve(f)] = f
        files = list(unique_files.values())

        plan = []
        planned_targets = {}  # target_path -> source_path
        lock = threading.Lock()

        def _process_with_lock(file_path: Path):
            res = self._process_one(file_path)
            target = res["target"]
            if res["status"] == ProcessStatus.MOVE and target:
                with lock:
                    if target in planned_targets:
                        # 如果同一个计划中已经有文件占用了这个目标路径
                        # 检查是否是同一个物理文件
                        if safe_resolve(planned_targets[target]) == safe_resolve(
                            file_path
                        ):
                            res["status"] = ProcessStatus.SKIP_ALREADY_ORGANIZED
                        else:
                            res["status"] = (
                                ProcessStatus.DELETE_DUPLICATE
                                if self.delete_duplicates
                                else ProcessStatus.SKIP_DUPLICATE
                            )
                    else:
                        planned_targets[target] = file_path
            return res

        with ThreadPoolExecutor(max_workers=8) as executor:
            for result in executor.map(_process_with_lock, files):
                plan.append(result)
                if progress_callback:
                    progress_callback()
        return plan

    def _process_one(self, file_path: Path) -> Dict[str, Any]:
        """处理单个文件"""
        try:
            exif = PixExif(file_path)
            target_path, status = self._compute_target(exif)
            return {
                "source": file_path,
                "target": target_path,
                "status": status,
                "exif": exif,
            }
        except Exception as e:
            return {
                "source": file_path,
                "target": None,
                "status": f"{ProcessStatus.ERROR}: {e}",
                "exif": None,
            }

    def _compute_target(self, exif: PixExif) -> tuple[Path, str]:
        """计算目标路径并处理冲突"""
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

    def execute_plan(self, plan: List[Dict[str, Any]]):
        """执行移动计划"""
        created_dirs = set()

        for item in plan:
            source = item["source"]
            target = item["target"]
            status = item["status"]

            # 安全前置检查：源文件是否还存在
            if not source.exists():
                item["status"] = f"{status} (Failed: Source file no longer exists)"
                yield item
                continue

            if status == ProcessStatus.MOVE and target is not None:
                try:
                    parent = target.parent
                    if parent not in created_dirs:
                        parent.mkdir(parents=True, exist_ok=True)
                        created_dirs.add(parent)

                    shutil.move(str(source), str(target))
                    log_action(self.log_dir, self.log_file, source, target, status)
                    item["status"] = f"{status} (Success)"
                except Exception as e:
                    item["status"] = f"{status} (Failed: {e})"
            elif status == ProcessStatus.DELETE_DUPLICATE:
                try:
                    if not target.exists():
                        item["status"] = (
                            f"{status} (Failed: Target file missing, aborting deletion to prevent data loss)"
                        )
                    else:
                        source.unlink()
                        log_action(self.log_dir, self.log_file, source, target, status)
                        item["status"] = f"{status} (Success)"
                except Exception as e:
                    item["status"] = f"{status} (Failed: {e})"
            elif status == ProcessStatus.SKIP_DUPLICATE:
                # 将重复文件移动到 target_dir/duplicates
                try:
                    dup_dir = self.target_dir / "duplicates"
                    if dup_dir not in created_dirs:
                        dup_dir.mkdir(parents=True, exist_ok=True)
                        created_dirs.add(dup_dir)

                    # 保持源文件名
                    dest = dup_dir / source.name
                    if dest.exists():
                        dest = (
                            dup_dir
                            / f"{source.stem}_{datetime.now().strftime('%H%M%S')}{source.suffix}"
                        )

                    shutil.move(str(source), str(dest))
                    log_action(
                        self.log_dir, self.log_file, source, dest, "Move (Duplicate)"
                    )
                    item["status"] = "Move (Duplicate Success)"
                except Exception as e:
                    item["status"] = f"Move (Duplicate Failed: {e})"
            elif status == ProcessStatus.SKIP_ALREADY_ORGANIZED:
                log_action(self.log_dir, self.log_file, source, target, status)

            yield item
