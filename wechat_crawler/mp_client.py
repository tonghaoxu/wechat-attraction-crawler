"""微信公众平台接口客户端。

原理：登录自己的公众号后台（mp.weixin.qq.com）后，
"图文素材 -> 超链接" 功能提供了两个接口：
  1. searchbiz  —— 按名称搜索任意公众号，得到其 fakeid
  2. appmsg     —— 按 fakeid 分页拉取该公众号的历史图文列表

注意：该接口有严格频控，短时间大量请求会被临时冻结（通常几小时到一天），
所以本客户端在每次请求之间强制随机休眠。
"""

import logging
import random
import time

import requests

logger = logging.getLogger(__name__)

BASE = "https://mp.weixin.qq.com/cgi-bin"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def _parse_cookie(cookie: str) -> dict[str, str]:
    """把 "k=v; k2=v2" 形式的 cookie 字符串解析为字典。"""
    result = {}
    for part in cookie.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            result[k.strip()] = v.strip()
    return result


class FreezeError(RuntimeError):
    """接口被临时冻结（频控触发），应停止本轮抓取，数小时后再试。"""


class AuthError(RuntimeError):
    """token / cookie 失效，需要重新登录获取。"""


class MPClient:
    def __init__(self, token: str, cookie: str, min_delay: float = 12, max_delay: float = 25):
        if not token or not cookie:
            raise AuthError(
                "config.yaml 中 credentials.token / credentials.cookie 未填写，"
                "请先登录 mp.weixin.qq.com 获取（见 README.md）"
            )
        self.token = token
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Referer": "https://mp.weixin.qq.com/",
            }
        )
        # 把 cookie 放进 cookie jar（而非写死请求头），这样服务器通过 Set-Cookie
        # 滚动更新的 cookie 会被自动合并进来，会话得以"续命"。
        self._initial_cookie = cookie
        for k, v in _parse_cookie(cookie).items():
            self.session.cookies.set(k, v, domain=".weixin.qq.com")
        self._last_request = 0.0

    def current_cookie(self) -> str:
        """返回当前会话最新的 cookie 字符串（含服务器滚动更新后的值）。"""
        return "; ".join(f"{c.name}={c.value}" for c in self.session.cookies)

    def cookie_changed(self) -> bool:
        """会话过程中 cookie 是否发生了变化（需要写回时用）。"""
        return _parse_cookie(self._initial_cookie) != {
            c.name: c.value for c in self.session.cookies
        }

    # ---------- 内部 ----------

    def _throttle(self) -> None:
        """保证两次请求之间有随机间隔，降低被冻结的概率。"""
        elapsed = time.time() - self._last_request
        wait = random.uniform(self.min_delay, self.max_delay) - elapsed
        if wait > 0:
            logger.debug("频控休眠 %.1f 秒", wait)
            time.sleep(wait)
        self._last_request = time.time()

    def _get(self, endpoint: str, params: dict) -> dict:
        self._throttle()
        params = {
            **params,
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        resp = self.session.get(f"{BASE}/{endpoint}", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        ret = (data.get("base_resp") or {}).get("ret", 0)
        if ret == 200013:
            raise FreezeError("接口被临时冻结（ret=200013），请停止抓取，几小时后再试")
        if ret in (-6, 200003):
            raise AuthError(f"登录态失效（ret={ret}），请重新登录 mp.weixin.qq.com 更新 token 和 cookie")
        if ret != 0:
            raise RuntimeError(f"接口返回异常 ret={ret}: {data.get('base_resp')}")
        return data

    # ---------- 对外接口 ----------

    def search_account(self, keyword: str) -> list[dict]:
        """按关键词搜索公众号，返回候选列表 [{fakeid, nickname, alias, signature}, ...]。"""
        data = self._get(
            "searchbiz",
            {"action": "search_biz", "query": keyword, "begin": 0, "count": 5},
        )
        return [
            {
                "fakeid": item.get("fakeid", ""),
                "nickname": item.get("nickname", ""),
                "alias": item.get("alias", ""),
                "signature": item.get("signature", ""),
            }
            for item in data.get("list", [])
        ]

    def list_articles(self, fakeid: str, page: int = 0, page_size: int = 5) -> tuple[list[dict], int]:
        """拉取某公众号第 page 页的图文列表。

        返回 (文章列表, 文章总数)。文章字段：aid, title, link, digest, create_time。
        """
        data = self._get(
            "appmsg",
            {
                "action": "list_ex",
                "begin": page * page_size,
                "count": page_size,
                "query": "",
                "fakeid": fakeid,
                "type": "9",
            },
        )
        articles = [
            {
                "aid": str(item.get("aid", "")),
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "digest": item.get("digest", ""),
                "create_time": int(item.get("create_time") or item.get("update_time") or 0),
            }
            for item in data.get("app_msg_list", [])
        ]
        total = int(data.get("app_msg_cnt", 0))
        return articles, total
