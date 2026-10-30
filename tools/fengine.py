#!/usr/bin/env python3
"""Kerdos flagship multi-asset model — daily engine (stateless: recomputes everything from its inputs each run).

Usage: python3 tools/fengine.py --store store_daily.csv --macro macro_monthly.csv \
           --stocks stocks/history.csv --btc bitcoin/history.csv --out flagship

Rules (version 2, fixed Oct 30 2026, before live tracking starts):
  Stocks sleeve 70%  = SPY 35% + QQQ 35%, scaled by the US stocks desk: 100% when Bullish / Neutral / Recovery,
                       50% in a Correction, 0 when Bearish.
  Bitcoin sleeve 20% = scaled by the Bitcoin desk: 100% when Bullish / Recovery, 50% when Neutral / Correction, 0 when Bearish.
                       Before 2014 (no Bitcoin desk history) it is added to the stocks sleeve.
  Gold 10%           = held at all times.
  Anything not invested sits in 3-month T-bills.
  Positions follow the previous close's signals; rebalance whenever a target changes and at each month start, at 0.05%
  per unit of turnover. Dividends are approximated (SPY 1.7%/yr, QQQ 0.7%/yr); IEF (60/40 benchmark only) earns the
  10-year yield less 0.2 pt.
Chosen from a 150+ portfolio study (Oct 2026) of index, sector, factor, international, leveraged, bond, commodity and
gold ETFs plus Bitcoin, timed by the same desks; see the flagship page's "How the mix was chosen".
Version 1 (Oct 2026, never tracked live) used regime weight tables with Treasuries, more cash and a 10% Bitcoin cap.
"""
import argparse, json, os
import numpy as np, pandas as pd

STOCKS = dict(SPY=.35, QQQ=.35)
BTC_W, GLD_W = .20, .10
STK_E = {'Bullish': 1.0, 'Neutral': 1.0, 'Recovery': 1.0, 'Correction': .5, 'Bearish': 0.0}
BTC_E = {'Bullish': 1.0, 'Neutral': .5, 'Recovery': 1.0, 'Correction': .5, 'Bearish': 0.0}
REG = {'Bullish': 'Risk-On', 'Neutral': 'Risk-On', 'Recovery': 'Risk-On', 'Correction': 'Neutral', 'Bearish': 'Risk-Off'}
ASSETS = ['SPY', 'QQQ', 'IEF', 'GLD', 'BTC', 'CASH']
DIV = dict(SPY=.017, QQQ=.007)
COST, START, LIVE = .0005, '2005-01-01', '2026-11-02'


def load(a):
    S = pd.read_csv(a.store, parse_dates=['date']).set_index('date')
    M = pd.read_csv(a.macro, parse_dates=['month']).set_index('month')
    H = pd.read_csv(a.stocks, parse_dates=['date']).set_index('date')
    B = pd.read_csv(a.btc, parse_dates=['date']).set_index('date')
    X = S[['SPY', 'QQQ', 'IEF', 'GLD']].dropna(subset=['SPY']).loc['2004-11-18':].ffill(limit=3)
    X = X[X.index <= H.index.max()]
    X['BTC'] = B.price.reindex(X.index, method='ffill')
    X['btc_reg'] = B.regime.reindex(X.index, method='ffill')
    X['stk_reg'] = H.regime.reindex(X.index).ffill()
    for c in ['TB3MS', 'GS10']:
        s = M[c].dropna(); s.index = s.index + pd.offsets.MonthEnd(0)
        X[c.lower()] = s.reindex(X.index, method='ffill').bfill() / 100
    return X


def returns(X):
    R = pd.DataFrame(index=X.index)
    for a in ['SPY', 'QQQ']: R[a] = X[a].pct_change() + DIV[a] / 252
    R['IEF'] = X.IEF.pct_change() + (X.gs10 - .002) / 252
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


def stats(eq, cash):
    r = eq.pct_change().dropna()
    if len(r) < 2: return None
    yrs = len(r) / 252; c = cash.reindex(r.index).fillna(0)
    return dict(cagr=round(float(eq.iloc[-1] ** (1 / yrs) - 1), 4) if yrs >= 1 else None, total=round(float(eq.iloc[-1] / eq.iloc[0] - 1), 4),
                vol=round(float(r.std() * np.sqrt(252)), 4), sharpe=round(float((r - c).mean() / r.std() * np.sqrt(252)), 2),
                maxdd=round(float((eq / eq.cummax() - 1).min()), 4), days=int(len(r)))


def bench(R, kind):
    T = pd.DataFrame(0.0, index=R.index, columns=ASSETS)
    if kind == 'spy': T['SPY'] = 1.0
    else: T['SPY'] = .6; T['IEF'] = .4
    return T


def main():
    ap = argparse.ArgumentParser()
    for k in ['store', 'macro', 'stocks', 'btc', 'out']: ap.add_argument('--' + k, required=True)
    a = ap.parse_args(); os.makedirs(a.out, exist_ok=True)
    X = load(a); R = returns(X)
    T, reg = targets(X); Tn, _ = targets(X, btc=False)
    curves = {'flagship': T, 'no_btc': Tn, 'spy': bench(R, 'spy'), 'sixty40': bench(R, '6040')}
    periods = {'2005–26': (START, None), '2005–14': (START, '2014-12-31'), '2015–26': ('2015-01-01', None)}
    bt, eqs, turnover = {}, {}, None
    for name, TT in curves.items():
        bt[name] = {}
        for lab, (s, e) in periods.items():
            eq, to = simulate(TT, R, s, e); bt[name][lab] = stats(eq, R.CASH)
            if lab == '2005–26': eqs[name] = eq; turnover = round(to, 2) if name == 'flagship' else turnover
    live = {}
    if X.index.max() >= pd.Timestamp(LIVE):
        for name, TT in curves.items():
            eq, _ = simulate(TT, R, LIVE); live[name] = stats(eq, R.CASH)
    E = pd.DataFrame(eqs).resample('W-FRI').last().round(4); E.index.name = 'date'
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
    out = dict(asof=str(t.date()), generated=pd.Timestamp.now('UTC').strftime('%Y-%m-%d %H:%M UTC'),
               regime=reg[t], regime_since=str(since.date()), stocks_regime=X.stk_reg[t], btc_regime=X.btc_reg[t],
               weights={k: round(float(T.loc[t, k]), 4) for k in ASSETS}, equity_weight=round(float(T.loc[t, 'SPY'] + T.loc[t, 'QQQ']), 4),
               rules=dict(stocks=STOCKS, btc=BTC_W, gold=GLD_W, stocks_exposure=STK_E, btc_exposure=BTC_E), regime_map=REG, version=2, backtest=bt, yearly=yearly, turnover=turnover, live_since=LIVE, live=live,
               changes=changes, days={k: int(v) for k, v in reg.loc[START:].value_counts().items()},
               prices={k: round(float(X[k].iloc[-1]), 2) for k in ['SPY', 'QQQ', 'IEF', 'GLD', 'BTC']})
    json.dump(out, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, allow_nan=False, default=str)
    print(json.dumps({k: out[k] for k in ['asof', 'regime', 'regime_since', 'weights', 'turnover']}))


if __name__ == '__main__':
    main()
