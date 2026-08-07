#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
选股台账 + 胜率归因 — 配套 references/选股台账与胜率归因.md。

追加式台账(picks.jsonl，一行一 JSON)：每次推荐即 add 一行，事后 close 落结果，
report 按 模式/情绪阶段/形态/板块 维度算 胜率+期望+盈亏比，反哺选股。

用法：
  # 追加一条推荐（出票时）
  python3 picks-ledger.py add --json '{"code":"sh600584","name":"长电科技",
      "mode":"激进","emotion_phase":"主升期","emotion_temp":64,
      "setup":"首板龙头","sector":"半导体封测",
      "entry":38.5,"stop":36.2,"target":44.0,"bought":true,"note":""}'

  # 平仓/了结（跨天）——自动按阈值判 win/loss/flat，也可 --status 覆盖
  python3 picks-ledger.py close --id 20260806-1 --exit 42.3

  # 归因报告（默认按 setup；--by mode|emotion_phase|setup|sector；--days N 只看近N天）
  python3 picks-ledger.py report --by setup

  # 列出未平仓
  python3 picks-ledger.py open

文件默认 picks.jsonl（可用 --file 指定）。字段/枚举/胜负阈值见 references/选股台账与胜率归因.md。
"""

import sys, json, os
from datetime import date

WIN_TH, LOSS_TH = 1.0, -1.0        # 胜/负阈值(%)，见 reference §1
DEFAULT_FILE = "picks.jsonl"


# ---------- 小工具：参数解析 ----------
def flag(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def ledger_path():
    return flag("--file", DEFAULT_FILE)


def load_rows(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def append_row(path, row):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def rewrite(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def next_id(rows, d):
    seq = sum(1 for r in rows if r.get("date") == d) + 1
    return f"{d}-{seq}"


# ---------- 命令：add ----------
def cmd_add(path):
    rows = load_rows(path)
    payload = json.loads(flag("--json", "{}"))
    d = payload.get("date") or date.today().isoformat()
    row = {
        "id": payload.get("id") or next_id(rows, d),
        "date": d,
        "code": payload.get("code", ""),
        "name": payload.get("name", ""),
        "mode": payload.get("mode", ""),
        "emotion_phase": payload.get("emotion_phase", ""),
        "emotion_temp": payload.get("emotion_temp"),
        "setup": payload.get("setup", "其它"),
        "sector": payload.get("sector", ""),
        "entry": payload.get("entry"),
        "stop": payload.get("stop"),
        "target": payload.get("target"),
        "bought": bool(payload.get("bought", False)),
        "status": "open",
        "exit": None, "pnl_pct": None, "hold_days": None,
        "note": payload.get("note", ""),
    }
    append_row(path, row)
    print(f"✅ 追加 {row['id']}  {row['name']}({row['code']})  "
          f"{row['mode']}/{row['emotion_phase']}/{row['setup']}  "
          f"entry={row['entry']} bought={row['bought']}")


# ---------- 命令：close ----------
def _hold_days(d0):
    try:
        y, m, dd = (int(x) for x in d0.split("-"))
        return (date.today() - date(y, m, dd)).days
    except Exception:
        return None


def classify_status(pnl):
    if pnl >= WIN_TH:
        return "win"
    if pnl <= LOSS_TH:
        return "loss"
    return "flat"


def cmd_close(path):
    rows = load_rows(path)
    rid = flag("--id")
    ex = flag("--exit")
    if rid is None or ex is None:
        print("用法: close --id <ID> --exit <价格> [--status win|loss|flat]"); return
    ex = float(ex)
    hit = False
    for r in rows:
        if r.get("id") == rid:
            entry = r.get("entry")
            if not entry:
                print(f"⚠️ {rid} 无 entry 价，无法算盈亏"); return
            pnl = (ex - entry) / entry * 100.0
            r["exit"] = ex
            r["pnl_pct"] = round(pnl, 2)
            r["status"] = flag("--status") or classify_status(pnl)
            r["hold_days"] = _hold_days(r.get("date", ""))
            hit = True
            print(f"✅ 平仓 {rid}  {r['name']}  pnl={pnl:+.2f}%  "
                  f"→ {r['status']}  持有{r['hold_days']}天")
            break
    if not hit:
        print(f"未找到 id={rid}")
        return
    rewrite(path, rows)


# ---------- 命令：report ----------
def cmd_report(path):
    rows = load_rows(path)
    by = flag("--by", "setup")
    days = flag("--days")
    bought_only = "--all" not in sys.argv   # 默认只看真买的；--all 含没买的
    closed = [r for r in rows if r.get("status") in ("win", "loss", "flat")]
    if days:
        cutoff = (date.today().toordinal() - int(days))
        closed = [r for r in closed
                  if _ordinal(r.get("date")) and _ordinal(r["date"]) >= cutoff]
    if bought_only:
        closed = [r for r in closed if r.get("bought")]

    if not closed:
        print("（无已平仓样本。open 命令看未平仓，或先 close 几笔）"); return

    groups = {}
    for r in closed:
        key = r.get(by) or "(空)"
        groups.setdefault(key, []).append(r)

    scope = "真实买入" if bought_only else "全部(含没买)"
    print(f"胜率归因 · 按 {by} · {scope}" + (f" · 近{days}天" if days else ""))
    print(f"{'维度值':<14}{'N':>4}{'胜':>4}{'负':>4}{'平':>4}{'胜率':>7}{'期望%':>8}{'盈亏比':>7}")
    print("-" * 62)
    for key, rs in sorted(groups.items(), key=lambda kv: -_expectancy(kv[1])):
        n = len(rs)
        win = [r for r in rs if r["status"] == "win"]
        loss = [r for r in rs if r["status"] == "loss"]
        flat = [r for r in rs if r["status"] == "flat"]
        wr = len(win) / n * 100 if n else 0
        exp = _expectancy(rs)
        avg_w = sum(r["pnl_pct"] for r in win) / len(win) if win else 0
        avg_l = sum(r["pnl_pct"] for r in loss) / len(loss) if loss else 0
        pr = (avg_w / abs(avg_l)) if avg_l else float("inf")
        pr_s = f"{pr:.2f}" if pr != float("inf") else "∞"
        tag = "  ⚠样本少" if n < 10 else ""
        print(f"{str(key):<14}{n:>4}{len(win):>4}{len(loss):>4}{len(flat):>4}"
              f"{wr:>6.0f}%{exp:>+8.2f}{pr_s:>7}{tag}")
    print("-" * 62)
    print("读法：以「期望%」为主判据(低胜率高盈亏比可正EV)；N<10 只参考。反哺见 reference §4。")


def _ordinal(dstr):
    try:
        y, m, dd = (int(x) for x in dstr.split("-"))
        return date(y, m, dd).toordinal()
    except Exception:
        return None


def _expectancy(rs):
    vals = [r["pnl_pct"] for r in rs if r.get("pnl_pct") is not None]
    return sum(vals) / len(vals) if vals else 0.0


# ---------- 命令：open ----------
def cmd_open(path):
    rows = [r for r in load_rows(path) if r.get("status") == "open"]
    if not rows:
        print("（无未平仓台账）"); return
    print(f"{'id':<13}{'标的':<10}{'模式':<6}{'阶段':<6}{'setup':<10}{'entry':>7} bought")
    print("-" * 60)
    for r in rows:
        print(f"{r['id']:<13}{r.get('name',''):<10}{r.get('mode',''):<6}"
              f"{r.get('emotion_phase',''):<6}{r.get('setup',''):<10}"
              f"{str(r.get('entry','')):>7} {r.get('bought')}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    path = ledger_path()
    {"add": cmd_add, "close": cmd_close, "report": cmd_report,
     "open": cmd_open}.get(cmd, cmd_report)(path)


if __name__ == "__main__":
    main()
