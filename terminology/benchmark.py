"""
术语正确率量化评测
==================

把「同一个术语库里的词，翻译后有没有正确出现」变成一个可计算的指标。

对每个句子：
  1. 找出句子里包含哪些术语（按术语表匹配）
  2. 两个服务各翻一遍
  3. 检查每个术语的俄语标准译法有没有出现在译文里
  4. 统计正确率

这样就能拿出一个数字：改造前 xx% → 改造后 xx%

跑法（5000 = 原版，5001 = 改造后，两个服务都要开）：
  .venv/Scripts/python.exe terminology/benchmark.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from libretranslate.terminology import Terminology  # noqa: E402

ORIGINAL_API = "http://127.0.0.1:5000/translate"
CAMPUS_API = "http://127.0.0.1:5001/translate"

SAMPLES = [
    "本学期《计算机组成原理》课程期末考试安排在第二教学楼302教室。",
    "请同学们在选课前完成俄语水平测试。",
    "根据《计算机组成原理》教学大纲，实验课占30%成绩。",
    "补考安排在第二教学楼302教室，请携带校园卡到教务处办理报到。",
    "《数据结构》期末考试的成绩计入绩点，重修需要重新选课。",
    "请到教务处领取成绩单，并在图书馆一楼的阶梯教室参加入学教育。",
]


def translate(api, text, source="zh-Hans", target="ru"):
    payload = json.dumps({
        "q": text, "source": source, "target": target, "format": "text",
    }).encode("utf-8")
    req = urllib.request.Request(
        api, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)["translatedText"]


def evaluate(terminology, api, sentences):
    """返回 (命中数, 总数, 明细)"""
    hit = 0
    total = 0
    detail = []

    for zh in sentences:
        # 找出这句话命中了哪些术语（长词优先，避免重复计数）
        found = []
        probe = zh
        for term in sorted(terminology.terms, key=lambda t: len(t.get("zh", "")), reverse=True):
            src = term.get("zh", "")
            if src and src in probe:
                found.append(term)
                probe = probe.replace(src, "\x00")  # 占位，防止短词重复匹配

        if not found:
            continue

        out = translate(api, zh)
        line = []
        for term in found:
            total += 1
            ru = term.get("ru", "")
            ok = bool(ru) and ru.lower() in out.lower()
            if ok:
                hit += 1
            line.append((term["zh"], ru, ok))
        detail.append((zh, out, line))

    return hit, total, detail


def main():
    terminology = Terminology()
    print(f"术语库: {terminology.csv_path}")
    print(f"词条数: {len(terminology.terms)}")
    print()

    results = {}
    for label, api in (("原版 LibreTranslate", ORIGINAL_API), ("校园术语库版", CAMPUS_API)):
        hit, total, detail = evaluate(terminology, api, SAMPLES)
        results[label] = (hit, total, detail)

    # 逐句明细
    for idx, zh in enumerate(SAMPLES):
        print("=" * 76)
        print(f"句子：{zh}")
        print()
        for label in results:
            hit, total, detail = results[label]
            if idx >= len(detail):
                continue
            _, out, line = detail[idx]
            print(f"  【{label}】{out}")
            for cn, ru, ok in line:
                print(f"      {'✅' if ok else '❌'} {cn} → {ru}")
            print()

    # 汇总
    print("=" * 76)
    print("汇总：术语俄语译法正确率")
    print()
    for label, (hit, total, _) in results.items():
        rate = hit / total * 100 if total else 0
        bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
        print(f"  {label:18} {bar} {hit}/{total} = {rate:.1f}%")
    print()


if __name__ == "__main__":
    main()
