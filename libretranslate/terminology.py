"""
校园术语库模块
==============

解决的问题
----------
LibreTranslate 没有中俄直连模型，中译俄必须绕道英语：

    中文 →[zh_en]→ 英文 →[en_ru]→ 俄语

两次翻译会让「计算机组成原理」这类专业术语彻底崩坏（实测变成了
"计算机参谋学院"这种不存在的机构名）。

本模块的思路
-----------
在**翻译之前**先把命中的术语换成一个占位符，让模型完全碰不到它：

    原文：请同学们在 选课 前完成俄语水平测试
      ↓ mask()   扫描术语表，把「选课」换成占位符 @1@
    送入：请同学们在 @1@ 前完成俄语水平测试
      ↓ 模型翻译（模型不认识 @1@，原样带过去）
    译出：Студентам ... перед @1@
      ↓ unmask()  把 @1@ 换成术语表里的俄语标准译法
    结果：Студентам ... перед выбор курса

占位符为什么用 @数字@
-------------------
这是**两轮压力测试**选出来的结果，不是拍脑袋定的。

第一轮（一句话只有 1 个占位符）—— 大部分格式都能活：
    [[7]]  → 被吃成 [7]              ❌
    ⟦7⟧    → 变成 "7-летием"（七周年）❌
    {7}    → 变成 77                  ❌
    #7#    → 变成 #7                  ❌
    §7§    → 变成 § 7                 ❌
    XQ7QX  → 存活，但把整句变成大写    ⚠️
    <7>    → 原样存活                  ✅

第二轮（一句话同时出现 5 个占位符，更接近真实情况）：
    @1@ @2@ @3@ @4@ @5@   → 存活 5/5   ✅  ← 采用
    <1> ... <5>           → 存活 3/5   ⚠️
    [[1]] ... [[5]]       → 存活 3/5   ⚠️
    {{1}} ... {{5}}       → 存活 0/5   ❌
    #T1# ... #T5#         → 存活 0/5   ❌（模型疯狂复读，输出一大串）
    ~1~ ... ~5~           → 存活 0/5   ❌
    ※1※ ... ※5※          → 存活 0/5   ❌
    __1__ ... __5__       → 存活 0/5   ❌
    <<1>> ... <<5>>       → 存活 0/5   ❌

结论：只有 @数字@ 在「多个占位符扎堆」时仍然稳定。
（第一轮看似能用的 <7>，在真实句子里会成片崩坏 —— 这就是为什么要压测。）

已知局限（要写进项目文档，别藏着）
--------------------------------
一、俄语名词有「格变化」，同一个词在主格/属格/宾格长得不同。
    本模块填回去的是术语的**基础形式**，如果上下文要求别的格，
    语法可能不完美。第一期只保证**术语词本身不会翻错**，
    格变化问题留待第二期（给术语维护词形表）。

二、术语被保护住了，但术语**周围的句子**仍然走「中→英→俄」两次翻译，
    语序和虚词仍可能不自然。本模块解决的是「术语翻错」，
    不是「整句语法完美」。

数据文件与代码分离
----------------
术语表是独立的 CSV 文件（terminology/campus_terms.csv），
教务老师或俄方教师可以直接用 Excel 编辑，**不需要碰代码**。
"""

import csv
import os
import re

# 占位符格式：@1@ @2@ @3@ ...
# 这个格式是压测出来的：一句话里出现 5 个占位符时，只有它 5 个全部存活。
#
# 实测补充（更真实的一轮）：
#   @1@         直接替换        存活 15/16 (94%)  ← 主方案
#   前后补空格    ␣@1@␣         存活  2/16 (12%)  ← 补空格会把中文切碎，反而更差
#   〖@1@〗      特殊符号包裹     存活  0/16 (0%)
#   @@1@@       双@包裹         存活  0/16 (0%)
#
# 两套备选编号方案，互为兜底：
#   方案 0：@1@ @2@  （数字）
#   方案 1：@a@ @b@  （字母，存活 14/16）
# 实测发现「丢词」是方案相关的 —— 数字方案弄丢的词，字母方案往往能保住。
# 所以翻译后如果发现术语没保住，会自动换另一套方案重试一次。
_PLACEHOLDER_TEMPLATE = "@{}@"
_PLACEHOLDER_RE = re.compile(r"@([0-9a-z]+)@")


def _placeholder(scheme, index):
    """生成第 index 个占位符（从 1 开始）。

    scheme=0 → @1@ @2@ @3@ ...
    scheme=1 → @a@ @b@ @c@ ...（超过 26 个退回数字）
    """
    if scheme == 0:
        return _PLACEHOLDER_TEMPLATE.format(index)
    if 1 <= index <= 26:
        return _PLACEHOLDER_TEMPLATE.format(chr(96 + index))
    return _PLACEHOLDER_TEMPLATE.format(index)

# 术语表默认位置：仓库根目录下的 terminology/campus_terms.csv
_DEFAULT_CSV_RELPATH = os.path.join("terminology", "campus_terms.csv")


def normalize_code(code):
    """把各种语种写法归一化。

    翻译 API 里中文的代码是 zh-Hans，而术语表里写的是 zh，
    这里统一一下，避免因为写法不同而匹配不上。
    """
    if not code:
        return None
    c = str(code).lower()
    if c in ("zh", "zh-hans", "zh-cn", "zh-sg", "zh-hant", "zh-tw"):
        return "zh"
    return c.split("-")[0]


def default_csv_path():
    """定位术语表文件。

    优先读环境变量 LIBRETRANSLATE_TERMINOLOGY，方便部署时指向别处。
    否则从当前工作目录往上找到仓库根目录。
    """
    env_path = os.environ.get("LIBRETRANSLATE_TERMINOLOGY")
    if env_path:
        return env_path

    # 从本文件位置往上两级：libretranslate/terminology.py -> 仓库根
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, _DEFAULT_CSV_RELPATH)


class Terminology:
    """校园术语库。

    用法：
        term = Terminology()
        masked, mapping = term.mask("请在选课前完成测试", "zh")
        # masked  = "请在@1@前完成测试"
        # mapping = {"@1@": {...术语行...}}
        ...
        result = term.unmask(translated_text, mapping, "ru")
    """

    def __init__(self, csv_path=None, enabled=True):
        self.enabled = enabled
        self.csv_path = csv_path or default_csv_path()
        self.terms = []
        self.load_error = None
        self.load()

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load(self):
        """从 CSV 读入术语表。文件不存在也不报错，只是术语库为空。"""
        self.terms = []
        self.load_error = None
        if not os.path.isfile(self.csv_path):
            self.load_error = f"术语表不存在: {self.csv_path}"
            return
        try:
            # utf-8-sig 是为了兼容 Excel 存出来的带 BOM 的文件
            with open(self.csv_path, "r", encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    cleaned = {
                        (k or "").strip(): (v or "").strip()
                        for k, v in row.items()
                    }
                    # 至少要有一个中文词
                    if cleaned.get("zh"):
                        self.terms.append(cleaned)
        except Exception as e:  # 术语表坏了不能让整个翻译服务挂掉
            self.load_error = f"读取术语表失败: {e}"

    # ------------------------------------------------------------------
    # 翻译前：把术语换成占位符
    # ------------------------------------------------------------------
    def mask(self, text, src_lang, scheme=0):
        """扫描 text，把命中的术语替换成占位符。

        scheme: 0 = 用数字占位符（@1@），1 = 用字母占位符（@a@）。
                两套方案互为兜底，见文件顶部说明。

        返回 (处理后的文本, 占位符映射表)
        """
        mapping = {}
        if not self.enabled or not text or not self.terms:
            return text, mapping

        src = normalize_code(src_lang)
        if src is None:
            return text, mapping

        # 只挑「源语言有词」的术语。
        # 按源词长度从长到短排序，保证长词优先匹配：
        # 否则「计算机」会先把「计算机组成原理」切碎。
        pairs = [
            (t.get(src, ""), t)
            for t in self.terms
            if t.get(src)
        ]
        pairs.sort(key=lambda p: len(p[0]), reverse=True)

        counter = 0
        for source_term, term_row in pairs:
            if source_term not in text:
                continue
            counter += 1
            placeholder = _placeholder(scheme, counter)
            text = text.replace(source_term, placeholder)
            mapping[placeholder] = term_row

        return text, mapping

    # ------------------------------------------------------------------
    # 翻译后：把占位符换回目标语言的术语
    # ------------------------------------------------------------------
    def unmask(self, text, mapping, tgt_lang):
        """把译文里的占位符还原成目标语言的术语。

        如果模型把某个占位符弄丢了或改坏了，还原不了就跳过，
        并在返回值里报告，方便排查。
        """
        stats = {"restored": 0, "missing": []}
        if not text or not mapping:
            return text, stats

        tgt = normalize_code(tgt_lang)

        for placeholder, term_row in mapping.items():
            if placeholder not in text:
                stats["missing"].append(placeholder)
                continue
            replacement = term_row.get(tgt) or term_row.get("en") or ""
            if not replacement:
                stats["missing"].append(placeholder)
                continue
            text = text.replace(placeholder, replacement)
            stats["restored"] += 1

        # 兜底：万一译文里还残留着没配对的占位符，清掉，
        # 不然用户会看到 <1> 这种东西。
        text = _PLACEHOLDER_RE.sub("", text)

        return text, stats

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def stats(self):
        """术语库概况，用于 /terminology 接口展示。"""
        by_category = {}
        for t in self.terms:
            cat = t.get("category") or "未分类"
            by_category[cat] = by_category.get(cat, 0) + 1
        return {
            "file": self.csv_path,
            "enabled": self.enabled,
            "total": len(self.terms),
            "by_category": by_category,
            "error": self.load_error,
        }
