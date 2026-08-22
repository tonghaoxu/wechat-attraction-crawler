"""配置加载。"""

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.yaml"


def save_cookie(cookie: str, token: str | None = None, path: Path = CREDENTIALS_PATH) -> None:
    """把最新 cookie（及可选 token）写回 credentials.yaml，保留原有的另一项。

    credentials.yaml 不入 git，仅用于本地续存滚动更新后的登录态。

    写入采用三重加固：
    1. 用 yaml.safe_dump 序列化，正确转义 cookie 里可能出现的引号/特殊字符
       （手工拼 `"{cookie}"` 遇到含引号的值会写出坏 YAML，下次读取即失败）；
    2. 先写同目录临时文件、再原子 rename 覆盖，避免写到一半被中断产生半截文件；
    3. 落盘后强制 0600 权限，凭证不被其他用户读取。
    """
    existing = {}
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        existing = loaded.get("credentials", loaded)
    token = token if token is not None else existing.get("token", "")

    header = (
        "# 公众号后台凭证（本文件已被 .gitignore 排除，不会上传）\n"
        "# cookie 会在每次抓取后自动更新为最新值，以延长登录态有效期\n"
    )
    body = yaml.safe_dump(
        {"credentials": {"token": str(token), "cookie": cookie}},
        allow_unicode=True,
        sort_keys=False,
    )

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".credentials.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(header + body)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)  # 原子替换
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


@dataclass
class Account:
    name: str
    keyword: str
    fakeid: str = ""
    city: str = ""
    category: str = ""
    ticket_url: str = ""
    ticket_note: str = ""


@dataclass
class Config:
    token: str
    cookie: str
    pages_per_account: int
    min_delay: float
    max_delay: float
    fetch_content: bool
    db_path: Path
    export_dir: Path
    max_age_days: int = 90          # 只抓最近 N 天的文章，0 = 不限
    filter_enabled: bool = True     # 是否启用游客相关性过滤
    include_keywords: list[str] = field(default_factory=list)  # 空 = 用 filter.py 默认值
    exclude_keywords: list[str] = field(default_factory=list)
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_keys: list[str] = field(default_factory=list)
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    accounts: list[Account] = field(default_factory=list)


def load_config(path: str | Path | None = None) -> Config:
    """加载配置。优先级：显式参数 > 环境变量 WECHAT_CRAWLER_CONFIG > 项目根目录 config.yaml。"""
    if path is None:
        path = os.environ.get("WECHAT_CRAWLER_CONFIG") or DEFAULT_CONFIG_PATH
    path = Path(path)
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    cred = raw.get("credentials") or {}
    # 凭证优先从 config.yaml 同目录的 credentials.yaml 读取（该文件不入 git）
    cred_file = path.parent / "credentials.yaml"
    if cred_file.exists():
        local = yaml.safe_load(cred_file.read_text(encoding="utf-8")) or {}
        local = local.get("credentials", local)  # 兼容带/不带 credentials: 外层的写法
        for key in ("token", "cookie"):
            if local.get(key):
                cred[key] = local[key]
    crawl = raw.get("crawl") or {}
    storage = raw.get("storage") or {}
    api = raw.get("api") or {}

    def _resolve(p: str) -> Path:
        p = Path(p)
        return p if p.is_absolute() else PROJECT_ROOT / p

    accounts = [
        Account(
            name=a["name"],
            keyword=a.get("keyword", a["name"]),
            fakeid=a.get("fakeid", "") or "",
            city=a.get("city", "") or "",
            category=a.get("category", "") or "",
            ticket_url=a.get("ticket_url", "") or "",
            ticket_note=a.get("ticket_note", "") or "",
        )
        for a in raw.get("accounts") or []
    ]

    return Config(
        token=str(cred.get("token", "") or ""),
        cookie=str(cred.get("cookie", "") or ""),
        pages_per_account=int(crawl.get("pages_per_account", 1)),
        min_delay=float(crawl.get("min_delay", 12)),
        max_delay=float(crawl.get("max_delay", 25)),
        fetch_content=bool(crawl.get("fetch_content", True)),
        max_age_days=int(crawl.get("max_age_days", 90)),
        filter_enabled=bool((crawl.get("filter") or {}).get("enabled", True)),
        include_keywords=[str(k) for k in (crawl.get("filter") or {}).get("include_keywords") or []],
        exclude_keywords=[str(k) for k in (crawl.get("filter") or {}).get("exclude_keywords") or []],
        db_path=_resolve(storage.get("db_path", "data/articles.db")),
        export_dir=_resolve(storage.get("export_dir", "data/export")),
        api_host=str(api.get("host", "0.0.0.0")),
        api_port=int(api.get("port", 8000)),
        api_keys=[str(k) for k in (api.get("api_keys") or []) if k],
        cors_origins=[str(o) for o in (api.get("cors_origins") or ["*"])],
        accounts=accounts,
    )
