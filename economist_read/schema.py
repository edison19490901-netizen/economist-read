"""analysis.json 的数据结构。"""

from dataclasses import dataclass, field, asdict

from .llm import CallUsage


def _s(value, default: str = "") -> str:
    return value.strip() if isinstance(value, str) else default


def _i(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _i_or_none(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x).strip() for x in value if str(x).strip()]


def _int_list(value) -> list[int]:
    if not isinstance(value, list):
        return []
    out = []
    for x in value:
        n = _i_or_none(x)
        if n is not None:
            out.append(n)
    return out


# ── 元信息 ──────────────────────────────────────


@dataclass
class Meta:
    id: str = ""
    title: str = ""
    source: str = "paste"
    url: str | None = None
    language: str = "en"
    created: str = ""
    model: str = "deepseek-chat"
    word_count: int = 0
    paragraph_count: int = 0
    truncated: bool = False
    duration_seconds: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "Meta":
        d = d or {}
        return cls(
            id=_s(d.get("id")),
            title=_s(d.get("title")),
            source=_s(d.get("source"), "paste"),
            url=d.get("url"),
            language=_s(d.get("language"), "en"),
            created=_s(d.get("created")),
            model=_s(d.get("model"), "deepseek-chat"),
            word_count=_i(d.get("word_count")),
            paragraph_count=_i(d.get("paragraph_count")),
            truncated=bool(d.get("truncated", False)),
            duration_seconds=_f(d.get("duration_seconds")),
        )


@dataclass
class Summary:
    zh_points: list[str] = field(default_factory=list)
    en_points: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Summary":
        d = d or {}
        return cls(
            zh_points=_str_list(d.get("zh_points")),
            en_points=_str_list(d.get("en_points")),
        )


@dataclass
class Paragraph:
    index: int
    en: str = ""
    zh: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Paragraph":
        d = d or {}
        return cls(index=_i(d.get("index")), en=_s(d.get("en")), zh=_s(d.get("zh")))


# ── 词汇与长难句 ──────────────────────────────────


@dataclass
class VocabularyItem:
    id: str = ""
    word: str = ""
    context_sentence: str = ""
    paragraph_index: int | None = None
    difficulty: str = ""
    chinese_note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "VocabularyItem":
        d = d or {}
        return cls(
            id=_s(d.get("id")),
            word=_s(d.get("word")),
            context_sentence=_s(d.get("context_sentence")),
            paragraph_index=_i_or_none(d.get("paragraph_index")),
            difficulty=_s(d.get("difficulty")),
            chinese_note=_s(d.get("chinese_note")),
        )


@dataclass
class Clause:
    text: str = ""
    type: str = ""
    function: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Clause":
        d = d or {}
        return cls(text=_s(d.get("text")), type=_s(d.get("type")), function=_s(d.get("function")))


@dataclass
class Modifier:
    text: str = ""
    type: str = ""
    modifies: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Modifier":
        d = d or {}
        return cls(text=_s(d.get("text")), type=_s(d.get("type")), modifies=_s(d.get("modifies")))


@dataclass
class LongSentence:
    id: str = ""
    sentence: str = ""
    paragraph_index: int | None = None
    main_clause: str = ""
    subordinate_clauses: list[Clause] = field(default_factory=list)
    modifiers: list[Modifier] = field(default_factory=list)
    translation: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "LongSentence":
        d = d or {}
        return cls(
            id=_s(d.get("id")),
            sentence=_s(d.get("sentence")),
            paragraph_index=_i_or_none(d.get("paragraph_index")),
            main_clause=_s(d.get("main_clause")),
            subordinate_clauses=[
                Clause.from_dict(x) for x in (d.get("subordinate_clauses") or []) if isinstance(x, dict)
            ],
            modifiers=[
                Modifier.from_dict(x) for x in (d.get("modifiers") or []) if isinstance(x, dict)
            ],
            translation=_s(d.get("translation")),
            note=_s(d.get("note")),
        )


# ── 写作拆解 ──────────────────────────────────────


@dataclass
class Section:
    title: str = ""
    role: str = ""
    argument: str = ""
    evidence: str = ""
    technique: str = ""
    paragraph_indices: list[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Section":
        d = d or {}
        return cls(
            title=_s(d.get("title")),
            role=_s(d.get("role")),
            argument=_s(d.get("argument")),
            evidence=_s(d.get("evidence")),
            technique=_s(d.get("technique")),
            paragraph_indices=_int_list(d.get("paragraph_indices")),
        )


@dataclass
class WritingTechnique:
    name: str = ""
    example: str = ""
    effect: str = ""
    paragraph_index: int | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "WritingTechnique":
        d = d or {}
        return cls(
            name=_s(d.get("name")),
            example=_s(d.get("example")),
            effect=_s(d.get("effect")),
            paragraph_index=_i_or_none(d.get("paragraph_index")),
        )


@dataclass
class Deconstruction:
    overview: str = ""
    sections: list[Section] = field(default_factory=list)
    writing_techniques: list[WritingTechnique] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Deconstruction":
        d = d or {}
        return cls(
            overview=_s(d.get("overview")),
            sections=[Section.from_dict(x) for x in (d.get("sections") or []) if isinstance(x, dict)],
            writing_techniques=[
                WritingTechnique.from_dict(x)
                for x in (d.get("writing_techniques") or [])
                if isinstance(x, dict)
            ],
        )


# ── 背景 ──────────────────────────────────────


@dataclass
class KeyFact:
    fact: str = ""
    data: str = ""
    paragraph_index: int | None = None

    @classmethod
    def from_dict(cls, d: dict) -> "KeyFact":
        d = d or {}
        return cls(
            fact=_s(d.get("fact")),
            data=_s(d.get("data")),
            paragraph_index=_i_or_none(d.get("paragraph_index")),
        )


@dataclass
class Background:
    event_context: str = ""
    key_facts: list[KeyFact] = field(default_factory=list)
    author_stance: str = ""
    implications: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "Background":
        d = d or {}
        return cls(
            event_context=_s(d.get("event_context")),
            key_facts=[KeyFact.from_dict(x) for x in (d.get("key_facts") or []) if isinstance(x, dict)],
            author_stance=_s(d.get("author_stance")),
            implications=_s(d.get("implications")),
        )


# ── 实际应用 ──────────────────────────────────────


@dataclass
class ActionableSkill:
    skill: str = ""
    how_to_apply: str = ""
    example: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ActionableSkill":
        d = d or {}
        return cls(
            skill=_s(d.get("skill")),
            how_to_apply=_s(d.get("how_to_apply")),
            example=_s(d.get("example")),
        )


@dataclass
class ThinkingModel:
    model: str = ""
    explanation: str = ""
    how_to_use: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ThinkingModel":
        d = d or {}
        return cls(
            model=_s(d.get("model")),
            explanation=_s(d.get("explanation")),
            how_to_use=_s(d.get("how_to_use")),
        )


@dataclass
class PracticalApplication:
    actionable_skills: list[ActionableSkill] = field(default_factory=list)
    thinking_models: list[ThinkingModel] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "PracticalApplication":
        d = d or {}
        return cls(
            actionable_skills=[
                ActionableSkill.from_dict(x)
                for x in (d.get("actionable_skills") or [])
                if isinstance(x, dict)
            ],
            thinking_models=[
                ThinkingModel.from_dict(x)
                for x in (d.get("thinking_models") or [])
                if isinstance(x, dict)
            ],
        )


# ── 背诵 ──────────────────────────────────────


@dataclass
class RecitationChunk:
    index: int = 0
    text: str = ""
    hint: str = ""
    translation: str = ""
    paragraph_start: int = 1
    paragraph_end: int = 1

    @classmethod
    def from_dict(cls, d: dict) -> "RecitationChunk":
        d = d or {}
        return cls(
            index=_i(d.get("index")),
            text=_s(d.get("text")),
            hint=_s(d.get("hint")),
            translation=_s(d.get("translation")),
            paragraph_start=_i(d.get("paragraph_start"), 1),
            paragraph_end=_i(d.get("paragraph_end"), 1),
        )


@dataclass
class Recitation:
    title_suggested: str = ""
    advice: str = ""
    start_date: str = ""
    intervals: list[int] = field(default_factory=lambda: [1, 2, 4, 7, 15])
    chunks_per_day: int = 2
    chunks: list[RecitationChunk] = field(default_factory=list)
    schedule: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "Recitation":
        d = d or {}
        return cls(
            title_suggested=_s(d.get("title_suggested")),
            advice=_s(d.get("advice")),
            start_date=_s(d.get("start_date")),
            intervals=_int_list(d.get("intervals")) or [1, 2, 4, 7, 15],
            chunks_per_day=_i(d.get("chunks_per_day"), 2),
            chunks=[
                RecitationChunk.from_dict(x) for x in (d.get("chunks") or []) if isinstance(x, dict)
            ],
            schedule=d.get("schedule") if isinstance(d.get("schedule"), dict) else {},
        )


# ── 用量与总结果 ──────────────────────────────────


@dataclass
class UsageInfo:
    calls: list[CallUsage] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_cny: float = 0.0

    @classmethod
    def from_dict(cls, d: dict) -> "UsageInfo":
        d = d or {}
        calls = []
        for x in d.get("calls") or []:
            if isinstance(x, dict):
                calls.append(CallUsage(
                    stage=_s(x.get("stage")),
                    prompt_tokens=_i(x.get("prompt_tokens")),
                    completion_tokens=_i(x.get("completion_tokens")),
                    total_tokens=_i(x.get("total_tokens")),
                    cost_cny=_f(x.get("cost_cny")),
                    finish_reason=_s(x.get("finish_reason")),
                ))
        return cls(
            calls=calls,
            prompt_tokens=_i(d.get("prompt_tokens")),
            completion_tokens=_i(d.get("completion_tokens")),
            total_tokens=_i(d.get("total_tokens")),
            cost_cny=_f(d.get("cost_cny")),
        )


@dataclass
class AnalysisResult:
    meta: Meta = field(default_factory=Meta)
    summary: Summary = field(default_factory=Summary)
    paragraphs: list[Paragraph] = field(default_factory=list)
    vocabulary: list[VocabularyItem] = field(default_factory=list)
    long_sentences: list[LongSentence] = field(default_factory=list)
    deconstruction: Deconstruction = field(default_factory=Deconstruction)
    background: Background = field(default_factory=Background)
    practical_application: PracticalApplication = field(default_factory=PracticalApplication)
    recitation: Recitation = field(default_factory=Recitation)
    usage: UsageInfo = field(default_factory=UsageInfo)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AnalysisResult":
        d = d or {}
        return cls(
            meta=Meta.from_dict(d.get("meta") or {}),
            summary=Summary.from_dict(d.get("summary") or {}),
            paragraphs=[Paragraph.from_dict(x) for x in (d.get("paragraphs") or []) if isinstance(x, dict)],
            vocabulary=[
                VocabularyItem.from_dict(x) for x in (d.get("vocabulary") or []) if isinstance(x, dict)
            ],
            long_sentences=[
                LongSentence.from_dict(x) for x in (d.get("long_sentences") or []) if isinstance(x, dict)
            ],
            deconstruction=Deconstruction.from_dict(d.get("deconstruction") or {}),
            background=Background.from_dict(d.get("background") or {}),
            practical_application=PracticalApplication.from_dict(d.get("practical_application") or {}),
            recitation=Recitation.from_dict(d.get("recitation") or {}),
            usage=UsageInfo.from_dict(d.get("usage") or {}),
            warnings=_str_list(d.get("warnings")),
        )
