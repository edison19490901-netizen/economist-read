# 经济学人精读（Economist Read）

把一篇《经济学人》英文文章变成可交互的精读看板：总结、逐段对照翻译、词汇与长难句、写作论证拆解、背景观点、实际应用、背诵版和用量统计。

## 快速开始

```bash
cd D:\Claudeee\Economist_Read
pip install -r requirements.txt
copy .env.example .env        # 填入 DEEPSEEK_API_KEY
python app.py
```

打开 <http://127.0.0.1:5001>。端口 5001 是为了避开本机 5000 上常驻的旧服务；需要手机访问时设置 `HOST=0.0.0.0`。

## 输入方式

- **粘贴正文**（优先）：直接把英文全文粘进文本框。
- **网页链接**：正文为空时，用 trafilatura 抓取文章；付费墙或抓取失败会提示改用粘贴。

文章至少 80 词 / 500 字符，且需为英文；超过 60,000 字符按段落边界截断。

## 看板八个 Tab

| Tab | 内容 |
|---|---|
| 总结 | 中文要点 + English Key Points |
| 对照翻译 | 英文在上、中文在下；可全局或单段隐藏译文 |
| 词汇长句 | 12–20 个生词 + 5–8 个长难句结构拆解 |
| 写作拆解 | 写法总览、结构分段、可迁移技巧 |
| 背景观点 | 事件背景、关键事实、作者立场、启示 |
| 实际应用 | 可操作技能与思维模型 |
| 背诵 | 自动分块、中文译文默认收起、艾宾浩斯复习表、每日打卡 |
| 统计 | 词数/段落/各项数量、分阶段 token 与费用 |

### 交互

- 点生词表任意一行 → 切到「对照翻译」，滚动到对应段落并高亮该词。
- 点原文中带虚线的词 → 弹出中文释义 tooltip；点空白处或 Esc 关闭。
- 点长难句卡片 → 定位到对应段落。
- 背诵分块：点「显示翻译」展开中文；点「遮住自测」遮住英文。
- 打卡记录保存在浏览器 localStorage，按文章 id 区分。

## 输出

每次分析写入 `output/<id>/`：

- `analysis.json` — 完整结构化结果
- `source.json` — 原始标题、链接、全文
- `workbook.html` — 生成的单页看板

`<id>` 格式为 `YYYY-MM-DD_HHMM_<slug>_<hash6>`，同一篇重复分析不会覆盖旧结果。首页列出最近 5 条。

## 技术说明

- DeepSeek `deepseek-chat`，JSON 模式；四路并行：核心分析、逐段翻译、词汇长难句、背诵分块。
- 翻译按 ≤8 段 / ≤4,500 字符分批；输出被 `max_tokens` 截断时自动拆分重试。
- 段落索引统一为 1-based，作为跨 Tab 定位的主键。
- 生词标注在服务端完成：所有原文先 HTML 转义，只输出受控的 `<span data-vid>`，避免 XSS。
- 费用按 DeepSeek 定价估算：输入 ¥1/百万 token，输出 ¥2/百万 token。

## 目录

```
app.py                     Flask 入口（首页 / process / result）
economist_read/
  parser.py                段落切分、清洗、词数、语言检测
  downloader.py            trafilatura 网页抓取
  llm.py                   DeepSeek 客户端、JSON 修复、重试、用量
  schema.py                dataclass 与序列化
  prompts.py               四组提示词
  analyzer.py              并行编排、校验、兜底、保存/加载
  recite/                  艾宾浩斯计划（复用智读）
  outputs/workbook.py      看板渲染与生词标注
  templates/article.html.j2 八栏单页看板
output/<id>/               分析结果
```
