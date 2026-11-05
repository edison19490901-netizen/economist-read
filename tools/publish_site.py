"""把 output/ 里已生成的分析发布成 GitHub Pages 站点。

用法：
    python tools/publish_site.py          # 只重建 docs/ 并写入索引页
    python tools/publish_site.py --check  # 只报告会发布哪些文章
    python tools/publish_site.py --push   # 重建后自动提交 docs/ + output/ 并推送

Pages 只能托管静态文件，所以这里做的事情很单纯：把每篇的 workbook.html
复制成 docs/<id>/index.html，再生成一个列出全部文章的 docs/index.html。
新分析生成后跑一次 `--push` 即可完成发布与上传。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
DOCS_DIR = BASE_DIR / "docs"
SITE_DIR = BASE_DIR / "site"  # 图标、manifest 等静态资源，整份复制到 docs/

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light">
<title>经济学人精读</title>
<link rel="icon" href="icons/favicon-32.png" sizes="32x32">
<link rel="icon" href="icons/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="icons/apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<meta name="theme-color" content="#e3120b">
<meta name="apple-mobile-web-app-title" content="精读">
<meta name="apple-mobile-web-app-capable" content="yes">
<style>
  :root{--accent:#e3120b;--ink:#12263a;--muted:#6b7280;--bg:#f4f1ec;--line:#e6e0d8;--card:#fffdf8}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
       background:var(--bg);color:var(--ink);line-height:1.6;-webkit-text-size-adjust:100%}
  .wrap{max-width:760px;margin:0 auto;padding:36px 18px 72px}
  .kicker{font-size:10px;letter-spacing:.22em;color:var(--accent);font-weight:800}
  h1{font-size:26px;letter-spacing:-.02em;margin:8px 0 6px}
  .sub{color:var(--muted);font-size:14px}
  .rule{height:3px;width:56px;background:var(--accent);margin:22px 0 26px}
  ul{list-style:none;display:grid;gap:12px}
  li a{display:block;text-decoration:none;color:var(--ink);background:var(--card);
       border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;
       padding:16px 18px;transition:border-color .15s,transform .15s}
  li a:hover{border-color:#e9b7b2;transform:translateY(-1px)}
  .t{font-size:16px;font-weight:800;line-height:1.4}
  .m{display:flex;gap:14px;flex-wrap:wrap;color:var(--muted);font-size:12.5px;margin-top:8px}
  .m b{color:var(--accent);font-weight:700}
  .empty{color:var(--muted);font-size:14px;padding:22px;text-align:center;
         border:1px dashed var(--line);border-radius:10px}
  footer{margin-top:40px;color:var(--muted);font-size:12px;line-height:1.8;
         border-top:1px solid var(--line);padding-top:18px}
  @media(max-width:520px){h1{font-size:22px}.wrap{padding:26px 14px 56px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="kicker">THE ECONOMIST · 精读</div>
  <h1>精读看板</h1>
  <div class="sub">在电脑上分析，在手机上读。点开任意一篇即可查看八个面板。</div>
  <div class="rule"></div>
  {% if items %}
  <ul>
    {% for it in items %}
    <li><a href="{{ it.href }}">
      <div class="t">{{ it.title }}</div>
      <div class="m">
        <span>{{ it.created }}</span>
        <span><b>{{ it.words }}</b> 词</span>
        <span>{{ it.paragraphs }} 段</span>
        <span><b>{{ it.vocab }}</b> 生词</span>
        <span><b>{{ it.chunks }}</b> 背诵块</span>
      </div>
    </a></li>
    {% endfor %}
  </ul>
  {% else %}
  <div class="empty">还没有已发布的分析。</div>
  {% endif %}
  <footer>
    共 {{ items|length }} 篇 · 更新于 {{ updated }}<br>
    本站为静态页面，只读；新的文章请在本机运行 app.py 生成后重新发布。
  </footer>
</div>
</body>
</html>
"""


def _collect() -> list[dict]:
    """扫描 output/，返回可发布的文章列表（按分析时间倒序）。"""
    items: list[dict] = []
    if not OUTPUT_DIR.exists():
        return items
    for folder in OUTPUT_DIR.iterdir():
        if not folder.is_dir():
            continue
        analysis_path = folder / "analysis.json"
        workbook_path = folder / "workbook.html"
        if not (analysis_path.exists() and workbook_path.exists()):
            continue
        try:
            data = json.loads(analysis_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[skip] {folder.name}: {exc}")
            continue
        meta = data.get("meta") or {}
        recitation = data.get("recitation") or {}
        items.append(
            {
                "id": folder.name,
                "href": f"{folder.name}/",
                "title": (meta.get("title") or folder.name).strip(),
                "created": (meta.get("created") or "")[:10],
                "words": meta.get("word_count", 0),
                "paragraphs": meta.get("paragraph_count", 0),
                "vocab": len(data.get("vocabulary") or []),
                "chunks": len(recitation.get("chunks") or []),
                "sort": meta.get("created") or "",
                "workbook": workbook_path,
            }
        )
    items.sort(key=lambda x: x["sort"], reverse=True)
    return items


def _render_index(items: list[dict], updated: str) -> str:
    from jinja2 import Environment

    env = Environment(autoescape=True)
    return env.from_string(INDEX_HTML).render(items=items, updated=updated)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(BASE_DIR), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _push_site(items: list[dict]) -> int:
    """提交 docs/ 与 output/ 的改动并推送到当前分支的上游。"""
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        print("当前目录不是 Git 仓库，无法自动提交/推送。")
        return 1

    added = _git("add", "--", "docs", "output")
    if added.returncode != 0:
        print(f"git add 失败：{added.stderr.strip()}")
        return 1

    if _git("diff", "--cached", "--quiet", "--", "docs", "output").returncode != 0:
        message = f"发布站点：{items[0]['title']}（共 {len(items)} 篇）"
        # 只提交 docs/ 与 output/，不把用户其他已暂存的改动带进来
        committed = _git("commit", "-m", message, "--", "docs", "output")
        if committed.returncode != 0:
            print(f"git commit 失败：{committed.stderr.strip() or committed.stdout.strip()}")
            return 1
        print(f"已提交：{message}")
    else:
        print("docs/ 与 output/ 没有变化，跳过提交。")

    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    has_upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    push_args = ["push", "origin", branch]
    if has_upstream.returncode == 0:
        ahead = _git("rev-list", "--count", "@{u}..HEAD")
        if ahead.returncode == 0 and ahead.stdout.strip() == "0":
            print("没有待推送的提交，已是最新。")
            return 0
    else:
        push_args = ["push", "-u", "origin", branch]

    pushed = _git(*push_args)
    if pushed.returncode != 0:
        print(f"git push 失败：{pushed.stderr.strip() or pushed.stdout.strip()}")
        return 1
    print(f"已推送到 origin/{branch}，GitHub Pages 约 1 分钟后更新。")
    return 0


def main() -> int:
    check = "--check" in sys.argv
    push = "--push" in sys.argv
    items = _collect()
    if not items:
        print("output/ 里没有可发布的分析（需要同时存在 analysis.json 和 workbook.html）。")
        return 0

    print(f"待发布 {len(items)} 篇：")
    for it in items:
        print(f"  - {it['id']}  ({it['words']} 词)")

    if check:
        return 0

    if DOCS_DIR.exists():
        shutil.rmtree(DOCS_DIR)
    DOCS_DIR.mkdir(parents=True)

    # 先铺静态资源（图标、manifest），再生成页面
    if SITE_DIR.exists():
        for src in SITE_DIR.iterdir():
            dest = DOCS_DIR / src.name
            if src.is_dir():
                shutil.copytree(src, dest)
            else:
                shutil.copyfile(src, dest)

    # 关掉 Jekyll，避免下划线开头或含特殊字符的路径被处理
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    for it in items:
        target = DOCS_DIR / it["id"]
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(it["workbook"], target / "index.html")

    # 用最新一篇文章的日期而不是构建时间，保证没有新内容时重建结果完全一致，
    # 这样 --push 才能判断“没有改动”并跳过空提交。
    updated = items[0]["created"] or "—"
    (DOCS_DIR / "index.html").write_text(
        _render_index(items, updated), encoding="utf-8"
    )
    print(f"已写入 {DOCS_DIR}")
    if push:
        return _push_site(items)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
