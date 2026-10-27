"""精读分析编排：四路并行调用 + 校验 + 兜底。"""

import difflib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .llm import CallUsage, OutputTruncated, chat_json
from .prompts import (
    build_core_prompt,
    build_language_prompt,
    build_recitation_prompt,
    build_translation_prompt,
)
from .recite.planner import build_schedule
from .schema import (
    AnalysisResult,
    Background,
    Deconstruction,
    LongSentence,
    Meta,
    Paragraph,
    PracticalApplication,
    Recitation,
    RecitationChunk,
    Summary,
    UsageInfo,
    VocabularyItem,
)
from .utils import now_iso

MAX_TEXT_CHARS = 60_000
TRANSLATION_MAX_CHARS = 4_500
TRANSLATION_MAX_ITEMS = 8


# ── 主入口 ──────────────────────────────────────


def analyze_article(
    paragraphs: list[str],
    title: str = "",
    *,
    output_id: str = "",
    source: str = "paste",
    url: str | None = None,
    language: str = "en",
    truncated: bool = False,
    api_key: str | None = None,
    model: str = "deepseek-chat",
    max_workers: int = 3,
) -> AnalysisResult:
    """对文章段落做完整精读分析。"""
    paragraphs = [p.strip() for p in paragraphs if p and p.strip()]
    if not paragraphs:
        raise ValueError("文章内容为空，无法分析。")

    started = time.time()
    calls: list[CallUsage] = []
    warnings: list[str] = []

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        f_core = pool.submit(_run_core, paragraphs, title, api_key, model)
        f_trans = pool.submit(_run_translation, paragraphs, title, api_key, model)
        f_lang = pool.submit(_run_language, paragraphs, title, api_key, model)
        f_rec = pool.submit(_run_recitation, paragraphs, title, api_key, model)

        core_data = _gather(f_core, "核心分析", calls, warnings, required=True)
        trans_map = _gather(f_trans, "对照翻译", calls, warnings)
        lang_data = _gather(f_lang, "词汇长难句", calls, warnings)
        rec_data = _gather(f_rec, "背诵分块", calls, warnings)

    # 段落与译文
    trans_map = trans_map or {}
    out_paragraphs: list[Paragraph] = []
    missing_zh = []
    for i, en in enumerate(paragraphs, 1):
        zh = trans_map.get(i, "")
        if not zh:
            zh = "（本段翻译生成失败）"
            missing_zh.append(i)
        out_paragraphs.append(Paragraph(index=i, en=en, zh=zh))
    if missing_zh:
        warnings.append(f"有 {len(missing_zh)} 段翻译失败，已用占位符代替。")

    core_data = core_data or {}
    summary = Summary.from_dict(core_data.get("summary") or {})
    deconstruction = Deconstruction.from_dict(core_data.get("deconstruction") or {})
    background = Background.from_dict(core_data.get("background") or {})
    practical = PracticalApplication.from_dict(core_data.get("practical_application") or {})

    # 校验段落索引
    _clamp_deconstruction(deconstruction, len(paragraphs))
    _clamp_background(background, len(paragraphs))

    lang_data = lang_data or {}
    vocabulary = _build_vocabulary(lang_data.get("vocabulary") or [], paragraphs)
    long_sentences = _build_long_sentences(lang_data.get("long_sentences") or [], paragraphs)

    recitation = _build_recitation(rec_data or {}, out_paragraphs, warnings)

    usage = _sum_usage(calls)
    result = AnalysisResult(
        meta=Meta(
            id=output_id,
            title=title,
            source=source,
            url=url,
            language=language,
            created=now_iso(),
            model=model,
            word_count=sum(len(_words(p)) for p in paragraphs),
            paragraph_count=len(paragraphs),
            truncated=truncated,
            duration_seconds=round(time.time() - started, 1),
        ),
        summary=summary,
        paragraphs=out_paragraphs,
        vocabulary=vocabulary,
        long_sentences=long_sentences,
        deconstruction=deconstruction,
        background=background,
        practical_application=practical,
        recitation=recitation,
        usage=usage,
        warnings=warnings,
    )
    return result


# ── 四个 stage ───────────────────────────────────


def _run_core(paragraphs, title, api_key, model):
    calls: list[CallUsage] = []
    try:
        r = chat_json("core", build_core_prompt(paragraphs, title), api_key=api_key, model=model)
        calls.append(r.usage)
        return r.data, calls
    except OutputTruncated as e:
        if e.usage:
            calls.append(e.usage)

    # 输出截断：拆成两次
    r1 = chat_json(
        "core:summary_decon",
        build_core_prompt(paragraphs, title, part="summary_decon"),
        api_key=api_key,
        model=model,
    )
    calls.append(r1.usage)
    r2 = chat_json(
        "core:background_apply",
        build_core_prompt(paragraphs, title, part="background_apply"),
        api_key=api_key,
        model=model,
    )
    calls.append(r2.usage)
    return {**r1.data, **r2.data}, calls


def _run_translation(paragraphs, title, api_key, model):
    calls: list[CallUsage] = []
    batches = _translation_batches(paragraphs)
    result: dict[int, str] = {}
    for i, batch in enumerate(batches, 1):
        try:
            result.update(_translate_batch(batch, title, api_key, model, calls, f"translation:{i}"))
            continue
        except Exception:  # noqa: BLE001
            pass
        # 单批失败不阻塞其他批
        try:
            result.update(_translate_batch(batch, title, api_key, model, calls, f"translation:{i}:retry"))
        except Exception:  # noqa: BLE001
            pass
    return result, calls


def _translate_batch(batch, title, api_key, model, calls, stage):
    try:
        r = chat_json(stage, build_translation_prompt(batch, title), api_key=api_key, model=model)
        calls.append(r.usage)
        out: dict[int, str] = {}
        for item in r.data.get("translations") or []:
            if not isinstance(item, dict):
                continue
            idx = _to_int(item.get("index"))
            zh = (item.get("zh") or "").strip()
            if idx is not None and zh:
                out[idx] = zh
        return out
    except OutputTruncated as e:
        if e.usage:
            calls.append(e.usage)
        if len(batch) <= 1:
            raise
        mid = len(batch) // 2
        left = _translate_batch(batch[:mid], title, api_key, model, calls, stage + "a")
        right = _translate_batch(batch[mid:], title, api_key, model, calls, stage + "b")
        return {**left, **right}


def _run_language(paragraphs, title, api_key, model):
    calls: list[CallUsage] = []
    try:
        r = chat_json("language", build_language_prompt(paragraphs, title), api_key=api_key, model=model)
        calls.append(r.usage)
        return r.data, calls
    except OutputTruncated as e:
        if e.usage:
            calls.append(e.usage)

    v = chat_json(
        "language:vocab",
        build_language_prompt(paragraphs, title, part="vocab"),
        api_key=api_key,
        model=model,
    )
    calls.append(v.usage)
    l = chat_json(
        "language:long",
        build_language_prompt(paragraphs, title, part="long"),
        api_key=api_key,
        model=model,
    )
    calls.append(l.usage)
    return {**v.data, **l.data}, calls


def _run_recitation(paragraphs, title, api_key, model):
    calls: list[CallUsage] = []
    try:
        r = chat_json(
            "recitation", build_recitation_prompt(paragraphs, title), api_key=api_key, model=model
        )
        calls.append(r.usage)
        return r.data, calls
    except OutputTruncated as e:
        if e.usage:
            calls.append(e.usage)
        if len(paragraphs) <= 1:
            raise

    mid = len(paragraphs) // 2
    r1 = chat_json(
        "recitation:1", build_recitation_prompt(paragraphs[:mid], title), api_key=api_key, model=model
    )
    calls.append(r1.usage)
    r2 = chat_json(
        "recitation:2", build_recitation_prompt(paragraphs[mid:], title), api_key=api_key, model=model
    )
    calls.append(r2.usage)

    chunks = list(r1.data.get("chunks") or [])
    for c in r2.data.get("chunks") or []:
        if not isinstance(c, dict):
            continue
        c = dict(c)
        if _to_int(c.get("paragraph_start")) is not None:
            c["paragraph_start"] = _to_int(c.get("paragraph_start")) + mid
        if _to_int(c.get("paragraph_end")) is not None:
            c["paragraph_end"] = _to_int(c.get("paragraph_end")) + mid
        chunks.append(c)

    return {
        "title_suggested": r1.data.get("title_suggested") or r2.data.get("title_suggested") or "",
        "advice": r1.data.get("advice") or r2.data.get("advice") or "",
        "chunks": chunks,
    }, calls


# ── 汇总与校验 ───────────────────────────────────


def _gather(future, label, calls, warnings, required=False):
    try:
        data, used = future.result()
        calls.extend(used)
        return data
    except OutputTruncated as e:
        if e.usage:
            calls.append(e.usage)
        if required:
            raise RuntimeError(f"{label}失败：{e}") from e
        warnings.append(f"{label}输出被截断，已降级。")
        return None
    except Exception as e:  # noqa: BLE001
        if required:
            raise RuntimeError(f"{label}失败：{e}") from e
        warnings.append(f"{label}失败：{e}")
        return None


def _sum_usage(calls: list[CallUsage]) -> UsageInfo:
    p = sum(c.prompt_tokens for c in calls)
    co = sum(c.completion_tokens for c in calls)
    return UsageInfo(
        calls=calls,
        prompt_tokens=p,
        completion_tokens=co,
        total_tokens=p + co,
        cost_cny=round(sum(c.cost_cny for c in calls), 6),
    )


def _translation_batches(paragraphs: list[str]) -> list[list[tuple[int, str]]]:
    batches: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    chars = 0
    for i, p in enumerate(paragraphs, 1):
        if current and (chars + len(p) > TRANSLATION_MAX_CHARS or len(current) >= TRANSLATION_MAX_ITEMS):
            batches.append(current)
            current, chars = [], 0
        current.append((i, p))
        chars += len(p)
    if current:
        batches.append(current)
    return batches or [[(1, paragraphs[0])]]


def _build_vocabulary(raw, paragraphs) -> list[VocabularyItem]:
    out: list[VocabularyItem] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        v = VocabularyItem.from_dict(item)
        if not v.word or not v.chinese_note:
            continue
        key = v.word.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        v.id = v.id or f"v{len(out) + 1}"
        v.paragraph_index = _resolve_paragraph(v.context_sentence, v.paragraph_index, paragraphs)
        if v.paragraph_index is None and v.word:
            needle = _norm(v.word)
            for i, p in enumerate(paragraphs, 1):
                if needle and needle in _norm(p):
                    v.paragraph_index = i
                    break
        out.append(v)
        if len(out) >= 20:
            break
    return out


def _build_long_sentences(raw, paragraphs) -> list[LongSentence]:
    out: list[LongSentence] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        s = LongSentence.from_dict(item)
        if not s.sentence:
            continue
        s.id = s.id or f"s{len(out) + 1}"
        s.paragraph_index = _resolve_paragraph(s.sentence, s.paragraph_index, paragraphs)
        out.append(s)
    return out


def _clamp_deconstruction(d: Deconstruction, n: int) -> None:
    for sec in d.sections:
        sec.paragraph_indices = [i for i in sec.paragraph_indices if 1 <= i <= n]
    for t in d.writing_techniques:
        if t.paragraph_index is not None and not (1 <= t.paragraph_index <= n):
            t.paragraph_index = None


def _clamp_background(b: Background, n: int) -> None:
    for f in b.key_facts:
        if f.paragraph_index is not None and not (1 <= f.paragraph_index <= n):
            f.paragraph_index = None


def _resolve_paragraph(text: str, claimed: int | None, paragraphs: list[str]) -> int | None:
    """把引用文本定位到段落：先信 claimed，再做子串/模糊匹配。"""
    if not text:
        return claimed
    n = len(paragraphs)
    if claimed is not None and 1 <= claimed <= n:
        if _norm(text) in _norm(paragraphs[claimed - 1]):
            return claimed

    needle = _norm(text)
    for i, p in enumerate(paragraphs, 1):
        if needle and needle in _norm(p):
            return i

    best_i, best_ratio = None, 0.0
    for i, p in enumerate(paragraphs, 1):
        ratio = difflib.SequenceMatcher(None, needle, _norm(p)).ratio()
        if ratio > best_ratio:
            best_i, best_ratio = i, ratio
    if best_ratio >= 0.65:
        return best_i
    return None


# ── 背诵 ──────────────────────────────────────


def _build_recitation(raw: dict, paragraphs: list[Paragraph], warnings: list[str]) -> Recitation:
    rec = Recitation(
        title_suggested=(raw.get("title_suggested") or "").strip(),
        advice=(raw.get("advice") or "").strip(),
    )
    chunks = []
    for item in raw.get("chunks") or []:
        if not isinstance(item, dict):
            continue
        c = RecitationChunk.from_dict(item)
        if c.text.strip():
            chunks.append(c)

    valid = _chunks_cover(chunks, paragraphs)
    if not valid:
        if chunks:
            warnings.append("背诵分块与原文覆盖不一致，已按段落重建。")
        chunks = _fallback_chunks(paragraphs)

    n = len(paragraphs)
    for c in chunks:
        if not (1 <= c.paragraph_start <= n) or not (1 <= c.paragraph_end <= n) or c.paragraph_start > c.paragraph_end:
            c.paragraph_start, c.paragraph_end = _locate_chunk(c.text, paragraphs)
        if not c.translation:
            c.translation = _translation_span(c.paragraph_start, c.paragraph_end, paragraphs)
        if not c.hint:
            c.hint = " ".join(_words(c.text)[:4])
    for i, c in enumerate(chunks, 1):
        c.index = i

    schedule = build_schedule(len(chunks), start_date=date.today())
    rec.chunks = chunks
    rec.start_date = schedule.start_date
    rec.intervals = list(schedule.intervals)
    rec.chunks_per_day = schedule.chunks_per_day
    rec.schedule = {
        "total_days": schedule.total_days,
        "per_chunk": [asdict(c) for c in schedule.chunks],
        "daily": [asdict(d) for d in schedule.daily],
    }
    return rec


def _chunks_cover(chunks: list[RecitationChunk], paragraphs: list[Paragraph]) -> bool:
    if not chunks:
        return False
    full = [w for p in paragraphs for w in _words(p.en)]
    if not full:
        return False

    pos = 0
    matched = 0
    for c in chunks:
        cw = _words(c.text)
        if not cw:
            return False
        found = -1
        for j in range(pos, len(full) - len(cw) + 1):
            if full[j : j + len(cw)] == cw:
                found = j
                break
        if found == -1:
            return False
        matched += len(cw)
        pos = found + len(cw)
    return matched / len(full) >= 0.9


def _fallback_chunks(paragraphs: list[Paragraph]) -> list[RecitationChunk]:
    units: list[tuple[int, str]] = []
    for p in paragraphs:
        sents = re.split(r"(?<=[.!?])\s+", p.en)
        for s in sents:
            s = s.strip()
            if s:
                units.append((p.index, s))

    chunks: list[RecitationChunk] = []
    buf: list[str] = []
    words = 0
    start = end = None

    def flush():
        nonlocal buf, words, start, end
        if not buf:
            return
        text = " ".join(buf)
        chunks.append(RecitationChunk(
            index=len(chunks) + 1,
            text=text,
            hint=" ".join(_words(text)[:4]),
            translation=_translation_span(start or 1, end or 1, paragraphs),
            paragraph_start=start or 1,
            paragraph_end=end or 1,
        ))
        buf, words, start, end = [], 0, None, None

    for idx, sent in units:
        if start is None:
            start = idx
        buf.append(sent)
        words += len(_words(sent))
        end = idx
        if words >= 45:
            flush()
    flush()

    if not chunks:
        text = " ".join(p.en for p in paragraphs)
        chunks = [RecitationChunk(
            index=1, text=text, hint=" ".join(_words(text)[:4]),
            translation=" ".join(p.zh for p in paragraphs),
            paragraph_start=1, paragraph_end=len(paragraphs),
        )]
    return chunks


def _locate_chunk(text: str, paragraphs: list[Paragraph]) -> tuple[int, int]:
    ens = [p.en for p in paragraphs]
    head = text[:160]
    tail = text[-160:] if len(text) > 160 else text
    s = _resolve_paragraph(head, None, ens)
    e = _resolve_paragraph(tail, s, ens)
    if s is None and e is None:
        return 1, len(paragraphs)
    s = s if s is not None else e
    e = e if e is not None else s
    return min(s, e), max(s, e)


def _translation_span(start: int, end: int, paragraphs: list[Paragraph]) -> str:
    return " ".join(p.zh for p in paragraphs if start <= p.index <= end).strip()


# ── 通用 ──────────────────────────────────────


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", (text or "").lower())


def _norm(text: str) -> str:
    s = (text or "")
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


# ── 保存 / 加载 ──────────────────────────────────


def save_analysis(result: AnalysisResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_analysis(path: Path) -> AnalysisResult:
    return AnalysisResult.from_dict(json.loads(path.read_text(encoding="utf-8")))
