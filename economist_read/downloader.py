"""网页文章抓取（trafilatura）。"""

from dataclasses import dataclass

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)


@dataclass
class WebArticle:
    text: str
    title: str = ""
    site: str = ""
    url: str = ""


def fetch_web_article(url: str) -> WebArticle:
    """抓取网页正文，返回纯文本（段落间空行分隔）与元数据。

    Raises:
        ValueError: 无法访问或无法提取有效正文时。
    """
    try:
        import trafilatura
    except ImportError:
        raise RuntimeError("缺少 trafilatura 依赖，请先执行: pip install trafilatura")

    try:
        import requests

        resp = requests.get(url, timeout=25, headers={"User-Agent": _USER_AGENT})
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        raise ValueError(f"无法访问网页: {url}\n原因: {e}")

    if not html:
        raise ValueError(f"网页返回为空: {url}\n请改用「粘贴文本」输入。")

    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    if not text or len(text.strip()) < 60:
        raise ValueError(
            f"未能从该网页提取到有效正文: {url}\n"
            "该页面可能是付费墙、视频页或动态页面，请改用「粘贴文本」输入。"
        )

    # trafilatura 通常每行一个段落；统一成空行分隔
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    normalized = "\n\n".join(lines)

    title = ""
    site = ""
    try:
        meta = trafilatura.extract_metadata(html)
        if meta:
            title = (meta.title or "").strip()
            site = (meta.sitename or "").strip()
    except Exception:
        pass

    return WebArticle(text=normalized, title=title, site=site, url=url)
