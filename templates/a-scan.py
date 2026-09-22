# -*- coding: utf-8 -*-
"""
A股全局选股 一次性扫描器（单文件，仅标准库）

用法：
    PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/a-scan.py
    PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/a-scan.py --date 20260901

一次调用出完整六步法数据，避免多轮工具往返（配套 templates/hk-scan.py 的港股版）。
    阶段1 并发：指数 / 行业+概念板块排行 / 涨停池+炸板池+跌停池 / 昨日涨停今日表现
                / 全A涨跌家数 / 30行业铺面universe
    阶段2 并发：入围候选 60 日 K 线 → 分位 / 均线 / ATR / 量能
    阶段3     ：自动合成情绪温度（复用 emotion-temp.py），输出阶段+模式+仓位水位

═══ 本机数据源实测（2026-09-01）═══
  ✅ qt.gtimg.cn                批量 250 只 / 0.22s
  ✅ web.ifzq.gtimg.cn          日K线，并发
  ✅ push2delay.eastmoney.com   行业/概念板块排行、资金流、全A榜  0.11~0.14s
  ✅ push2ex.eastmoney.com      涨停池/炸板池/跌停池（自带 hybk 行业 + lbc 连板）
  ❌ push2.eastmoney.com        clist 被本机 IP 封（stock/get 时通时断）—— 不依赖它
  ❌ hq.sinajs.cn               403（需 Referer）

⚠️ 更正 CLAUDE.md 的旧结论：被封的只是 push2 主域，push2delay / push2ex 完全可用，
   因此「板块排行必须走 CLS 浏览器」这条降级链在本机并不需要。
"""
import urllib.request
import json
import time
import os
import sys
import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
      'Referer': 'https://quote.eastmoney.com/'}
TIMEOUT = 10
RETRY = 2
BACKOFF = 0.4

UT = "bd1d9ddb04089700cf9c27f6f7426281"
UT_EX = "7eea3edcaed734bea9cbfc24409ed989"
DELAY = "https://push2delay.eastmoney.com/api/qt/clist/get"
EX = "https://push2ex.eastmoney.com/getTopic%sPool"
FS_ALL_A = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"      # 深主板+创业板+沪主板+科创板

# 铺面 universe —— 唯一事实源：references/扫描全覆盖.md 的 all_scan（30行业）
ALL_SCAN = {
    "游戏":      "sz002555,sh603444,sz002602,sz002624",
    "半导体":    "sz002371,sh600584,sh603986,sz002049",
    "通信":      "sz300308,sz000063,sh600487,sz300502",
    "电子":      "sz002475,sz300433,sz002241,sz002384",
    "AI":       "sz300624,sz300229,sz000977,sh603019",
    "机器人":    "sz300124,sz002472,sz002050,sz300607",
    "军工":      "sh600893,sh600760,sh600150,sz000768",
    "有色":      "sh601899,sh603993,sh600362,sh601168,sz000630",
    "化工":      "sh600309,sh600346,sz002648,sh600426",
    "煤炭":      "sh601088,sh601225,sh601898,sh601001",
    "电力":      "sh600900,sh600021,sh600025,sh600886",
    "中药":      "sz000538,sh600085,sh600436,sz002424",
    "创新药":    "sh603259,sz300347,sh600276,sz300759",
    "白酒":      "sh600519,sz000858,sh600809,sz000568",
    "食品饮料":  "sh600887,sz002557,sh600298,sz002311",
    "家电":      "sz000333,sh600690,sz000651,sz002032",
    "汽车":      "sh600660,sh601689,sz002594,sz000625",
    "机械":      "sh600031,sz000338,sh601100,sz002008",
    "养殖":      "sz002714,sz002311,sz300498,sz002299",
    "新能源":    "sz300750,sz300274,sz300014,sz002074",
    "建材":      "sh600585,sz002271,sh600176,sz000786",
    "物流":      "sz002352,sh601919,sh600233,sz603056",
    "旅游/社服": "sh601888,sh600258,sh600754,sz000796,sh600138,sz002707",
    "证券":      "sh600030,sz300059,sh601066,sh600999",
    "商贸零售":  "sh600859,sz002419,sz002251",
    "农林牧渔":  "sz002041,sh600598,sz000998,sh601952",
    "传媒影视":  "sz300251,sh601595,sh600037",
    "建筑装饰":  "sh601668,sz002081,sh600170",
    # ↓ 2026-09-02 补入：原28行业无能源/航运，当日主线（美伊冲突→原油）整个落在盲区
    "石油石化":  "sh601857,sh600938,sh601808,sh603619,sz000852,sz002278",
    "航运":      "sh601872,sh600026,sh601975,sh600798",
}

INDEX = [("s_sh000001", "上证"), ("s_sz399001", "深成"), ("s_sz399006", "创业板"),
         ("s_sh000688", "科创50"), ("s_sz399303", "国证2000"), ("s_bj899050", "北证50")]


def _get(url, enc='utf-8'):
    last = None
    for _ in range(RETRY):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=TIMEOUT).read().decode(enc, 'ignore')
        except Exception as e:
            last = e
            time.sleep(BACKOFF)
    raise last


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def jsonp(txt):
    return json.loads(txt[txt.index('(') + 1:txt.rindex(')')])


def em_list(fs, fid="f3", fields="f2,f3,f12,f14", pz=50, pn=1, po=1):
    """push2delay clist —— 本机可用。失败返回 []，绝不阻塞。"""
    try:
        u = ("%s?cb=j&pn=%d&pz=%d&po=%d&np=1&fltt=2&invt=2&fid=%s&fs=%s&fields=%s&ut=%s"
             % (DELAY, pn, pz, po, fid, fs, fields, UT))
        d = jsonp(_get(u)).get('data')
        return (d or {}).get('diff') or []
    except Exception:
        return []


def ex_pool(kind, date):
    """push2ex 涨停/炸板/跌停池。涨停池自带 hybk(行业) + lbc(连板) + ltsz(流通市值)。"""
    srt = "fund%3Aasc" if kind == "DT" else "fbt%3Aasc"
    try:
        u = ("%s?cb=j&ut=%s&dpt=wz.ztzt&Pageindex=0&pagesize=400&sort=%s&date=%s"
             % (EX % kind, UT_EX, srt, date))
        d = jsonp(_get(u)).get('data') or {}
        return d.get('pool') or []
    except Exception:
        return []


def parse_q(line):
    if '="' not in line:
        return None
    f = line.split('="', 1)[1].rstrip('";\n').split('~')
    if len(f) < 47:
        return None

    def F(i):
        return num(f[i]) if i < len(f) else 0.0

    rng = F(33) - F(34)
    return dict(code=f[2], name=f[1].strip(), price=F(3), prev=F(4), open=F(5),
                ts=f[30], pct=F(32), high=F(33), low=F(34), amt=F(37) * 1e4,
                turn=F(38), pe=F(39), amp=F(43), cap=F(44), fcap=F(45),
                us=0.0 if rng <= 0 else (F(33) - max(F(5), F(3))) / rng * 100,
                ls=0.0 if rng <= 0 else (min(F(5), F(3)) - F(34)) / rng * 100)


def quotes(prefixed):
    """腾讯批量，实测 250 只 0.22s。prefixed 形如 sh600519 / sz000858。"""
    chunks = [prefixed[i:i + 150] for i in range(0, len(prefixed), 150)]

    def one(ch):
        try:
            return _get("https://qt.gtimg.cn/q=" + ",".join(ch), 'gbk')
        except Exception:
            return ""

    out = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for txt in ex.map(one, chunks):
            for line in txt.split(';'):
                d = parse_q(line.strip())
                if d:
                    out[d['code']] = d
    return out


def pfx(code):
    """6位代码 → 腾讯前缀。"""
    if code.startswith(('60', '68', '90', '11', '51', '58')):
        return 'sh' + code
    if code.startswith(('4', '8', '92')):
        return 'bj' + code
    return 'sz' + code


def ma(a, n):
    return sum(a[-n:]) / max(1, min(n, len(a)))


def klines(prefixed):
    def one(p):
        try:
            u = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=%s,day,,,60,qfq" % p)
            d = json.loads(_get(u))['data'][p]
            k = d.get('qfqday') or d.get('day') or []
            if len(k) < 6:
                return p, None
            cl = [float(r[2]) for r in k]
            hi = [float(r[3]) for r in k]
            lo = [float(r[4]) for r in k]
            vo = [float(r[5]) for r in k]
            cur, rng = cl[-1], max(hi) - min(lo)
            m5, m10, m20 = ma(cl, 5), ma(cl, 10), ma(cl, 20)
            trs = [max(hi[i] - lo[i], abs(hi[i] - cl[i - 1]), abs(lo[i] - cl[i - 1]))
                   for i in range(1, len(cl))]
            atr = sum(trs[-14:]) / min(14, len(trs))
            # ⚠ 2026-09-03 修正：先判均线结构，再判价格相对 MA5 的位置。
            # 旧逻辑 `cur > m5` 短路在 `m5 < m10 < m20` 之前 → 空头排列中反弹
            # 站上 MA5 的票被标成「刚站上MA5」并通过闸门（接刀陷阱）。
            # 实例见 hk-scan.py 同处注释（华润置地 01109，2026-09-03）。
            bull = m5 > m10 > m20
            bear = m5 < m10 < m20
            if bear:
                tr = "空头反弹" if cur > m5 else "空头排列"
            elif bull and cur > m5:
                tr = "多头排列"
            elif cur > m5 and m5 > m10:
                tr = "短期多头"
            elif cur > m5:
                tr = "刚站上MA5"
            else:
                tr = "破MA5"
            # ⚠ 2026-09-04 新增 q20 / ovh，说明见 hk-scan.py 同处注释。
            #   q20 = 20日区间分位（只看 q60 会把箱体中部当低位）
            #   ovh = 上方套牢率（60日内均价高于现价的交易日成交量占比）
            q20 = ((cur - min(lo[-20:])) / (max(hi[-20:]) - min(lo[-20:])) * 100
                   if len(cl) >= 20 and max(hi[-20:]) > min(lo[-20:]) else 0.0)
            tv = sum(vo) or 1.0
            ovh = sum(vo[i] for i in range(len(cl)) if (hi[i] + lo[i]) / 2 > cur) / tv * 100
            return p, dict(q60=(cur - min(lo)) / rng * 100 if rng > 0 else 0.0,
                           q20=q20, ovh=ovh,
                           dd=(max(hi) - cur) / max(hi) * 100, trend=tr,
                           ma5=m5, ma20=m20, atr=atr, atrp=atr / cur * 100,
                           stop2=cur - 2 * atr,
                           vr=vo[-1] / (sum(vo[-21:-1]) / 20) if len(vo) > 21 else 0.0)
        except Exception:
            return p, None

    out = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for p, v in ex.map(one, prefixed):
            if v:
                out[p] = v
    return out


def adv_dec():
    """全A涨跌家数：对按涨幅降序的榜单二分找 0 轴所在页（~6 次请求，比翻 56 页便宜）。"""
    total = 0
    try:
        u = ("%s?cb=j&pn=1&pz=1&po=1&np=1&fltt=2&invt=2&fid=f3&fs=%s&fields=f3&ut=%s"
             % (DELAY, FS_ALL_A, UT))
        total = (jsonp(_get(u)).get('data') or {}).get('total') or 0
    except Exception:
        return 0, 0, 0
    if not total:
        return 0, 0, 0
    pages = (total + 99) // 100
    lo, hi = 1, pages

    def last_pct(pn):
        r = em_list(FS_ALL_A, "f3", "f3", pz=100, pn=pn)
        return num(r[-1].get('f3')) if r else -99.0

    while lo < hi:
        mid = (lo + hi) // 2
        if last_pct(mid) > 0:
            lo = mid + 1
        else:
            hi = mid
    page = em_list(FS_ALL_A, "f3", "f3", pz=100, pn=lo)
    up = (lo - 1) * 100 + sum(1 for x in page if num(x.get('f3')) > 0)
    flat = sum(1 for x in page if num(x.get('f3')) == 0)
    return up, total - up - flat, total


def prev_trade_date(d):
    for back in range(1, 12):
        cand = (d - datetime.timedelta(days=back)).strftime("%Y%m%d")
        if ex_pool("ZT", cand):
            return cand
    return None


def gate(d, k):
    bad, warn = [], []
    if k['q60'] > 85:
        bad.append("分位>85")
    elif k['q60'] > 70:
        warn.append("分位>70")
    if d['us'] > 40:
        bad.append("上影>40")
    elif d['us'] > 25:
        warn.append("上影偏长")
    if d['pct'] > 7:
        bad.append("追高>7")
    elif d['pct'] > 5:
        warn.append("5-7高危区")
    if k.get('q20', 0) > 85:
        warn.append("20日极高位")
    elif k.get('q20', 0) > 70:
        warn.append("20日高位")
    if k.get('ovh', 0) > 60:
        warn.append("上方套牢%.0f%%" % k['ovh'])
    if k['trend'] == "空头排列":
        bad.append("空头排列")
    elif k['trend'] == "空头反弹":
        # 空头排列中反弹站上 MA5 —— 下跌中继的接刀区，非趋势转好。强制人工复核。
        warn.append("空头反弹·非趋势转好")
    if 0 <= d['pe'] < 0.01 or d['pe'] > 200 or d['pe'] < -100:
        warn.append("PE异常")
    if bad:
        return 2, "❌ " + "/".join(bad)
    if warn:
        return 1, "⚠ " + "/".join(warn)
    return 0, "✅ 通过"


def emotion(payload):
    """复用 templates/emotion-temp.py，避免两套打分逻辑漂移。
    注意 temperature() 返回 (score, sub_scores)，classify() 返回 5 元组。"""
    try:
        import importlib.util
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emotion-temp.py")
        spec = importlib.util.spec_from_file_location("emotemp", p)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        score, subs = m.temperature(payload)
        name, mode, level, chase, allow = m.classify(score, payload)
        hard, notes = m.guardrails(payload, name, allow)
        return dict(score=score, subs=subs, phase=name, mode=mode, level=level,
                    chase=chase, allow=allow and not hard, hard=hard, notes=notes), None
    except Exception as e:
        return None, e


def main():
    t0 = time.time()
    today = datetime.date.today()
    if "--date" in sys.argv:
        ds = sys.argv[sys.argv.index("--date") + 1]
        today = datetime.datetime.strptime(ds, "%Y%m%d").date()
    date = today.strftime("%Y%m%d")

    # ALL_SCAN 用带前缀代码(sh/sz)，但腾讯行情返回的是裸6位码 —— sec_of 按裸码建索引
    uni_codes = []
    sec_of = {}
    for s, cs in ALL_SCAN.items():
        for c in cs.split(','):
            bare = c[2:]
            if bare not in sec_of:
                sec_of[bare] = s
                uni_codes.append(c)

    # ── 阶段1：全部实时并发 ────────────────────────────────
    IND_F = "f2,f3,f8,f12,f14,f62,f104,f105"
    with ThreadPoolExecutor(max_workers=10) as ex:
        f_idx = ex.submit(_get, "https://qt.gtimg.cn/q=" + ",".join(c for c, _ in INDEX), 'gbk')
        f_uni = ex.submit(quotes, uni_codes)
        f_ind = ex.submit(em_list, "m:90+t:2", "f3", IND_F, 40)
        f_con = ex.submit(em_list, "m:90+t:3", "f3", IND_F, 40)
        f_mny = ex.submit(em_list, "m:90+t:2", "f62", "f12,f14,f3,f62", 20)
        f_zt = ex.submit(ex_pool, "ZT", date)
        f_zb = ex.submit(ex_pool, "ZB", date)
        f_dt = ex.submit(ex_pool, "DT", date)
        f_ad = ex.submit(adv_dec)
        f_pd = ex.submit(prev_trade_date, today)
        idx_raw = f_idx.result()
        uni = f_uni.result()
        ind, con, mny = f_ind.result(), f_con.result(), f_mny.result()
        zt, zb, dt = f_zt.result(), f_zb.result(), f_dt.result()
        up, dn, tot = f_ad.result()
        pdate = f_pd.result()

    # 昨日涨停股今日表现（情绪温度权重最高的一项，0.25）
    yst_perf, yst_n = None, 0
    if pdate:
        ypool = ex_pool("ZT", pdate)
        ycodes = [pfx(x['c']) for x in ypool]
        if ycodes:
            yq = quotes(ycodes)
            vals = [d['pct'] for d in yq.values() if d['price'] > 0]
            if vals:
                yst_perf = sum(vals) / len(vals)
                yst_n = len(vals)
    t1 = time.time() - t0

    print("=" * 112)
    print("A股全局扫描    本机时间 %s    交易日 %s"
          % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), date))
    print("=" * 112)

    print("\n【STEP1 大盘】")
    for line in idx_raw.split(';'):
        if '="' not in line:
            continue
        f = line.split('="', 1)[1].rstrip('";\n').split('~')
        if len(f) > 5:
            print("  %-10s %12s  %+7s%%   成交 %s亿" % (f[1], f[3], f[5], f[9] if len(f) > 9 else '-'))
    if tot:
        print("  涨跌家数：涨 %d / 跌 %d / 共 %d → 上涨占比 %.0f%%  涨跌比 %.2f:1"
              % (up, dn, tot, 100.0 * up / tot, up / max(1, dn)))

    # ── 情绪温度（自动合成，不再手填）─────────────────────
    nzt, nzb, ndt = len(zt), len(zb), len(dt)
    seal = 100.0 * nzt / max(1, nzt + nzb)
    broken = 100.0 * nzb / max(1, nzt + nzb)
    streak = max([x.get('lbc') or 1 for x in zt], default=0)
    payload = dict(limit_up=nzt, limit_down=ndt, max_streak=streak,
                   seal_rate=seal, broken_rate=broken,
                   yst_limit_perf=yst_perf if yst_perf is not None else 0.0,
                   adv_dec_ratio=(up / max(1, dn)) if tot else 1.0,
                   index_2day_crash=False, account_drawdown=0.0)
    print("\n【情绪温度 · 自动合成】涨停%d 炸板%d 跌停%d | 封板率%.0f%% 炸板率%.0f%% | 最高%d板 | 昨涨停今表现%s(%d只)"
          % (nzt, nzb, ndt, seal, broken, streak,
             ("%+.2f%%" % yst_perf) if yst_perf is not None else "N/A", yst_n))
    emo, err = emotion(payload)
    if emo:
        print("  温度分 %.1f  →  【%s】  默认模式=%s  仓位水位=%s  追热门=%s  自动激进=%s"
              % (emo['score'], emo['phase'], emo['mode'], emo['level'],
                 emo['chase'], "允许" if emo['allow'] else "禁止"))
        print("  分项：" + "  ".join("%s%.0f" % (k, v) for k, v in emo['subs'].items()))
        for n in emo['notes']:
            print("  护栏 " + n)
        print("  注：index_2day_crash / account_drawdown 需人工确认，本脚本按 False/0 兜底")
    else:
        print("  （emotion-temp.py 调用失败：%s）payload=%s"
              % (err, json.dumps(payload, ensure_ascii=False)))

    # ── STEP 2a 连板梯队 ────────────────────────────────
    if zt:
        lad = sorted(zt, key=lambda x: -(x.get('lbc') or 1))
        print("\n【STEP2a 连板梯队】连板(>=2板) %d 只 / 涨停 %d 只 = %.0f%%"
              % (sum(1 for x in zt if (x.get('lbc') or 1) >= 2), nzt,
                 100.0 * sum(1 for x in zt if (x.get('lbc') or 1) >= 2) / max(1, nzt)))
        print("  " + "  ".join("%s%d板(%s)" % (x['n'].replace(' ', ''), x.get('lbc') or 1, x.get('hybk', ''))
                               for x in lad[:10]))

    # ── STEP 2b 涨停归类反推 ─────────────────────────────
    if zt:
        by = defaultdict(list)
        for x in zt:
            by[x.get('hybk') or '未知'].append(x)
        print("\n【STEP2b 涨停归类反推】≥2只涨停的方向一律强制评估（无论资金流入多少、在不在排名前六）")
        strong = sorted([kv for kv in by.items() if len(kv[1]) >= 2],
                        key=lambda kv: -len(kv[1]))
        for k, v in strong:
            ms = sorted(x.get('ltsz', 0) for x in v)
            med = ms[len(ms) // 2] / 1e8
            print("  %-12s %2d只  中位流通市值%6.0f亿  %s"
                  % (k, len(v), med, "/".join(x['n'].replace(' ', '') for x in v[:6])))
        print("  单只涨停方向 %d 个（可不深挖）" % sum(1 for kv in by.items() if len(kv[1]) == 1))

    # ── STEP 2 板块排行 ─────────────────────────────────
    if ind:
        print("\n【STEP2 行业板块 TOP12】(push2delay)")
        print("  %-8s %-12s %8s %7s %9s %12s" % ("BK", "板块", "涨幅%", "量比", "涨停/家数", "主力净额亿"))
        for x in ind[:12]:
            print("  %-8s %-12s %+8.2f %7.2f %6s/%-4s %12.2f"
                  % (x['f12'], str(x['f14'])[:10], num(x['f3']), num(x.get('f8')),
                     x.get('f105'), x.get('f104'), num(x.get('f62')) / 1e8))
    if con:
        print("\n【STEP2 概念板块 TOP10】")
        for x in con[:10]:
            print("  %-8s %-14s %+8.2f%%  涨停%3s/%-4s" %
                  (x['f12'], str(x['f14'])[:12], num(x['f3']), x.get('f105'), x.get('f104')))
    if mny:
        print("\n【主力净流入 TOP8（绝对额，注意会歧视小市值板块 → 交叉看 Step2b）】")
        for x in mny[:8]:
            print("  %-8s %-12s %+7.2f%%  净额%9.2f亿" %
                  (x['f12'], str(x['f14'])[:10], num(x.get('f3')), num(x.get('f62')) / 1e8))

    # ── STEP 3 铺面 30 行业聚合 ──────────────────────────
    print("\n【STEP3 铺面30行业】锚定位=市值最大  弹性位=市值最小（扫描全覆盖.md 铁律二）")
    print("  %-12s %8s %8s %14s %14s %10s %9s" %
          ("行业", "涨/总", "均涨%", "锚定位", "弹性位", "弹性-锚定", "上影>40%"))
    aggs = []
    for s, cs in ALL_SCAN.items():
        ds = [uni[c[2:]] for c in cs.split(',') if c[2:] in uni and uni[c[2:]]['price'] > 0]
        if not ds:
            continue
        big = max(ds, key=lambda d: d['cap'])
        small = min(ds, key=lambda d: d['cap'])
        aggs.append((sum(d['pct'] for d in ds) / len(ds), s,
                     sum(1 for d in ds if d['pct'] > 0), len(ds), big, small,
                     sum(1 for d in ds if d['us'] > 40)))
    for avg, s, u, n, big, small, lus in sorted(aggs, reverse=True):
        flag = "  ⚠资金在做小票→强制深扫" if (small['pct'] - big['pct']) > 3 else ""
        print("  %-12s %4d/%-3d %+8.2f %7s%+6.2f%% %7s%+6.2f%% %+10.2f %6d/%-3d%s"
              % (s, u, n, avg, big['name'][:5], big['pct'], small['name'][:5],
                 small['pct'], small['pct'] - big['pct'], lus, n, flag))

    # ── 阶段2：入围候选 K线 ─────────────────────────────
    pool = [d for d in uni.values()
            if d['pct'] > 0.5 and d['amt'] > 5e7
            and 'ST' not in d['name'].upper() and not d['code'].startswith('688')]
    pool.sort(key=lambda d: -d['amt'])
    kl = klines([pfx(d['code']) for d in pool[:40]])

    print("\n【STEP3 候选过闸】涨幅>0.5%% 成交>0.5亿，排除 ST / 688，按成交额取前40")
    print("  闸门：60日&20日分位  上方套牢  上影  涨幅区间  均线结构  PE")
    print("  %-7s %-8s %-10s %6s %6s %6s %6s %6s %6s %6s %6s %9s %8s  %s"
          % ("代码", "名称", "行业", "涨幅%", "60分%", "20分%", "套牢%", "上影%",
             "下影%", "量比", "ATR%", "2ATR止损", "成交亿", "判定"))
    rank = []
    for d in pool:
        k = kl.get(pfx(d['code']))
        if not k:
            continue
        sev, v = gate(d, k)
        rank.append((sev, -d['amt'], d, k, v))
    for _, _, d, k, v in sorted(rank, key=lambda r: (r[0], r[1]))[:30]:
        print("  %-7s %-8s %-10s %6.2f %6.0f %6.0f %6.0f %6.1f %6.1f %6.2f %6.1f %9.2f %8.2f  %s"
              % (d['code'], d['name'][:6], sec_of.get(d['code'], '-')[:8], d['pct'],
                 k['q60'], k.get('q20', 0), k.get('ovh', 0), d['us'], d['ls'],
                 k['vr'], k['atrp'], k['stop2'], d['amt'] / 1e8, v))

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    sdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scans")
    out = os.path.join(sdir, "scan-a-%s.json" % stamp)
    try:
        os.makedirs(sdir, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fp:
            json.dump({"stamp": stamp, "date": date, "universe": uni, "kline": kl,
                       "industry": ind, "concept": con, "moneyflow": mny,
                       "zt": zt, "zb": zb, "dt": dt, "emotion": payload,
                       "adv": up, "dec": dn, "total": tot}, fp, ensure_ascii=False)
        saved = os.path.normpath(out)
    except Exception as e:
        saved = "落盘失败 %s" % e

    print("\n" + "-" * 112)
    print("阶段1 全部实时 %.2fs  |  阶段2 %d只K线 %.2fs  |  合计 %.2fs"
          % (t1, len(kl), time.time() - t0 - t1, time.time() - t0))
    print("快照 %s" % saved)


if __name__ == "__main__":
    main()
