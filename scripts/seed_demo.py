# -*- coding: utf-8 -*-
"""向数据库写入演示数据，让 Telegram Bot / 微信客服 / 官网在真实爬取前就能开发调试。

用法：  python scripts/seed_demo.py
清除：  python scripts/seed_demo.py --remove   （只删除演示数据，不动真实数据）

所有演示文章的 aid 都以 "demo-" 开头，标题带【演示】前缀，方便识别与清理。
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_crawler.config import load_config
from wechat_crawler.storage import Storage

NOW = int(time.time())
DAY = 86400

DEMO = [
    {
        "account": "故宫博物院（微故宫）",
        "keyword": "微故宫",
        "articles": [
            {
                "title": "故宫门票预约全攻略",
                "digest": "实名预约、开放时间、入院须知一文看懂",
                "days_ago": 1,
                "content": "故宫博物院实行网上实名预约购票，请提前十天通过官方渠道预约。"
                "开放时间：旺季8:30-17:00（16:00停止入院），周一闭馆（法定节假日除外）。"
                "外籍游客可凭护照在综合服务窗口核验入院，也可通过官方英文网站预约。"
                "馆内提供多语种讲解器租赁服务，支持英语、法语、德语、日语、韩语等40种语言。",
            },
            {
                "title": "太和殿建筑细节里的中国智慧",
                "digest": "屋脊上的脊兽为什么是奇数？",
                "days_ago": 5,
                "content": "太和殿是紫禁城内规模最大、等级最高的建筑。屋脊之上排列着十只脊兽，"
                "为现存古建筑中孤例。太和殿广场可容纳数万人，是明清两代举行大典的场所。",
            },
        ],
    },
    {
        "account": "八达岭长城",
        "keyword": "八达岭长城",
        "articles": [
            {
                "title": "八达岭长城交通指南：高铁、公交、自驾全攻略",
                "digest": "从北京市区出发的最优路线",
                "days_ago": 2,
                "content": "乘坐京张高铁至八达岭长城站仅需27分钟，出站后步行即可抵达景区入口。"
                "市区游客也可在德胜门乘877路公交直达。景区实行全网络实名制预约售票，"
                "当日票售完即止，建议外国游客提前通过官方渠道用护照信息预约。",
            },
        ],
    },
    {
        "account": "秦始皇帝陵博物院（兵马俑）",
        "keyword": "秦始皇帝陵博物院",
        "articles": [
            {
                "title": "兵马俑参观路线推荐：一号坑到铜车马",
                "digest": "怎样看懂两千年前的地下军团",
                "days_ago": 3,
                "content": "推荐参观顺序：一号坑—三号坑—二号坑—铜车马博物馆。一号坑是规模最大的俑坑，"
                "现已出土陶俑千余件。院内提供英语、日语、韩语等外语讲解服务，"
                "也可租用多语种自助讲解器。持护照可在人工窗口购票。",
            },
        ],
    },
    {
        "account": "成都大熊猫繁育研究基地",
        "keyword": "成都大熊猫繁育研究基地",
        "articles": [
            {
                "title": "看熊猫的最佳时间：为什么要赶早？",
                "digest": "上午9点前的熊猫最活跃",
                "days_ago": 1,
                "content": "大熊猫在清晨气温较低时最为活跃，建议开园（7:30）后尽早入园。"
                "上午9点前往往能看到熊猫进食、爬树、打闹。中午气温升高后熊猫多在睡觉。"
                "基地支持护照直接购票入园，园区标识均有中英文对照。",
            },
        ],
    },
    {
        "account": "杭州西湖",
        "keyword": "杭州西湖风景名胜区",
        "articles": [
            {
                "title": "西湖十景漫步路线：从断桥到雷峰塔",
                "digest": "一日走完经典十景",
                "days_ago": 4,
                "content": "推荐路线：断桥残雪—白堤—平湖秋月—孤山—苏堤春晓—花港观鱼—雷峰夕照。"
                "西湖景区大部分区域免费开放，雷峰塔等个别景点需购票。"
                "环湖观光车支持随上随下，是节省体力的好选择。",
            },
        ],
    },
    {
        "account": "上海迪士尼度假区",
        "keyword": "上海迪士尼度假区",
        "articles": [
            {
                "title": "上海迪士尼一日游省时攻略",
                "digest": "热门项目怎么排、烟花几点看",
                "days_ago": 2,
                "content": "开园即冲创极速光轮或翱翔·飞越地平线可大幅减少排队时间。"
                "官方App支持英文界面，可实时查看各项目等候时长并领取预约等候卡。"
                "夜光幻影秀（烟花表演）通常在闭园前开始，城堡正前方为最佳观赏位。",
            },
        ],
    },
]


def seed(store: Storage) -> int:
    count = 0
    for acc in DEMO:
        # fakeid 必须留空：写入假值会被爬虫当作缓存使用，导致真实抓取拿空结果
        store.save_account(acc["account"], acc["keyword"], "", acc["account"])
        for i, art in enumerate(acc["articles"]):
            aid = f"demo-{acc['keyword']}-{i}"
            store.save_article(
                acc["account"],
                {
                    "aid": aid,
                    "title": f"【演示】{art['title']}",
                    "link": "https://mp.weixin.qq.com/s/demo",
                    "digest": art["digest"],
                    "create_time": NOW - art["days_ago"] * DAY,
                },
                {
                    "content_text": art["content"],
                    "content_html": f"<div id=\"js_content\"><p>{art['content']}</p></div>",
                    "images": [],
                },
            )
            count += 1
    return count


def remove(store: Storage) -> int:
    # 只删演示文章；账号行是真实景点（由 config 同步维护），不能删
    cur = store.conn.execute("DELETE FROM articles WHERE aid LIKE 'demo-%'")
    store.conn.execute("UPDATE accounts SET fakeid='' WHERE fakeid LIKE 'demo-fakeid-%'")
    store.conn.commit()
    return cur.rowcount


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true", help="删除演示数据")
    args = parser.parse_args()

    cfg = load_config()
    store = Storage(cfg.db_path)
    try:
        if args.remove:
            n = remove(store)
            print(f"已删除 {n} 篇演示文章")
        else:
            n = seed(store)
            print(f"已写入 {n} 篇演示文章 -> {cfg.db_path}")
    finally:
        store.close()
