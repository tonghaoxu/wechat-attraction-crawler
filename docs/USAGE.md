# 使用手册

README 只放了最短路径，这里是完整的命令参数、配置项与运维经验。

## 1. 安装

```bash
pip install -e .          # 仅运行
pip install -e ".[dev]"   # 含 pytest
```

需要 Python 3.10+（代码用了 `X | None` 类型语法）。

## 2. 获取凭证

1. 用**自己的**公众号登录 https://mp.weixin.qq.com （个人免费订阅号即可，无需认证）；
2. 登录后地址栏形如 `.../cgi-bin/home?t=home/index&lang=zh_CN&token=1234567890`，
   记下 `token=` 后面的数字；
3. F12 → Network → 刷新页面 → 点任意 `mp.weixin.qq.com` 的请求 → Request Headers →
   复制整串 `Cookie` 的值；
4. 在项目根目录建 `credentials.yaml`：

   ```yaml
   credentials:
     token: "1234567890"
     cookie: "appmsglist_action_xxx=card; ua_id=...; wxuin=..."
   ```

该文件已被 `.gitignore` 排除。`config.yaml` 里的 `credentials` 段留空即可——
两处都填时以 `credentials.yaml` 为准。

### Cookie 自动续期

每次 `crawl` 结束后（无论成功、被冻结还是 Ctrl+C 中断），程序都会把微信服务器
滚动更新的最新 Cookie 写回 `credentials.yaml`。保持定期抓取就能持续续期。

微信的会话最终仍会失效（安全机制要求重新扫码），届时程序报「登录态失效」，
重新走一遍上面的步骤即可。

## 3. 命令

### `search` — 核对公众号

```bash
python -m wechat_crawler search 微故宫
```

返回最多 5 个候选及其 `fakeid`。**建议新增景点时先搜一次**，确认匹配到的是官方号
而不是同名营销号。确认后可把 `fakeid` 手动写进 `config.yaml` 对应条目，跳过后续搜索请求。

### `crawl` — 抓取

```bash
python -m wechat_crawler crawl                      # 按配置抓全部景点
python -m wechat_crawler crawl --account 颐和园      # 只抓一个
python -m wechat_crawler crawl --pages 5            # 每号抓 5 页（每页 5 篇）
python -m wechat_crawler crawl --no-content         # 只抓列表，不抓正文
python -m wechat_crawler crawl --no-filter          # 临时关闭相关性过滤
python -m wechat_crawler -v crawl                   # 输出调试日志
```

已入库且已有正文的文章会自动跳过，因此**重复运行是安全的**，天然支持断点续抓。

### `stats` — 入库统计

```bash
python -m wechat_crawler stats
```

按公众号列出文章数与已抓正文数。

### `prune` — 用当前过滤规则清理历史数据

调整过滤词表后，库里旧数据仍是按老规则抓的。`prune` 会用当前规则重新判定：

```bash
python -m wechat_crawler prune          # 预演：只打印将删除哪些，不改动
python -m wechat_crawler prune --apply  # 确认后真正删除
```

**默认只预演**，看清楚要删什么再加 `--apply`。删完建议重跑 `export` 刷新导出文件。

### `export` — 导出 JSON + Markdown

```bash
python -m wechat_crawler export
```

产出在 `data/export/`：

- `articles.json` —— 全部文章的结构化数据；
- `<公众号名>/<日期>_<标题>.md` —— 每篇一个 Markdown，自带原文链接。

注意：导出目录是**纯生成产物**，每次导出前会清空各公众号子目录，
避免残留已删除文章的旧文件。别往里面放手写内容。

### `bundle` — 打包给其他项目

```bash
python -m wechat_crawler bundle
python -m wechat_crawler bundle -o /path/to/data.json
```

产出单个自包含 JSON（景点 + 购票信息 + 全部文章正文），
下游项目直接读文件即可，不需要数据库、也不需要本项目代码。适合离线交付。

### `serve` — 启动 API 服务

```bash
python -m wechat_crawler serve
```

等价于 `uvicorn wechat_crawler.server:app --host 0.0.0.0 --port 8000`。
接口契约见 [API.md](API.md)。

## 4. 配置项

全部在 `config.yaml`。

```yaml
crawl:
  pages_per_account: 1    # 每号抓几页列表（每页 5 篇）；只要最新内容设 1
  min_delay: 12           # 请求最小间隔（秒）——不要调低
  max_delay: 25           # 请求最大间隔（秒）
  fetch_content: true     # 是否抓正文
  max_age_days: 90        # 只抓最近 N 天，0 = 不限
  filter:
    enabled: true
    include_keywords: []  # 留空 = 用内置词表；填了则**完全替换**，不是追加
    exclude_keywords: []
```

```yaml
api:
  host: 0.0.0.0
  port: 8000
  api_keys:               # 为每个接入平台各发一个 key，留空 = 不鉴权（仅限本机调试）
    - "tg-bot-xxxxxxxx"
  cors_origins: ["*"]     # 官网前端直连时填官网域名
```

景点清单每条支持：`name`（展示名，存库主键）、`keyword`（搜索用）、`fakeid`（可选，
手动指定则跳过搜索）、`city`、`category`、`ticket_url`、`ticket_note`。
景点元数据以 `config.yaml` 为唯一事实来源，每次抓取/启动服务时自动同步进数据库。

### 过滤词表

内置词表在 [`wechat_crawler/filter.py`](../wechat_crawler/filter.py)，分两组：

- `DEFAULT_INCLUDE` —— 开闭园、票价、预约、索道游船、天气预警、假期安排……
- `DEFAULT_EXCLUDE` —— 招聘招标、党建表彰、文创带货、促销营销、研学征稿、公务往来……

判定顺序是 **排除词 → 保留词 → 默认丢弃**。排除词优先级更高，
所以"关于公开招聘讲解员的公告"会被丢弃，尽管它含有保留词"公告"。

调整词表后记得跑 `pytest`，测试里有一组真实标题样本用于防止误伤核心公告。

## 5. 频控与封禁

这是使用本项目最需要注意的地方。公众平台接口有严格频控：

- 短时间请求过多会被**临时冻结**（`ret=200013`），一般数小时后自动解冻，
  不影响公众号本身，也不影响正常网页登录；
- 程序在每次列表请求间强制随机休眠 12–25 秒，**不建议调低**；
- 建议每次只抓 2–3 页，分多天增量抓取；
- 被冻结时程序会自动停止并保存进度，**不要立刻重试**——重试只会延长冻结时间。
  等几小时后重新运行即可从断点继续。

## 6. 常见问题

**「第 1 页就没有文章」** —— 缓存的 `fakeid` 可能失效或搜错了号。
用 `search` 重新核对，把正确的 `fakeid` 写进 `config.yaml`。

**「未找到正文」** —— 文章被删除、违规屏蔽或需要验证。程序会跳过并记录日志，
文章元数据仍会入库，下次运行会重试抓正文。

**「登录态失效（ret=-6 / 200003）」** —— 重新登录 mp.weixin.qq.com 获取 token 和 cookie。

**数据库锁冲突** —— 已开启 WAL 模式，爬虫写入与 API 读取可并发。
若仍遇到，检查是否有多个 `crawl` 进程同时运行。
