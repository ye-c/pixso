import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
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
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.log_dir / f"px_{timestamp}.log"

    def plan_moves(
        self, files: List[Path], progress_callback=None
    ) -> List[Dict[str, Any]]:
        """为文件列表生成移动计划"""

        plan = []
        # 使用 ThreadPoolExecutor 因为 metadata 提取 (ffmpeg probe) 主要是 I/O 密集型
        with ThreadPoolExecutor(max_workers=8) as executor:
            for result in executor.map(self._process_one, files):
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
                "status": f"Error: {e}",
                "exif": None,
            }

    def _compute_target(self, exif: PixExif) -> tuple[Path, str]:
        """计算目标路径并处理冲突"""
        source_path = exif._path
        # 确定类别 (如果没有成功提取时间戳，进入 unknown)
        if exif._meta.is_unknown_time:
            category = "unknown"
        else:
            category = "archive"

        # 确定日期文件夹 (YYYYMM)
        date_folder = (
            exif._meta.timestamp[:6] if not exif._meta.is_unknown_time else "000000"
        )

        # 确定媒体类型
        if exif.is_image:
            media_type = "p"
        elif exif.is_video:
            media_type = "v"
        else:
            media_type = "misc"

        # 基础目标路径
        if category == "unknown":
            base_dir = self.target_dir / category
        else:
            base_dir = self.target_dir / category / date_folder / media_type

        # 统一使用 rename() 获取带时间戳的文件名
        target_name = exif.rename()
        target_path = base_dir / target_name

        # 检查是否已经是归档好的文件
        if (
            source_path.name == target_path.name
            and source_path.parent.resolve() == target_path.parent.resolve()
        ):
            return target_path, "Skip (Already Organized)"

        status = "Move"

        # 冲突处理
        if target_path.exists():
            # 优化：先比大小，大小不同直接认定不是重复
            if source_path.stat().st_size != target_path.stat().st_size:
                # 冲突但内容不同，重命名 (跳过哈希计算)
                pass
            else:
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
        # 缓存已创建的目录以减少 mkdir 系统调用
        created_dirs = set()

        for item in plan:
            source = item["source"]
            target = item["target"]
            status = item["status"]

            if status == "Move" and target is not None:
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
            elif status == "Delete (Duplicate)":
                try:
                    source.unlink()
                    log_action(self.log_dir, self.log_file, source, target, status)
                    item["status"] = f"{status} (Success)"
                except Exception as e:
                    item["status"] = f"{status} (Failed: {e})"
            elif status.startswith("Skip") and "Duplicate" in status:
                # 将重复文件移动到 target_dir/duplicates
                try:
                    dup_dir = self.target_dir / "duplicates"
                    if dup_dir not in created_dirs:
                        dup_dir.mkdir(parents=True, exist_ok=True)
                        created_dirs.add(dup_dir)

                    dest = dup_dir / source.name

                    # 如果文件名冲突，加时间戳防止覆盖
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
            elif status.startswith("Skip"):
                log_action(self.log_dir, self.log_file, source, target, status)

            yield item
