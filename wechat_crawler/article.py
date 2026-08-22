"""文章正文抓取与解析。

公众号文章页（https://mp.weixin.qq.com/s/...）无需登录即可访问，
正文位于 id="js_content" 的容器中。已删除/违规文章会返回提示页。
"""

import logging
import random
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def fetch_article(link: str, min_delay: float = 3, max_delay: float = 6) -> dict | None:
    """抓取文章正文。返回 {content_text, content_html, images}，失败返回 None。"""
    time.sleep(random.uniform(min_delay, max_delay))
    try:
        resp = requests.get(link, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("正文请求失败 %s: %s", link, e)
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    content = soup.find(id="js_content")
    if content is None:
        # 文章被删除、违规屏蔽或需要验证
        hint = soup.find(class_="weui-msg__title")
        logger.warning("未找到正文（%s）: %s", hint.get_text(strip=True) if hint else "原因未知", link)
        return None

    # 图片：懒加载的真实地址在 data-src 上
    images = []
    for img in content.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if src.startswith("http"):
            images.append(src)

    # 提取纯文本，按块级元素分段
    for br in content.find_all("br"):
        br.replace_with("\n")
    paragraphs = []
    for block in content.find_all(["p", "section", "h1", "h2", "h3", "li", "blockquote"]):
        # 只取"叶子"块，避免嵌套 section 导致文本重复
        if block.find(["p", "section", "h1", "h2", "h3", "li", "blockquote"]):
            continue
        text = block.get_text(strip=True)
        if text:
            paragraphs.append(text)
    content_text = "\n\n".join(paragraphs) if paragraphs else content.get_text("\n", strip=True)

    return {
        "content_text": content_text,
        "content_html": str(content),
        "images": images,
    }
