"""HTTP API 服务：向 Telegram Bot、微信客服、官网等多个平台统一提供已爬取的数据。

启动：
  python -m wechat_crawler serve
  （或 uvicorn wechat_crawler.server:app --host 0.0.0.0 --port 8000）

鉴权：config.yaml 的 api.api_keys 非空时，所有 /api/* 请求需带请求头 X-API-Key。
文档：启动后访问 http://<host>:<port>/docs 查看交互式 API 文档。
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import load_config
from .storage import Storage

cfg = load_config()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动时把 config.yaml 的景点清单（分类/购票信息）同步进数据库
    store = Storage(cfg.db_path)
    try:
        store.sync_accounts(cfg.accounts)
    finally:
        store.close()
    yield


app = FastAPI(
    title="景点公众号内容 API",
    description="外国游客热门景点官方公众号文章数据，供 Telegram Bot / 微信客服 / 官网调用",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def require_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    if cfg.api_keys and x_api_key not in cfg.api_keys:
        raise HTTPException(status_code=401, detail="无效或缺失的 X-API-Key")


def get_store():
    store = Storage(cfg.db_path)
    try:
        yield store
    finally:
        store.close()


@app.get("/health", tags=["系统"])
def health():
    return {"status": "ok"}


@app.get("/api/accounts", tags=["数据"], dependencies=[Depends(require_key)])
def list_accounts(
    category: str | None = Query(default=None, description="按景点分类过滤，如：历史文化/博物馆/自然风光/主题乐园/古镇古城/都市地标"),
    city: str | None = Query(default=None, description="按城市过滤，如：北京"),
    store: Storage = Depends(get_store),
):
    """全部景点公众号：城市、分类、官方购票链接与说明、文章数量。"""
    return {"accounts": store.list_accounts(category=category, city=city)}


@app.get("/api/articles", tags=["数据"], dependencies=[Depends(require_key)])
def list_articles(
    account: str | None = Query(default=None, description="按公众号名称过滤"),
    since: int | None = Query(default=None, description="只返回该 Unix 时间戳之后发布的文章"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    store: Storage = Depends(get_store),
):
    """分页获取文章列表（元数据，不含正文）。"""
    items, total = store.list_articles(account=account, since=since, page=page, page_size=page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@app.get("/api/articles/{aid}", tags=["数据"], dependencies=[Depends(require_key)])
def get_article(aid: str, store: Storage = Depends(get_store)):
    """单篇文章详情（含正文全文与图片列表）。"""
    item = store.get_article(aid)
    if item is None:
        raise HTTPException(status_code=404, detail="文章不存在")
    return item


@app.get("/api/search", tags=["数据"], dependencies=[Depends(require_key)])
def search(
    q: str = Query(min_length=1, description="关键词，空格分隔多个词为 AND 关系"),
    account: str | None = Query(default=None, description="限定某个公众号"),
    limit: int = Query(default=20, ge=1, le=50),
    store: Storage = Depends(get_store),
):
    """全文搜索（标题/摘要/正文），返回带命中片段的结果。适合客服机器人问答场景。"""
    return {"query": q, "items": store.search(q, account=account, limit=limit)}


@app.get("/api/latest", tags=["数据"], dependencies=[Depends(require_key)])
def latest(
    limit: int = Query(default=10, ge=1, le=50),
    store: Storage = Depends(get_store),
):
    """全部公众号的最新文章，适合做推送/首页信息流。"""
    items, _ = store.list_articles(page=1, page_size=limit)
    return {"items": items}
