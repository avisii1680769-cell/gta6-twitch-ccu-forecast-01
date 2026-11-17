import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys_path = None
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]


def round2(x):
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def parse_dt(s):
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


PLATFORM_KEYS = ["PC", "PS5", "PS4", "Xbox", "Switch", "Stadia"]


def platform_set(text):
    t = (text or "").upper()
    s = set()
    for k in PLATFORM_KEYS:
        if k.upper() in t:
            s.add(k)
    # normalize PS4/PS5
    if "PS4" in t or "PS5" in t:
        pass
    return s


def extract_unlock_hour(text):
    # first UTC time like 04:00Z or 04:00 Z
    m = re.search(r"(\d{1,2}):(\d{2})\s*Z", text or "")
    if not m:
        return None
    h = int(m.group(1)); mi = int(m.group(2))
    return h + mi / 60.0


def circ_dist(a, b):
    if a is None or b is None:
        return 0.0
    d = abs(a - b)
    d = min(d, 24 - d)
    return d


def jaccard(a, b):
    if not a and not b:
        return 1.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def launch_hours(comp):
    # returns dict hour->viewers for hours 1..24 of launch day
    ds = parse_dt(comp["day_start"])
    end = ds + timedelta(hours=24)
    out = {}
    for e in comp["hourly"]:
        t = parse_dt(e["from"])
        if ds <= t < end:
            idx = int((t - ds).total_seconds() // 3600) + 1
            if 1 <= idx <= 24:
                v = e.get("viewers", 0)
                if v is None:
                    v = 0
                out[idx] = v
    return out, ds



def steep_unlock_hour(hours):
    # estimate unlock hour (0..23) as hour of steepest increase in first 24h
    vals = [hours.get(h, 0) for h in range(1, 25)]
    vals = [max(1, v if v is not None else 1) for v in vals]
    best = 0; best_delta = -1e18
    for h in range(1, 24):
        delta = vals[h] - vals[h-1]
        if delta > best_delta:
            best_delta = delta; best = h  # transition into hour h+1? 
    # best is index in 0-based vals difference: hour (best+1) is where jump occurs? 
    return float(best)  # approximate UTC hour

def prelaunch_momentum(comp, hours):
    # mean log viewers over 24h before day_start, and log hour1
    ds = parse_dt(comp["day_start"])
    start = ds - timedelta(hours=24)
    vals = []
    for e in comp["hourly"]:
        t = parse_dt(e["from"])
        if start <= t < ds:
            v = e.get("viewers", 0)
            if v is None or v < 1:
                v = 1
            vals.append(math.log(v))
    if not vals:
        return None
    mean_log = sum(vals) / len(vals)
    h1 = hours.get(1, 0)
    h1 = max(1, h1 if h1 is not None else 1)
    return math.log(h1) - mean_log




def case_prelaunch_momentum(case):
    ds = parse_dt(case["day_start"])
    start = ds - timedelta(hours=24)
    # use history_hourly
    vals = []
    for e in case["history_hourly"]:
        t = parse_dt(e["from"])
        if start <= t < ds:
            v = e.get("viewers", 0)
            if v is None or v < 1:
                v = 1
            vals.append(math.log(v))
    if not vals:
        return None
    mean_log = sum(vals) / len(vals)
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    p1 = max(1, first["viewers"] if first else 1)
    return math.log(p1) - mean_log


def last24_logmap_case(case):
    ds = parse_dt(case["day_start"])
    start = ds - timedelta(hours=24)
    out = {}
    for e in case["history_hourly"]:
        t = parse_dt(e["from"])
        if start <= t < ds:
            off = int((t - start).total_seconds() // 3600)  # 0..23
            v = e.get("viewers", 0)
            if v is None or v < 1:
                v = 1
            out[off] = math.log(v)
    return out, ds


def last24_logmap_comp(comp):
    ds = parse_dt(comp["day_start"])
    start = ds - timedelta(hours=24)
    out = {}
    for e in comp["hourly"]:
        t = parse_dt(e["from"])
        if start <= t < ds:
            off = int((t - start).total_seconds() // 3600)
            v = e.get("viewers", 0)
            if v is None or v < 1:
                v = 1
            out[off] = math.log(v)
    return out


def shape24_weight(case, comp):
    cmap, ds = last24_logmap_case(case)
    compmap = last24_logmap_comp(comp)
    common = [k for k in cmap if k in compmap]
    if len(common) < 3:
        return 1.0
    # standardize each series over common
    cv = [cmap[k] for k in common]
    pv = [compmap[k] for k in common]
    mc = sum(cv)/len(cv); mp = sum(pv)/len(pv)
    vc = [x-mc for x in cv]; vp = [x-mp for x in pv]
    denom = (sum(x*x for x in vc)*sum(x*x for x in vp))**0.5
    if denom <= 0:
        return 1.0
    corr = sum(a*b for a,b in zip(vc,vp))/denom
    # map corr [-1,1] to weight
    return math.exp(1.5 * corr)


def weighted_quantile(xs, ws, q):
    if not xs:
        return 0.0
    pairs = sorted(zip(xs, ws))
    xs = [p[0] for p in pairs]
    ws = [p[1] for p in pairs]
    total = sum(ws)
    if total <= 0:
        # unweighted
        n = len(xs)
        pos = (n - 1) * q
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        if lo == hi:
            return xs[lo]
        frac = pos - lo
        return xs[lo] * (1 - frac) + xs[hi] * frac
    # cumulative
    cum = [0.0]
    for w in ws:
        cum.append(cum[-1] + w)
    # normalize
    # find index
    target = q * total
    # cum[i] is sum of first i weights
    # find smallest i (1-based) with cum[i] >= target
    idx = 1
    while idx < len(cum) and cum[idx] < target:
        idx += 1
    if idx <= 1:
        return xs[0]
    if idx >= len(xs):
        return xs[-1]
    # interpolate between xs[idx-2] and xs[idx-1]
    lo_cum = cum[idx - 1]
    hi_cum = cum[idx]
    denom = hi_cum - lo_cum
    if denom <= 0:
        return xs[idx - 1]
    frac = (target - lo_cum) / denom
    frac = clamp(frac, 0.0, 1.0)
    return xs[idx - 2] + frac * (xs[idx - 1] - xs[idx - 2])


def forecast_case(case):
    first = next((k for k in case["known"] if k["hour"] == 1), None)
    if first is None:
        raise ValueError("no hour1")
    p1 = max(1, first["viewers"])

    # case platforms from notes
    case_platforms = platform_set(case.get("notes", ""))
    # also try game name? no
    case_unlock = extract_unlock_hour(case.get("notes", ""))
    case_momentum = case_prelaunch_momentum(case)

    # parameters
    SIGMA_SCALE = 0.55
    ALPHA_PLATFORM = 0.5
    ALPHA_UNLOCK = 0.3
    ALPHA_HIST = 0.5
    SIGMA_HIST = 1.0

    comparables_data = []
    for comp in case["comparables"]:
        hours, ds = launch_hours(comp)
        if 1 not in hours:
            continue
        c1 = hours[1]
        if c1 is None:
            continue
        c1 = max(1, c1)
        # build log ratios for hours present
        ratios = {}  # hour -> logratio
        for h in range(2, 25):
            if h in hours:
                vh = hours[h]
                if vh is None:
                    vh = 0
                vh = max(1, vh)
                ratios[h] = math.log(vh / c1)

        # weight
        # scale
        d_scale = abs(math.log(c1) - math.log(p1))
        w_scale = math.exp(-0.5 * (d_scale / SIGMA_SCALE) ** 2)

        # history momentum
        comp_mom = prelaunch_momentum(comp, hours)
        if case_momentum is not None and comp_mom is not None:
            d_hist = abs(comp_mom - case_momentum)
            w_hist = math.exp(-0.5 * (d_hist / 1.0) ** 2)
        else:
            w_hist = 1.0

        w_shape = shape24_weight(case, comp)
        # platforms
        comp_platforms = platform_set(comp.get("platforms", ""))
        if not case_platforms:
            w_plat = 1.0
        else:
            # boost if comparable covers all case platforms
            if case_platforms.issubset(comp_platforms):
                w_plat = 1.4
            else:
                w_plat = 0.6

        # unlock
        comp_unlock = steep_unlock_hour(hours)
        d_unlock = circ_dist(case_unlock, comp_unlock)
        w_unlock = math.exp(-d_unlock / 4.0) if (case_unlock is not None and comp_unlock is not None) else 1.0

        w = w_scale * w_hist * w_shape * w_plat * w_unlock
        if w <= 0 or not math.isfinite(w):
            w = 1e-12
        comparables_data.append((comp, hours, ratios, w))

    if not comparables_data:
        # persistence fallback
        out_hours = []
        for row in case["forecast"]:
            h = row["hour"]
            qs = [round2(p1 * math.exp(z * 0.15 * math.sqrt(h - 1))) for z in Z]
            out_hours.append({"hour": h, "q": qs})
        return {"hours": out_hours}

    # effective N
    ws = [c[3] for c in comparables_data]
    total_w = sum(ws)
    eff_n = (total_w ** 2) / sum(w * w for w in ws) if sum(w * w for w in ws) > 0 else 0

    # blend toward persistence if thin: add pseudo-comparable with weight prior
    # prior weight = max(0, 5 - eff_n) * (total_w / max(eff_n,1))? 
    # Simpler: if eff_n < 8, add pseudo entries (all ratios 0, spread baseline) with weight = (8-eff_n)*avg_w
    if eff_n < 8:
        avg_w = total_w / len(ws)
        pseudo_w = (8 - eff_n) * avg_w
        # pseudo comparable has ratio_log 0 for all hours, and we handle spread via separate? 
        # We'll add pseudo as a comparable with ratios 0 for all h
        pseudo_ratios = {h: 0.0 for h in range(2, 25)}
        comparables_data.append((None, {}, pseudo_ratios, pseudo_w))

    # Recompute for each hour
    out_hours = []
    for row in case["forecast"]:
        h = row["hour"]
        # collect ratios for this hour
        xs = []
        wts = []
        for comp, hours, ratios, w in comparables_data:
            if h in ratios:
                xs.append(ratios[h])
                wts.append(w)
        if not xs:
            # persistence for this hour
            qs = [round2(p1 * math.exp(z * 0.15 * math.sqrt(h - 1))) for z in Z]
            out_hours.append({"hour": h, "q": qs})
            continue
        # weighted quantiles of log ratios
        qlogs = [weighted_quantile(xs, wts, tau) for tau in LEVELS]
        # use weighted mean for median
        totalw = sum(wts)
        wmean = sum(x*w for x,w in zip(xs,wts))/totalw
        qlogs[2] = wmean
        # enforce non-decreasing
        for i in range(1, len(qlogs)):
            if qlogs[i] < qlogs[i - 1]:
                qlogs[i] = qlogs[i - 1]
        qs = [round2(p1 * math.exp(ql)) for ql in qlogs]
        # ensure non-decreasing in q space too
        for i in range(1, len(qs)):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        # ensure >0
        qs = [max(0.01, q) for q in qs]
        # cap
        qs = [min(1e9, q) for q in qs]
        out_hours.append({"hour": h, "q": qs})

    return {"hours": out_hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
