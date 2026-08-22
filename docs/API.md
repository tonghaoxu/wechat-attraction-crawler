# 景点公众号内容 API — 接口文档

供 Telegram Bot、微信自动客服、官方网站等下游平台接入的数据服务接口契约。
以下所有响应示例均为真实抓取（基于演示数据）。

## 基本信息

| 项目 | 说明 |
|---|---|
| Base URL | `http://<服务器地址>:8000`（端口在 `config.yaml` 的 `api.port` 配置） |
| 协议 | HTTP GET，全部接口只读 |
| 响应格式 | JSON，UTF-8 |
| 在线文档 | `GET /docs`（Swagger UI，可直接试调） |
| OpenAPI 规范 | `GET /openapi.json`（可导入 Postman / 生成客户端 SDK） |

## 鉴权

`config.yaml` 的 `api.api_keys` 非空时，所有 `/api/*` 请求必须携带请求头：

```
X-API-Key: <你的平台专属 key>
```

- 每个接入平台使用独立的 key（便于单独吊销）
- 缺失或错误返回 `401 {"detail": "无效或缺失的 X-API-Key"}`
- `/health` 不需要鉴权，可用于存活探测

## 通用约定

- **时间格式**：响应中的 `publish_time` / `latest_publish_time` 为 ISO 8601 本地时间字符串（如 `2026-07-13T12:14:49`）；请求参数 `since` 为 **Unix 秒级时间戳**
- **aid**：文章唯一 ID（字符串，可能含中文），放入 URL 路径时需做 URL 编码
- **has_content**：`false` 表示该文章只有元数据（标题/链接/摘要），暂无正文
- **演示数据**：标题带`【演示】`前缀、`aid` 以 `demo-` 开头的为联调用假数据，正式上线前会清除（`python scripts/seed_demo.py --remove`）

---

## 1. 健康检查

`GET /health`（无需鉴权）

```json
{"status": "ok"}
```

## 2. 景点公众号列表（含购票信息）

`GET /api/accounts` — 全部收录的景点：城市、分类、**官方购票链接与说明**、文章数量。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `category` | string | 否 | 按分类过滤：`历史文化` / `博物馆` / `自然风光` / `主题乐园` / `古镇古城` / `都市地标` |
| `city` | string | 否 | 按城市过滤，如 `北京`、`西安` |

`GET /api/accounts?city=西安&category=历史文化`：

```json
{
  "accounts": [
    {
      "name": "秦始皇帝陵博物院（兵马俑）",
      "nickname": "秦始皇帝陵博物院（兵马俑）",
      "city": "西安",
      "category": "历史文化",
      "ticket_url": "https://bmy.com.cn/",
      "ticket_note": "官网或\"秦始皇帝陵博物院\"公众号实名预约，已取消线下售票，护照可预约",
      "article_count": 1,
      "latest_publish_time": "2026-07-11T12:14:49"
    }
  ]
}
```

- `ticket_url` 为**官方**购票/预约入口；为空字符串表示该景点主要通过公众号菜单购票，详见 `ticket_note`
- 景点元数据（分类/购票信息）的事实来源是服务端 `config.yaml`，服务启动时自动同步入库
- 当前收录 57 个景点，覆盖北京、西安、上海、江南、川渝、云南、广西、中原、东南、东北、西北等外国游客主要目的地

## 3. 文章列表（分页）

`GET /api/articles`

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `account` | string | 否 | 按公众号名称过滤（精确匹配 `accounts` 里的 `name`） |
| `since` | int | 否 | 只返回该 Unix 时间戳之后发布的文章（适合增量同步） |
| `page` | int | 否 | 页码，从 1 开始，默认 1 |
| `page_size` | int | 否 | 每页条数，默认 20，最大 100 |

`GET /api/articles?page_size=1&account=八达岭长城`：

```json
{
  "total": 1,
  "page": 1,
  "page_size": 1,
  "items": [
    {
      "aid": "demo-八达岭长城-0",
      "account": "八达岭长城",
      "title": "【演示】八达岭长城交通指南：高铁、公交、自驾全攻略",
      "link": "https://mp.weixin.qq.com/s/demo",
      "digest": "从北京市区出发的最优路线",
      "publish_time": "2026-07-12T12:14:49",
      "has_content": true
    }
  ]
}
```

按 `publish_time` 倒序排列。列表接口不含正文，正文请用详情接口取。

## 4. 文章详情

`GET /api/articles/{aid}` — 含正文全文与图片列表。

`GET /api/articles/demo-八达岭长城-0`（aid 需 URL 编码）：

```json
{
  "aid": "demo-八达岭长城-0",
  "account": "八达岭长城",
  "title": "【演示】八达岭长城交通指南：高铁、公交、自驾全攻略",
  "link": "https://mp.weixin.qq.com/s/demo",
  "digest": "从北京市区出发的最优路线",
  "publish_time": "2026-07-12T12:14:49",
  "has_content": true,
  "content_text": "乘坐京张高铁至八达岭长城站仅需27分钟，出站后步行即可抵达景区入口。……",
  "images": []
}
```

- `content_text`：纯文本正文，段落以 `\n\n` 分隔；未抓正文时为 `null`
- `images`：正文中图片的原始 URL 数组（微信 CDN 直链，**网页端直接引用会因防盗链显示失败**，官网使用时需服务端代理或转存）
- 不存在时返回 `404 {"detail": "文章不存在"}`

## 5. 全文搜索

`GET /api/search` — 搜索标题/摘要/正文，适合客服问答、Bot 查询场景。

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `q` | string | 是 | 关键词，多个词用空格分隔（AND 关系），如 `故宫 门票` |
| `account` | string | 否 | 限定某个公众号 |
| `limit` | int | 否 | 返回条数，默认 20，最大 50 |

`GET /api/search?q=门票&limit=1`：

```json
{
  "query": "门票",
  "items": [
    {
      "aid": "demo-微故宫-0",
      "account": "故宫博物院（微故宫）",
      "title": "【演示】故宫门票预约全攻略",
      "link": "https://mp.weixin.qq.com/s/demo",
      "digest": "实名预约、开放时间、入院须知一文看懂",
      "publish_time": "2026-07-13T12:14:49",
      "has_content": true,
      "snippet": "故宫博物院实行网上实名预约购票，请提前十天通过官方渠道预约。开放时间：旺季8:30-17:00……"
    }
  ]
}
```

`snippet` 为首个关键词命中位置前后各约 60 字的片段，已去除换行。无结果时 `items` 为空数组。

## 6. 最新文章

`GET /api/latest?limit=10` — 全部公众号按发布时间倒序的最新文章（字段同列表接口），适合信息流/推送。

---

## 接入建议

- **官网前端跨域**：把官网域名加进 `config.yaml` 的 `api.cors_origins`。若为纯静态站，注意 key 会暴露在前端，建议由官网后端代理调用
- **增量同步**：下游如需本地缓存，记录上次同步时间，用 `GET /api/articles?since=<ts>` 拉增量
- **联调**：服务方执行 `python scripts/seed_demo.py` 即可提供演示数据；`--remove` 清除
- **错误处理**：非 2xx 响应均为 `{"detail": "<原因>"}` 结构
