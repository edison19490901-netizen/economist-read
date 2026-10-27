"""DeepSeek 调用层：JSON 模式、用量统计、重试与残缺 JSON 修复。"""

import json
import os
import re
import time
from dataclasses import dataclass

SYSTEM_PROMPT = (
    "你是一名资深的《经济学人》精读教练，精通英文精读、翻译、语法分析与写作拆解。"
    "请严格按照要求的 JSON 格式输出，不要输出任何 JSON 之外的内容；"
    "确保 JSON 完整闭合，所有字符串正确转义，引用原文时必须逐字摘录。"
)


class OutputTruncated(RuntimeError):
    """模型输出达到 max_tokens 上限。"""

    def __init__(self, message: str, usage=None):
        super().__init__(message)
        self.usage = usage


class JsonParseError(RuntimeError):
    """无法把模型输出解析为 JSON。"""


@dataclass
class CallUsage:
    stage: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_cny: float
    finish_reason: str

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_cny": self.cost_cny,
            "finish_reason": self.finish_reason,
        }


@dataclass
class CallResult:
    data: dict
    usage: CallUsage
    raw: str


def cost_cny(prompt_tokens: int, completion_tokens: int) -> float:
    """DeepSeek-chat 价格：输入 ¥1/1M，输出 ¥2/1M。"""
    return round(prompt_tokens / 1_000_000 * 1 + completion_tokens / 1_000_000 * 2, 6)


def chat_json(
    stage: str,
    user_prompt: str,
    *,
    system_prompt: str = SYSTEM_PROMPT,
    api_key: str | None = None,
    model: str = "deepseek-chat",
    max_tokens: int = 8192,
    temperature: float = 0.3,
    max_attempts: int = 3,
) -> CallResult:
    """调用 DeepSeek，返回解析后的 JSON 与用量。

    - `finish_reason == "length"`：抛 OutputTruncated（附带 usage），由调用方拆分重试。
    - HTTP 429/5xx/超时：指数退避重试。
    - JSON 解析失败：追加提醒后重试。
    """
    api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise ValueError(
            "请设置 DEEPSEEK_API_KEY（环境变量或项目 .env 文件）。\n"
            "获取 Key: https://platform.deepseek.com/api_keys"
        )

    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("缺少 openai 依赖，请先执行: pip install openai")

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    prompt = user_prompt

    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        except Exception as e:  # noqa: BLE001 - 网络/SDK 异常统一处理
            if attempt < max_attempts and _retryable(e):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"[{stage}] API 调用失败: {e}") from e

        finish = resp.choices[0].finish_reason or ""
        raw = resp.choices[0].message.content or ""
        usage = _make_usage(stage, resp, finish)

        if finish == "length":
            raise OutputTruncated(
                f"[{stage}] 输出达到 max_tokens 上限，请缩小范围后重试。", usage=usage
            )
        if not raw.strip():
            raise RuntimeError(f"[{stage}] API 返回空内容。")

        try:
            data = loads_loose(raw)
            if not isinstance(data, dict):
                raise JsonParseError("顶层不是 JSON 对象")
            return CallResult(data=data, usage=usage, raw=raw)
        except JsonParseError as e:
            if attempt < max_attempts:
                prompt = (
                    user_prompt
                    + "\n\n注意：上一次输出不是合法 JSON。"
                    "请只返回合法 JSON，不要 markdown 代码块，不要任何解释。"
                )
                time.sleep(1)
                continue
            raise JsonParseError(f"[{stage}] 无法解析模型返回的 JSON: {e}") from e

    raise RuntimeError(f"[{stage}] 重试 {max_attempts} 次后仍失败。")


def _make_usage(stage: str, resp, finish: str) -> CallUsage:
    p = c = t = 0
    if getattr(resp, "usage", None):
        p = resp.usage.prompt_tokens or 0
        c = resp.usage.completion_tokens or 0
        t = resp.usage.total_tokens or 0
    return CallUsage(
        stage=stage,
        prompt_tokens=p,
        completion_tokens=c,
        total_tokens=t,
        cost_cny=cost_cny(p, c),
        finish_reason=finish,
    )


def _retryable(e: Exception) -> bool:
    status = getattr(e, "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    text = str(e).lower()
    return any(k in text for k in ("timeout", "timed out", "connection", "rate limit"))


# ── JSON 修复 ──────────────────────────────────────


def loads_loose(text: str) -> dict:
    """尽量把模型输出解析成 dict。"""
    s = (text or "").strip()
    if not s:
        raise JsonParseError("空内容")

    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s).strip()

    try:
        obj = json.loads(s)
        return obj
    except Exception:
        pass

    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            pass

    if start != -1:
        try:
            repaired = repair_truncated_json(s[start:])
            return json.loads(repaired)
        except json.JSONDecodeError as e:
            raise JsonParseError(f"JSON 修复后仍无法解析: {e}") from e

    raise JsonParseError("未找到 JSON 对象")


def repair_truncated_json(text: str) -> str:
    """尽最大努力补全被截断的 JSON，返回合法 JSON 字符串。"""
    s = text.strip()
    for _ in range(8):
        candidate = _close_json(s)
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            cut = _last_safe_cut(s)
            if cut is None or cut <= 0:
                break
            s = s[:cut].rstrip()
    raise JsonParseError("JSON 修复失败")


def _close_json(s: str) -> str:
    s = s.rstrip()
    stack, in_str, esc = _scan(s)
    if in_str:
        if esc:
            s = s[:-1]
        s += '"'
        stack, in_str, esc = _scan(s)

    s = s.rstrip()
    while s and s[-1] in ", \n\r\t":
        s = s[:-1]

    closers = "".join("}" if c == "{" else "]" for c in reversed(stack))
    return s + closers


def _scan(s: str) -> tuple[list[str], bool, bool]:
    """返回 (未闭合括号栈, 是否在字符串内, 是否以转义符结尾)。"""
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()
    return stack, in_str, esc


def _last_safe_cut(s: str) -> int | None:
    """找到最后一个可安全截断的位置（字符串外的逗号，或最后一个开括号后）。"""
    last_comma: int | None = None
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == ",":
                last_comma = i
    if last_comma is not None:
        return last_comma
    idx = max(s.rfind("{"), s.rfind("["))
    return idx + 1 if idx != -1 else None
