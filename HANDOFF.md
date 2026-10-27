# 交接文档 — 经济学人精读（Economist Read）

> 最后更新：2026-10-27 21:00
> 状态：**可用**。本地能跑通完整分析，线上站点已发布并通过手机端验证。

---

## 1. 这是什么

把一篇《经济学人》英文文章变成一份**可交互的精读看板**：八个面板，单文件 HTML。

- 语言学习：逐段上下对照翻译、生词点查、长难句拆句
- 内容理解：写作论证拆解、背景观点
- 记忆应用：艾宾浩斯背诵分块、实际应用、用量统计

**两种使用方式**

| 场景 | 入口 |
|---|---|
| 电脑上生成新分析 | `python app.py` → <http://127.0.0.1:5001> |
| 手机上阅读已生成的看板 | <https://edison19490901-netizen.github.io/economist-read/> |

GitHub Pages 只能托管静态文件，**跑不了 Flask**。所以"生成"永远在电脑上，"阅读"才在线上。

**仓库**：<https://github.com/edison19490901-netizen/economist-read>（公开，`main` 分支，26 个文件，约 3,400 行）

---

## 2. 目录结构

```
D:\Claudeee\Economist_Read\
├─ app.py                       # Flask：首页 / process / result，端口 5001
├─ requirements.txt             # openai, jinja2, flask, trafilatura, requests
├─ .env                         # DEEPSEEK_API_KEY 等（gitignored，勿提交）
├─ .env.example
├─ README.md
├─ HANDOFF.md                   # 本文档
├─ economist_read/
│  ├─ parser.py                 # 段落切分、单行长文回退、语言检测、截断
│  ├─ downloader.py             # fetch_web_article（trafilatura）
│  ├─ llm.py                    # DeepSeek 客户端、JSON 修复、重试、计费
│  ├─ prompts.py                # 四组 prompt
│  ├─ schema.py                 # 全部 dataclass 与序列化
│  ├─ analyzer.py               # 四路并行编排、校验、兜底
│  ├─ utils.py                  # slugify / make_output_id / now_iso
│  ├─ recite/planner.py         # 艾宾浩斯计划（D+1/2/4/7/15）
│  ├─ outputs/workbook.py       # 看板渲染上下文 + 生词标注
│  └─ templates/article.html.j2 # 8 面板单文件模板（CSS/JS 全内联）
├─ tools/publish_site.py        # 扫描 output/ → 生成 docs/ 静态站点
├─ docs/                        # GitHub Pages 托管目录（提交进仓库）
├─ output/<id>/                 # 每次分析：analysis.json / source.json / workbook.html
└─ promo/                        # 小红书推广图文（**已 gitignore，不入库**）
```

---

## 3. 分析流水线

四个 stage 并行（`ThreadPoolExecutor(max_workers=3)`），互不依赖：

| stage | 调用数 | 产出 | 失败策略 |
|---|---:|---|---|
| `core` | 1 | summary / deconstruction / background / practical_application | **必需**，失败中止整次分析 |
| `translation` | 1–3 | 每段中文译文（≥8 段或 ≥4,500 字符自动分批） | 单批重试 → 递归对半拆 → 占位符 + warning |
| `language` | 1 | vocabulary（上限 20）+ long_sentences（5–8） | 留空 + warning，看板显示提示 |
| `recitation` | 1–2 | 背诵分块（含中文译文与回忆提示） | 按段落 45 词兜底重建 |

**真实数据**（示例文章，1,032 词 / 12 段）：

```
35 秒 · 5 次调用 · 输入 7,686 + 输出 10,473 tokens · ¥0.0286
  core 4793 / translation:1 2073 / translation:2 1108 / language 5178 / recitation 5007
warnings: []
```

**为什么拆成四路**：全文翻译是最大的一块输出，和总结/解构混在一次调用里极易触发 `finish_reason=length`（max_tokens 8192）。

**合并阶段的本地校验**（不信任模型）：
1. `paragraphs` 以本地 `split_paragraphs()` 为准，索引 1-based，是跨 Tab 定位的主键
2. 词汇/长难句用 `context_sentence` 反查段落；找不到时用 `difflib` 全篇重定位（阈值 0.65）；再失败则按单词子串兜底
3. 背诵校验拼接覆盖率 ≥90% 且顺序一致，否则按段落重建
4. 解构/背景的 `paragraph_index` 越界直接丢弃

---

## 4. 看板八个面板

| Tab | 内容 |
|---|---|
| 总结 | 中文要点 + English Key Points（上下堆叠，**无口播稿**） |
| 对照翻译 | 每段一卡；**英文在上、中文在下**（用户明确要求，不要左右分栏） |
| 词汇长句 | 生词表（20）+ 长难句拆解（主干/从句/修饰） |
| 写作拆解 | 结构总览 + 可迁移技巧 + 原文例句 |
| 背景观点 | 事件背景、关键事实、作者立场、启示 |
| 实际应用 | 可操作技能 + 思维模型 |
| 背诵 | 分块（译文默认收起，按钮展开）+ D+1/2/4/7/15 复习表 + localStorage 打卡 |
| 统计 | 词数、各板块数量、分 stage 的 token 与费用明细 |

**关键交互**
- 点生词行 → 切到对照翻译 → 滚到 `#para-N` → 闪烁 + 高亮命中词
- 点原文高亮词 → 固定定位 tooltip（词义/难度/注释）
- 背诵译文 `.rc-zh{display:none}`，`.zh-on` 时显示
- 打印时展开全部面板与译文

**XSS 安全**：`outputs/workbook.py` 的 `annotate_paragraph()` 先转义全文，再只插入受控 `<span data-vid>`。

---

## 5. 发布到 GitHub Pages

```bash
python tools/publish_site.py     # 重建 docs/（索引页 + 各篇 index.html + .nojekyll）
git add docs && git commit -m "publish" && git push
```

- Pages 源：`main` 分支 `/docs`，HTTPS 已强制
- 每次新分析后重跑脚本并提交 `docs/`，约 30 秒生效
- `tools/publish_site.py --check` 只列出会发布哪些文章，不写文件

---

## 6. 配置项（`.env`）

```ini
DEEPSEEK_API_KEY=sk-...        # 必需
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_MAX_WORKERS=3         # 1–6
HOST=127.0.0.1                 # 本机；改 0.0.0.0 才可局域网访问
PORT=5001                      # 5000 被另一常驻服务占用
```

`.env` 已被 `.gitignore` 拦截。**任何情况下不要把 key 打进日志、终端输出或提交里**（本次会话中曾有一条打印 `key[:3]` 的命令被系统安全策略拦下）。

---

## 7. 本次会话做了什么

| 提交 | 内容 |
|---|---|
| `14fa1bc` | 初始化项目（后经 amend 剔除 `promo/`） |
| `46b43fc` | 新增 Pages 静态站点 + 修复 `.env` 里 HOST/PORT 不生效 |
| `1b2c5a9` | 修复深链跳转时 sticky 导航遮挡面板标题 |
| `3431c1d` | README 以 Pages 作为手机阅读方案 |

另在 `promo/`（不入库）产出 9 张 1080×1440 小红书图文及渲染脚本。

---

## 8. 踩过的坑（别重复踩）

1. **`.env` 的 HOST/PORT 不生效** — `__main__` 里原本在 `_load_env_file()` 之前就读了环境变量，导致永远绑 127.0.0.1。已修：启动时先加载 `.env`。
2. **单行长文被当成一个段落** — 父项目 `full_text` 零换行，`split_paragraphs()` 返回 1 段 1,032 词。已加 `_split_long_block()` 按句子切 ~700 字符伪段落。
3. **`loads_loose` 抛裸 `JSONDecodeError`** — 修复后仍可能失败，异常没包住。已统一转成 `JsonParseError`。
4. **词汇数量超标** — 模型给了 25 条，超出 12–20 的规格。已在 `_build_vocabulary` 里截断到 20。
5. **生词定位失败** — 模型给的 `paragraph_index` 不可靠，2/20 定位不到。已加单词子串兜底，现在 20/20。
6. **深链被固定导航遮住** — 带 `#tab-summary` 打开时浏览器滚到面板顶部，被 50px sticky tab 栏盖住。已加 `.tab-panel{scroll-margin-top:62px}`。
7. **Windows 防火墙** — 当时的 WiFi（"Xiaomi 169"）被判为**公用网络**，入站包被静默丢弃，且加规则需要管理员权限。这条路线已放弃，改用 Pages。
8. **端口 5000 被占用** — 本机有一个常驻旧服务，所以本项目用 5001。

---

## 9. 已知限制

- **无登录验证**：谁能访问 Flask 端口，谁就能花你的 API Key。所以 HOST 保持 `127.0.0.1`。
- **Pages 是只读的**：手机上无法新建分析。
- **版权**：仓库是公开的，`output/` 与 `docs/` 里含《经济学人》文章全文（约 1,000 词）。若要撤下，需要 `git rm --cached` **并改写历史**，仅删文件不够。
- **`promo/` 未入库**：本地保留，`.gitignore` 里写了 `promo/`。强制推送后 GitHub 仍会短暂保留旧 blob，直到 GC。
- **不做**：期号/主题归档、跨文章生词本、全库统计、PDF/EPUB/音视频输入。

---

## 10. 下次接手先做什么

- [ ] 再跑 1–2 篇文章验证泛化（不同长度、不同栏目），重点看 `warnings` 是否为空
- [ ] 超过 1,600 词的长文：确认翻译分批与背诵拆分都不报错
- [ ] `docs/index.html` 目前只有 1 篇，多于 5 篇时考虑加分页或按月份分组
- [ ] 若要在手机上"生成"，需重写为静态前端 + 无服务器转发（Cloudflare Worker 等）；注意 DeepSeek API 是否允许浏览器直连（CORS 未知，需先验证）
- [ ] `promo/images` 若将来要入库，建议走 Releases 而不是塞进仓库（2.9MB）

---

## 11. 快速验证命令

```bash
cd /d/Claudeee/Economist_Read

python -m compileall -q app.py economist_read tools     # 语法
python -c "from economist_read.llm import loads_loose; print(loads_loose('{\"a\": [1, 2, {\"b\": \"x\"'))"
python tools/publish_site.py --check                    # 会发布哪些文章

python app.py                                           # 起服务，浏览器开 5001
curl -s -o /dev/null -w "%{http_code}\n" https://edison19490901-netizen.github.io/economist-read/
```
