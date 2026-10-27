"""通用工具：目录名、输出 id、时间格式化。"""

import hashlib
import re
from datetime import datetime
from pathlib import Path


def slugify(text: str, limit: int = 40) -> str:
    """把标题转成安全的目录名片段（保留中文、字母、数字、连字符）。"""
    s = re.sub(r"[^\w一-鿿-]+", "-", text or "").strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s[:limit].strip("-")


def make_output_id(title: str, seed: str, root: Path) -> str:
    """生成唯一输出目录名：日期_时间_标题slug_hash。

    seed 用 URL 或正文前 500 字，保证同一文章再跑一次也有稳定 hash。
    """
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    digest = hashlib.md5((seed or "").encode("utf-8")).hexdigest()[:6]
    base = f"{stamp}_{slugify(title) or 'article'}_{digest}"
    candidate = base
    n = 2
    while (root / candidate).exists():
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def format_duration(seconds: float) -> str:
    """秒数转可读时长。"""
    seconds = max(0, int(seconds or 0))
    if seconds <= 0:
        return "0s"
    m, s = divmod(seconds, 60)
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
