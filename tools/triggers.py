"""Price levels that would change a desk's exposure, found by re-running the desk's own published engine on
hypothetical closes. Assumption, stated on the site: the price holds at the level for HOLD sessions while every other
input stays at today's reading (stocks: the other equity ETFs move by the same percentage; VIX, credit, rates unchanged).
Writes <out>/triggers.json, and <out>/sim/sim.json (a grid of hypothetical prices, each run through the desk's engine,
with the group and factor readings the site's scenario simulator starts from).
Context only: it does not change any model."""
import argparse, importlib.util, json, os, shutil, sys, tempfile, time
import numpy as np, pandas as pd

HOLD = 5
LAST = {}      # the last scenario run per desk: features, groups, scores, states
EQ = ['SPY', 'QQQ', 'IWM', 'RSP', 'SMH', 'EEM', 'XLY', 'XLP']


def mod(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def stocks_state(E, S, M, r):
    S2 = S.copy(); t = S2.SPY.last_valid_index(); last = S2.loc[:t].ffill().iloc[-1]
    days = pd.bdate_range(t + pd.Timedelta(days=1), periods=HOLD)
    add = pd.DataFrame([last] * HOLD, index=days); add.index.name = 'date'
    for c in EQ:
        if c in add: add[c] = last[c] * r
    if 'spy_vol' in add: add['spy_vol'] = last.get('spy_vol')
    S2 = pd.concat([S2, add])
    X = E.assemble(S2, M); f = E.features(X, M); score, grp = E.composite(f); sig, sm = E.regimes(score)
    reg = E.states(sig, grp['macro'], X.SPY, f._m50, cpi=f._cpi)
    LAST['stocks'] = dict(f=f, grp=grp, score=score, sm=sm, reg=reg)
    return E.EXPOSURE[reg.iloc[-1]], reg


def btc_state(E, S, G, FX, r):
    S2 = S.copy(); t = S2.btc.last_valid_index(); last = S2.loc[:t].ffill().iloc[-1]
    days = pd.date_range(t + pd.Timedelta(days=1), periods=HOLD, freq='D')
    add = pd.DataFrame([last] * HOLD, index=days); add['btc'] = last['btc'] * r; add.index.name = 'date'
    S2 = pd.concat([S2, add])
    X = E.assemble(S2, G, FX); X = X[X.btc.notna()]; f = E.features(X); score, grp = E.composite(f); sig, sm = E.regimes(score)
    reg = E.states(sig, grp['macro'], X.btc, f._m20w, f._m200w)
    LAST['bitcoin'] = dict(f=f, grp=grp, score=score, sm=sm, reg=reg, deep=bool(E.deep_flag(X.btc, sig).iloc[-1]))
    return E.EXPOSURE[reg.iloc[-1]], reg


def r3(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 3)


def grid(fn, desk, E, ratios, spot, nd):
    """Run the engine at each hypothetical price; keep what the simulator needs to recompute the score in the browser."""
    pts = []
    for r in ratios:
        e, reg = fn(r); L = LAST[desk]; t = L['grp'].index[-1]
        pts.append({'r': round(r, 4), 'price': round(spot * r, nd), 'exposure': e, 'state': reg.iloc[-1],
                    'raw': r3(L['score'].iloc[-1]), 'smooth': r3(L['sm'].iloc[-1]),
                    'groups': {g: r3(L['grp'][g].iloc[-1]) for g in L['grp'].columns},
                    'factors': {k: r3(L['f'][k].iloc[-1]) for k in E.FACTORS if k in L['f']},
                    **({'deep': L['deep']} if 'deep' in L else {})})
    return pts


def model_spec(E):
    """Group weights and factor weights exactly as the engine uses them (composite = weighted average of groups)."""
    return {'groups': {g: w for g, w in E.GROUPS.items()},
            'factors': {k: {'group': v[0], 'w': v[1], 'label': v[2]} for k, v in E.FACTORS.items()},
            'up': E.UP, 'dn': E.DN, 'exposure': E.EXPOSURE, **({'gate': E.MACRO_GATE} if hasattr(E, 'MACRO_GATE') else {})}


def levels(fn, spot, base, lo, hi, nd):
    """Every exposure change reachable by holding a price between lo*spot and hi*spot, nearest first."""
    res, b = {'down': [], 'up': []}, base
    while b > 0:
        r, e = search(fn, lo, 1.0, b, True, cur=1.0 if not res['down'] else res['down'][-1]['r'])
        if r is None: break
        res['down'].append({'r': r, 'price': round(spot * r, nd), 'move': round((r - 1) * 100, 1), 'exposure': e}); b = e
    b = base
    while b < 1:
        r, e = search(fn, 1.0, hi, b, False, cur=1.0 if not res['up'] else res['up'][-1]['r'])
        if r is None: break
        res['up'].append({'r': r, 'price': round(spot * r, nd), 'move': round((r - 1) * 100, 1), 'exposure': e}); b = e
    for k in res:
        for x in res[k]: x.pop('r')
    return res


def search(fn, lo, hi, base, want_lower, cur=1.0, it=13):
    """Bisection on the price ratio: the ratio nearest cur at which exposure moves below (want_lower) or above base."""
    ok = lambda e: (e < base) if want_lower else (e > base)
    e_far, _ = fn(lo if want_lower else hi)
    if not ok(e_far): return None, None
    a, b = (lo, cur) if want_lower else (cur, hi)      # want_lower: ok at a, not ok at b
    for _ in range(it):
        m = (a + b) / 2; e, _ = fn(m)
        if want_lower: (a, b) = (m, b) if ok(e) else (a, m)
        else: (a, b) = (a, m) if ok(e) else (m, b)
    r = a if want_lower else b
    return r, fn(r)[0]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--stocks-engine'); ap.add_argument('--stocks-dir')
    ap.add_argument('--btc-engine'); ap.add_argument('--btc-dir'); ap.add_argument('--out', required=True)
    a = ap.parse_args(); out = {'hold_sessions': HOLD, 'generated': pd.Timestamp.now('UTC').strftime('%Y-%m-%d %H:%M UTC')}
    tmp = tempfile.mkdtemp()                          # the engines' loaders rewrite their stores: never touch the originals
    sim = {'generated': out['generated'], 'hold_sessions': HOLD}
    if a.stocks_engine:
        t0 = time.time(); E = mod(a.stocks_engine, 'mengine')
        sd = shutil.copytree(a.stocks_dir, os.path.join(tmp, 's')); S, M = E.load(sd)
        spy = float(S.SPY.dropna().iloc[-1]); fn = lambda r: stocks_state(E, S, M, r); base, reg = fn(1.0)
        out['stocks'] = {'asof': str(S.SPY.last_valid_index().date()), 'price': round(spy, 2), 'exposure': base,
                         **levels(fn, spy, base, 0.70, 1.30, 2)}
        try:
            sim['stocks'] = {'asof': out['stocks']['asof'], 'price': round(spy, 2), 'spec': model_spec(E),
                             'grid': grid(fn, 'stocks', E, [round(x, 4) for x in np.arange(0.80, 1.1501, 0.025)], spy, 2)}
        except Exception as e:
            print('stocks grid skipped:', type(e).__name__, e, file=sys.stderr)
        out['stocks']['secs'] = round(time.time() - t0, 1)
    if a.btc_engine:
        t0 = time.time(); E = mod(a.btc_engine, 'bengine')
        bd = shutil.copytree(a.btc_dir, os.path.join(tmp, 'b')); S, G, FX = E.load_store(bd)
        px = float(S.btc.dropna().iloc[-1]); fn = lambda r: btc_state(E, S, G, FX, r); base, reg = fn(1.0)
        out['bitcoin'] = {'asof': str(S.btc.last_valid_index().date()), 'price': round(px), 'exposure': base,
                          **levels(fn, px, base, 0.55, 1.60, 0)}
        try:
            sim['bitcoin'] = {'asof': out['bitcoin']['asof'], 'price': round(px), 'spec': model_spec(E),
                              'grid': grid(fn, 'bitcoin', E, [round(x, 4) for x in np.arange(0.60, 1.5001, 0.05)], px, 0)}
        except Exception as e:
            print('bitcoin grid skipped:', type(e).__name__, e, file=sys.stderr)
        out['bitcoin']['secs'] = round(time.time() - t0, 1)
    shutil.rmtree(tmp, ignore_errors=True)
    if 'stocks' in sim or 'bitcoin' in sim:
        os.makedirs(os.path.join(a.out, 'sim'), exist_ok=True)
        json.dump(sim, open(os.path.join(a.out, 'sim', 'sim.json'), 'w'), separators=(',', ':'))
    os.makedirs(a.out, exist_ok=True); json.dump(out, open(os.path.join(a.out, 'triggers.json'), 'w'), indent=1)
    print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ('asof', 'price', 'exposure', 'down', 'up', 'secs')}) for k, v in out.items()}))


if __name__ == '__main__':
    sys.exit(main())
