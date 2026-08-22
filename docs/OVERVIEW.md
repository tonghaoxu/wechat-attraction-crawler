# 项目概览

微信景点公众号爬虫 + 多平台数据服务。抓取中国热门旅游景点**官方公众号**里
**对游客出行有用的公告**（开闭园、票价、临时闭馆、天气、假期安排等），
连同各景点的**官方购票链接**一起存入本地数据库，通过一套只读 HTTP API
供 Telegram Bot、微信客服、官网等多个平台统一取用。

```
微信公众平台后台接口 ──搜索公众号/拉文章列表──┐
                                          ▼
                              爬虫 crawl（过滤 + 抓正文）
                                          ▼
                              SQLite (data/articles.db, WAL)
                                          ▼
                              API 服务 (FastAPI, X-API-Key)
                             ┌────────────┼────────────┐
                        Telegram Bot   微信客服        官网
```

## 核心能力

1. **抓取**：用自有公众号后台登录态，搜索任意景点公众号并分页拉取历史文章列表，
   再抓取文章正文（纯文本 + 图片链接）。内置随机频控（12–25 秒）与断点续抓。
2. **过滤**：抓正文前基于标题+摘要做游客相关性判断，只保留出行相关公告，
   自动跳过广告、招聘、党建、文创带货等（真实样本保留率约 25%）。
3. **购票信息**：每个景点带城市、分类、官方购票链接与说明（人工维护于 config.yaml）。
4. **对外服务**：只读 REST API + 单文件数据包（bundle），两种方式供其他项目接入。
5. **登录态维护**：每次抓取后自动把微信滚动更新的最新 cookie 写回，延长登录有效期。

## 命令速查

```powershell
python -m wechat_crawler search <关键词>   # 搜索公众号，核对 fakeid
python -m wechat_crawler crawl             # 抓取（默认最近90天、启用过滤、只抓最新一页）
        crawl --account <名称>              #   只抓某个景点
        crawl --pages N                     #   多抓几页（抓历史）
        crawl --no-filter                   #   临时关闭过滤，抓全部
python -m wechat_crawler stats             # 各景点入库统计
python -m wechat_crawler prune [--apply]   # 用过滤规则清理库中旧的无关文章（默认预演）
python -m wechat_crawler export            # 导出 JSON + 每篇一个 Markdown
python -m wechat_crawler bundle [-o 路径]  # 打包单个自包含 JSON，交付其他项目
python -m wechat_crawler serve             # 启动 API 服务（默认 0.0.0.0:8000，/docs 有文档）
```

## API 接口（详见 docs/API.md）

| 接口 | 用途 |
|---|---|
| `GET /api/accounts` | 景点列表（城市/分类/购票链接），支持 `?category=` `?city=` |
| `GET /api/articles` | 文章列表（分页、可按账号/时间过滤） |
| `GET /api/articles/{aid}` | 单篇详情（正文全文 + 图片） |
| `GET /api/search?q=` | 全文搜索，返回命中片段（适合客服问答） |
| `GET /api/latest` | 各号最新文章（适合推送/信息流） |

调用 `/api/*` 需带请求头 `X-API-Key`（在 config.yaml 的 `api.api_keys` 配置）。

## 数据模型（SQLite 两张表）

- **accounts（景点）**：`name`(主键) / `city` / `category` / **`ticket_url`**(官方购票链接) /
  **`ticket_note`**(购票说明) / `keyword`,`fakeid`,`nickname`(爬虫用)。
  景点元数据以 config.yaml 为准，启动/抓取时自动同步入库。
- **articles（文章）**：`aid`(主键) / `account_name`(关联景点) / `title` / `link`(微信永久链接) /
  `digest` / `publish_time` / `content_text`(正文) / `images`(图片URL数组)。

## 目录结构

```
config.yaml                 # 景点清单(57个) + 抓取/过滤/API 配置（不含凭证）
credentials.yaml            # 公众号 token/cookie（本地，.gitignore 排除，不入库）
wechat_crawler/
  config.py                 # 配置加载 + 凭证安全写回
  mp_client.py              # 公众平台接口（搜号/拉列表，含频控、cookie 滚动更新）
  article.py                # 文章正文抓取与解析
  filter.py                 # 游客相关性过滤词表与判定
  storage.py                # SQLite 存储 / 查询 / 导出 / 打包
  server.py                 # FastAPI 只读数据服务
  main.py                   # 命令行入口
tests/test_filter.py        # 过滤规则测试（pytest）
docs/API.md                 # 对外接口文档
docs/USAGE.md               # 完整使用手册（命令参数、配置、频控经验）
docs/OVERVIEW.md            # 本文件
scripts/seed_demo.py        # 演示数据（联调用）
data/                       # 运行产物：数据库、导出、数据包（.gitignore 排除）
```

## 当前规模

- 配置景点 **57 个**，覆盖 20 个省级行政区，6 大分类（历史文化/自然风光/古镇古城/主题乐园/都市地标/博物馆）
- 其中 **23 个**有官方购票网址可直接跳转，其余为公众号内购票（见 `ticket_note`）
- 已抓取 **112 篇**有效公告，分布在 **34 个**账号（数据持续增量更新）

## 凭证与安全

- token/cookie 存于本地 `credentials.yaml`，已被 .gitignore 排除，**不进 git、不上传**
- 抓取数据（`data/`）同样不入库；其他项目要用数据，通过 API 或 bundle 数据包获取
- 登录态最终仍会失效（微信安全机制），届时重新登录 mp.weixin.qq.com 获取一次即可
