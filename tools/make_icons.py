"""由根目录的 study.png 生成全套站点图标。

    python tools/make_icons.py

产物写在 site/icons/，发布时由 tools/publish_site.py 原样复制到 docs/：
  - apple-touch-icon.png   iOS 主屏图标（不透明底，iOS 不支持透明）
  - icon-192 / icon-512    Android 与 manifest 用
  - icon-maskable.png      Android 自适应图标，内容收在安全区内
  - favicon-32.png / favicon.ico
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE = BASE_DIR / "study.png"
OUT_DIR = BASE_DIR / "site" / "icons"

# 画布底色，和站点纸张色一致
BG = (247, 243, 236, 255)


def _compose(size: int, scale: float) -> Image.Image:
    """把原图按 scale 缩放后居中贴到不透明画布上。"""
    src = Image.open(SOURCE).convert("RGBA")
    canvas = Image.new("RGBA", (size, size), BG)
    inner = max(1, int(size * scale))
    art = src.resize((inner, inner), Image.LANCZOS)
    offset = (size - inner) // 2
    canvas.alpha_composite(art, (offset, offset))
    return canvas.convert("RGB")


def main() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"找不到源图：{SOURCE}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    targets = [
        ("apple-touch-icon.png", 180, 0.82),
        ("icon-192.png", 192, 0.88),
        ("icon-512.png", 512, 0.88),
        # 自适应图标：内容要落在中间 80% 的安全圆内，留足裁切余量
        ("icon-maskable.png", 512, 0.62),
        ("favicon-32.png", 32, 0.96),
    ]
    for name, size, scale in targets:
        _compose(size, scale).save(OUT_DIR / name, "PNG", optimize=True)
        print(f"  {name}  {size}x{size}")

    # favicon.ico 打包多尺寸，浏览器标签页用
    ico = _compose(48, 0.96)
    ico.save(OUT_DIR / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    print("  favicon.ico  16/32/48")

    print(f"已写入 {OUT_DIR}")


if __name__ == "__main__":
    main()
