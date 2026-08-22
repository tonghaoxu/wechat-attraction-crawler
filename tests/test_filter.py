"""filter.is_relevant 的规则测试。

三条规则（见 filter.py 模块文档）：
  1. 命中排除词 -> 丢弃（优先级最高）
  2. 命中保留词 -> 保留
  3. 都未命中   -> 丢弃（白名单模式）

用例中的"真实标题"取自实际抓取样本，用于防止调整词表时误伤核心公告。
"""

import pytest

from wechat_crawler.filter import DEFAULT_EXCLUDE, DEFAULT_INCLUDE, is_relevant


# ---------- 规则 2：影响出行的公告应保留 ----------

# 抓取样本中的真实标题，覆盖开闭园/交通/天气/票务四类核心公告
REAL_KEPT = [
    "上海之巅观光厅临时闭馆公告",
    "关于八达岭长城景区临时暂停开放的公告",
    "关于天门山东线玻璃栈道恢复开放的通告",
    "关于漓江精华段游览线路游船暂停营运的通知",
    "九寨沟景区发布：明日天气预报",
    "布达拉宫暂缓暑期周一闭馆机制公告",
    "上海野生动物园调整运营时间公告",
    "恭王府博物馆关于2026年端午节假期开放时间的公告",
]


@pytest.mark.parametrize("title", REAL_KEPT)
def test_real_notices_are_kept(title):
    keep, reason = is_relevant(title)
    assert keep, f"核心公告被误杀：{title}（原因：{reason}）"


# ---------- 规则 1：与游客无关的内容应丢弃 ----------

REAL_DROPPED = [
    "2026年度公开招聘编外工作人员公告",     # 招聘 > 公告
    "我馆党支部开展主题党日活动",
    "文创上新！限时特惠不容错过",
    "“我与长城的故事”征稿启事",
    "我馆荣获省级文明单位称号",
    "省文旅厅领导一行来我馆调研指导",
]


@pytest.mark.parametrize("title", REAL_DROPPED)
def test_irrelevant_content_is_dropped(title):
    keep, _ = is_relevant(title)
    assert not keep, f"无关内容未被过滤：{title}"


# ---------- 规则 1 优先于规则 2（本项目的关键设计） ----------


def test_exclude_beats_include():
    """同时含排除词与保留词时，必须丢弃。

    否则"招聘公告""文创上新预约"这类标题会因含"公告""预约"被放行。
    """
    keep, reason = is_relevant("关于公开招聘讲解员的公告")
    assert not keep
    assert "招聘" in reason


def test_exclude_beats_include_in_digest():
    """排除词出现在摘要里同样生效。"""
    keep, _ = is_relevant("重要通知", digest="本周文创产品限时特惠，欢迎选购")
    assert not keep


# ---------- 规则 3：白名单模式，未命中即丢弃 ----------


@pytest.mark.parametrize(
    "title",
    ["春日的颐和园，海棠开了", "馆藏文物背后的故事", "一组照片带你看初雪"],
)
def test_unmatched_is_dropped(title):
    keep, reason = is_relevant(title)
    assert not keep
    assert reason == "未命中游客相关关键词"


# ---------- 摘要参与判定 ----------


def test_digest_participates():
    """标题无信号但摘要含保留词时应保留（列表接口的 digest 常带关键信息）。"""
    assert not is_relevant("温馨提醒")[0], "前置条件：标题本身不应命中任何词"
    keep, reason = is_relevant("温馨提醒", digest="因台风影响，景区今日暂停开放")
    assert keep
    assert "台风" in reason or "暂停" in reason


def test_empty_input_is_dropped():
    assert not is_relevant("")[0]
    assert not is_relevant("", "")[0]


# ---------- 自定义词表 ----------


def test_custom_include_replaces_default():
    """传入自定义 include 时完全替换默认词表（config.yaml 的语义）。"""
    keep, _ = is_relevant("临时闭馆公告", include=["演出"])
    assert not keep, "自定义词表应完全替换默认值，而非追加"

    keep, reason = is_relevant("今晚有演出", include=["演出"])
    assert keep
    assert "演出" in reason


def test_custom_exclude_replaces_default():
    keep, _ = is_relevant("招聘公告", exclude=["无关词"])
    assert keep, "自定义 exclude 后，默认的'招聘'不再生效，应命中'公告'被保留"


def test_empty_list_falls_back_to_default():
    """config.yaml 中留空（[]）表示使用内置词表。"""
    assert is_relevant("临时闭馆公告", include=[], exclude=[])[0]


# ---------- 词表自身的健康检查 ----------


def test_keyword_tables_have_no_overlap():
    """同一个词同时出现在保留与排除词表中会让规则含义不清。"""
    overlap = set(DEFAULT_INCLUDE) & set(DEFAULT_EXCLUDE)
    assert not overlap, f"词表冲突：{overlap}"


def test_keyword_tables_have_no_duplicates():
    for name, table in (("INCLUDE", DEFAULT_INCLUDE), ("EXCLUDE", DEFAULT_EXCLUDE)):
        dupes = {k for k in table if table.count(k) > 1}
        assert not dupes, f"DEFAULT_{name} 中有重复词：{dupes}"
