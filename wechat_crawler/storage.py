"""SQLite 存储与导出。"""

import json
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    name        TEXT PRIMARY KEY,
    keyword     TEXT NOT NULL,
    fakeid      TEXT NOT NULL DEFAULT '',
    nickname    TEXT NOT NULL DEFAULT '',
    city        TEXT NOT NULL DEFAULT '',   -- 所在城市
    category    TEXT NOT NULL DEFAULT '',   -- 景点分类：历史文化/博物馆/自然风光/主题乐园/古镇古城/都市地标
    ticket_url  TEXT NOT NULL DEFAULT '',   -- 官方购票/预约链接
    ticket_note TEXT NOT NULL DEFAULT ''    -- 购票方式说明
);

CREATE TABLE IF NOT EXISTS articles (
    aid          TEXT PRIMARY KEY,
    account_name TEXT NOT NULL,
    title        TEXT NOT NULL,
    link         TEXT NOT NULL,
    digest       TEXT NOT NULL DEFAULT '',
    publish_time INTEGER NOT NULL DEFAULT 0,
    content_text TEXT,
    content_html TEXT,
    images       TEXT,          -- JSON 数组
    fetched_at   TEXT NOT NULL,
    FOREIGN KEY (account_name) REFERENCES accounts(name)
);

CREATE INDEX IF NOT EXISTS idx_articles_account ON articles(account_name, publish_time DESC);
"""


class Storage:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        # WAL 模式：允许爬虫写入的同时 API 服务并发读取
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """老版本数据库自动补齐新增列。"""
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(accounts)")}
        for col in ("city", "category", "ticket_url", "ticket_note"):
            if col not in existing:
                self.conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # ---------- 账号 ----------

    def get_fakeid(self, name: str) -> str:
        row = self.conn.execute("SELECT fakeid FROM accounts WHERE name = ?", (name,)).fetchone()
        return row["fakeid"] if row else ""

    def save_account(self, name: str, keyword: str, fakeid: str, nickname: str) -> None:
        """爬虫解析到 fakeid 后回写。只更新爬虫字段，不覆盖景点元数据。"""
        self.conn.execute(
            "INSERT INTO accounts(name, keyword, fakeid, nickname) VALUES (?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET keyword=excluded.keyword, "
            "fakeid=excluded.fakeid, nickname=excluded.nickname",
            (name, keyword, fakeid, nickname),
        )
        self.conn.commit()

    def sync_accounts(self, accounts) -> None:
        """把 config.yaml 中的景点清单（城市/分类/购票信息）同步进数据库。

        config 是景点元数据的唯一事实来源；fakeid/nickname 由爬虫维护，此处不动。
        """
        for a in accounts:
            self.conn.execute(
                "INSERT INTO accounts(name, keyword, city, category, ticket_url, ticket_note) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET keyword=excluded.keyword, "
                "city=excluded.city, category=excluded.category, "
                "ticket_url=excluded.ticket_url, ticket_note=excluded.ticket_note",
                (a.name, a.keyword, a.city, a.category, a.ticket_url, a.ticket_note),
            )
        self.conn.commit()

    # ---------- 文章 ----------

    def has_article(self, aid: str) -> bool:
        return self.conn.execute("SELECT 1 FROM articles WHERE aid = ?", (aid,)).fetchone() is not None

    def article_needs_content(self, aid: str) -> bool:
        row = self.conn.execute("SELECT content_text FROM articles WHERE aid = ?", (aid,)).fetchone()
        return row is not None and row["content_text"] is None

    def save_article(self, account_name: str, meta: dict, content: dict | None) -> None:
        self.conn.execute(
            "INSERT INTO articles(aid, account_name, title, link, digest, publish_time, "
            "content_text, content_html, images, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(aid) DO UPDATE SET content_text=COALESCE(excluded.content_text, content_text), "
            "content_html=COALESCE(excluded.content_html, content_html), "
            "images=COALESCE(excluded.images, images)",
            (
                meta["aid"],
                account_name,
                meta["title"],
                meta["link"],
                meta.get("digest", ""),
                meta.get("create_time", 0),
                content["content_text"] if content else None,
                content["content_html"] if content else None,
                json.dumps(content["images"], ensure_ascii=False) if content else None,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.conn.commit()

    def all_articles_meta(self) -> list[sqlite3.Row]:
        """返回所有文章的 (aid, account_name, title, digest)，供过滤/清理使用。"""
        return self.conn.execute(
            "SELECT aid, account_name, title, digest FROM articles"
        ).fetchall()

    def delete_articles(self, aids: list[str]) -> int:
        if not aids:
            return 0
        self.conn.executemany("DELETE FROM articles WHERE aid = ?", [(a,) for a in aids])
        self.conn.commit()
        return len(aids)

    def stats(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT account_name, COUNT(*) AS total, "
            "SUM(CASE WHEN content_text IS NOT NULL THEN 1 ELSE 0 END) AS with_content "
            "FROM articles GROUP BY account_name ORDER BY total DESC"
        ).fetchall()

    # ---------- 查询（供 API 服务使用） ----------

    def list_accounts(self, category: str | None = None, city: str | None = None) -> list[dict]:
        where, params = [], []
        if category:
            where.append("a.category = ?")
            params.append(category)
        if city:
            where.append("a.city = ?")
            params.append(city)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.conn.execute(
            f"SELECT a.name, a.nickname, a.city, a.category, a.ticket_url, a.ticket_note, "
            f"COUNT(ar.aid) AS total, MAX(ar.publish_time) AS latest "
            f"FROM accounts a LEFT JOIN articles ar ON ar.account_name = a.name "
            f"{clause} GROUP BY a.name ORDER BY a.category, total DESC",
            params,
        ).fetchall()
        return [
            {
                "name": r["name"],
                "nickname": r["nickname"],
                "city": r["city"],
                "category": r["category"],
                "ticket_url": r["ticket_url"],
                "ticket_note": r["ticket_note"],
                "article_count": r["total"],
                "latest_publish_time": _ts_to_iso(r["latest"]),
            }
            for r in rows
        ]

    def list_articles(
        self,
        account: str | None = None,
        since: int | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """分页查询文章元数据（不含正文）。返回 (列表, 总数)。"""
        where, params = [], []
        if account:
            where.append("account_name = ?")
            params.append(account)
        if since:
            where.append("publish_time >= ?")
            params.append(since)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        total = self.conn.execute(
            f"SELECT COUNT(*) AS n FROM articles {clause}", params
        ).fetchone()["n"]
        rows = self.conn.execute(
            f"SELECT aid, account_name, title, link, digest, publish_time, "
            f"content_text IS NOT NULL AS has_content FROM articles {clause} "
            f"ORDER BY publish_time DESC LIMIT ? OFFSET ?",
            [*params, page_size, (page - 1) * page_size],
        ).fetchall()
        return [_meta_dict(r) for r in rows], total

    def get_article(self, aid: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM articles WHERE aid = ?", (aid,)).fetchone()
        if r is None:
            return None
        item = _meta_dict(r)
        item["content_text"] = r["content_text"]
        item["images"] = json.loads(r["images"]) if r["images"] else []
        return item

    def search(self, query: str, account: str | None = None, limit: int = 20) -> list[dict]:
        """关键词搜索标题/摘要/正文。多个关键词（空格分隔）为 AND 关系，返回带片段的结果。"""
        keywords = [k for k in query.split() if k]
        if not keywords:
            return []
        where, params = [], []
        for kw in keywords:
            where.append("(title LIKE ? OR digest LIKE ? OR content_text LIKE ?)")
            like = f"%{kw}%"
            params.extend([like, like, like])
        if account:
            where.append("account_name = ?")
            params.append(account)
        rows = self.conn.execute(
            f"SELECT aid, account_name, title, link, digest, publish_time, content_text, "
            f"content_text IS NOT NULL AS has_content "
            f"FROM articles WHERE {' AND '.join(where)} "
            f"ORDER BY publish_time DESC LIMIT ?",
            [*params, limit],
        ).fetchall()

        results = []
        for r in rows:
            item = _meta_dict(r)
            item["snippet"] = _make_snippet(r["content_text"] or r["digest"] or "", keywords[0])
            results.append(item)
        return results

    # ---------- 数据打包（交付给其他项目） ----------

    def bundle(self, out_path: Path) -> tuple[int, int]:
        """导出单个自包含 JSON：景点（含购票信息）+ 其下文章（含正文）。

        结构：
        {
          "meta": {...},
          "attractions": [
            {"name","city","category","ticket_url","ticket_note","article_count",
             "articles": [{"aid","title","link","digest","publish_time","content_text","images"}]}
          ]
        }
        返回 (景点数, 文章数)。
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)
        accounts = self.conn.execute(
            "SELECT name, nickname, city, category, ticket_url, ticket_note FROM accounts ORDER BY category, city"
        ).fetchall()

        attractions = []
        total_articles = 0
        for a in accounts:
            arts = self.conn.execute(
                "SELECT aid, title, link, digest, publish_time, content_text, images "
                "FROM articles WHERE account_name = ? ORDER BY publish_time DESC",
                (a["name"],),
            ).fetchall()
            # 只收录已抓到正文或有内容的账号相关文章；无文章的景点仍保留（购票信息本身有用）
            article_list = [
                {
                    "aid": r["aid"],
                    "title": r["title"],
                    "link": r["link"],
                    "digest": r["digest"],
                    "publish_time": _ts_to_iso(r["publish_time"]),
                    "content_text": r["content_text"],
                    "images": json.loads(r["images"]) if r["images"] else [],
                }
                for r in arts
            ]
            total_articles += len(article_list)
            attractions.append(
                {
                    "name": a["name"],
                    "nickname": a["nickname"],
                    "city": a["city"],
                    "category": a["category"],
                    "ticket_url": a["ticket_url"],
                    "ticket_note": a["ticket_note"],
                    "article_count": len(article_list),
                    "articles": article_list,
                }
            )

        payload = {
            "meta": {
                "description": "中国热门景点官方公众号数据（景点购票信息 + 出行相关公告）",
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "attraction_count": len(attractions),
                "article_count": total_articles,
                "schema_version": 1,
            },
            "attractions": attractions,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(attractions), total_articles

    # ---------- 导出 ----------

    def export(self, export_dir: Path) -> tuple[Path, int]:
        """导出为 JSON（全量一个文件）+ Markdown（每篇一个文件）。

        导出目录是纯生成产物：每次导出前清空各公众号子目录，避免残留已删除文章的旧文件。
        """
        export_dir.mkdir(parents=True, exist_ok=True)
        for child in export_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
        rows = self.conn.execute(
            "SELECT * FROM articles ORDER BY account_name, publish_time DESC"
        ).fetchall()

        # JSON
        items = []
        for r in rows:
            items.append(
                {
                    "account": r["account_name"],
                    "title": r["title"],
                    "link": r["link"],
                    "digest": r["digest"],
                    "publish_time": datetime.fromtimestamp(r["publish_time"]).isoformat()
                    if r["publish_time"]
                    else None,
                    "content_text": r["content_text"],
                    "images": json.loads(r["images"]) if r["images"] else [],
                }
            )
        json_path = export_dir / "articles.json"
        json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

        # Markdown：有正文的输出正文；纯图片文章（无文字）输出图片链接
        md_count = 0
        for r in rows:
            images = json.loads(r["images"]) if r["images"] else []
            if not r["content_text"] and not images:
                continue
            account_dir = export_dir / _safe_name(r["account_name"])
            account_dir.mkdir(exist_ok=True)
            date = (
                datetime.fromtimestamp(r["publish_time"]).strftime("%Y-%m-%d")
                if r["publish_time"]
                else "unknown"
            )
            md_path = account_dir / f"{date}_{_safe_name(r['title'])[:50]}.md"
            parts = [
                f"# {r['title']}\n",
                f"- 公众号：{r['account_name']}",
                f"- 发布时间:{date}",
                f"- 原文链接:{r['link']}\n",
                "---\n",
            ]
            if r["content_text"]:
                parts.append(f"{r['content_text']}\n")
            else:
                parts.append("*（本文为纯图片推文，无文字内容，图片如下）*\n")
            if images:
                parts.append("## 图片\n")
                parts.extend(f"{i}. {url}" for i, url in enumerate(images, 1))
                parts.append("")
            md_path.write_text("\n".join(parts), encoding="utf-8")
            md_count += 1

        return json_path, md_count


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_") or "untitled"


def _ts_to_iso(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts).isoformat() if ts else None


def _meta_dict(r: sqlite3.Row) -> dict:
    has_content = (
        bool(r["has_content"]) if "has_content" in r.keys() else r["content_text"] is not None
    )
    return {
        "aid": r["aid"],
        "account": r["account_name"],
        "title": r["title"],
        "link": r["link"],
        "digest": r["digest"],
        "publish_time": _ts_to_iso(r["publish_time"]),
        "has_content": has_content,
    }


def _make_snippet(text: str, keyword: str, radius: int = 60) -> str:
    """截取命中关键词前后各 radius 个字符作为片段。"""
    if not text:
        return ""
    text = text.replace("\n", " ")
    pos = text.find(keyword)
    if pos < 0:
        return text[: radius * 2] + ("…" if len(text) > radius * 2 else "")
    start = max(0, pos - radius)
    end = min(len(text), pos + len(keyword) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"
