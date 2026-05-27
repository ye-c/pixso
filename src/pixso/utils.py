import hashlib
import json
import re
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

def get_clean_name(name: str) -> str:
    """提取纯字母数字的名称"""
    if not name:
        return ""
    return re.sub(r'[^a-zA-Z0-9]', '', str(name))

_TS_PREFIX_RE = re.compile(r'^(20\d{12})_(.*)$')

def parse_filename_stem(stem: str) -> tuple[str | None, str]:
    """
    解析文件名的 stem，提取前面的时间戳和后面的名称。
    如果不匹配时间戳格式，返回 (None, stem)。
    """
    match = _TS_PREFIX_RE.match(stem)
    if match:
        return match.group(1), match.group(2)
    return None, stem
