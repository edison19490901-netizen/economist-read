"""《经济学人》精读 prompt 模板。

四个 stage：
  core        总结 + 写作拆解 + 背景 + 实际应用
  translation 逐段中译
  language    词汇 + 长难句
  recitation  背诵分块 + 每块翻译
"""

_INTRO = (
    "下面是一篇《经济学人》（The Economist）的英文文章。"
    "请把它当作精读材料处理。所有引用原文的字段必须逐字摘录，不能改写或编造。"
)


def _numbered(paragraphs: list[str]) -> str:
    return "\n\n".join(f"[P{i}] {p}" for i, p in enumerate(paragraphs, 1))


def _header(title: str) -> str:
    return f'标题: "{title}"\n' if title else ""


# ── core ─────────────────────────────────────────


def build_core_prompt(paragraphs: list[str], title: str = "", part: str = "all") -> str:
    """总结 / 写作拆解 / 背景 / 实际应用。part 用于输出截断时拆分。"""
    schema_parts: list[str] = []

    if part in ("all", "summary_decon"):
        schema_parts.append(
            """
  "summary": {
    "zh_points": ["4-6 条中文要点，每条独立成句"],
    "en_points": ["4-6 条 English key points, one sentence each"]
  },
  "deconstruction": {
    "overview": "整篇文章的写法总览（结构、主线、风格，80-150 字）",
    "sections": [
      {
        "title": "该部分简短标题",
        "role": "引入/提出论点/论证/例证/转折/结论",
        "argument": "该部分的核心论点",
        "evidence": "支撑论据（数据/案例/引用/逻辑推演）",
        "technique": "使用的写作技巧",
        "paragraph_indices": [1, 2]
      }
    ],
    "writing_techniques": [
      {
        "name": "可迁移的写作技巧名",
        "example": "从原文逐字摘录的例子",
        "effect": "这个技巧达到的效果",
        "paragraph_index": 5
      }
    ]
  }"""
        )

    if part in ("all", "background_apply"):
        schema_parts.append(
            """
  "background": {
    "event_context": "事件背景（政治/经济/社会脉络）",
    "key_facts": [
      { "fact": "关键事实", "data": "关键数据（没有则空字符串）", "paragraph_index": 6 }
    ],
    "author_stance": "作者的立场、倾向与隐含判断",
    "implications": "这件事对读者/行业/政策意味着什么"
  },
  "practical_application": {
    "actionable_skills": [
      { "skill": "可操作技能", "how_to_apply": "具体怎么做", "example": "一个可执行的例子" }
    ],
    "thinking_models": [
      { "model": "可迁移的思维模型", "explanation": "它是什么", "how_to_use": "何时用、怎么用" }
    ]
  }"""
        )

    schema = "{\n" + ",\n".join(schema_parts) + "\n}"

    return f"""{_INTRO}

材料语言: 英文
{_header(title)}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_numbered(paragraphs)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请只返回下面的 JSON 结构，不要 markdown 代码块，不要任何解释：

{schema}

要求：
1. summary：中英各 4-6 条，概括文章核心内容；**不要口播稿、不要逐字翻译**。
2. deconstruction：按文章实际结构分 4-8 个部分；每个部分都要给 paragraph_indices；
   写作技巧提炼 3-6 个，example 必须逐字来自原文。
3. background：区分事实/数据与作者立场，不臆造数据；key_facts 至少 4 条。
4. practical_application：3-5 个可操作技能、3-5 个思维模型。
5. 所有 paragraph_index / paragraph_indices 使用 1-based 段落编号，范围 1-{len(paragraphs)}。
6. 中文解释自然、口语化，不要教科书腔。
"""


# ── translation ──────────────────────────────────


def build_translation_prompt(batch: list[tuple[int, str]], title: str = "") -> str:
    """逐段翻译。batch 为 [(index, text), ...]。"""
    body = "\n\n".join(f"[P{idx}] {text}" for idx, text in batch)
    return f"""请把下面《经济学人》文章段落逐段翻译成中文。

{_header(title)}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{body}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请只返回 JSON：
{{
  "translations": [
    {{ "index": {batch[0][0]}, "zh": "对应段落的中文翻译" }}
  ]
}}

要求：
1. **每个 [P编号] 恰好对应一条翻译**，不得遗漏、合并、拆分或改变顺序。
2. 忠实原意，中文通顺自然；保留原文的逻辑关系与语气。
3. 人名、机构名、专有名词使用通行译名；数字、日期、百分比保持原样。
4. 不加任何解释、评论、小标题或原文回显。
5. 只返回纯 JSON，不要 markdown 代码块。
"""


# ── language ─────────────────────────────────────


def build_language_prompt(paragraphs: list[str], title: str = "", part: str = "all") -> str:
    """词汇 + 长难句。part 用于输出截断时拆分。"""
    schema_parts: list[str] = []

    if part in ("all", "vocab"):
        schema_parts.append(
            """
  "vocabulary": [
    {
      "word": "单词或短语",
      "context_sentence": "该词在原文中出现的完整句子（逐字）",
      "paragraph_index": 3,
      "difficulty": "★☆☆ / ★★☆ / ★★★",
      "chinese_note": "中文释义 + 用法/搭配说明"
    }
  ]"""
        )

    if part in ("all", "long"):
        schema_parts.append(
            """
  "long_sentences": [
    {
      "sentence": "原文长句（逐字，约 25 词以上）",
      "paragraph_index": 8,
      "main_clause": "句子主干",
      "subordinate_clauses": [
        { "text": "从句原文", "type": "定语从句/状语从句/名词性从句", "function": "在句中的作用" }
      ],
      "modifiers": [
        { "text": "修饰成分原文", "type": "介词短语/分词短语/副词", "modifies": "修饰谁" }
      ],
      "translation": "整句中文翻译",
      "note": "难在哪里、怎么读懂"
    }
  ]"""
        )

    schema = "{\n" + ",\n".join(schema_parts) + "\n}"

    return f"""{_INTRO}

材料语言: 英文
{_header(title)}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_numbered(paragraphs)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请只返回下面的 JSON 结构，不要 markdown 代码块，不要任何解释：

{schema}

要求：
1. vocabulary：12-20 条，优先《经济学人》高频搭配、习语、经济/政治/政策术语；
   context_sentence 必须是包含该词的完整原句，paragraph_index 为 1-based。
2. long_sentences：5-8 条，必须是含从句、插入语或复杂修饰的真实长句；
   主干、从句、修饰成分要拆清楚，translation 准确通顺。
3. difficulty 只能是 ★☆☆、★★☆、★★★ 之一。
4. 不要收录过于简单的词（如 the, make, good）。
"""


# ── recitation ───────────────────────────────────


def build_recitation_prompt(paragraphs: list[str], title: str = "") -> str:
    return f"""{_INTRO}

请把文章切成适合背诵的意群块。必须逐字覆盖全文，不增不减、不改写。

材料语言: 英文
{_header(title)}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{_numbered(paragraphs)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请只返回 JSON：
{{
  "title_suggested": "建议的背诵标题",
  "advice": "2-4 句背诵建议（长句在哪换气、用哪些关键词串起全文）",
  "chunks": [
    {{
      "text": "原文分块，逐字保留标点",
      "hint": "1-5 个词的回忆提示",
      "translation": "该块的中文翻译",
      "paragraph_start": 1,
      "paragraph_end": 2
    }}
  ]
}}

要求：
1. 8-24 块，按原文顺序完整覆盖全文；块与块之间不重叠、不遗漏。
2. 英文每块 25-70 词，在自然语义边界（句子、分号、破折号）处切分。
3. hint 只给 1-5 个关键词，不要泄露整块内容。
4. translation 是该块自然、准确的中文翻译。
5. paragraph_start / paragraph_end 是该块覆盖的 1-based 段落编号。
6. 只返回纯 JSON，不要 markdown 代码块。
"""
