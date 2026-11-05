"""把上传的文件提取为纯文本。

支持（“包括但不限于”）：

- 纯文本：txt / text / md / markdown / rst / log / csv / json / xml / yaml / ini / src …
- 源码：py / js / ts / java / c / cpp / go / rs / rb / php / sql / sh …
- 网页：html / htm / xhtml
- 文档：docx / docm / odt / rtf / pdf / epub
- 旧版 doc：识别 OLE 容器后尝试 antiword / catdoc / LibreOffice 转换

识别以文件内容为主、扩展名为辅：扩展名不认识时会先看魔数，再看能否按文本解码。
所有解析都在内存中完成，上传的文件不会落盘（只有旧版 doc 转换会写临时文件，用完即删）。
"""

from __future__ import annotations

import codecs
import html
import io
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .parser import clean_text, normalize_text

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_ZIP_MEMBER_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 200

# 明确按纯文本处理的扩展名（含常见源码后缀）
_TEXT_EXTS = {
    "txt", "text", "md", "markdown", "mdown", "rst", "log", "csv", "tsv",
    "json", "jsonl", "xml", "yaml", "yml", "toml", "ini", "cfg", "conf", "src",
    "py", "js", "mjs", "ts", "jsx", "tsx", "java", "c", "h", "cpp", "hpp",
    "cc", "cs", "go", "rs", "rb", "php", "pl", "lua", "swift", "kt", "kts",
    "scala", "r", "m", "sql", "sh", "bash", "zsh", "bat", "ps1", "tex", "org",
}

_HTML_EXTS = {"html", "htm", "xhtml", "xht"}

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"


class FileReadError(ValueError):
    """上传的文件无法解析为可读文本。"""


def extract_text(filename: str, data: bytes) -> str:
    """从上传文件中提取纯文本；无法识别时抛出 FileReadError。"""
    if not data:
        raise FileReadError("文件是空的。")
    if len(data) > MAX_UPLOAD_BYTES:
        raise FileReadError(
            f"文件过大（{len(data) / 1024 / 1024:.1f} MB），请上传 20 MB 以内的文件。"
        )

    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = Path(name).suffix.lower().lstrip(".")
    head = data[:8]

    if ext in {"docx", "docm"}:
        text = _docx_to_text(data)
    elif ext == "odt":
        text = _odt_to_text(data)
    elif ext == "epub":
        text = _epub_to_text(data)
    elif ext == "pdf":
        text = _pdf_to_text(data)
    elif ext == "rtf":
        text = _rtf_to_text(data)
    elif ext in _HTML_EXTS:
        text = _html_to_text(_decode_text(data))
    elif ext == "doc":
        text = _doc_to_text(data)
    elif head.startswith(_PDF_MAGIC):
        text = _pdf_to_text(data)
    elif head.startswith(_ZIP_MAGIC):
        text = _office_zip_to_text(data)
    elif _is_rtf(data):
        text = _rtf_to_text(data)
    elif ext in _TEXT_EXTS or not ext:
        text = _decode_text(data)
    else:
        # 扩展名未知：优先看内容能否按文本解码
        try:
            text = _decode_text(data)
        except FileReadError:
            try:
                text = _office_zip_to_text(data)
            except (FileReadError, zipfile.BadZipFile):
                raise FileReadError(
                    f"无法识别「{name}」的格式。请上传 txt / md / docx / rtf / pdf 等文本文件，"
                    "或改用「粘贴正文」。"
                ) from None

    text = normalize_text(text)
    if not text.strip():
        raise FileReadError(
            f"没能从「{name}」里提取到文字。若为扫描版 PDF/图片型文档，请改用 OCR 或粘贴正文。"
        )
    return text


# ── 纯文本 ──────────────────────────────────────


def _decode_text(data: bytes) -> str:
    """按 BOM、UTF-8、UTF-16 无 BOM、GB18030、Big5、CP1252 的顺序解码。"""
    if data.startswith(codecs.BOM_UTF8):
        return data.decode("utf-8-sig", errors="replace")
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", errors="replace")

    guessed = _guess_bomless_utf16(data)
    if guessed:
        return data.decode(guessed, errors="replace")

    # 二进制内容也可能“恰好”是合法 UTF-8（例如含 \\x00），先排除
    if _looks_binary(data):
        raise FileReadError("文件像是二进制格式，无法按纯文本读取。")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    for encoding in ("gb18030", "big5", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _guess_bomless_utf16(data: bytes) -> str | None:
    """无 BOM 的 UTF-16：ASCII 文本会有一半字节是 0。"""
    sample = data[:4000]
    if len(sample) < 4:
        return None
    even_zeros = sum(1 for b in sample[0::2] if b == 0)
    odd_zeros = sum(1 for b in sample[1::2] if b == 0)
    half = len(sample) / 2
    guess = None
    if odd_zeros > half * 0.3 and odd_zeros > even_zeros * 4:
        guess = "utf-16-le"
    elif even_zeros > half * 0.3 and even_zeros > odd_zeros * 4:
        guess = "utf-16-be"
    if not guess:
        return None

    # 字节分布符合 UTF-16，还要确认解出来像文本，避免把二进制当 UTF-16
    decoded = sample[: len(sample) - len(sample) % 2].decode(guess, errors="replace")
    if not decoded:
        return None
    printable = sum(1 for ch in decoded if ch.isprintable() or ch in "\r\n\t")
    return guess if printable / len(decoded) >= 0.85 else None


def _looks_binary(data: bytes) -> bool:
    sample = data[:8192]
    if b"\x00" in sample:
        return True
    # 控制字符（除常见空白）占比过高，多半是二进制
    controls = sum(1 for b in sample if b < 32 and b not in (9, 10, 12, 13))
    return controls > max(8, len(sample) * 0.05)


def _is_rtf(data: bytes) -> bool:
    return data.lstrip()[:5] == b"{\\rtf"


# ── HTML / Word / ODT / EPUB（zip 容器）───────────


def _html_to_text(raw: str) -> str:
    return html.unescape(clean_text(raw))


def _read_zip_member(zf: zipfile.ZipFile, name: str, limit: int = MAX_ZIP_MEMBER_BYTES) -> bytes:
    info = zf.getinfo(name)
    if info.file_size > limit:
        raise FileReadError(
            f"文档内部文件过大（{info.file_size / 1024 / 1024:.1f} MB），已拒绝解析。"
        )
    with zf.open(name) as fh:
        return fh.read(limit)


def _docx_to_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" not in names:
                raise FileReadError("不是有效的 Word 文档（缺少 word/document.xml）。")
            xml = _read_zip_member(zf, "word/document.xml").decode("utf-8", errors="replace")
    except zipfile.BadZipFile:
        raise FileReadError("Word 文档已损坏或不是 .docx 格式。") from None

    xml = (
        xml.replace("<w:tab/>", "\t")
        .replace("<w:tab />", "\t")
        .replace("<w:br/>", "\n")
        .replace("<w:br />", "\n")
        .replace("<w:cr/>", "\n")
        .replace("<w:cr />", "\n")
    )
    paragraphs: list[str] = []
    for block in re.findall(r"<w:p\b.*?</w:p>|<w:p\b[^>]*/>", xml, re.S):
        runs = re.findall(r"<w:t\b[^>]*>(.*?)</w:t>", block, re.S)
        line = html.unescape("".join(runs)).strip()
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs)


def _odt_to_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = _read_zip_member(zf, "content.xml").decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, KeyError):
        raise FileReadError("不是有效的 ODT 文档。") from None

    xml = re.sub(r"<text:(?:line-break|tab)\b[^>]*/>", " ", xml)
    paragraphs: list[str] = []
    for block in re.findall(r"<text:(?:p|h)\b.*?</text:(?:p|h)>", xml, re.S):
        line = html.unescape(re.sub(r"<[^>]+>", " ", block)).strip()
        line = re.sub(r"\s{2,}", " ", line)
        if line:
            paragraphs.append(line)
    return "\n\n".join(paragraphs)


def _epub_to_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            hrefs = _epub_spine_hrefs(zf, names) or [
                n for n in sorted(names) if n.lower().endswith((".xhtml", ".html", ".htm"))
            ]
            blocks: list[str] = []
            for href in hrefs:
                if href not in names:
                    continue
                raw = _read_zip_member(zf, href).decode("utf-8", errors="replace")
                text = _html_to_text(raw)
                if text.strip():
                    blocks.append(text)
    except zipfile.BadZipFile:
        raise FileReadError("不是有效的 EPUB 文件。") from None
    return "\n\n".join(blocks)


def _epub_spine_hrefs(zf: zipfile.ZipFile, names: set[str]) -> list[str]:
    """按 OPF spine 顺序返回正文文件路径；解析失败返回空列表。"""
    try:
        container = _read_zip_member(zf, "META-INF/container.xml").decode("utf-8", "replace")
    except KeyError:
        return []
    m = re.search(r'full-path="([^"]+)"', container)
    if not m or m.group(1) not in names:
        return []
    opf_path = m.group(1)
    opf = _read_zip_member(zf, opf_path).decode("utf-8", errors="replace")
    base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest: dict[str, str] = {}
    for tag in re.findall(r"<item\b[^>]*>", opf):
        id_m = re.search(r'\bid="([^"]+)"', tag)
        href_m = re.search(r'\bhref="([^"]+)"', tag)
        if id_m and href_m:
            manifest[id_m.group(1)] = href_m.group(1)

    hrefs: list[str] = []
    for idref in re.findall(r"<itemref\b[^>]*\bidref=\"([^\"]+)\"", opf):
        href = manifest.get(idref)
        if not href:
            continue
        full = (base + href) if base else href
        full = full.split("#", 1)[0]
        if full in names:
            hrefs.append(full)
    return hrefs


def _office_zip_to_text(data: bytes) -> str:
    """未知扩展名的 zip：依次尝试 docx / odt / epub。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        raise FileReadError("压缩包已损坏。") from None
    if "word/document.xml" in names:
        return _docx_to_text(data)
    if "content.xml" in names:
        return _odt_to_text(data)
    if "META-INF/container.xml" in names:
        return _epub_to_text(data)
    raise FileReadError("压缩包里没有可读取的文档正文。")


# ── RTF ────────────────────────────────────────

_RTF_SKIP_DESTINATIONS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "object", "objdata",
    "header", "headerl", "headerr", "headerf", "footer", "footerl", "footerr",
    "footerf", "footnote", "listtable", "listoverridetable", "rsidtbl",
    "generator", "xmlnstbl", "themedata", "datastore", "latentstyles",
}

_RTF_CODEPAGES = {
    "936": "gb18030",
    "950": "big5",
    "932": "cp932",
    "949": "cp949",
    "65001": "utf-8",
}


def _int_param(param: str, default: int) -> int:
    try:
        return int(param)
    except ValueError:
        return default


def _rtf_to_text(data: bytes) -> str:
    """轻量 RTF → 纯文本：处理段落、换行、制表、\\uN 与 \\'hh。"""
    raw = data.decode("latin-1", errors="replace")
    cp_match = re.search(r"\\ansicpg(\d+)", raw[:2048])
    codepage = _RTF_CODEPAGES.get(cp_match.group(1), "cp1252") if cp_match else "cp1252"

    out: list[str] = []
    stack: list[tuple[bool, int]] = []
    hexbuf = bytearray()
    skipping = False
    uc = 1  # \ucN：\uN 后面还有几个替代字符需要跳过
    i, n = 0, len(raw)

    def flush_hex() -> None:
        if not hexbuf:
            return
        try:
            out.append(hexbuf.decode(codepage, errors="replace"))
        except LookupError:
            out.append(hexbuf.decode("cp1252", errors="replace"))
        hexbuf.clear()

    while i < n:
        ch = raw[i]
        if ch == "{":
            flush_hex()
            stack.append((skipping, uc))
            i += 1
            continue
        if ch == "}":
            flush_hex()
            if stack:
                skipping, uc = stack.pop()
            i += 1
            continue
        if ch != "\\":
            if not skipping:
                out.append(ch)
            i += 1
            continue

        j = i + 1
        if j >= n:
            break
        if raw[j] in "\\{}":
            if not skipping:
                flush_hex()
                out.append(raw[j])
            i = j + 1
            continue
        if raw[j] == "*":
            flush_hex()
            skipping = True
            i = j + 1
            continue
        if raw[j] == "'":
            if not skipping:
                try:
                    hexbuf.append(int(raw[j + 1 : j + 3], 16))
                except ValueError:
                    pass
            i = j + 3
            continue
        if not raw[j].isalpha():
            # \\- \\~ \\_ 等符号控制字
            if not skipping and raw[j] in "~_":
                flush_hex()
                out.append(" " if raw[j] == "~" else "-")
            i = j + 1
            continue

        k = j
        while k < n and raw[k].isalpha():
            k += 1
        word = raw[j:k]
        p = k
        if p < n and (raw[p] == "-" or raw[p].isdigit()):
            p += 1
            while p < n and raw[p].isdigit():
                p += 1
        param = raw[k:p]
        had_space = p < n and raw[p] == " "
        if had_space:
            p += 1
        i = p

        if skipping:
            continue
        if word in _RTF_SKIP_DESTINATIONS:
            flush_hex()
            skipping = True
            continue
        if word in {"par", "line", "sect", "page"}:
            flush_hex()
            out.append("\n")
        elif word == "tab":
            flush_hex()
            out.append("\t")
        elif word == "uc" and param:
            uc = max(0, min(_int_param(param, 1), 16))
        elif word == "u" and param:
            flush_hex()
            code = _int_param(param, -1)
            if code < 0:
                code += 65536
            if 0 <= code <= 0x10FFFF:
                out.append(chr(code))
            # 紧跟在 \uN 后面的是回退字符（通常是 ?）；有空格分隔时不跳过
            if not had_space:
                skipped = 0
                while skipped < uc and i < n and raw[i] not in "\\{}":
                    i += 1
                    skipped += 1
        elif word == "emdash":
            flush_hex()
            out.append("—")
        elif word == "endash":
            flush_hex()
            out.append("–")

    flush_hex()
    text = "".join(out)
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── PDF ────────────────────────────────────────


def _pdf_to_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise FileReadError(
            "未安装 pypdf，无法解析 PDF。请运行 pip install pypdf，或改用 txt / docx。"
        ) from None

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - pypdf 的异常类型不稳定
        raise FileReadError(f"PDF 解析失败：{exc}") from None
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            raise FileReadError("PDF 已加密，无法读取正文。") from None

    pages: list[str] = []
    for page in reader.pages[:MAX_PDF_PAGES]:
        try:
            pages.append((page.extract_text() or "").strip())
        except Exception:  # noqa: BLE001 - 个别损坏页面不影响整体
            continue
    return "\n\n".join(p for p in pages if p)


# ── 旧版 .doc（OLE 容器）────────────────────────


def _doc_to_text(data: bytes) -> str:
    if data.startswith(_ZIP_MAGIC):
        return _docx_to_text(data)
    if _is_rtf(data):
        return _rtf_to_text(data)
    if _looks_like_html(data):
        return _html_to_text(_decode_text(data))
    if not data.startswith(_OLE_MAGIC):
        # 有些 .doc 其实是纯文本或未知内容
        return _decode_text(data)

    text = _convert_with_external_tool(data)
    if text is None:
        raise FileReadError(
            "旧版 .doc（Word 97-2003）需要本机安装 LibreOffice 或 antiword 才能解析。"
            "请用 Word 另存为 .docx / .txt 后重试，或直接粘贴正文。"
        )
    return text


def _looks_like_html(data: bytes) -> bool:
    head = data[:1024].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head", b"<body"))


def _convert_with_external_tool(data: bytes) -> str | None:
    """依次尝试 antiword、catdoc、LibreOffice；都没有则返回 None。"""
    tmpdir = Path(tempfile.mkdtemp(prefix="econread-doc-"))
    try:
        src = tmpdir / "upload.doc"
        src.write_bytes(data)

        for cmd in (["antiword", str(src)], ["catdoc", "-w", str(src)]):
            exe = shutil.which(cmd[0])
            if not exe:
                continue
            try:
                proc = subprocess.run(
                    [exe, *cmd[1:]], capture_output=True, timeout=60, check=False
                )
            except (OSError, subprocess.SubprocessError):
                continue
            text = _decode_tool_output(proc.stdout)
            if text.strip():
                return text

        soffice = _find_soffice()
        if soffice:
            try:
                subprocess.run(
                    [soffice, "--headless", "--convert-to", "txt:Text",
                     "--outdir", str(tmpdir), str(src)],
                    capture_output=True, timeout=120, check=False,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            txt = tmpdir / "upload.txt"
            if txt.exists():
                return _decode_tool_output(txt.read_bytes())
        return None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _decode_tool_output(raw: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _find_soffice() -> str | None:
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    if Path("C:/Program Files/LibreOffice/program/soffice.exe").is_file():
        return "C:/Program Files/LibreOffice/program/soffice.exe"
    if Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe").is_file():
        return "C:/Program Files (x86)/LibreOffice/program/soffice.exe"
    return None
