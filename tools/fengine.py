#!/usr/bin/env python3
"""Kerdos flagship multi-asset model — daily engine (stateless: recomputes everything from its inputs each run).

Usage: python3 tools/fengine.py --store store_daily.csv --macro macro_monthly.csv \
           --stocks stocks/history.csv --btc bitcoin/history.csv --out flagship

Rules (fixed in Oct 2026, before any live tracking):
  Regime from the US stocks desk:  Risk-On = Bullish / Neutral / Recovery;  Neutral = Correction;  Risk-Off = Bearish.
  Weights by regime (cash = the remainder, earning the 3-month T-bill):
      Risk-On   SPY 35%  QQQ 25%  Treasuries (IEF) 15%  Gold (GLD) 10%  Bitcoin 10%
      Neutral   SPY 20%  QQQ 10%  Treasuries 30%        Gold 15%        Bitcoin 5%
      Risk-Off  SPY 0    QQQ 0    Treasuries 45%        Gold 20%        Bitcoin 0
  The Bitcoin sleeve is scaled by the Bitcoin desk's exposure (100% / 50% / 0); before 2014, when the Bitcoin desk has no
  history, the Bitcoin sleeve is held in SPY. Positions follow the previous close's signals; the portfolio is rebalanced
  whenever a target changes and at each month start, at 0.05% per unit of turnover. Dividends and Treasury coupons are
  approximated (SPY 1.7%/yr, QQQ 0.7%/yr, IEF the 10-year yield less 0.2 pt).
Tested and rejected: holding Treasuries and gold only above their 200-day averages (more than twice the turnover and a lower
return for a 2-point smaller worst drawdown).
"""
import argparse, json, os
import numpy as np, pandas as pd

W = {
    'Risk-On':  dict(SPY=.35, QQQ=.25, IEF=.15, GLD=.10, BTC=.10),
    'Neutral':  dict(SPY=.20, QQQ=.10, IEF=.30, GLD=.15, BTC=.05),
    'Risk-Off': dict(SPY=.00, QQQ=.00, IEF=.45, GLD=.20, BTC=.00),
}
REG = {'Bullish': 'Risk-On', 'Neutral': 'Risk-On', 'Recovery': 'Risk-On', 'Correction': 'Neutral', 'Bearish': 'Risk-Off'}
BTC_E = {'Bullish': 1.0, 'Neutral': .5, 'Recovery': 1.0, 'Correction': .5, 'Bearish': 0.0}
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
    reg = X.stk_reg.map(REG)
    rows = []
    for t in X.index:
        r = reg[t]
        if pd.isna(r): rows.append(dict(CASH=1.0)); continue
        w = dict(W[r]); b = X.btc_reg[t]
        if not btc or pd.isna(b) or pd.isna(X.BTC[t]): w['SPY'] += w['BTC']; w['BTC'] = 0.0
        else: w['BTC'] *= BTC_E.get(b, 0)
        w['CASH'] = max(0.0, 1 - sum(w.values())); rows.append(w)
    return pd.DataFrame(rows, index=X.index).reindex(columns=ASSETS).fillna(0.0), reg


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
               weight_map=W, regime_map=REG, backtest=bt, yearly=yearly, turnover=turnover, live_since=LIVE, live=live,
               changes=changes, days={k: int(v) for k, v in reg.loc[START:].value_counts().items()},
               prices={k: round(float(X[k].iloc[-1]), 2) for k in ['SPY', 'QQQ', 'IEF', 'GLD', 'BTC']})
    json.dump(out, open(os.path.join(a.out, 'report.json'), 'w'), indent=1, allow_nan=False, default=str)
    print(json.dumps({k: out[k] for k in ['asof', 'regime', 'regime_since', 'weights', 'turnover']}))


if __name__ == '__main__':
    main()
