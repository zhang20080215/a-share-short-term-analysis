#!/usr/bin/env python3
"""
收盘前批量检查模板 — 复制此文件并修改股票代码后使用。
与 cronjob 搭配，在指定时间自动拉取数据并推送分析报告给用户。

使用方法：
1. 复制此文件到 ~/.hermes/scripts/check_{date}.py
2. 修改 STOCK_CODES 列表为要检查的股票
3. 创建 cronjob:
   cronjob action=create name="收盘检查" schedule="2026-05-25 14:30:00" \
     script="check_XXX.py" prompt="看输出，分析各标的收盘前走势并给出操作建议" \
     skills="[\"a-share-short-term-analysis\"]" deliver="origin"
"""

import subprocess, json, sys

# ====== 修改以下配置 ======
STOCK_CODES = [
    ("sh600089", "特变电工"),
    ("sh603799", "华友钴业"),
    ("sz159636", "159636 ETF"),
    ("sz300274", "阳光电源"),
    ("sh600584", "长电科技"),
    ("sh688981", "中芯国际"),
    ("sz002371", "北方华创"),
]
# ==========================

codes_param = ",".join(code for code, _ in STOCK_CODES)
url = f"https://qt.gtimg.cn/q={codes_param}"

try:
    result = subprocess.run(
        ["curl", "-sL", "--max-time", "10", url],
        capture_output=True, timeout=12
    )
    raw = result.stdout.decode('gbk', errors='replace')
except Exception as e:
    print(f"FETCH_ERROR: {e}")
    sys.exit(0)

for line in raw.strip().split("\n"):
    if not line or "=" not in line:
        continue
    data = line.split("=", 1)[1].strip('"')
    fields = data.split("~")

    name = fields[1] if len(fields) > 1 else "?"
    code = fields[2] if len(fields) > 2 else "?"
    price = fields[3] if len(fields) > 3 else "?"
    prev_close = fields[4] if len(fields) > 4 else "?"
    open_p = fields[5] if len(fields) > 5 else "?"
    volume = fields[6] if len(fields) > 6 else "?"
    high = fields[33] if len(fields) > 33 else "?"
    low = fields[34] if len(fields) > 34 else "?"
    change_pct = fields[32] if len(fields) > 32 else "?"
    change_amt = fields[31] if len(fields) > 31 else "?"
    turnover = fields[38] if len(fields) > 38 else "?"
    ts = fields[30] if len(fields) > 30 else "?"

    # 量比不在标准Tencent返回中（从额外参数获取）
    # 估算量比：成交量/均量需额外计算

    arrow = "📈" if float(change_pct or 0) >= 0 else "📉"
    print(f"{arrow} {name}({code}) 现价{price} 涨跌{change_amt}({change_pct}%) 量{volume}手")
