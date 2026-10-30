#!/usr/bin/env python3
"""Kerdos flagship model portfolio — daily engine (stateless: recomputes everything from its inputs each run).

Usage: python3 tools/fengine.py --store store_daily.csv --macro macro_monthly.csv \
           --stocks stocks/history.csv --btc bitcoin/history.csv --out flagship

Rules (version 3, set Oct 30 2026):
  Stocks sleeve 60%  = SPY 35% + QQQ 25%, scaled by the US stocks desk: 100% when Bullish / Neutral / Recovery,
                       50% in a Correction, 0 when Bearish.
  Bitcoin sleeve 30% = scaled by the Bitcoin desk: 100% when Bullish / Recovery, 50% when Neutral / Correction, 0 when Bearish.
                       Before 2014 (no Bitcoin desk history) it is added to the stocks sleeve.
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
LIVE = '2026-10-26'                                     # inception: the open of this session
OPEN = dict(SPY=762.25, QQQ=707.06, GLD=367.295, BTC=79804.14)   # inception prices (Oct 26 2026, 9:30 ET)
VERSION = 3


def load(a):
    S = pd.read_csv(a.store, parse_dates=['date']).set_index('date')
    M = pd.read_csv(a.macro, parse_dates=['month']).set_index('month')
    H = pd.read_csv(a.stocks, parse_dates=['date']).set_index('date')
    B = pd.read_csv(a.btc, parse_dates=['date']).set_index('date')
    X = S[['SPY', 'QQQ', 'GLD']].dropna(subset=['SPY']).loc['2004-11-18':].ffill(limit=3)
    X = X[X.index <= H.index.max()]
    X['BTC'] = B.price.reindex(X.index, method='ffill')
    X['btc_reg'] = B.regime.reindex(X.index, method='ffill')
    X['stk_reg'] = H.regime.reindex(X.index).ffill()
    s = M['TB3MS'].dropna(); s.index = s.index + pd.offsets.MonthEnd(0)
    X['tb3ms'] = s.reindex(X.index, method='ffill').bfill() / 100
    return X


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
    curves = {'flagship': T, 'no_btc': Tn, 'spy': Ts}
    periods = {'2005–26': (START, None), '2005–14': (START, '2014-12-31'), '2015–26': ('2015-01-01', None)}
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
    E = pd.DataFrame({k: eqs[k] for k in ['flagship', 'spy']}).resample('W-FRI').last().round(4); E.index.name = 'date'
    E.to_csv(os.path.join(a.out, 'equity.csv'))
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
               changes=changes, days={k: int(v) for k, v in reg.loc[START:].value_counts().items()},
               prices={k: round(float(X[k].iloc[-1]), 2) for k in ['SPY', 'QQQ', 'GLD', 'BTC']})
    json.dump(out, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, allow_nan=False, default=str)
    print(json.dumps({k: out[k] for k in ['asof', 'regime', 'weights', 'turnover']} | {'live': live and {k: live[k] for k in ['sessions', 'flagship', 'spy']}}))


if __name__ == '__main__':
    main()
