#!/usr/bin/env python3
"""Kerdos flagship model portfolio — daily engine (stateless: recomputes everything from its inputs each run).

Usage: python3 tools/fengine.py --store store_daily.csv --macro macro_monthly.csv \
           --stocks stocks/history.csv --btc bitcoin/history.csv --out flagship

Rules (version 3, set Oct 30 2026):
  Stocks sleeve 60%  = SPY 35% + QQQ 25%, scaled by the US stocks desk: 100% when Bullish / Neutral / Recovery,
                       50% in a Correction, 0 when Bearish.
  Bitcoin sleeve 30% = scaled by the Bitcoin desk: 100% when Bullish / Recovery, 50% when Neutral / Correction, 0 when Bearish.
                       Held only from 2021-10-19, the launch of the first US Bitcoin ETF; before that date its weight is
                       added to the stocks sleeve, so no backtested return comes from Bitcoin held before it was investable
                       through an ordinary brokerage account.
  Gold 10%           = held at all times.
  Anything not invested sits in 3-month T-bills. Benchmark: the S&P 500 (SPY, dividends approximated).
Backtest: a signal at one close is traded at the next close; the portfolio also rebalances at each month start; 0.05% per
unit of turnover. Dividends are approximated (SPY 1.7%/yr, QQQ 0.7%/yr).
Live record: starts at the open on Monday Oct 26 2026 with the allocation set by the Oct 23 close (inception prices below;
Bitcoin is the CME CF Bitcoin Real Time Index at 9:30 ET). After the first day it follows the backtest's conventions.
"""
import argparse, json, os
import numpy as np, pandas as pd

STOCKS = dict(SPY=.35, QQQ=.25)
BTC_W, GLD_W = .30, .10
STK_E = {'Bullish': 1.0, 'Neutral': 1.0, 'Recovery': 1.0, 'Correction': .5, 'Bearish': 0.0}
BTC_E = {'Bullish': 1.0, 'Neutral': .5, 'Recovery': 1.0, 'Correction': .5, 'Bearish': 0.0}
REG = {'Bullish': 'Risk-On', 'Neutral': 'Risk-On', 'Recovery': 'Risk-On', 'Correction': 'Neutral', 'Bearish': 'Risk-Off'}
ASSETS = ['SPY', 'QQQ', 'BTC', 'GLD', 'CASH']
DIV = dict(SPY=.017, QQQ=.007)
COST, START = .0005, '2005-01-01'
# The Bitcoin sleeve is held only once it could be bought in a normal brokerage account. 2021-10-19 is the first US
# Bitcoin ETF (ProShares BITO, futures-based); the spot ETFs followed on 2024-01-11. The Bitcoin desk's history runs
# from 2014, but those years are deliberately excluded from the sleeve: before BTC_START the 30% goes to the stocks
# sleeve, exactly as it used to before 2014.
BTC_START = '2021-10-19'
BTC_NOTE = ('Past performance is not inclusive of Bitcoin returns prior to the ETFs launching. The Bitcoin sleeve is '
            'held only from 19 October 2021, when the first US Bitcoin ETF launched; before that date its 30% sits in '
            'the stocks sleeve, so no part of the backtest before then comes from Bitcoin returns — including '
            'Bitcoin’s much larger 2014–2021 gains.')
LIVE = '2026-10-26'                                     # inception: the open of this session
OPEN = dict(SPY=762.25, QQQ=707.06, GLD=367.295, BTC=79804.14)   # inception prices (Oct 26 2026, 9:30 ET)
VERSION = 4

# --- v4 candidate (adopted 2026-10-31, forward test starts 2026-11-01) -----------------------------
# Fixed sleeve SPY 35 / QQQ 25 / BTC 30 / GLD 10. The model's only job is total exposure: 100%, 50% or 0%,
# set by a majority vote of four monthly, point-in-time signals:
#   1. Bitcoin above its 10-month average      (trend on the asset carrying ~70% of the sleeve's risk)
#   2. the dollar weakening over 3 months      (Bitcoin and gold are both inverse-dollar)
#   3. gold above its 10-month average         (trend on the diversifier)
#   4. Baa-10y credit spread not widening      (credit conditions)
# Chosen on signal frequency and economic logic, NOT on backtest rank: of 10,879 combinations searched,
# those that beat the fully-invested sleeve on all three metrics in 2014-2021 were LESS likely to repeat in
# 2022-2026 (8%) than a combination picked at random (28%). See journal/research_log.md, 2026-10-31.
V4_W = dict(SPY=.35, QQQ=.25, BTC=.30, GLD=.10)
V4_LIVE = '2026-11-01'                                  # forward test begins here; everything before is backtest


def load(a):
    S = pd.read_csv(a.store, parse_dates=['date']).set_index('date')
    M = pd.read_csv(a.macro, parse_dates=['month']).set_index('month')
    H = pd.read_csv(a.stocks, parse_dates=['date']).set_index('date')
    B = pd.read_csv(a.btc, parse_dates=['date']).set_index('date')
    X = S[[c for c in ['SPY', 'QQQ', 'GLD', 'UUP'] if c in S]].dropna(subset=['SPY']).loc['2004-11-18':].ffill(limit=3)
    if 'UUP' not in X: X['UUP'] = np.nan                  # v4's dollar signal degrades rather than failing the build
    X = X[X.index <= H.index.max()]
    X['BTC'] = B.price.reindex(X.index, method='ffill')
    X['btc_reg'] = B.regime.reindex(X.index, method='ffill')
    pre = X.index < pd.Timestamp(BTC_START)                   # Bitcoin was not investable through an ETF before this
    X.loc[pre, 'BTC'] = np.nan; X.loc[pre, 'btc_reg'] = None  # every "have Bitcoin" test below follows from these two
    X['stk_reg'] = H.regime.reindex(X.index).ffill()
    s = M['TB3MS'].dropna(); s.index = s.index + pd.offsets.MonthEnd(0)
    X['tb3ms'] = s.reindex(X.index, method='ffill').bfill() / 100
    if {'BAA', 'GS10'} <= set(M.columns):
        sp = (M['BAA'] - M['GS10']).dropna(); sp.index = sp.index + pd.DateOffset(months=1) + pd.offsets.MonthEnd(0)
        X['baa10'] = sp.reindex(X.index, method='ffill')
    else:
        X['baa10'] = np.nan                               # same: a missing input drops one vote, it does not crash
    return X


def v4_signals(X):
    """Four monthly point-in-time signals. A month's signal is computed from that month's close and applied
    from the following month, so nothing uses information it would not have had."""
    mo = X[['BTC', 'GLD', 'UUP', 'baa10']].resample('ME').last()
    sig = pd.DataFrame(index=mo.index)
    sig['btc_above10m'] = mo.BTC > mo.BTC.rolling(10).mean()
    sig['dollar_weak'] = mo.UUP.pct_change(3) < 0
    sig['gld_above10m'] = mo.GLD > mo.GLD.rolling(10).mean()
    sig['spread_narrowing'] = (mo.baa10 - mo.baa10.shift(3)) <= 0
    sig = sig.where(mo.notna().rename(columns={'BTC': 'btc_above10m', 'UUP': 'dollar_weak',
                                               'GLD': 'gld_above10m', 'baa10': 'spread_narrowing'}))
    sig = sig.astype(float).shift(1)                       # apply from the next month
    share = sig.mean(axis=1)                               # mean skips missing inputs
    expo = (share * 2).round() / 2                         # -> 0.0 / 0.5 / 1.0
    out = sig.reindex(X.index, method='ffill')
    out['share'] = share.reindex(X.index, method='ffill')
    out['exposure'] = expo.reindex(X.index, method='ffill')
    return out


def sleeve_weights(index, have):
    """The fixed v4 sleeve at full exposure. On days Bitcoin is not held its 30% is added to the stocks sleeve
    pro-rata, the same convention the v3 model uses, so the pre-ETF years are a stocks-and-gold portfolio rather
    than a portfolio carrying 30% idle cash."""
    sw = V4_W['SPY'] + V4_W['QQQ']
    extra = (~have).astype(float) * V4_W['BTC']
    W = pd.DataFrame(0.0, index=index, columns=ASSETS)
    for a in ['SPY', 'QQQ']: W[a] = V4_W[a] + extra * V4_W[a] / sw
    W['GLD'] = V4_W['GLD']
    W['BTC'] = V4_W['BTC'] * have.astype(float)
    return W


def targets_v4(X, sig):
    """The fixed sleeve scaled by the v4 exposure; the remainder waits in T-bills."""
    e = sig.exposure
    W = sleeve_weights(X.index, X.BTC.notna())
    T = W.mul(e, axis=0)
    T['CASH'] = 1 - T.drop(columns='CASH').sum(axis=1)
    T[e.isna()] = 0.0; T.loc[e.isna(), 'CASH'] = 1.0
    return T.clip(lower=0.0)


def returns(X):
    R = pd.DataFrame(index=X.index)
    for a in ['SPY', 'QQQ']: R[a] = X[a].pct_change() + DIV[a] / 252
    R['GLD'] = X.GLD.pct_change(); R['BTC'] = X.BTC.pct_change(); R['CASH'] = X.tb3ms / 252
    return R.fillna(0)


def targets(X, btc=True):
    """Daily target weights. btc=False puts the Bitcoin sleeve into the stocks sleeve throughout (the no-Bitcoin variant)."""
    reg = X.stk_reg.map(REG)
    se = X.stk_reg.map(STK_E)
    have = X.btc_reg.notna() & X.BTC.notna()
    be = X.btc_reg.map(BTC_E).where(have, 0.0).fillna(0.0)
    extra = (~have | (not btc)).astype(float) * BTC_W          # Bitcoin weight routed to stocks when unavailable
    sw = sum(STOCKS.values())
    T = pd.DataFrame(0.0, index=X.index, columns=ASSETS)
    for a, w in STOCKS.items():
        T[a] = (w + extra * w / sw) * se
    T['BTC'] = (BTC_W * be) if btc else 0.0
    T['GLD'] = GLD_W
    T['CASH'] = 1 - T.drop(columns='CASH').sum(axis=1)
    T[se.isna()] = 0.0; T.loc[se.isna(), 'CASH'] = 1.0
    return T.clip(lower=0.0), reg


def simulate(T, R, start, end=None):
    T = T.shift(1).loc[start:end].dropna(); R = R.loc[T.index]
    w = T.iloc[0].values.copy(); eq = [1.0]; turn = 0.0; m = T.index.to_period('M')
    Tv, Rv = T.values, R[ASSETS].values
    for i in range(1, len(T)):
        g = w * (1 + Rv[i]); v = g.sum(); wd = g / v
        if (m[i] != m[i - 1]) or not np.allclose(Tv[i], Tv[i - 1]):
            tc = np.abs(Tv[i] - wd).sum(); turn += tc / 2; v *= (1 - tc * COST); w = Tv[i].copy()
        else: w = wd
        eq.append(eq[-1] * v)
    return pd.Series(eq, index=T.index), turn / max(1e-9, len(T) / 252)


def live_curve(T, R, X):
    """Value of $1 invested at the inception open. Day one earns open-to-close; afterwards the same rules as the backtest."""
    idx = X.index[X.index >= pd.Timestamp(LIVE)]
    if not len(idx): return None
    d0, prev = idx[0], X.index[X.index < pd.Timestamp(LIVE)][-1]
    R1 = R.loc[idx, ASSETS].copy()
    for a, p in OPEN.items():
        R1.loc[d0, a] = X.loc[d0, a] / p - 1 + DIV.get(a, 0) / 252
    Ts = T.shift(1)
    w = T.loc[prev].values.copy(); last = w.copy(); v = 1.0
    vals = [(f'{LIVE} open', 1.0)]; peak, mdd = 1.0, 0.0
    for i, d in enumerate(idx):
        g = w * (1 + R1.loc[d].values); s = g.sum(); wd = g / s; v *= s
        tgt = Ts.loc[d].values
        newm = i > 0 and d.month != idx[i - 1].month
        if newm or not np.allclose(tgt, last):
            tc = np.abs(tgt - wd).sum(); v *= (1 - tc * COST); w = tgt.copy(); last = tgt.copy()
        else: w = wd
        vals.append((str(d.date()), v)); peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    return vals, mdd


def stats(eq, cash):
    r = eq.pct_change().dropna()
    if len(r) < 2: return None
    yrs = len(r) / 252; c = cash.reindex(r.index).fillna(0)
    return dict(cagr=round(float(eq.iloc[-1] ** (1 / yrs) - 1), 4) if yrs >= 1 else None, total=round(float(eq.iloc[-1] / eq.iloc[0] - 1), 4),
                vol=round(float(r.std() * np.sqrt(252)), 4), sharpe=round(float((r - c).mean() / r.std() * np.sqrt(252)), 2),
                maxdd=round(float((eq / eq.cummax() - 1).min()), 4), days=int(len(r)))


def spy_only(index):
    T = pd.DataFrame(0.0, index=index, columns=ASSETS); T['SPY'] = 1.0
    return T


def main():
    ap = argparse.ArgumentParser()
    for k in ['store', 'macro', 'stocks', 'btc', 'out']: ap.add_argument('--' + k, required=True)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    X = load(a); R = returns(X)
    T, reg = targets(X); Tn, _ = targets(X, btc=False); Ts = spy_only(X.index)
    SIG = v4_signals(X); T4 = targets_v4(X, SIG)
    Tfull = sleeve_weights(X.index, X.BTC.notna())               # the sleeve held at 100%, the v4 benchmark
    Tfull['CASH'] = 1 - Tfull.drop(columns='CASH').sum(axis=1)
    curves = {'flagship': T, 'no_btc': Tn, 'spy': Ts, 'v4': T4, 'sleeve_100': Tfull}
    # '2021–26' starts at the Bitcoin ETF launch: the only window in which all four sleeves were actually holdable.
    periods = {'2005–26': (START, None), '2005–14': (START, '2014-12-31'), '2015–26': ('2015-01-01', None),
               '2014–26': ('2014-01-01', None), '2021–26': (BTC_START, None), '2022–26': ('2022-01-01', None)}
    bt, eqs, turnover = {}, {}, None
    for name, TT in curves.items():
        bt[name] = {}
        for lab, (s, e) in periods.items():
            eq, to = simulate(TT, R, s, e); bt[name][lab] = stats(eq, R.CASH)
            if lab == '2005–26': eqs[name] = eq; turnover = round(to, 2) if name == 'flagship' else turnover
    # live record since inception
    live = None
    lf, ls = live_curve(T, R, X), live_curve(Ts, R, X)
    if lf:
        (fv, fdd), (sv, sdd) = lf, ls
        prev = X.index[X.index < pd.Timestamp(LIVE)][-1]
        live = dict(since=LIVE, sessions=len(fv) - 1, asof=fv[-1][0],
                    flagship=dict(total=round(fv[-1][1] - 1, 4), maxdd=round(fdd, 4)),
                    spy=dict(total=round(sv[-1][1] - 1, 4), maxdd=round(sdd, 4)),
                    series=[dict(date=d, flagship=round(x, 5), spy=round(y, 5)) for (d, x), (_, y) in zip(fv, sv)],
                    start_weights={k: round(float(T.loc[prev, k]), 4) for k in ASSETS},
                    start_prices=OPEN, start_signals=dict(stocks=X.stk_reg[prev], bitcoin=X.btc_reg[prev]))
    # --- v4 head-to-head, both models from the v4 forward-test start
    v4live = None
    i4 = X.index[X.index >= pd.Timestamp(V4_LIVE)]
    if len(i4) > 1:
        def track(TT):
            e, _ = simulate(TT, R, V4_LIVE, None); return e / e.iloc[0]
        a4, a3, asl = track(T4), track(T), track(Tfull)
        v4live = dict(since=V4_LIVE, sessions=len(a4) - 1, asof=str(a4.index[-1].date()),
                      v4=dict(total=round(float(a4.iloc[-1]) - 1, 5), maxdd=round(float((a4 / a4.cummax() - 1).min()), 5)),
                      v3=dict(total=round(float(a3.iloc[-1]) - 1, 5), maxdd=round(float((a3 / a3.cummax() - 1).min()), 5)),
                      sleeve=dict(total=round(float(asl.iloc[-1]) - 1, 5), maxdd=round(float((asl / asl.cummax() - 1).min()), 5)),
                      series=[dict(date=str(d.date()), v4=round(float(a4[d]), 5), v3=round(float(a3[d]), 5), sleeve=round(float(asl[d]), 5))
                              for d in a4.index])
    SK = ['btc_above10m', 'dollar_weak', 'gld_above10m', 'spread_narrowing']
    v4 = dict(live_since=V4_LIVE, sleeve=V4_W, exposure=float(SIG.exposure.iloc[-1]), share=round(float(SIG.share.iloc[-1]), 3),
              signals={k: (None if pd.isna(SIG[k].iloc[-1]) else bool(SIG[k].iloc[-1])) for k in SK},
              signals_available=int(SIG[SK].iloc[-1].notna().sum()),
              weights={k: round(float(T4.loc[t_, k]), 4) for k in ASSETS} if (t_ := X.index[-1]) is not None else {},
              backtest=dict(v4=bt['v4'], sleeve_100=bt['sleeve_100']),
              history=[dict(date=str(d.date()), exposure=float(v)) for d, v in
                       SIG.exposure.resample('ME').last().dropna().items()],
              live=v4live,
              note=('Forward test from ' + V4_LIVE + '. Everything before that date is a backtest. Chosen on signal '
                    'frequency and economic logic, not backtest rank: of 10,879 combinations searched, those that beat '
                    'the fully-invested sleeve on all three metrics in 2014-2021 were less likely to repeat in 2022-2026 '
                    '(8%) than one picked at random (28%).'))
    # daily comparison log, appended by the capture task
    cmp = pd.DataFrame({'v3_equity_weight': (T.SPY + T.QQQ + T.BTC).round(4), 'v4_exposure': SIG.exposure,
                        'v3_regime': reg, **{f'sig_{k}': SIG[k] for k in SK}}).loc['2014-01-01':]
    cmp.index.name = 'date'; cmp.to_csv(os.path.join(a.out, 'compare.csv'))
    # 'sleeve' is appended last on purpose: the charts read flagship at column 1 and spy at column 2 by position,
    # so adding a column at the end is safe where inserting one is not.
    E = pd.DataFrame({'flagship': eqs['flagship'], 'spy': eqs['spy'], 'sleeve': eqs['sleeve_100']}).resample('W-FRI').last().round(4)
    E.index.name = 'date'; E.to_csv(os.path.join(a.out, 'equity.csv'))
    E4 = pd.DataFrame({k: eqs[k] for k in ['v4', 'sleeve_100', 'flagship']}).resample('W-FRI').last().round(4)
    E4.index.name = 'date'; E4.to_csv(os.path.join(a.out, 'equity_v4.csv'))
    ye = pd.DataFrame(eqs).groupby(lambda d: d.year).last()
    ye = ye / pd.concat([pd.DataFrame(1.0, index=[ye.index[0] - 1], columns=ye.columns), ye]).shift(1).iloc[1:] - 1
    yearly = [dict(year=int(y), **{k: round(float(v) * 100, 1) for k, v in r.items()}) for y, r in ye.iterrows()]
    h = T.loc[START:].copy(); h.insert(0, 'regime', reg.loc[START:]); h.insert(1, 'stocks', X.stk_reg.loc[START:]); h.insert(2, 'bitcoin', X.btc_reg.loc[START:])
    h[ASSETS] = h[ASSETS].round(4); h.index.name = 'date'; h.to_csv(os.path.join(a.out, 'history.csv'))
    t = X.index[-1]; runs = (reg != reg.shift()).cumsum(); since = reg[runs == runs.iloc[-1]].index[0]
    key = h[ASSETS].round(4).astype(str).agg('|'.join, axis=1)
    chg = h[key != key.shift()].iloc[1:].tail(8)
    prev = h.shift(1)
    changes = [dict(date=str(d.date()), regime=r.regime, stocks=r.stocks, bitcoin=(None if pd.isna(r.bitcoin) else r.bitcoin),
                    weights={k: float(r[k]) for k in ASSETS}, before={k: float(prev.loc[d, k]) for k in ASSETS})
               for d, r in chg.iloc[::-1].iterrows()]
    out = dict(asof=str(t.date()), generated=pd.Timestamp.now('UTC').strftime('%Y-%m-%d %H:%M UTC'), version=VERSION,
               regime=reg[t], regime_since=str(since.date()), stocks_regime=X.stk_reg[t], btc_regime=X.btc_reg[t],
               weights={k: round(float(T.loc[t, k]), 4) for k in ASSETS}, equity_weight=round(float(T.loc[t, 'SPY'] + T.loc[t, 'QQQ']), 4),
               rules=dict(stocks=STOCKS, btc=BTC_W, gold=GLD_W, stocks_exposure=STK_E, btc_exposure=BTC_E), regime_map=REG,
               backtest=bt, yearly=yearly, turnover=turnover, live_since=LIVE, live=live,
               btc_start=BTC_START, btc_note=BTC_NOTE,
               changes=changes, days={k: int(v) for k, v in reg.loc[START:].value_counts().items()}, v4=v4,
               prices={k: round(float(X[k].iloc[-1]), 2) for k in ['SPY', 'QQQ', 'GLD', 'BTC']})
    json.dump(out, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, allow_nan=False, default=str)
    print(json.dumps({k: out[k] for k in ['asof', 'regime', 'weights']} | {'v4': {k: v4[k] for k in ['exposure', 'signals']},
                      'v4_backtest_2014_26': bt['v4'].get('2014–26'), 'sleeve_2014_26': bt['sleeve_100'].get('2014–26'),
                      'head_to_head': v4live and {k: v4live[k] for k in ['sessions', 'v4', 'v3', 'sleeve']}}))


if __name__ == '__main__':
    main()
