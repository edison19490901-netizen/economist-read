"""英文文章解析：清洗、段落切分、词数统计、语言检测。

只处理纯文本（粘贴或网页抓取），不涉及字幕/PDF/视频。
"""

import re

# ── 文本清理 ──────────────────────────────────────

_CLEANUP_PATTERNS: list[tuple[str, str]] = [
    (r"<script[\s\S]*?</script>", " "),
    (r"<style[\s\S]*?</style>", " "),
    (r"<[^>]+>", " "),
    (r"[​‌‍﻿]", ""),
    (r"\r\n?", "\n"),
    (r"[ \t]{2,}", " "),
    (r"\n{3,}", "\n\n"),
]

# 网页正文里常见的样板行（整行匹配时丢弃）
_BOILERPLATE_RE = re.compile(
    r"^(?:"
    r"this article was downloaded by.*|"
    r"enjoy more audio and podcasts.*|"
    r"listen to this story.*|"
    r"listen on .*|"
    r"sign up to .*newsletter.*|"
    r"subscribe(?: now| to .*)?|"
    r"reuse this content|"
    r"share this article|"
    r"read more|"
    r"all rights reserved.*|"
    r"©.*|"
    r"https?://\S+|"
    r"the economist\s*$"
    r")$",
    re.IGNORECASE,
)

# 句末标点（用于判断换行是否为段落续行）
_SENTENCE_END = ".!?。！？；:;”\"')）】"


def clean_text(text: str) -> str:
    """清洗 HTML 标签、零宽字符与多余空白。"""
    for pattern, replacement in _CLEANUP_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return text.strip()


def split_paragraphs(raw: str) -> list[str]:
    """把文章正文切成段落列表。

    优先按空行分段；没有空行时按单换行分段，并合并明显的自动换行续行。
    同时丢弃网页样板行（订阅、版权、分享等）。
    """
    text = clean_text(raw or "")
    if not text:
        return []

    # 先按空行分段
    blocks = re.split(r"\n\s*\n", text)
    if len(blocks) <= 1:
        # 没有空行：按单换行分段
        blocks = text.split("\n")

    paragraphs: list[str] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue

        merged: list[str] = []
        for line in lines:
            if _BOILERPLATE_RE.match(line):
                continue
            if merged:
                prev = merged[-1]
                # 自动换行续行：上一行没有句末标点，且本行以小写字母/逗号继续
                if (
                    prev
                    and prev[-1] not in _SENTENCE_END
                    and re.match(r"^[a-z,;:)\]]", line)
                ):
                    merged[-1] = prev + " " + line
                    continue
            merged.append(line)

        para = " ".join(merged).strip()
        para = re.sub(r"\s{2,}", " ", para)
        if len(para) > 1:
            paragraphs.append(para)

    # 从某些来源复制来的正文可能完全没有换行：按句子重组为伪段落，
    # 否则整篇文章会被当成一段，翻译与定位都会失效。
    if len(paragraphs) == 1 and len(paragraphs[0]) > 1200:
        paragraphs = _split_long_block(paragraphs[0])

    return paragraphs


def _split_long_block(text: str, target_chars: int = 700, max_sentences: int = 5) -> list[str]:
    """把没有换行的长文按句子聚合成约 700 字符的段落。"""
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“\'(\[])', text)
    if len(sentences) < 3:
        return [text]

    out: list[str] = []
    buf: list[str] = []
    size = 0
    for sentence in sentences:
        buf.append(sentence)
        size += len(sentence) + 1
        if size >= target_chars or len(buf) >= max_sentences:
            out.append(" ".join(buf))
            buf, size = [], 0
    if buf:
        out.append(" ".join(buf))

    # 末尾过短的段落并入上一段
    if len(out) > 1 and len(out[-1]) < 120:
        out[-2] = out[-2] + " " + out[-1]
        out.pop()
    return [p for p in out if p]


def cap_paragraphs(paragraphs: list[str], max_chars: int = 60_000) -> tuple[list[str], bool]:
    """按段落边界截断超长文章，返回 (段落, 是否截断)。"""
    total = sum(len(p) + 2 for p in paragraphs)
    if total <= max_chars:
        return paragraphs, False

    kept: list[str] = []
    used = 0
    for p in paragraphs:
        cost = len(p) + 2
        if used + cost > max_chars and kept:
            break
        kept.append(p)
        used += cost
    return kept, True


def join_paragraphs(paragraphs: list[str]) -> str:
    return "\n\n".join(paragraphs)


# ── 字数统计与语言检测 ──────────────────────────────

_CJK_RANGES = [
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
    (0x3000, 0x303F),
]


def count_words(text: str) -> int:
    """英文按词、中文按字统计。"""
    cjk_count = 0
    latin_tokens = 0
    token: list[str] = []
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk_count += 1
        elif ch.isalnum():
            token.append(ch)
        else:
            if token:
                latin_tokens += 1
                token = []
    if token:
        latin_tokens += 1
    return cjk_count + latin_tokens


def detect_language(text: str) -> str:
    """粗略判断语言：CJK 占比 > 30% 视为中文，否则英文。"""
    cjk = 0
    latin = 0
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk += 1
        elif ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
            latin += 1
    total = cjk + latin
    if total == 0:
        return "en"
    return "zh" if (cjk / total) > 0.3 else "en"


def guess_title(paragraphs: list[str]) -> str:
    """从正文猜一个标题：首个较短、无句末标点的段落。"""
    for p in paragraphs[:3]:
        if 8 <= len(p) <= 140 and p[-1] not in ".!?。！？":
            return p
    if paragraphs:
        first = paragraphs[0]
        # 单行正文没有独立标题行时，取开头第一个完整句子作为标题
        m = re.match(r"^(.{8,160}?[.!?])(?:\s|$)", first)
        if m:
            return m.group(1)
        return first[:80]
    return ""
