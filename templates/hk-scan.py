# -*- coding: utf-8 -*-
"""
港股全局选股 一次性扫描器（单文件，仅标准库）

用法：
    PYTHONIOENCODING=utf-8 "D:/Anaconda/python.exe" templates/hk-scan.py
    ... --wait[=分钟]   开盘前后跑：先轮询等个股行情追平连续交易，再扫描（默认等 30 分钟）
    ... --force         明知数据是竞价/过时，仍强制输出候选过闸（不推荐）

⚠️ 腾讯港股【个股】行情延迟约 20 分钟，【指数】实时。09:30 后个股 ts 可能仍停在
   09:20:35（集合竞价），此时所有涨幅/成交/上影都是虚价。脚本已内置新鲜度校验，
   数据不可信时会拒绝输出候选过闸——不要用 --force 绕过。

设计目标：一次调用出全部六步法所需数据，避免多轮工具往返。
    阶段1 并发拉：指数 / 港股通池排行 / 全港成交额榜+涨幅榜 / 铺面universe实时
    阶段2 只对入围候选并发拉60日K线，算 分位 / 均线 / ATR / 量能
落盘：scan-hk-YYYYmmdd-HHMM.json（同一时间戳快照，便于事后对账）

实测：腾讯 qt 单请求 120 只 = 0.40s；K线 12 只并发 = 1.12s。
"""
import urllib.request
import json
import sys
import time
import os
import datetime
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120',
      'Referer': 'https://quote.eastmoney.com/'}
TIMEOUT = 10
RETRY = 2       # 快速失败，不做长退避（push2 挂了就跳过，别干等）
BACKOFF = 0.4


def _get(url, enc):
    last = None
    for _ in range(RETRY):
        try:
            req = urllib.request.Request(url, headers=UA)
            return urllib.request.urlopen(req, timeout=TIMEOUT).read().decode(enc, 'ignore')
        except Exception as e:
            last = e
            time.sleep(BACKOFF)
    raise last


def gbk(url):
    return _get(url, 'gbk')


def utf(url):
    return _get(url, 'utf-8')


# 港股铺面 universe —— HK 版「扫描全覆盖」，每板块含锚定位(大市值)+弹性位(中小市值)
HK_UNIVERSE = {
    "互联网平台":    "00700,09988,03690,09618,01024,09888,09961,00780,09698,09999",
    "AI大模型/GPU": "02513,00100,06082,09903,09678,00020,09660,02228,09880,06809",
    "半导体":       "00981,01347,01385,00522,03986,02631,02577,00303",
    "苹果链/光学":   "02382,02018,00285,01415,01478,06088,02038,00698,06613,02475",
    "光模块/光通信":  "03308,06166,06869,00763,01300,02342",
    "PCB/覆铜板":   "01888,00148,01989,02476",
    "汽车整车":      "01211,02015,09868,09866,09863,00175,02333,02238",
    "汽车零部件":     "02338,01316,03898,03606,00425,02050,01057",
    "创新药":       "01801,06160,09926,02162,09995,01952,06996,02696,06990,01548",
    "医药CXO/传统":  "02269,03759,01177,03692,01530,02196,01099,02359,01093,02268",
    "有色黄金":      "02899,01818,03993,01787,00358,01208,03939,06693,03330,02099,02259,06181",
    "钢铁铝业":      "01378,02600,00323,00347",
    "煤炭":         "01088,01898,00639,01171",
    "石油石化":      "00857,00386,00883,02883",
    "电力公用":      "00902,00991,00836,01816,00003,00006",
    "光伏新能源":     "00968,03800,01799,06865",
    "电池储能":      "03931,09696,00819,02845",
    "银行":         "01398,00939,03988,01288,03968,02388,01658",
    "保险":         "02318,02628,01299,01336,06060,02328,02601",
    "券商交易所":     "00388,06030,06886,01776,03908,06099,03958,01428",
    "运动服饰/纺织":  "02020,02331,01368,06110,02313,00551",
    "新消费潮玩":     "09992,09896,02150,06862,01579,02097",
    "食品饮料":      "00291,02319,00322,00151,00168,00288,09633",
    "地产物业":      "00688,01109,00960,02202,01113,06098,02602,02423",
    "建材水泥":      "00914,01313,03323",
    "基建工程机械":   "00390,01186,01766,01157,00669,01133,01072",
    "电信":         "00941,00728,00762",
    "航运物流":      "00753,00670,01919,02866,02057,02618,01519",
    "传媒教育":      "09626,00772,01797,00268,03888",
    "香港本地":      "00001,00016,00005,00823",
    "澳门博彩":      "01928,00027,02282,01128,00880",
    "农业食品加工":   "01610,00288,02689",
    "ETF/杠杆":     "02800,03033,03067,03191,07226,02828,07709",
}

HK_INDEX = [("r_hkHSI", "恒生指数"), ("r_hkHSTECH", "恒生科技"), ("r_hkHSCEI", "国企指数")]
A_INDEX = [("s_sh000001", "上证"), ("s_sz399001", "深成"), ("s_sz399006", "创业板")]

UT = "&ut=bd1d9ddb04089700cf9c27f6f7426281"
EM_TPL = ("https://push2.eastmoney.com/api/qt/clist/get?cb=j&pn=%d&pz=50&po=%d&np=1"
          "&fltt=2&invt=2&fid=%s&fs=%s&fields=f2,f3,f6,f12,f14,f20" + UT)
FS_HK_MAIN = "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2"
FS_CONNECT = "b:DLMK0106"


def parse_quote(line):
    """腾讯港股行情字段：3现价 4昨收 5开 30时间 32涨幅 33高 34低 36量 37额 39PE 43振幅 44市值 48/49 52周高低"""
    if '="' not in line:
        return None
    f = line.split('="', 1)[1].rstrip('";\n').split('~')
    if len(f) < 50:
        return None

    def F(i):
        try:
            return float(f[i])
        except Exception:
            return 0.0

    rng = F(33) - F(34)
    return dict(
        code=f[2], name=f[1], price=F(3), prev=F(4), open=F(5), vol=F(36),
        ts=f[30], pct=F(32), high=F(33), low=F(34), amt=F(37), pe=F(39),
        amp=F(43), cap=F(44), w52h=F(48), w52l=F(49),
        us=0.0 if rng <= 0 else (F(33) - max(F(5), F(3))) / rng * 100,
        ls=0.0 if rng <= 0 else (min(F(5), F(3)) - F(34)) / rng * 100,
    )


def fetch_quotes(codes):
    """批量并发。实测单请求塞 120 只只要 0.4s，别再 25 只一批 + sleep。"""
    chunks = [codes[i:i + 100] for i in range(0, len(codes), 100)]

    def one(ch):
        try:
            return gbk("https://qt.gtimg.cn/q=" + ",".join("hk" + c for c in ch))
        except Exception:
            return ""

    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for txt in ex.map(one, chunks):
            for line in txt.split(';'):
                d = parse_quote(line.strip())
                if d:
                    out[d['code']] = d
    return out


def fetch_em(fs, fid="f3", po=1, pages=(1, 2, 3)):
    """东财榜单。港股接口在本机可用（A股 push2 常年被封，港股这条通）。失败返回空，不阻塞。"""
    def one(pn):
        try:
            r = utf(EM_TPL % (pn, po, fid, fs))
            return json.loads(r[r.index('(') + 1:r.rindex(')')])['data']['diff']
        except Exception:
            return []

    rows = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for r in ex.map(one, pages):
            rows += (r or [])
    seen, out = set(), []
    for x in rows:
        if x['f12'] in seen:
            continue
        seen.add(x['f12'])
        if isinstance(x.get('f3'), (int, float)):
            out.append(x)
    return out


def num(v, default=0.0):
    """东财对停牌/无数据标的返回字符串 '-'，直接做算术会 TypeError。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def ma(a, n):
    return sum(a[-n:]) / max(1, min(n, len(a)))


def fetch_klines(codes):
    def one(c):
        try:
            url = "https://web.ifzq.gtimg.cn/appstock/app/hkfqkline/get?param=hk%s,day,,,60,qfq" % c
            d = json.loads(utf(url))['data']['hk' + c]
            k = d.get('qfqday') or d.get('day') or []
            if len(k) < 6:
                return c, None
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
            # 旧逻辑把 `cur > m5` 短路在 `m5 < m10 < m20` 之前，导致**空头排列中
            # 反弹站上 MA5 的票被标成「刚站上MA5」并通过闸门**。
            # 实例：华润置地 01109（09-03）MA5 30.47 < MA10 32.49 < MA20 33.21，
            # 明确空头排列，却因反弹到 30.70 站上 MA5 而被判 ✅ 通过——而它刚在
            # 8/31 单日 -9.40%（9375万手巨量）、7 日累计 -20.2%，上方 32.7~35.3
            # 压着 44.3% 套牢盘。这类「空头反弹」是最典型的接刀陷阱，必须单列。
            bull = m5 > m10 > m20        # 均线向上发散
            bear = m5 < m10 < m20        # 均线向下发散
            if bear:
                trend = "空头反弹" if cur > m5 else "空头排列"
            elif bull and cur > m5:
                trend = "多头排列"
            elif cur > m5 and m5 > m10:
                trend = "短期多头"
            elif cur > m5:
                trend = "刚站上MA5"
            else:
                trend = "破MA5"
            # ⚠ 2026-09-04 新增 q20 / ovh —— 三次深挖三次推翻扫描结论后补的两个维度：
            #   q20  20日区间分位。只看 q60 会把「箱体中部」误判成低位：
            #        新鸿基 q60=53 但 q20=51（110~128 箱体正中）；中国铝业 q60=43 但 q20=65。
            #   ovh  上方套牢率＝60日内均价高于现价的那些交易日的成交量占比。
            #        华润置地 ovh=80.3%、快手 93.1%、腾讯 63.4% —— 深跌反弹票的共同特征，
            #        闸门原先完全看不见。华润按120日口径只有44%，60日口径更灵敏。
            q20 = ((cur - min(lo[-20:])) / (max(hi[-20:]) - min(lo[-20:])) * 100
                   if len(cl) >= 20 and max(hi[-20:]) > min(lo[-20:]) else 0.0)
            tv = sum(vo) or 1.0
            ovh = sum(vo[i] for i in range(len(cl)) if (hi[i] + lo[i]) / 2 > cur) / tv * 100
            return c, dict(
                q60=(cur - min(lo)) / rng * 100 if rng > 0 else 0.0,
                q20=q20, ovh=ovh,
                dd=(max(hi) - cur) / max(hi) * 100,
                ma5=m5, ma10=m10, ma20=m20, trend=trend,
                atr=atr, atrp=atr / cur * 100, stop2=cur - 2 * atr,
                vr=vo[-1] / (sum(vo[-21:-1]) / 20) if len(vo) > 21 else 0.0,
            )
        except Exception:
            return c, None

    out = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for c, v in ex.map(one, codes):
            if v:
                out[c] = v
    return out


def gate(d, k):
    """框架强制闸门：60日分位 / 上影 / 涨幅区间 / 均线"""
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
    # 20日高位：q60 低但 q20 高 = 箱体中上部，不是低位（中国铝业 q60=43/q20=65）
    if k.get('q20', 0) > 85:
        warn.append("20日极高位")
    elif k.get('q20', 0) > 70:
        warn.append("20日高位")
    # 上方套牢：深跌反弹票的共同特征，每一步反弹都在啃解套盘
    if k.get('ovh', 0) > 60:
        warn.append("上方套牢%.0f%%" % k['ovh'])
    if k['trend'] == "空头排列":
        bad.append("空头排列")
    elif k['trend'] == "空头反弹":
        # 空头排列中反弹站上 MA5 —— 不是「趋势转好」，是下跌中继的接刀区。
        # 不直接否决（超跌反弹确有可做的），但必须显式标出来强制人工复核：
        # 看上方套牢盘、MA10 距离、反弹量能是否递减。
        warn.append("空头反弹·非趋势转好")
    if bad:
        return 2, "❌ " + "/".join(bad)
    if warn:
        return 1, "⚠ " + "/".join(warn)
    return 0, "✅ 通过"


# ── 行情新鲜度校验（2026-09-02 新增，血的教训） ────────────────────────
# 腾讯港股【个股】行情延迟约 20 分钟，【指数】实时。09:30 开盘后个股 ts 常仍停在
# 09:20:35（集合竞价收尾）不动，此时涨幅/成交/振幅/上影全是竞价虚价：大批股票
# 显示 +0.00% / 成交 0 万，少数票挂出离谱虚价。
# 实测 2026-09-02：竞价快照给出「石油石化 +1.42% 全场第一」，09:55 实盘是 -0.50%；
# 中海油服 +2.37%→-2.10%、山东墨龙 +13.57%→+7.37%、联想 +2.03%→-1.77%、
# 广度 上涨23%→13%。用竞价数据选股 = 结论全错。
# 因此：ts 未进入连续交易 / 滞后 >5 分钟 / 停在上一交易日 时，拒绝输出候选过闸。

# 阈值标定（2026-09-02 实测）：本机免费源对港股个股的【稳态延迟就是 ~15 分钟】，
# 这是正常的、数据本身是真实成交价，只是滞后——可用，但必须标注"N 分钟前"。
# 真正会让结论全错的是【集合竞价虚价】（ts 停在 09:20 左右不动），以及行情源卡死。
# 所以：竞价 → 拦；15 分钟级延迟 → 只警告；超 30 分钟 → 视为卡死，拦。
FRESH_LAG_WARN = 8.0                # 超过此值标注"数据为 N 分钟前"
FRESH_LAG_BLOCK = 30.0              # 超过此值视为行情源卡死，拒绝过闸
CONT_OPEN_MIN = 9 * 60 + 32         # 连续交易起点（09:30 开盘 + 2 分钟缓冲）
SESSIONS = ((9 * 60 + 30, 12 * 60), (13 * 60, 16 * 60 + 10))  # 港股连续交易时段

STATE_TXT = {
    "LIVE":    ("✅", "行情新鲜，数据可用"),
    "DELAYED": ("🟡", "个股行情延迟（港股免费源常态 ~15 分钟）—— 可用，但按滞后时点解读"),
    "AUCTION": ("🔴", "个股仍是【集合竞价虚价】—— 涨幅/成交/振幅/上影全部不可用"),
    "STALE":   ("🔴", "个股行情【疑似卡死】—— 滞后远超常态延迟"),
    "HOLIDAY": ("🔴", "个股行情停在【上一交易日】—— 疑似休市，参见 SKILL.md 节假日检测"),
    "CLOSED":  ("🟡", "当前非连续交易时段，以下为【收盘/休市快照】"),
    "UNKNOWN": ("🔴", "无法解析个股行情时间戳"),
}
BLOCK_STATES = {"AUCTION", "STALE", "HOLIDAY", "UNKNOWN"}


def _parse_ts(s):
    for fmt in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S"):
        try:
            return datetime.datetime.strptime((s or "").strip(), fmt)
        except Exception:
            pass
    return None


def _index_ts(idx_raw):
    out = []
    for line in idx_raw.split(';'):
        if '="' not in line:
            continue
        f = line.split('="', 1)[1].rstrip('";\n').split('~')
        if len(f) > 30:
            t = _parse_ts(f[30])
            if t:
                out.append(t)
    return max(out) if out else None


def freshness(uni, idx_raw):
    """判定行情状态。个股取 max(ts)——最近成交的那只最能代表行情源进度。"""
    now = datetime.datetime.now()
    tss = [t for t in (_parse_ts(d.get('ts')) for d in uni.values()) if t]
    q, i = (max(tss) if tss else None), _index_ts(idx_raw)
    info = dict(quote_ts=q, index_ts=i, now=now,
                lag=None if not q else (now - q).total_seconds() / 60.0)
    if not q:
        return "UNKNOWN", info
    nowmin = now.hour * 60 + now.minute
    if not any(a <= nowmin < b for a, b in SESSIONS):
        return "CLOSED", info          # 盘前 / 午休 / 收盘后，静态数据属正常
    if q.date() != now.date():
        return "HOLIDAY", info
    if q.hour * 60 + q.minute < CONT_OPEN_MIN:
        return "AUCTION", info
    if info['lag'] > FRESH_LAG_BLOCK:
        return "STALE", info
    if info['lag'] > FRESH_LAG_WARN:
        return "DELAYED", info
    return "LIVE", info


def print_freshness(state, info):
    mark, txt = STATE_TXT[state]
    q, i, lag = info['quote_ts'], info['index_ts'], info['lag']
    print("\n【行情新鲜度】%s %s" % (mark, txt))
    print("  个股行情时间 %s   滞后本机 %s"
          % (q.strftime("%Y/%m/%d %H:%M:%S") if q else "解析失败",
             "%.1f 分钟" % lag if lag is not None else "—"))
    print("  指数行情时间 %s   本机时间 %s"
          % (i.strftime("%Y/%m/%d %H:%M:%S") if i else "解析失败",
             info['now'].strftime("%Y/%m/%d %H:%M:%S")))
    if state in BLOCK_STATES:
        print("  ⛔ 候选过闸已【拒绝输出】：拿竞价/卡死数据选股，结论必错。")
        print("     处理：稍等片刻重跑，或用 --wait 自动等到行情追平；确要强出用 --force。")
    elif state == "DELAYED":
        print("  ⚠ 下方个股涨幅/成交/上影 均为 %s 的状态，非此刻；盘口快变时以实时终端为准。"
              % (q.strftime("%H:%M") if q else "?"))


def wait_until_live(max_min=30.0, probe="00700"):
    """轮询直到个股行情进入连续交易时段（--wait）。"""
    deadline = time.time() + max_min * 60
    n = 0
    while time.time() < deadline:
        n += 1
        try:
            f = gbk("https://qt.gtimg.cn/q=hk" + probe).split('~')
            t = _parse_ts(f[30]) if len(f) > 30 else None
        except Exception:
            t = None
        now = datetime.datetime.now()
        # 只需脱离集合竞价 + 行情源没卡死；~15 分钟的常态延迟不必等（等不到）
        ok = bool(t) and t.date() == now.date() and \
            t.hour * 60 + t.minute >= CONT_OPEN_MIN and \
            (now - t).total_seconds() / 60.0 <= FRESH_LAG_BLOCK
        print("  [wait %2d] 个股行情 %s  %s"
              % (n, t.strftime("%H:%M:%S") if t else "?", "→ 已追平，开始扫描" if ok else "…"))
        if ok:
            return True
        time.sleep(30)
    print("  [wait] 超时 %.0f 分钟，行情仍未追平——继续扫描但过闸会被拒绝。" % max_min)
    return False


def main():
    force = "--force" in sys.argv
    if any(a.startswith("--wait") for a in sys.argv):
        arg = [a for a in sys.argv if a.startswith("--wait")][0]
        mm = float(arg.split("=", 1)[1]) if "=" in arg else 30.0
        print("等待港股个股行情进入连续交易时段（最多 %.0f 分钟）…" % mm)
        wait_until_live(mm)

    t0 = time.time()
    sec_of, codes = {}, []
    for s, cs in HK_UNIVERSE.items():
        for c in cs.split(','):
            if c not in sec_of:
                sec_of[c] = s
                codes.append(c)

    # 阶段1：所有实时数据一次性并发
    with ThreadPoolExecutor(max_workers=6) as ex:
        f_idx = ex.submit(gbk, "https://qt.gtimg.cn/q=" + ",".join(c for c, _ in HK_INDEX))
        f_aidx = ex.submit(gbk, "https://qt.gtimg.cn/q=" + ",".join(c for c, _ in A_INDEX))
        f_uni = ex.submit(fetch_quotes, codes)
        f_conn = ex.submit(fetch_em, FS_CONNECT, "f3", 1, (1, 2, 3))
        f_amt = ex.submit(fetch_em, FS_HK_MAIN, "f6", 1, (1,))
        f_gain = ex.submit(fetch_em, FS_HK_MAIN, "f3", 1, (1, 2))
        idx_raw, aidx_raw = f_idx.result(), f_aidx.result()
        uni, conn = f_uni.result(), f_conn.result()
        amtl, gain = f_amt.result(), f_gain.result()
    t1 = time.time() - t0

    state, finfo = freshness(uni, idx_raw)
    blocked = state in BLOCK_STATES and not force

    print("=" * 108)
    print("港股全局扫描    本机时间 %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 108)
    print_freshness(state, finfo)
    if state in BLOCK_STATES and force:
        print("  ⚠ --force 已启用：以下候选过闸基于不可信数据，结论仅供调试，不得据此下单。")

    print("\n【STEP1 大盘】（指数为实时，不受个股延迟影响）")
    for line in idx_raw.split(';'):
        if '="' not in line:
            continue
        f = line.split('="', 1)[1].rstrip('";\n').split('~')
        if len(f) > 34:
            print("  %-10s %12s  %+7s%%    高 %10s  低 %10s    [行情时间 %s]"
                  % (f[1], f[3], f[32], f[33], f[34], f[30]))
    for line in aidx_raw.split(';'):
        if '="' not in line:
            continue
        f = line.split('="', 1)[1].rstrip('";\n').split('~')
        if len(f) > 5:
            print("  %-10s %12s  %+7s%%" % (f[1], f[3], f[5]))

    if conn:
        up = [x for x in conn if x['f3'] > 0]
        dn = [x for x in conn if x['f3'] < 0]
        print("\n【广度 · 港股通池 n=%d】涨%d 跌%d 平%d → 上涨%.0f%%  涨跌比%.2f:1"
              "  |  涨>3%%:%d  跌>3%%:%d  跌>5%%:%d"
              % (len(conn), len(up), len(dn), len(conn) - len(up) - len(dn),
                 100 * len(up) / len(conn), len(up) / max(1, len(dn)),
                 sum(1 for x in up if x['f3'] > 3),
                 sum(1 for x in dn if x['f3'] < -3),
                 sum(1 for x in dn if x['f3'] < -5)))
    else:
        print("\n【广度】⚠ 港股通池榜单获取失败，广度改用 universe 估算：涨%d/%d"
              % (sum(1 for d in uni.values() if d['pct'] > 0), len(uni)))

    # STEP2 板块聚合 + 锚定位/弹性位 + 上影普查
    print("\n【STEP2 板块聚合】按均涨幅排序   锚定位=市值最大  弹性位=市值最小%s"
          % ("   🔴 %s，以下排序不可信" % STATE_TXT[state][1] if state in BLOCK_STATES else ""))
    print("  %-14s %8s %7s %13s %13s %9s %9s" %
          ("板块", "涨/总", "均涨%", "锚定位", "弹性位", "弹性-锚定", "上影>40%"))
    aggs = []
    for s, cs in HK_UNIVERSE.items():
        ds = [uni[c] for c in cs.split(',') if c in uni and uni[c]['price'] > 0]
        if not ds:
            continue
        big = max(ds, key=lambda d: d['cap'])
        small = min(ds, key=lambda d: d['cap'])
        aggs.append((sum(d['pct'] for d in ds) / len(ds), s,
                     sum(1 for d in ds if d['pct'] > 0), len(ds), big, small,
                     sum(1 for d in ds if d['us'] > 40)))
    for avg, s, u, n, big, small, longus in sorted(aggs, reverse=True):
        flag = "  ⚠资金在做小票" if (small['pct'] - big['pct']) > 3 else ""
        print("  %-14s %4d/%-3d %+7.2f %6s%+6.2f%% %6s%+6.2f%% %+9.2f %6d/%-3d%s"
              % (s, u, n, avg, big['name'][:4], big['pct'], small['name'][:4],
                 small['pct'], small['pct'] - big['pct'], longus, n, flag))

    if gain:
        print("\n【全港涨幅榜 · 成交>0.8亿】")
        k = 0
        for x in sorted(gain, key=lambda x: -x['f3']):
            a = num(x.get('f6')) / 1e8
            if a < 0.8:
                continue
            print("  %-7s %-15s %+7.2f%% %11s  成交%7.2f亿  市值%7.0f亿"
                  % (x['f12'], str(x['f14'])[:13], num(x['f3']), x['f2'], a,
                     num(x.get('f20')) / 1e8))
            k += 1
            if k >= 18:
                break
    if amtl:
        print("\n【全港成交额榜 TOP15】")
        for x in amtl[:15]:
            print("  %-7s %-15s %+7.2f%% %11s  成交%7.2f亿"
                  % (x['f12'], str(x['f14'])[:13], num(x['f3']), x['f2'],
                     num(x.get('f6')) / 1e8))

    # 阶段2：只对入围候选拉K线（不是全 universe，省一半时间）
    # 行情不可信时直接跳过——省掉 40 次 K 线请求，更重要的是不产出误导性候选
    pool, kl = [], {}
    if blocked:
        print("\n【STEP3 候选过闸】⛔ 已拒绝输出")
        print("  原因：%s（个股 ts %s，滞后 %s）"
              % (STATE_TXT[state][1],
                 finfo['quote_ts'].strftime("%H:%M:%S") if finfo['quote_ts'] else "?",
                 "%.1f 分钟" % finfo['lag'] if finfo['lag'] is not None else "—"))
        print("  上方 STEP2 板块聚合同样基于该数据，只可用于看结构、不可用于下结论。")
        print("  重跑：PYTHONIOENCODING=utf-8 python templates/hk-scan.py --wait")
    else:
        pool = [d for d in uni.values() if d['pct'] > 0.5 and d['amt'] > 3e7]
        pool.sort(key=lambda d: -d['amt'])
        kl = fetch_klines([d['code'] for d in pool[:40]])

        print("\n【STEP3 候选过闸】筛选：涨幅>0.5%% 且 成交>0.3亿，按成交额取前40")
        print("  闸门：60日&20日分位  上方套牢  上影  涨幅区间  均线结构")
        print("  %-6s %-13s %-12s %6s %6s %6s %6s %6s %6s %6s %6s %9s %8s  %s"
              % ("代码", "名称", "板块", "涨幅%", "60分%", "20分%", "套牢%", "上影%",
                 "下影%", "量比", "ATR%", "2ATR止损", "成交亿", "判定"))
        rank = []
        for d in pool:
            k = kl.get(d['code'])
            if not k:
                continue
            sev, verdict = gate(d, k)
            rank.append((sev, -d['amt'], d, k, verdict))
        for _, _, d, k, v in sorted(rank, key=lambda r: (r[0], r[1]))[:28]:
            print("  %-6s %-13s %-12s %6.2f %6.0f %6.0f %6.0f %6.1f %6.1f %6.2f %6.1f %9.2f %8.2f  %s"
                  % (d['code'], d['name'][:11], sec_of.get(d['code'], '-')[:10], d['pct'],
                     k['q60'], k.get('q20', 0), k.get('ovh', 0), d['us'], d['ls'],
                     k['vr'], k['atrp'], k['stop2'], d['amt'] / 1e8, v))

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    sdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scans")
    out = os.path.join(sdir, "scan-hk-%s.json" % stamp)
    try:
        os.makedirs(sdir, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fp:
            json.dump({"stamp": stamp, "universe": uni, "kline": kl,
                       "connect": conn, "gainers": gain, "turnover": amtl,
                       "freshness": {
                           "state": state, "blocked": blocked,
                           "quote_ts": finfo['quote_ts'].strftime("%Y/%m/%d %H:%M:%S")
                                       if finfo['quote_ts'] else None,
                           "index_ts": finfo['index_ts'].strftime("%Y/%m/%d %H:%M:%S")
                                       if finfo['index_ts'] else None,
                           "lag_min": round(finfo['lag'], 2) if finfo['lag'] is not None else None}},
                      fp, ensure_ascii=False)
        saved = os.path.normpath(out)
    except Exception as e:
        saved = "落盘失败 %s" % e

    print("\n" + "-" * 108)
    print("阶段1 全部实时 %.2fs  |  阶段2 %d只K线 %.2fs  |  合计 %.2fs"
          % (t1, len(kl), time.time() - t0 - t1, time.time() - t0))
    print("快照 %s" % saved)


if __name__ == "__main__":
    main()
