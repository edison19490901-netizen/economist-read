"""命令行精读：分析本地文本/文档，生成看板并自动打开。

用法：
    python tools/analyze_text.py                     # 自动找当前目录下的文本文件
    python tools/analyze_text.py article.txt
    python tools/analyze_text.py article.docx --title "自定义标题" --no-open

也可以把文件拖到项目根目录的 analyze.bat 上，或把文本和 analyze.bat
放在同一目录后双击（同目录有多个候选文件时会列出让你选）。
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from economist_read.file_reader import FileReadError, extract_text  # noqa: E402
from economist_read.parser import split_paragraphs  # noqa: E402

import app as appmod  # noqa: E402

# 自动扫描时认这些后缀；拖拽/显式传参则交给 file_reader 按内容判断
CANDIDATE_EXTS = {
    ".txt", ".text", ".md", ".markdown", ".rst", ".log",
    ".docx", ".doc", ".docm", ".odt", ".rtf", ".pdf", ".epub",
    ".html", ".htm", ".xhtml",
}

# 项目自身的说明文件，不作为待分析文章
SKIP_STEMS = {"readme", "handoff", "requirements", "license", "changelog"}


def _candidates(folder: Path) -> list[Path]:
    files = []
    for path in folder.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in CANDIDATE_EXTS:
            continue
        if path.stem.lower() in SKIP_STEMS:
            continue
        files.append(path)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def _choose_file(folder: Path) -> Path | None:
    files = _candidates(folder)
    if not files:
        print(f"在 {folder} 里没有找到可分析的文本文件。")
        print("请把文章放到这个目录，或把文件直接拖到 analyze.bat 上。")
        print(f"支持的格式：{'、'.join(sorted(e.lstrip('.') for e in CANDIDATE_EXTS))}")
        return None
    if len(files) == 1:
        return files[0]

    print(f"在 {folder} 找到 {len(files)} 个候选文件：")
    for i, path in enumerate(files, 1):
        size_kb = path.stat().st_size / 1024
        print(f"  [{i}] {path.name}  ({size_kb:.0f} KB)")
    try:
        raw = input("输入序号选择要分析的文章（直接回车退出）：").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    try:
        index = int(raw)
    except ValueError:
        print("输入的不是序号。")
        return None
    if not 1 <= index <= len(files):
        print("序号超出范围。")
        return None
    return files[index - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description="把本地文件分析成《经济学人》精读看板")
    parser.add_argument("path", nargs="?", help="要分析的文件；省略则在当前目录自动查找")
    parser.add_argument("--title", default="", help="文章标题，留空自动识别")
    parser.add_argument("--no-open", action="store_true", help="生成后不自动打开浏览器")
    parser.add_argument("--auto", action="store_true", help="在当前目录自动查找文件")
    args = parser.parse_args()

    if args.path:
        path = Path(args.path).expanduser()
        if not path.is_file():
            print(f"找不到文件：{path}")
            return 1
        path = path.resolve()
    else:
        path = _choose_file(Path.cwd())
        if path is None:
            return 1

    api_key = appmod._load_api_key()
    if not api_key:
        print("未找到 DEEPSEEK_API_KEY。请在项目根目录的 .env 里写入：")
        print("DEEPSEEK_API_KEY=sk-...")
        return 1

    try:
        raw = path.read_bytes()
        text = extract_text(path.name, raw)
    except OSError as exc:
        print(f"[失败] 读取文件出错：{exc}")
        return 1
    except FileReadError as exc:
        print(f"[失败] {exc}")
        return 1

    paragraphs = split_paragraphs(text, strip_html=False)
    print(f"文件：{path}")
    print(f"正文：{len(paragraphs)} 段，约 {len(text)} 字符")
    print("正在分析（通常需要 30–90 秒，请勿关闭窗口）……")

    try:
        output_id, result = appmod.run_analysis(
            paragraphs,
            api_key=api_key,
            title=args.title,
            source="file",
            file_name=path.name,
        )
    except appmod.InputError as exc:
        print(f"[失败] {exc}")
        return 1

    page = appmod.OUTPUT_DIR / output_id / "workbook.html"
    cost = getattr(result.usage, "cost_cny", 0.0)
    print(f"完成：{result.meta.word_count} 词 · {result.meta.paragraph_count} 段 · ¥{cost:.4f}")
    if result.warnings:
        print(f"提示：{len(result.warnings)} 条警告，详情见 analysis.json")
    print(f"看板：{page}")

    if not args.no_open:
        webbrowser.open(page.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
