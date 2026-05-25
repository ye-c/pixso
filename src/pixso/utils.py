import hashlib
import json
from datetime import datetime
from pathlib import Path


def get_file_hash(path: Path, chunk_size: int = 8192) -> str:
    """计算文件的 SHA-256 哈希值（分块读取以节省内存）"""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def log_action(log_dir: Path, log_file: Path, source: Path, target: Path, status: str):
    """将执行记录追加到日志文件"""
    log_dir.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now().isoformat(),
        "source": str(source),
        "target": str(target),
        "status": status,
    }

    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
