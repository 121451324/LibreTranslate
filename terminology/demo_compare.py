"""
术语库效果对照脚本（A/B 测试）
==============================

同时请求两个服务，把同一句话翻译两遍：

  5000 端口 —— 原版 LibreTranslate（未做任何改动）
  5001 端口 —— 加入校园术语库后的版本

对比结果，直观展示术语库到底修好了什么。

跑法（两个服务都要先启动）：
  .venv/Scripts/python.exe terminology/demo_compare.py
"""

import json
import urllib.request

ORIGINAL_API = "http://127.0.0.1:5000/translate"   # 原版
CAMPUS_API = "http://127.0.0.1:5001/translate"     # 改造后

SAMPLES = [
    "本学期《计算机组成原理》课程期末考试安排在第二教学楼302教室。",
    "请同学们在选课前完成俄语水平测试。",
    "根据《计算机组成原理》教学大纲，实验课占30%成绩。",
]

WIDTH = 74


def translate(api, text, source="zh-Hans", target="ru"):
    payload = json.dumps({
        "q": text, "source": source, "target": target, "format": "text",
    }).encode("utf-8")
    req = urllib.request.Request(
        api, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.load(resp)["translatedText"]
    except Exception as e:
        return f"<请求失败: {e}>"


def main():
    for i, zh in enumerate(SAMPLES, 1):
        print("=" * WIDTH)
        print(f"样本 {i}")
        print("=" * WIDTH)
        print(f"【原文】{zh}")
        print()
        print(f"【原版｜中→俄】")
        print(f"  {translate(ORIGINAL_API, zh)}")
        print()
        print(f"【改造后｜中→俄】")
        print(f"  {translate(CAMPUS_API, zh)}")
        print()


if __name__ == "__main__":
    main()
