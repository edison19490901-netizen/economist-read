"""《经济学人》精读 — 本地 Web 应用。"""

from __future__ import annotations

import json
import os
import re
import shutil
import traceback
from datetime import datetime
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, send_file, url_for

from economist_read.analyzer import analyze_article, save_analysis
from economist_read.downloader import fetch_web_article
from economist_read.outputs.workbook import generate
from economist_read.parser import (
    cap_paragraphs,
    detect_language,
    guess_title,
    join_paragraphs,
    split_paragraphs,
)
from economist_read.utils import make_output_id, now_iso

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SOURCE_LABELS = {"paste": "粘贴文本", "url": "网页链接"}
MIN_WORDS = 80
MIN_CHARS = 500

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024


# ── 配置 ──────────────────────────────────────


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


def _load_api_key() -> str:
    _load_env_file(BASE_DIR / ".env")
    return os.environ.get("DEEPSEEK_API_KEY", "").strip()


def _model() -> str:
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"


def _max_workers() -> int:
    try:
        return max(1, min(6, int(os.environ.get("DEEPSEEK_MAX_WORKERS", "3"))))
    except ValueError:
        return 3


# ── 最近分析 ───────────────────────────────────


def _recent_analyses(limit: int = 5) -> list[dict]:
    items: list[dict] = []
    for folder in OUTPUT_DIR.iterdir():
        if not folder.is_dir():
            continue
        analysis = folder / "analysis.json"
        if not analysis.exists():
            continue
        try:
            data = json.loads(analysis.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        meta = data.get("meta") or {}
        items.append(
            {
                "id": folder.name,
                "title": meta.get("title") or folder.name,
                "created": (meta.get("created") or "")[:16].replace("T", " "),
                "words": meta.get("word_count", 0),
                "cost": (data.get("usage") or {}).get("cost_cny", 0),
                "source": SOURCE_LABELS.get(meta.get("source", ""), "文章"),
                "mtime": analysis.stat().st_mtime,
            }
        )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


# ── 首页 ──────────────────────────────────────


HOME_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>经济学人精读</title>
<style>
  :root{--accent:#e3120b;--ink:#12263a;--muted:#6b7280;--bg:#f4f1ec;--line:#e6e0d8}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--ink);line-height:1.6}
  .wrap{max-width:860px;margin:0 auto;padding:32px 16px 64px}
  header{margin-bottom:22px}
  .kicker{font-size:10px;letter-spacing:.22em;color:var(--accent);font-weight:800}
  h1{font-size:27px;letter-spacing:-.02em;margin:6px 0 6px}
  .sub{color:var(--muted);font-size:14px}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px;box-shadow:0 2px 10px rgba(18,38,58,.05)}
  fieldset{border:0;margin-bottom:16px}
  label{display:block;font-size:12px;font-weight:700;color:var(--ink);margin-bottom:6px}
  .hint{font-weight:400;color:var(--muted)}
  input[type=text],input[type=url],textarea{width:100%;border:1px solid var(--line);border-radius:9px;padding:10px 12px;font-size:14px;font-family:inherit;background:#fdfcf9;color:var(--ink);outline:none;transition:border-color .15s,box-shadow .15s}
  input:focus,textarea:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(227,18,11,.08)}
  textarea{min-height:260px;resize:vertical;line-height:1.7}
  .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:16px}
  button{border:0;background:var(--accent);color:#fff;border-radius:9px;padding:11px 22px;font-size:14px;font-weight:800;cursor:pointer;font-family:inherit;box-shadow:0 3px 10px rgba(227,18,11,.22)}
  button:disabled{opacity:.6;cursor:wait}
  .divider{display:flex;align-items:center;gap:10px;color:var(--muted);font-size:12px;margin:6px 0 16px}
  .divider:before,.divider:after{content:"";height:1px;background:var(--line);flex:1}
  .error{background:#fdf2f2;border:1px solid #f3c2c0;color:#8a1f1a;border-radius:9px;padding:10px 14px;font-size:13px;margin-bottom:16px;white-space:pre-wrap}
  .note{background:#fff8e6;border:1px solid #f0d9a8;color:#7a4a00;border-radius:9px;padding:10px 14px;font-size:13px;margin-bottom:16px}
  h2{font-size:15px;margin:26px 0 10px}
  .recent{list-style:none;display:grid;gap:8px}
  .recent a{display:flex;gap:10px;align-items:baseline;justify-content:space-between;text-decoration:none;color:var(--ink);background:#fff;border:1px solid var(--line);border-radius:10px;padding:11px 14px;font-size:13.5px;transition:border-color .15s}
  .recent a:hover{border-color:var(--accent)}
  .recent .t{font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .recent .m{color:var(--muted);font-size:11px;white-space:nowrap}
  .empty{color:var(--muted);font-size:13px;padding:14px;text-align:center;border:1px dashed var(--line);border-radius:10px}
  .spinner{display:none;margin-left:10px;font-size:13px;color:var(--muted)}
  @media(max-width:520px){h1{font-size:22px}.card{padding:16px}}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="kicker">THE ECONOMIST · 精读</div>
    <h1>经济学人精读</h1>
    <div class="sub">粘贴正文或网页链接，生成八栏交互看板：总结 · 翻译 · 词汇 · 拆解 · 背景 · 应用 · 背诵 · 统计。</div>
  </header>

  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  {% if not has_key %}<div class="note">未检测到 DEEPSEEK_API_KEY。请在项目根目录创建 <code>.env</code>，写入 <code>DEEPSEEK_API_KEY=sk-...</code>。</div>{% endif %}

  <form class="card" method="post" action="/process" onsubmit="document.getElementById('go').disabled=true;document.getElementById('go').textContent='分析中…';document.getElementById('spin').style.display='inline';">
    <fieldset>
      <label for="text">文章正文 <span class="hint">（优先使用；直接粘贴英文全文）</span></label>
      <textarea id="text" name="text" placeholder="Paste the full English article here…">{{ text }}</textarea>
    </fieldset>
    <div class="divider">或者</div>
    <fieldset>
      <label for="url">网页链接 <span class="hint">（仅当正文为空时使用）</span></label>
      <input type="url" id="url" name="url" placeholder="https://www.economist.com/…" value="{{ url }}">
    </fieldset>
    <fieldset>
      <label for="title">文章标题 <span class="hint">（可选，留空自动识别）</span></label>
      <input type="text" id="title" name="title" placeholder="例如：Does China really prize AI speed over safety?" value="{{ title }}">
    </fieldset>
    <div class="row">
      <button id="go" type="submit">开始精读</button>
      <span class="spinner" id="spin">通常需要 30-90 秒，请勿关闭页面。</span>
    </div>
  </form>

  <h2>最近分析</h2>
  {% if recent %}
  <ul class="recent">
    {% for r in recent %}
    <li><a href="/result/{{ r.id }}">
      <span class="t">{{ r.title }}</span>
      <span class="m">{{ r.created }} · {{ r.words }} 词 · ¥{{ "%.4f"|format(r.cost) }}</span>
    </a></li>
    {% endfor %}
  </ul>
  {% else %}
  <div class="empty">还没有分析记录。粘贴一篇文章开始吧。</div>
  {% endif %}
</div>
<script>
  var ta = document.getElementById('text');
  if (ta && !ta.value.trim()) ta.focus();
</script>
</body>
</html>
"""


def _home_context(**extra) -> dict:
    ctx = {
        "error": "",
        "has_key": bool(_load_api_key()),
        "recent": _recent_analyses(),
        "text": "",
        "url": "",
        "title": "",
    }
    ctx.update(extra)
    return ctx


@app.get("/")
def index():
    return render_template_string(HOME_HTML, **_home_context())


# ── 处理 ──────────────────────────────────────


def _fail(message: str, text: str, url: str, title: str):
    return (
        render_template_string(
            HOME_HTML,
            **_home_context(error=message, text=text, url=url, title=title),
        ),
        400,
    )


@app.post("/process")
def process():
    text = (request.form.get("text") or "").strip()
    url = (request.form.get("url") or "").strip()
    title = (request.form.get("title") or "").strip()

    api_key = _load_api_key()
    if not api_key:
        return _fail("未找到 DEEPSEEK_API_KEY，请先配置 .env。", text, url, title)

    source = "paste"
    site = ""
    if text:
        paragraphs = split_paragraphs(text)
    elif url:
        source = "url"
        try:
            article = fetch_web_article(url)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"网页抓取失败：{exc}\n可以改用「粘贴正文」。", text, url, title)
        paragraphs = split_paragraphs(article.text)
        title = title or article.title
        site = article.site
        text = join_paragraphs(paragraphs)
    else:
        return _fail("请粘贴文章正文，或输入网页链接。", text, url, title)

    if not paragraphs:
        return _fail("没有解析出正文段落，请检查内容。", text, url, title)

    cleaned = join_paragraphs(paragraphs)
    words = len(re.findall(r"[A-Za-z0-9']+", cleaned))
    if words < MIN_WORDS or len(cleaned) < MIN_CHARS:
        return _fail(
            f"内容过短（{words} 词 / {len(cleaned)} 字符），至少需要 {MIN_WORDS} 词或 {MIN_CHARS} 字符。",
            text,
            url,
            title,
        )
    language = detect_language(cleaned)
    if language != "en":
        return _fail("本工具面向英文文章，检测到正文可能不是英文。", text, url, title)

    paragraphs, truncated = cap_paragraphs(paragraphs)
    full_text = join_paragraphs(paragraphs)
    if not title:
        title = guess_title(paragraphs) or (site and f"{site} 文章") or "未命名文章"
    title = title.strip()[:160]

    output_id = make_output_id(title, full_text, OUTPUT_DIR)
    folder = OUTPUT_DIR / output_id
    folder.mkdir(parents=True, exist_ok=False)

    started = datetime.now()
    try:
        result = analyze_article(
            paragraphs,
            title,
            output_id=output_id,
            source=source,
            url=url or None,
            language=language,
            truncated=truncated,
            api_key=api_key,
            model=_model(),
            max_workers=_max_workers(),
        )
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        try:
            folder.rmdir()
        except OSError:
            pass
        return _fail(f"分析失败：{exc}", text, url, title)

    source_data = {
        "title": title,
        "url": url or None,
        "site": site,
        "source": source,
        "created": now_iso(),
        "language": language,
        "word_count": result.meta.word_count,
        "paragraph_count": result.meta.paragraph_count,
        "truncated": truncated,
        "full_text": full_text,
    }
    try:
        (folder / "source.json").write_text(
            json.dumps(source_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        save_analysis(result, folder / "analysis.json")
        generate(result, source_data, folder / "workbook.html")
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        shutil.rmtree(folder, ignore_errors=True)
        return _fail(f"结果保存失败：{exc}", text, url, title)

    elapsed = (datetime.now() - started).total_seconds()
    print(f"[done] {output_id} · {result.meta.word_count} words · {elapsed:.1f}s")
    return redirect(url_for("result", output_id=output_id))


# ── 结果 ──────────────────────────────────────

_ID_RE = re.compile(r"^[\w一-鿿-]+$")


@app.get("/result/<output_id>")
def result(output_id: str):
    if not _ID_RE.match(output_id):
        return "无效的分析 ID", 404
    folder = (OUTPUT_DIR / output_id).resolve()
    try:
        folder.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return "无效的分析 ID", 404
    page = folder / "workbook.html"
    if not page.exists():
        return "找不到该分析", 404
    return send_file(page, mimetype="text/html")


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5001"))
    print(f"经济学人精读 http://{host}:{port}")
    app.run(host=host, port=port, debug=False, threaded=True)
