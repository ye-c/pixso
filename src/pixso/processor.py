import shutil
from pathlib import Path
from typing import Any, Dict, List

from .exif import PixExif
from .utils import get_file_hash, log_action


class PixProcessor:
    def __init__(self, target_dir: str, delete_duplicates: bool = False):
        self.target_dir = Path(target_dir)
        self.log_dir = self.target_dir / ".pixso_logs"
        self.delete_duplicates = delete_duplicates

        # 为当前运行创建一个带时间戳的日志文件
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.log_dir / f"px_{timestamp}.log"

    def plan_moves(self, files: List[Path], progress_callback=None) -> List[Dict[str, Any]]:
        """为文件列表生成移动计划"""
        plan = []
        for file_path in files:
            try:
                exif = PixExif(file_path)
                target_path, status = self._compute_target(file_path, exif)
                plan.append(
                    {
                        "source": file_path,
                        "target": target_path,
                        "status": status,
                        "exif": exif,
                    }
                )
            except Exception as e:
                plan.append(
                    {
                        "source": file_path,
                        "target": None,
                        "status": f"Error: {e}",
                        "exif": None,
                    }
                )
            if progress_callback:
                progress_callback()
        return plan

    def _compute_target(self, source_path: Path, exif: PixExif) -> tuple[Path, str]:
        """计算目标路径并处理冲突"""
        # 确定类别 (如果没有成功提取时间戳，才进入 snapshot)
        category = "snapshot" if exif._meta.is_fallback_time else "archive"

        # 确定日期文件夹 (YYYYMM)
        date_folder = exif._meta.timestamp[:6]

        # 确定媒体类型
        if exif.is_image:
            media_type = "p"
        elif exif.is_video:
            media_type = "v"
        else:
            media_type = "misc"

        # 基础目标路径
        base_dir = self.target_dir / category / date_folder / media_type
        target_name = exif.rename()
        target_path = base_dir / target_name

        status = "Move"

        # 冲突处理
        if target_path.exists():
            source_hash = get_file_hash(source_path)
            target_hash = get_file_hash(target_path)

            if source_hash == target_hash:
                status = (
                    "Delete (Duplicate)"
                    if self.delete_duplicates
                    else "Skip (Duplicate)"
                )
                return target_path, status

            # 冲突但内容不同，重命名
            counter = 1
            while True:
                new_name = f"{target_path.stem}_{counter}{target_path.suffix}"
                new_target = base_dir / new_name
                if not new_target.exists():
                    target_path = new_target
                    status = "Rename (Collision)"
                    break
                counter += 1

        return target_path, status

    def execute_plan(self, plan: List[Dict[str, Any]]):
        """执行移动计划"""
        for item in plan:
            source = item["source"]
            target = item["target"]
            status = item["status"]

            if status in ("Move", "Rename (Collision)") and target is not None:
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(target))
                    log_action(self.log_dir, self.log_file, source, target, status)
                    item["status"] = f"{status} (Success)"
                except Exception as e:
                    item["status"] = f"{status} (Failed: {e})"
            elif status == "Delete (Duplicate)":
                try:
                    source.unlink()
                    log_action(self.log_dir, self.log_file, source, target, status)
                    item["status"] = f"{status} (Success)"
                except Exception as e:
                    item["status"] = f"{status} (Failed: {e})"
            elif "Skip" in status:
                log_action(self.log_dir, self.log_file, source, target, status)

            yield item
