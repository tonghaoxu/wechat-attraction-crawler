"""命令行入口。

用法：
  python -m wechat_crawler search <关键词>          # 试搜某个公众号，查看候选
  python -m wechat_crawler crawl [--account 名称] [--pages N] [--no-content]
  python -m wechat_crawler export                    # 导出 JSON + Markdown
  python -m wechat_crawler stats                     # 查看入库统计
"""

import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

import time

from .article import fetch_article
from .config import Account, Config, load_config, save_cookie
from .filter import is_relevant
from .mp_client import AuthError, FreezeError, MPClient
from .storage import Storage

logger = logging.getLogger("wechat_crawler")


def cmd_search(cfg: Config, keyword: str) -> None:
    client = MPClient(cfg.token, cfg.cookie, cfg.min_delay, cfg.max_delay)
    results = client.search_account(keyword)
    if not results:
        print(f"未搜到与「{keyword}」相关的公众号")
        return
    print(f"「{keyword}」搜索结果：")
    for i, r in enumerate(results, 1):
        print(f"  {i}. {r['nickname']}  (微信号: {r['alias'] or '-'})")
        print(f"     fakeid: {r['fakeid']}")
        if r["signature"]:
            print(f"     简介: {r['signature'][:60]}")


def _resolve_fakeid(client: MPClient, store: Storage, account: Account) -> str:
    """获取公众号 fakeid：优先用配置里手填的，其次用数据库缓存，最后在线搜索。"""
    if account.fakeid:
        return account.fakeid
    cached = store.get_fakeid(account.name)
    if cached:
        return cached
    logger.info("搜索公众号「%s」...", account.keyword)
    results = client.search_account(account.keyword)
    if not results:
        logger.warning("未搜到「%s」，跳过。可在 config.yaml 中调整 keyword", account.keyword)
        return ""
    top = results[0]
    logger.info("匹配到:%s (fakeid=%s)", top["nickname"], top["fakeid"])
    store.save_account(account.name, account.keyword, top["fakeid"], top["nickname"])
    return top["fakeid"]


def cmd_crawl(
    cfg: Config,
    only_account: str | None,
    pages: int | None,
    fetch_content: bool,
    use_filter: bool = True,
) -> None:
    client = MPClient(cfg.token, cfg.cookie, cfg.min_delay, cfg.max_delay)
    store = Storage(cfg.db_path)
    pages = pages or cfg.pages_per_account
    use_filter = use_filter and cfg.filter_enabled
    min_time = time.time() - cfg.max_age_days * 86400 if cfg.max_age_days else 0

    targets = cfg.accounts
    if only_account:
        targets = [a for a in targets if only_account in (a.name, a.keyword)]
        if not targets:
            print(f"config.yaml 中找不到名为「{only_account}」的账号")
            sys.exit(1)

    store.sync_accounts(cfg.accounts)

    total_new = 0
    total_filtered = 0
    try:
        for account in targets:
            fakeid = _resolve_fakeid(client, store, account)
            if not fakeid:
                continue

            logger.info("=== 抓取「%s」（最多 %d 页）===", account.name, pages)
            for page in range(pages):
                articles, total = client.list_articles(fakeid, page=page)
                if not articles:
                    if page == 0:
                        logger.warning(
                            "「%s」第 1 页就没有文章（fakeid=%s 可能无效），"
                            "可用 search 命令核对后在 config.yaml 手动指定 fakeid",
                            account.name,
                            fakeid,
                        )
                    break
                logger.info("第 %d 页：%d 篇（该号共 %d 篇）", page + 1, len(articles), total)
                for meta in articles:
                    if store.has_article(meta["aid"]) and not store.article_needs_content(meta["aid"]):
                        logger.debug("已存在，跳过:%s", meta["title"])
                        continue
                    # 时效过滤：太旧的公告对游客无意义
                    if min_time and meta["create_time"] and meta["create_time"] < min_time:
                        logger.debug("超过 %d 天，跳过:%s", cfg.max_age_days, meta["title"])
                        continue
                    # 相关性过滤：在抓正文之前判断，节省请求
                    if use_filter:
                        keep, reason = is_relevant(
                            meta["title"], meta["digest"],
                            cfg.include_keywords, cfg.exclude_keywords,
                        )
                        if not keep:
                            total_filtered += 1
                            logger.info("  过滤 [%s] %s", reason, meta["title"][:40])
                            continue
                        logger.debug("保留 [%s] %s", reason, meta["title"][:40])
                    content = None
                    if fetch_content and meta["link"]:
                        logger.info(
                            "  抓正文 [%s] %s",
                            datetime.fromtimestamp(meta["create_time"]).strftime("%Y-%m-%d")
                            if meta["create_time"]
                            else "----",
                            meta["title"][:40],
                        )
                        content = fetch_article(meta["link"])
                    store.save_article(account.name, meta, content)
                    total_new += 1
    except FreezeError as e:
        logger.error("%s", e)
        logger.error("已保存进度，之后重新运行即可从断点继续（已入库文章会自动跳过）")
    except AuthError as e:
        logger.error("%s", e)
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("用户中断，已保存进度")
    finally:
        store.close()
        # 把服务器滚动更新后的最新 cookie 写回，延长登录态有效期
        try:
            if client.cookie_changed():
                save_cookie(client.current_cookie(), token=cfg.token)
                logger.info("已自动更新 cookie（登录态已续期）")
        except Exception as e:  # 写回失败不应影响抓取结果
            logger.warning("cookie 自动更新失败（不影响本次抓取）：%s", e)

    print(f"\n本次新增/更新 {total_new} 篇文章（过滤掉 {total_filtered} 篇与游客无关的内容），数据库：{cfg.db_path}")


def cmd_prune(cfg: Config, apply: bool) -> None:
    """用当前过滤规则清理数据库中与游客无关的历史文章。默认只预演。"""
    store = Storage(cfg.db_path)
    try:
        rows = store.all_articles_meta()
        to_delete = [
            r for r in rows
            if not is_relevant(r["title"], r["digest"] or "",
                               cfg.include_keywords, cfg.exclude_keywords)[0]
        ]
        print(f"库中共 {len(rows)} 篇，按当前过滤规则将删除 {len(to_delete)} 篇、保留 {len(rows) - len(to_delete)} 篇\n")
        for r in to_delete[:30]:
            print(f"  - {r['title'][:50]}")
        if len(to_delete) > 30:
            print(f"  … 其余 {len(to_delete) - 30} 篇略")
        if apply:
            n = store.delete_articles([r["aid"] for r in to_delete])
            print(f"\n已删除 {n} 篇。建议重新运行 export 刷新导出文件。")
        else:
            print(f"\n以上为预演，未做改动。确认无误后加 --apply 执行删除。")
    finally:
        store.close()


def cmd_bundle(cfg: Config, out: str | None) -> None:
    """打包一份可交付给其他项目的自包含 JSON 数据文件。"""
    out_path = Path(out) if out else cfg.export_dir / "attractions_bundle.json"
    store = Storage(cfg.db_path)
    try:
        n_attr, n_art = store.bundle(out_path)
    finally:
        store.close()
    size_kb = out_path.stat().st_size // 1024
    print(f"已打包 {n_attr} 个景点、{n_art} 篇文章 -> {out_path}（{size_kb} KB）")
    print("其他项目可直接读取该 JSON，无需数据库或本项目代码。")


def cmd_export(cfg: Config) -> None:
    store = Storage(cfg.db_path)
    try:
        json_path, md_count = store.export(cfg.export_dir)
    finally:
        store.close()
    print(f"已导出 JSON:{json_path}")
    print(f"已导出 Markdown:{md_count} 篇 -> {cfg.export_dir}")


def cmd_stats(cfg: Config) -> None:
    store = Storage(cfg.db_path)
    try:
        rows = store.stats()
    finally:
        store.close()
    if not rows:
        print("数据库为空，先运行 crawl")
        return
    print(f"{'公众号':<24}{'文章数':>8}{'有正文':>8}")
    print("-" * 44)
    for r in rows:
        print(f"{r['account_name']:<24}{r['total']:>8}{r['with_content']:>8}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="wechat_crawler", description="微信公众号景点内容爬虫")
    parser.add_argument("-c", "--config", default=None, help="配置文件路径（默认 config.yaml）")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="搜索公众号，查看候选与 fakeid")
    p_search.add_argument("keyword")

    p_crawl = sub.add_parser("crawl", help="抓取配置中的公众号文章")
    p_crawl.add_argument("--account", help="只抓取指定名称的账号")
    p_crawl.add_argument("--pages", type=int, help="每个账号抓取的列表页数（覆盖配置）")
    p_crawl.add_argument("--no-content", action="store_true", help="只抓列表，不抓正文")
    p_crawl.add_argument("--no-filter", action="store_true", help="关闭游客相关性过滤，抓取全部文章")

    sub.add_parser("export", help="导出 JSON 与 Markdown")
    p_bundle = sub.add_parser("bundle", help="打包一份可交付给其他项目的自包含 JSON")
    p_bundle.add_argument("-o", "--out", help="输出文件路径（默认 data/export/attractions_bundle.json）")
    sub.add_parser("stats", help="查看入库统计")
    p_prune = sub.add_parser("prune", help="用过滤规则清理库中无关的历史文章")
    p_prune.add_argument("--apply", action="store_true", help="真正执行删除（默认只预演）")
    sub.add_parser("serve", help="启动 HTTP API 服务（供 Telegram Bot / 微信客服 / 官网调用）")

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(args.config) if args.config else load_config()

    try:
        if args.command == "search":
            cmd_search(cfg, args.keyword)
        elif args.command == "crawl":
            fetch = cfg.fetch_content and not args.no_content
            cmd_crawl(cfg, args.account, args.pages, fetch, use_filter=not args.no_filter)
        elif args.command == "export":
            cmd_export(cfg)
        elif args.command == "bundle":
            cmd_bundle(cfg, args.out)
        elif args.command == "stats":
            cmd_stats(cfg)
        elif args.command == "prune":
            cmd_prune(cfg, args.apply)
        elif args.command == "serve":
            import uvicorn

            uvicorn.run("wechat_crawler.server:app", host=cfg.api_host, port=cfg.api_port)
    except AuthError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
