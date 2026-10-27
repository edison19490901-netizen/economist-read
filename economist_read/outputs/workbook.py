"""精读看板 HTML 生成器。"""

import html
import json
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from ..analyzer import _words
from ..recite.utils import estimate_recite_minutes, first_letter_hint
from ..schema import AnalysisResult
from ..utils import format_duration

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

_SOURCE_LABELS = {"paste": "粘贴文本", "url": "网页链接"}


def generate(result: AnalysisResult, source: dict, output_path: Path) -> Path:
    """渲染精读看板。source 保存原始信息（full_text 等）。"""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    template = env.get_template("article.html.j2")

    term_map = {}
    vocab_rows = []
    for v in result.vocabulary:
        if v.word:
            term_map.setdefault(_norm_term(v.word), v.id or f"v{len(vocab_rows) + 1}")
        vocab_rows.append({
            "id": v.id,
            "word": v.word,
            "context_sentence": v.context_sentence,
            "paragraph_index": v.paragraph_index,
            "difficulty": v.difficulty,
            "chinese_note": v.chinese_note,
        })

    paragraphs = []
    for p in result.paragraphs:
        paragraphs.append({
            "index": p.index,
            "en_html": annotate_paragraph(p.en, term_map),
            "zh": p.zh,
            "word_count": len(_words(p.en)),
        })

    vocab_map = {
        v.id: {
            "word": v.word,
            "note": v.chinese_note,
            "difficulty": v.difficulty,
            "para": v.paragraph_index,
        }
        for v in result.vocabulary
        if v.id
    }

    long_sentences = [
        {
            "id": s.id,
            "sentence": s.sentence,
            "paragraph_index": s.paragraph_index,
            "main_clause": s.main_clause,
            "subordinate_clauses": s.subordinate_clauses,
            "modifiers": s.modifiers,
            "translation": s.translation,
            "note": s.note,
        }
        for s in result.long_sentences
    ]

    chunks = []
    for c in result.recitation.chunks:
        chunks.append({
            "index": c.index,
            "text": c.text,
            "hint": c.hint,
            "translation": c.translation,
            "paragraph_start": c.paragraph_start,
            "paragraph_end": c.paragraph_end,
            "word_count": len(_words(c.text)),
            "first_hint": first_letter_hint(c.text, "en"),
        })

    schedule = result.recitation.schedule or {}
    total_words = result.meta.word_count
    usage = result.usage

    context = {
        "meta": result.meta,
        "title": result.meta.title or "未命名文章",
        "source_label": _SOURCE_LABELS.get(result.meta.source, "文章"),
        "created_date": (result.meta.created or "")[:10],
        "duration": format_duration(result.meta.duration_seconds),
        "truncated": result.meta.truncated,
        "summary": result.summary,
        "paragraphs": paragraphs,
        "paragraph_count": len(paragraphs),
        "vocab_rows": vocab_rows,
        "vocab_count": len(vocab_rows),
        "vocab_map_json": json.dumps(vocab_map, ensure_ascii=False).replace("</", "<\\/"),
        "long_sentences": long_sentences,
        "long_count": len(long_sentences),
        "deconstruction": result.deconstruction,
        "section_count": len(result.deconstruction.sections),
        "technique_count": len(result.deconstruction.writing_techniques),
        "background": result.background,
        "practical": result.practical_application,
        "skill_count": len(result.practical_application.actionable_skills),
        "model_count": len(result.practical_application.thinking_models),
        "recitation": result.recitation,
        "chunks": chunks,
        "chunk_count": len(chunks),
        "schedule": schedule,
        "est_minutes": estimate_recite_minutes(total_words, "en"),
        "usage": usage,
        "warnings": result.warnings,
        "material_id": result.meta.id,
    }

    rendered = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return output_path


# ── 生词标注 ──────────────────────────────────────


def annotate_paragraph(text: str, term_map: dict[str, str]) -> str:
    """把段落中的生词包成可点击的 span，其余文本 HTML 转义。"""
    if not text:
        return ""
    terms = sorted(term_map, key=len, reverse=True)
    if not terms:
        return html.escape(text)

    pattern = "|".join(_term_pattern(t) for t in terms)
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error:
        return html.escape(text)

    out: list[str] = []
    last = 0
    for m in regex.finditer(text):
        out.append(html.escape(text[last:m.start()]))
        matched = m.group(0)
        vid = term_map.get(_norm_term(matched))
        if vid:
            out.append(
                f'<span class="w" data-vid="{html.escape(vid)}" '
                f'data-w="{html.escape(matched)}">{html.escape(matched)}</span>'
            )
        else:
            out.append(html.escape(matched))
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out)


def _term_pattern(term: str) -> str:
    parts = [re.escape(p) for p in term.split()]
    body = r"\s+".join(parts)
    return rf"(?<![A-Za-z0-9]){body}(?![A-Za-z0-9])"


def _norm_term(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())
