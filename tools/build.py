#!/usr/bin/env python3
"""Post-sync build for kerdoscapital.xyz.

Run from the repository root after the daily sync has mirrored the claude.ai artifact:
    python3 tools/build.py

What it does (idempotent: running it twice gives the same files):
  1. index.html  - strips the document wrappers the artifact service adds, so <title>, meta, links and styles
                   sit in a real <head>.
  2. every page  - one managed block in <head>: favicon, canonical URL, description, Open Graph / Twitter tags,
                   theme colour; consistent titles; the site's web fonts; one canonical nav (with the GitHub link)
                   and one canonical footer (with the disclosures), so every page shares them.
  3. first paint - today's numbers are written into the HTML (key figures, desk cards, portfolio card, track
                   record, page summaries), so the page shows real content before JavaScript loads and search
                   engines can read it. The page scripts still replace these with the full, live versions.
  4. pages       - about.html, flagship.html and methodology.html share the overview's head, nav and footer.
  5. assets      - og.png (share card with today's calls), robots.txt, sitemap.xml, favicons (K monogram).
Only the Python standard library and Pillow are needed. The share card uses the site's fonts when npm can fetch
them and falls back to system fonts otherwise.
"""
import html, json, os, re, sys, subprocess, tarfile, tempfile, datetime as dt

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
SITE = 'https://kerdoscapital.xyz'
NAME = 'Kerdos Capital'
TAG = 'Independent Quantitative Investment Research'
GH = 'https://github.com/kerdoscapital/kerdos-site'
FONTS_CSS = ('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400'
             '&family=Instrument+Serif:ital@0;1&display=swap')
BG, INK, INK2, MUTED, SAGE, RED, PANEL, HAIR = '#111315', '#E7E4DC', '#858B90', '#858B90', '#B9A98A', '#A9705F', '#191C1F', '#2A2E32'
PAGES = {   # file: (title, description, nav label)
    'index.html': (f'{NAME} · {TAG}',
                   'A systematic approach to navigating the markets: the Kerdos flagship model portfolio of US stocks, Bitcoin and gold, tracked live against the S&P 500, and the rules-based regime models behind it, updated daily.', 'Overview'),
    'flagship.html': (f'Flagship Portfolio · {NAME}',
                      'The Kerdos flagship model portfolio: 60% US stocks, 30% Bitcoin and 10% gold, sized daily by the Kerdos regime desks, with a live record since Oct 26, 2026 and a backtest against the S&P 500.', 'Flagship Portfolio'),
    'stocks.html': (f'US Stocks Desk · {NAME}',
                    'Daily regime model for US stocks (SPY and QQQ): trend, momentum, internals, macro and volatility, with a backtest since 2003.', 'Stocks'),
    'bitcoin.html': (f'Bitcoin Desk · {NAME}',
                     'Daily regime model for Bitcoin: trend, momentum and macro signals, with a backtest since 2015.', 'Bitcoin'),
    'highbeta.html': (f'High Beta Desk · {NAME}',
                      'Daily model for the 25 highest-beta Nasdaq-100 stocks, a satellite sleeve outside the flagship portfolio, with a backtest against holding the basket and QQQ.', 'High Beta'),
    'methodology.html': (f'Methodology · {NAME}',
                         'How the Kerdos models work: the inputs they read, how a score becomes a state and a position, how risk is managed, when they update, the signal archive and their limits.', 'Methodology'),
    'about.html': (f'About · {NAME}',
                   'What Kerdos Capital is, why it publishes its research in the open, how its models are built and run, and what it is not.', 'About'),
}
NAV_ORDER = ['index.html', 'flagship.html', 'stocks.html', 'bitcoin.html', 'highbeta.html', 'methodology.html', 'about.html']
RETIRED = {'portfolio.html': 'flagship.html'}   # old pages kept as redirects so outside links still work
MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
E = lambda s: html.escape(str(s), quote=True)


def p(*a): return os.path.join(ROOT, *a)
def exists(f): return os.path.exists(p(f))
def rd(f): return open(p(f), encoding='utf-8').read()
def wr(f, s): open(p(f), 'w', encoding='utf-8').write(s)
def jload(f):
    try: return json.load(open(p(f), encoding='utf-8'))
    except Exception: return None
def fmt_d(s):
    t = dt.date.fromisoformat(s[:10]); return f'{MON[t.month - 1]} {t.day}, {t.year}'
def sg(v, d=1):
    if v is None: return '—'
    r = round(float(v), d); return ('+' if r > 0 else '−' if r < 0 else '') + f'{abs(r):.{d}f}%'
def usd(v, d=2): return '—' if v is None else '$' + f'{float(v):,.{d}f}'


# ---------------------------------------------------------------- 1. clean the artifact wrapper off index.html
WRAP = re.compile(r'<!doctype html><html><head><meta charset=utf8><meta name=viewport[^>]*><style>:root\{color-scheme:light;.*?</style>(?:</head><body>)?', re.S | re.I)
BASE_STYLE = ('<style>:root{box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
              'html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;padding:0}img{max-width:100%}'
              '[hidden]:not([hidden=until-found i]){display:none!important}</style>')


def unwrap(s):
    if not WRAP.search(s): return s
    s = WRAP.sub('', s)
    s = re.sub(r'</?(?:html|head|body)\b[^>]*>', '', s, flags=re.I)
    s = re.sub(r'<!doctype html>', '', s, flags=re.I).strip()
    head, rest = [], s
    pat = re.compile(r'\s*(<title>.*?</title>|<meta\b[^>]*>|<link\b[^>]*>|<style\b[^>]*>.*?</style>)', re.S | re.I)
    while True:
        m = pat.match(rest)
        if not m: break
        head.append(m.group(1)); rest = rest[m.end():]
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
            + BASE_STYLE + '\n' + '\n'.join(head) + '\n</head>\n<body>\n' + rest.strip() + '\n</body>\n</html>\n')


# ---------------------------------------------------------------- 2. head block, titles, nav
def head_block(f, img_v):
    title, desc, _ = PAGES[f]
    url = SITE + '/' + ('' if f == 'index.html' else f)
    return f'''<!--kerdos-head-->
<link rel="icon" href="favicon.svg" type="image/svg+xml">
<link rel="icon" href="favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="canonical" href="{url}">
<meta name="theme-color" content="#111315">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{NAME}">
<meta property="og:title" content="{E(title)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/og.png?v={img_v}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{E(title)}">
<meta name="twitter:description" content="{E(desc)}">
<meta name="twitter:image" content="{SITE}/og.png?v={img_v}">
<!--/kerdos-head-->'''


MONO = ('<svg class="k-mono" viewBox="0 0 64 64" aria-hidden="true"><rect x="1" y="1" width="62" height="62" fill="none" stroke="currentColor" stroke-opacity=".3" stroke-width="2"/>'
        '<path d="M23 16V48" fill="none" stroke="currentColor" stroke-width="4"/><path class="k-mk" d="M44 16L29 32L44 48" fill="none" stroke-width="4" stroke-linejoin="miter"/></svg>')
GH_SVG = ('<svg viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')
MENU = ('<button class="k-menu-btn" type="button" aria-label="Menu" aria-expanded="false"><svg viewBox="0 0 18 18" aria-hidden="true">'
        '<path d="M3 6h12M3 12h12" stroke="currentColor" stroke-width="1.4" stroke-linecap="square"/></svg></button>')


def nav_links(cur, cls_attr):
    out = []
    for f in NAV_ORDER:
        if not exists(f): continue
        a = ' aria-current="page"' if (f == cur and cls_attr == 'site') else ''
        out.append(f'<a href="{f}"{a}>{PAGES[f][2]}</a>')
    return ''.join(out)


def header(cur):
    return (f'<header class="k-nav"><div class="k-bar"><a class="k-word" href="index.html" aria-label="Kerdos Capital, overview">{MONO}<span class="k-wt">Kerdos Capital</span></a>'
            f'<div class="k-right"><nav class="k-links" aria-label="Site"><span class="k-ind" aria-hidden="true"></span>{nav_links(cur, "site")}</nav>'
            f'<a class="k-gh" href="{GH}" rel="noopener" aria-label="Kerdos Capital on GitHub: source and model history">{GH_SVG}<span>GitHub</span></a>{MENU}</div></div></header>')


def footer(asof, live_since):
    year = dt.date.today().year
    ls = fmt_d(live_since) if live_since else None
    col = lambda title, links: (f'<div class="kf-col"><span class="label">{title}</span>' + ''.join(f'<a href="{h}"{r}>{t}</a>' for t, h, r in links) + '</div>')
    research = [(PAGES[f][2], f, '') for f in ['index.html', 'flagship.html', 'stocks.html', 'bitcoin.html', 'highbeta.html'] if exists(f)]
    firm = [('Methodology', 'methodology.html', ''), ('Signal archive', 'methodology.html#archive', ''), ('Model limitations', 'methodology.html#limits', ''), ('About', 'about.html', '')]
    open_ = [('GitHub repository', GH, ' rel="noopener"'), ('Daily update history', GH + '/commits/main', ' rel="noopener"'), ('Contact &amp; corrections', GH + '/issues', ' rel="noopener"')]
    live = (f' The flagship portfolio’s live record began at the open on {E(ls)}; every result before that date is a backtest.' if ls else '')
    stamp = f'Models as of the {E(fmt_d(asof))} close' if asof else 'Models update daily'
    return (f'<footer class="foot pub">\n    <div class="kf-top">'
            f'<div class="kf-brand"><a class="k-word" href="index.html" aria-label="Kerdos Capital, overview">{MONO}<span class="k-wt">Kerdos Capital</span></a>'
            f'<p class="k-pos">Transparency over promises. <i>Methodology over speculation.</i> Discipline over emotion.</p></div>'
            f'<nav class="kf-col fl" aria-label="Footer"><span class="label">Research</span>' + ''.join(f'<a href="{h}">{t}</a>' for t, h, _ in research) + '</nav>'
            + col('Method', firm) + col('In the open', open_) + '</div>\n'
            '    <div class="disc">\n'
            '      <p><b>Important information.</b> Kerdos Capital is an independent research project that publishes rules-based market models for education and discussion. '
            'It is not a registered investment adviser or broker-dealer. Nothing on this site is investment, tax or legal advice, or a recommendation to buy or sell any security or digital asset. '
            'The model portfolio is hypothetical: it manages no money, and its daily changes are not instructions to trade.</p>\n'
            '      <p><b>Hypothetical performance.</b> Backtested results are hypothetical and are not the returns of any investor. They were computed with hindsight, from rules chosen with that history in view, '
            'and they leave out taxes and most real-world trading frictions.' + live + ' Past and backtested performance does not guarantee future results. '
            'Bitcoin and high-beta stocks are highly volatile, and any investment can lose money. Do your own research, or speak with a licensed professional, before investing.</p>\n'
            '      <p><b>Data and timing.</b> Robinhood (prices, index levels, options open interest), FRED, Robert Shiller’s dataset, Coin Metrics, and the CME CF Bitcoin Real Time Index via Robinhood. '
            'Prices may be delayed or contain errors. Each model runs once a day on the latest completed session’s closing data, and this site refreshes once a day, by about 10:00 a.m. ET.</p>\n'
            '    </div>\n'
            f'    <div class="kf-base"><span>© {year} Kerdos Capital. Independent research.</span><span>{stamp} · Hypothetical models, not investment advice</span></div>\n'
            '  </footer>')


FOOT = (None, None)   # (asof, flagship live_since), set in main()


def fix_page(f, s, img_v):
    s = unwrap(s)
    title, desc, _ = PAGES[f]
    s = re.sub(r'<title>.*?</title>', f'<title>{E(title)}</title>', s, count=1, flags=re.S)
    if '<title>' not in s: s = s.replace('</head>', f'<title>{E(title)}</title>\n</head>', 1)
    if re.search(r'<meta name="description"[^>]*>', s):
        s = re.sub(r'<meta name="description"[^>]*>', f'<meta name="description" content="{E(desc)}">', s, count=1)
    else:
        s = s.replace('</head>', f'<meta name="description" content="{E(desc)}">\n</head>', 1)
    s = re.sub(r'\n?<!--kerdos-head-->.*?<!--/kerdos-head-->', '', s, flags=re.S)
    s = s.replace('</head>', head_block(f, img_v) + '\n</head>', 1)
    # one canonical nav and footer on every page
    s = re.sub(r'<header class="k-nav">.*?</header>', lambda m: header(f), s, count=1, flags=re.S)
    s = re.sub(r'<footer class="foot pub">.*?</footer>', lambda m: footer(*FOOT), s, count=1, flags=re.S)
    # the site's web fonts
    s = re.sub(r'<link rel="stylesheet" href="https://fonts\.googleapis\.com/css2\?[^"]*">', f'<link rel="stylesheet" href="{FONTS_CSS}">', s)
    return s


# ---------------------------------------------------------------- 3. pre-rendered numbers
def pre_block(id_, inner):
    return f'<!--pre:{id_}-->{inner}<!--/pre:{id_}-->'


def put_inside(s, open_tag_re, id_, inner):
    """Replace the contents of the element whose opening tag matches open_tag_re (first match) with inner.
    Works on empty containers and on containers that hold an earlier pre-render."""
    m = re.search(open_tag_re, s)
    if not m: return s
    start = m.end()
    pre = re.compile(r'<!--pre:' + re.escape(id_) + r'-->.*?<!--/pre:' + re.escape(id_) + r'-->', re.S)
    m2 = pre.match(s, start)
    end = m2.end() if m2 else start
    return s[:start] + pre_block(id_, inner) + s[end:]


def flag_card(F):
    w, RU, b, sp, L = F['weights'], F['rules'], F['backtest']['flagship']['2005–26'], F['backtest']['spy']['2005–26'], F.get('live')
    p1 = lambda v, d=1: ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(v) * 100:.{d}f}%'
    mix = f"{round((RU['stocks']['SPY'] + RU['stocks']['QQQ']) * 100)}% stocks · {round(RU['btc'] * 100)}% Bitcoin · {round(RU['gold'] * 100)}% gold"
    names = dict(SPY='SPY', QQQ='QQQ', BTC='Bitcoin', GLD='Gold', CASH='T-bills')
    leg = ''.join(f'<span>{names[k]} {round(w[k] * 100)}%</span>' for k in ['SPY', 'QQQ', 'BTC', 'GLD', 'CASH'] if w.get(k, 0) > 0)
    live = (f'<div><span>Since inception · Flagship</span><b>{p1(L["flagship"]["total"], 2)}</b><em>from the {E(fmt_d(L["since"]))} open</em></div>'
            f'<div><span>Since inception · S&amp;P 500</span><b>{p1(L["spy"]["total"], 2)}</b><em>to the {E(fmt_d(L["asof"]))} close</em></div>') if L else ''
    return (f'<div class="col"><div class="mix">{mix}</div><div class="big">{round((1 - w["CASH"]) * 100)}% invested</div><div class="leg">{leg}</div>'
            f'<div class="sub">Stocks desk <b>{E(st3(F["stocks_regime"], RU.get("stocks_exposure")))}</b> · Bitcoin desk <b>{E(st3(F.get("btc_regime"), RU.get("btc_exposure")) or "—")}</b> · as of the {E(fmt_d(F["asof"]))} close</div>'
            f'<a class="go" href="flagship.html">Open the flagship portfolio <span aria-hidden="true">→</span></a></div>'
            f'<div class="col"><div class="kv">{live}<div><span>Backtest 2005–26 · per year</span><b>{b["cagr"] * 100:.1f}%</b><em>S&amp;P 500 {sp["cagr"] * 100:.1f}%</em></div>'
            f'<div><span>Backtest · worst drop</span><b>−{abs(b["maxdd"]) * 100:.0f}%</b><em>S&amp;P 500 −{abs(sp["maxdd"]) * 100:.0f}%</em></div></div></div>')


def kpis(F):
    b, sp, L, w = F['backtest']['flagship']['2005–26'], F['backtest']['spy']['2005–26'], F.get('live'), F['weights']
    pf = lambda v: ('−' if v < 0 else '') + f'{abs(v) * 100:.1f}%'
    p1 = lambda v, d=2: ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(v) * 100:.{d}f}%'
    ud = lambda v: 'up' if v > 0 else 'dn' if v < 0 else ''
    live = (f'<div class="k-kpi"><span>Live since {E(fmt_d(L["since"])[:-6])}</span><b class="{ud(L["flagship"]["total"])}">{p1(L["flagship"]["total"])}</b>'
            f'<em>S&amp;P 500 {p1(L["spy"]["total"])} · {L["sessions"]} session{"" if L["sessions"] == 1 else "s"}</em></div>') if L else ''
    return (f'<div class="k-kpi"><span>Annualized return</span><b>{pf(b["cagr"])}</b><em>Backtest 2005–26 · S&amp;P 500 {pf(sp["cagr"])}</em></div>'
            f'<div class="k-kpi"><span>Maximum drawdown</span><b>−{abs(b["maxdd"]) * 100:.0f}%</b><em>Backtest 2005–26 · S&amp;P 500 −{abs(sp["maxdd"]) * 100:.0f}%</em></div>'
            + live +
            f'<div class="k-kpi"><span>Invested today</span><b>{round((1 - w["CASH"]) * 100)}%</b><em>as of the {E(fmt_d(F["asof"]))} close</em></div>'
            '<p class="k-fine">Backtests are hypothetical and not investor returns. Past performance does not guarantee future results.</p>')


def prerender_index(s, M, B, G, FL):
    if M and B:
        s = re.sub(r'(<div class="[^"]*" id="asof">)[^<]*(</div>)',
                   lambda m: m.group(1) + E(f'Models as of the {fmt_d(M["asof"])} close' if M['asof'] == B['asof'] else f'Stocks as of {fmt_d(M["asof"])} · Bitcoin as of {fmt_d(B["asof"])}') + m.group(2), s, count=1)
    cards = []
    def card(name, reg, expo, since, quote, href, short):
        return (f'<article class="desk"><div class="top"><h2>{E(name)}</h2></div><div><div class="call c-{E(reg)}">{E(reg)}</div></div>'
                f'<div class="expo"><span>Exposure</span><b>{round(expo * 100)}%</b><span>since {E(fmt_d(since))}</span></div>'
                f'<div class="meter" aria-hidden="true"><i style="width:{expo * 100:.0f}%"></i></div><div class="quotes">{quote}</div>'
                f'<a class="go" href="{href}">Open the {short} desk <span aria-hidden="true">→</span></a></article>')
    q = lambda tk, px, d1: f'<div class="q"><div class="tk">{tk}</div><div class="px">{px}</div><div class="ch"><span>{sg(d1)} 1d</span></div></div>'
    if M: cards.append(card('US stocks · SPY & QQQ', st3(M['regime'], M.get('exposure_map')), M['exposure'], st_since('stocks/history.csv', M.get('exposure_map')) or M['regime_since'], q('SPY', usd(M['spy']), M['spy_chg']['d1']) + q('QQQ', usd(M['qqq']), M['qqq_chg']['d1']), 'stocks.html', 'stocks'))
    if B: cards.append(card('Bitcoin', st3(B['regime'], B.get('exposure_map')), B['exposure'], st_since('bitcoin/history.csv', B.get('exposure_map')) or B['regime_since'], q('BTC', usd(B.get('price'), 0), B.get('chg1')), 'bitcoin.html', 'Bitcoin'))
    if G: cards.append(card('High beta · satellite sleeve', st3(G['regime'], G.get('exposure_map')), G['exposure'], st_since('highbeta/history.csv', G.get('exposure_map')) or G['regime_since'], q('Basket', f"{G['level']:.2f}", (G.get('chg') or {}).get('d1', 0) * 100), 'highbeta.html', 'high-beta'))
    if cards: s = put_inside(s, r'<section class="desks" id="desks"[^>]*>', 'desks', ''.join(cards))
    if FL:
        s = put_inside(s, r'<article class="desk feat-card" id="flagcard">', 'flagcard', flag_card(FL))
        try: s = put_inside(s, r'<div class="k-kpis" id="kpis">', 'kpis', kpis(FL))
        except Exception as e: print('kpis skipped:', e)
    if M and B:
        pc = lambda v: f'{v * 100:.1f}%'
        pcs = lambda v: ('−' if v < 0 else '') + f'{abs(v) * 100:.0f}%'
        row = lambda n, a, b: f'<tr><td>{n}</td><td class="n hl">{pc(a["cagr"])}</td><td class="n">{pc(b["cagr"])}</td><td class="n hl">{pcs(a["maxdd"])}</td><td class="n">{pcs(b["maxdd"])}</td><td class="n">{a["sharpe"]:.2f} / {b["sharpe"]:.2f}</td></tr>'
        rows = row('SPY since 2003', M['backtest']['SPY']['strategy'], M['backtest']['SPY']['buyhold']) + row('QQQ since 2003', M['backtest']['QQQ']['strategy'], M['backtest']['QQQ']['buyhold'])
        try: rows += row('Bitcoin since 2015', B['backtest']['strategy'], B['backtest']['buyhold'])
        except Exception: pass
        rec = ('<table><thead><tr><th>Asset</th><th class="n">Model / yr</th><th class="n">Buy & hold / yr</th><th class="n">Model worst drop</th>'
               '<th class="n">Buy & hold worst</th><th class="n">Sharpe</th></tr></thead><tbody>' + rows + '</tbody></table>')
        s = put_inside(s, r'<div class="tblwrap" id="record">', 'record', rec)
    return s


def prerender_loading(s, text):
    return re.sub(r'(<div class="loading" id="loading">)(?:<!--pre:loading-->.*?<!--/pre:loading-->|[^<]*)',
                  lambda m: m.group(1) + pre_block('loading', text), s, count=1, flags=re.S)


def summary_line(label, reg, expo, extra, asof):
    return (f'<span style="display:block;font-size:1.05rem;color:var(--ink,#d1d4dc)"><b>{E(label)}: {E(reg)}</b> · {round(expo * 100)}% invested · {extra}</span>'
            f'<span style="display:block;margin-top:6px">As of the {E(fmt_d(asof))} close. Loading the full report…</span>')


# ---------------------------------------------------------------- 4. assets
def font(paths, size):
    from PIL import ImageFont
    for f in paths:
        if os.path.exists(f): return ImageFont.truetype(f, size)
    return ImageFont.load_default()


FONT_CACHE = os.path.join(tempfile.gettempdir(), 'kerdos-fonts')
WEBFONTS = {   # npm package: files used for the share card
    'instrument-serif': ['instrument-serif-latin-400-normal.woff2', 'instrument-serif-latin-400-italic.woff2'],
    'ibm-plex-mono': ['ibm-plex-mono-latin-400-normal.woff2', 'ibm-plex-mono-latin-500-normal.woff2'],
    'ibm-plex-sans': ['ibm-plex-sans-latin-400-normal.woff2', 'ibm-plex-sans-latin-500-normal.woff2'],
}


def webfont(pkg, name):
    """Path to a site font for Pillow, fetched once with `npm pack @fontsource/<pkg>`; None if unavailable."""
    path = os.path.join(FONT_CACHE, pkg, name)
    if os.path.exists(path): return path
    try:
        os.makedirs(FONT_CACHE, exist_ok=True)
        r = subprocess.run(['npm', 'pack', f'@fontsource/{pkg}@5', '--silent'], cwd=FONT_CACHE, capture_output=True, text=True, timeout=120)
        tgz = os.path.join(FONT_CACHE, r.stdout.strip().splitlines()[-1])
        with tarfile.open(tgz) as t:
            for m in t.getmembers():
                if m.name.startswith('package/files/') and m.name.rsplit('/', 1)[-1] in WEBFONTS[pkg]:
                    m.name = m.name.rsplit('/', 1)[-1]
                    try: t.extract(m, os.path.join(FONT_CACHE, pkg), filter='data')
                    except TypeError: t.extract(m, os.path.join(FONT_CACHE, pkg))
        os.remove(tgz)
    except Exception as e:
        print('font fetch skipped:', pkg, e)
    return path if os.path.exists(path) else None


SERIF = [('instrument-serif', 'instrument-serif-latin-400-normal.woff2'), '/usr/share/fonts/truetype/google-fonts/Lora-Variable.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf']
SERIF_I = [('instrument-serif', 'instrument-serif-latin-400-italic.woff2'), '/usr/share/fonts/truetype/google-fonts/Lora-Italic-Variable.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf']
SANS_M = [('ibm-plex-sans', 'ibm-plex-sans-latin-500-normal.woff2'), '/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
SANS_R = [('ibm-plex-sans', 'ibm-plex-sans-latin-400-normal.woff2'), '/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
MONO_F = [('ibm-plex-mono', 'ibm-plex-mono-latin-400-normal.woff2'), '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']
COL = {'Bullish': SAGE, 'Neutral': INK2, 'Bearish': RED}


def font(cands, size):
    from PIL import ImageFont
    for c in cands:
        f = webfont(*c) if isinstance(c, tuple) else (c if os.path.exists(c) else None)
        if not f: continue
        try: return ImageFont.truetype(f, size)
        except Exception: continue
    return ImageFont.load_default()


def st3(reg, mp):
    """The site's three display states, by exposure: Bullish 100%, Neutral 50%, Bearish 0%."""
    e = (mp or {}).get(reg)
    if e is None: return reg
    return 'Bullish' if e >= .99 else 'Neutral' if e > 0 else 'Bearish'


def st_since(path, mp):
    """Date the current display state began, from a desk's history.csv (columns include date and regime)."""
    try:
        lines = open(p(path), encoding='utf-8').read().strip().splitlines()
        hd = lines[0].split(','); di, ri = hd.index('date'), hd.index('regime')
        rows = [(c[di], st3(c[ri], mp)) for c in (l.split(',') for l in lines[1:]) if len(c) > ri and c[ri]]
        i = len(rows) - 1
        while i > 0 and rows[i - 1][1] == rows[-1][1]: i -= 1
        return rows[i][0]
    except Exception:
        return None


# K monogram: a stem and a chevron that stops short of it; ivory stem, sage chevron
ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="8" fill="#111315"/>'
            '<path d="M22 14V50" fill="none" stroke="#E7E4DC" stroke-width="7"/>'
            '<path d="M45 14L28 32L45 50" fill="none" stroke="#B9A98A" stroke-width="7" stroke-linejoin="miter" stroke-miterlimit="10"/></svg>')


def k_img(n, pad=0.0, bg=True):
    """The K monogram as a Pillow image (drawn at 4x, then scaled down): stem 22, chevron 45 -> 28 -> 45 on a 64 grid."""
    import math
    from PIL import Image, ImageDraw
    S = 4; N = n * S; im = Image.new('RGBA', (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if bg: d.rounded_rectangle([0, 0, N - 1, N - 1], radius=int(8 / 64 * N), fill=BG)
    s = N / 64 * (1 - 2 * pad); o = N * pad
    P = lambda x, y: (o + x * s, o + y * s)
    d.polygon([P(18.5, 14), P(25.5, 14), P(25.5, 50), P(18.5, 50)], fill=INK)
    h = 3.5 / math.sin(math.atan2(18, 17))   # stroke half-width measured along x for the diagonals
    d.polygon([P(45 - h, 14), P(45 + h, 14), P(28 + h, 32), P(45 + h, 50), P(45 - h, 50), P(28 - h, 32)], fill=SAGE)
    return im.resize((n, n), Image.LANCZOS)


def make_icons():
    from PIL import Image
    wr('favicon.svg', ICON_SVG)
    k_img(256).save(p('favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
    big = Image.new('RGB', (180, 180), BG); m = k_img(180, pad=.14, bg=False); big.paste(m, (0, 0), m); big.save(p('apple-touch-icon.png'))


def make_og(M, B, G, FL, k_img=None):
    from PIL import Image, ImageDraw
    W, H = 1200, 630
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    for x in range(0, W, 60): d.line([(x, 0), (x, H)], fill='#16191C')     # faint architectural grid
    for y in range(0, H, 60): d.line([(0, y), (W, y)], fill='#16191C')
    if k_img:
        ic = k_img(56, pad=0, bg=False); im.paste(ic, (72, 62), ic)
    d.text((144, 66), 'Kerdos Capital', font=font(SERIF, 40), fill=INK)
    d.text((72, 150), 'A systematic approach', font=font(SERIF, 78), fill=INK)
    d.text((72, 232), 'to navigating the markets.', font=font(SERIF_I, 78), fill=INK2)
    rows = []
    if FL: rows.append(('Flagship portfolio', f"{round((1 - FL.get('weights', {}).get('CASH', 0)) * 100)}% invested", None))
    if M: rows.append(('US stocks', st3(M['regime'], M.get('exposure_map')), f"{round(M['exposure'] * 100)}%"))
    if B: rows.append(('Bitcoin', st3(B['regime'], B.get('exposure_map')), f"{round(B['exposure'] * 100)}%"))
    if G: rows.append(('High beta', st3(G['regime'], G.get('exposure_map')), f"{round(G['exposure'] * 100)}%"))
    y = 362; d.line([(72, y), (W - 72, y)], fill='#3A3F43')
    cw = (W - 144) // max(1, len(rows[:4]))
    for i, (name, reg, ex) in enumerate(rows[:4]):
        x = 72 + i * cw
        if i: d.line([(x - 20, y + 24), (x - 20, y + 150)], fill=HAIR)
        d.text((x, y + 28), name.upper(), font=font(SANS_M, 17), fill=MUTED)
        d.text((x, y + 60), reg, font=font(SERIF, 54 if len(reg) < 10 else 44), fill=COL.get(reg, INK))
        if ex: d.text((x, y + 128), f'{ex} invested', font=font(MONO_F, 20), fill=INK2)
    asof = fmt_d(M['asof']) if M else ''
    d.line([(72, H - 78), (W - 72, H - 78)], fill=HAIR)
    d.text((72, H - 56), f'kerdoscapital.xyz  ·  as of the {asof} close  ·  hypothetical models, not investment advice', font=font(MONO_F, 18), fill=MUTED)
    im.save(p('og.png'), optimize=True)


def make_about(index_html):
    """about.html shares the overview's head, nav and footer; its body comes from tools/about_body.html."""
    body = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'about_body.html'), encoding='utf-8').read()
    i_nav = index_html.find('class="k-nav"'); i_end = index_html.find('</header>', i_nav) + len('</header>')
    i_ft = index_html.find('<footer class="foot pub">'); i_fe = index_html.find('</footer>', i_ft) + len('</footer>')
    if min(i_nav, i_ft) < 0: return None
    extra = ''
    head_end = index_html.find('</head>')
    return (index_html[:head_end] + extra + index_html[head_end:i_end] + '\n' + body + '\n  ' + index_html[i_ft:i_fe] + '\n</div>\n</body>\n</html>\n')


def make_shell_page(index_html, body_name, fallback=None):
    """A page with the overview's head, nav and footer and its own body (tools/<body_name>, else the fallback text)."""
    bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), body_name)
    body = open(bp, encoding='utf-8').read() if os.path.exists(bp) else fallback
    if body is None: return None
    i_nav = index_html.find('class="k-nav"'); i_end = index_html.find('</header>', i_nav) + len('</header>')
    i_ft = index_html.find('<footer class="foot pub">'); i_fe = index_html.find('</footer>', i_ft) + len('</footer>')
    if min(i_nav, i_ft) < 0: return None
    return index_html[:i_end] + '\n' + body + '\n  ' + index_html[i_ft:i_fe] + '\n</div>\n</body>\n</html>\n'


# Body of methodology.html (a file at tools/methodology_body.html, if present, takes its place).
METHOD_BODY = r'''  <section class="intro">
    <div class="label">Methodology</div>
    <h1>How the models <em>make a call.</em></h1>
    <p>Every Kerdos desk follows the same discipline: read published market and economic data after the close, turn it into a score, map the score to one of three states, and size exposure from the state. There are no discretionary overrides. This page explains each step, what each desk reads, how risk is managed, when the models update, and where the method falls short.</p>
    <div><span class="hyp">Hypothetical models · not investment advice</span></div>
  </section>

  <section class="sec" id="process" aria-label="The process">
    <div class="k-sh"><div><span class="eyebrow">01 · The process</span><h2>From data to a position</h2></div><p>The stocks and Bitcoin desks run these five steps every day. The high-beta desk starts from the stocks desk’s state and applies its own risk rules on top.</p></div>
    <div class="k-flow">
      <div><span class="n">01</span><b>Data</b><p>Closing prices, index levels and published economic series: Robinhood, FRED, Robert Shiller’s long-run S&amp;P data, Coin Metrics.</p></div>
      <div><span class="n">02</span><b>Factors</b><p>Each input becomes a signal between −1 and +1: trend, momentum, internals, macro, volatility, valuation, calendar and cycle.</p></div>
      <div><span class="n">03</span><b>Score</b><p>Signals are averaged within groups, the groups are weighted into one composite score, and the score is smoothed over 5 days.</p></div>
      <div><span class="n">04</span><b>State</b><p>Thresholds map the score to Bullish, Neutral or Bearish. A new signal needs 3 straight days, to cut whipsaw.</p></div>
      <div><span class="n">05</span><b>Exposure</b><p>Bullish holds 100%, Neutral 50%, Bearish 0%. Money not invested earns the 3-month T-bill rate.</p></div>
    </div>
  </section>

  <section class="sec" id="desks" aria-label="The desks">
    <div class="k-sh"><div><span class="eyebrow">02 · The desks</span><h2>What each model reads</h2></div><p>Group weights are read from each desk’s latest report. They were set from the research before backtesting, not optimised.</p></div>
    <div class="k-desks3">
      <article class="panel"><span class="label">US stocks · SPY &amp; QQQ</span><h3>Stocks desk</h3>
        <p>Twenty-four factors in six groups. A score below −0.10 is a cut signal; it goes to cash only when the macro group confirms it, otherwise to half. Two early re-entry rules buy back after sell-offs before the score turns.</p>
        <div class="k-wbar" id="w-stocks"><p class="note">Loading weights…</p></div>
        <a class="k-tl" href="stocks.html#method">Full method and data <span aria-hidden="true">→</span></a></article>
      <article class="panel"><span class="label">Bitcoin</span><h3>Bitcoin desk</h3>
        <p>Eighteen factors in five groups. Above +0.20 is Bullish, below −0.15 Bearish, in between Neutral. Bottoming rules apply once Bitcoin is 50% or more below its high, and a top signal caps exposure at half.</p>
        <div class="k-wbar" id="w-btc"><p class="note">Loading weights…</p></div>
        <a class="k-tl" href="bitcoin.html#method">Full method and data <span aria-hidden="true">→</span></a></article>
      <article class="panel"><span class="label">Satellite sleeve</span><h3>High-beta desk</h3>
        <p>The 25 Nasdaq-100 stocks with the highest beta to QQQ over two years, equal weight, re-ranked each quarter. It takes the stocks desk’s state, then its own rules can cut it further; the lowest exposure wins. It is not part of the flagship.</p>
        <dl class="k-dl"><div><dt>Half (50%)</dt><dd>The basket is clearly lagging the S&amp;P 500, or falls 12% or more in 10 sessions.</dd></div><div><dt>None (0%)</dt><dd>The stocks desk is Bearish, or the basket closes below its 200-day average while the stock score is not firmly positive.</dd></div></dl>
        <a class="k-tl" href="highbeta.html">Open the high-beta desk <span aria-hidden="true">→</span></a></article>
    </div>
  </section>

  <section class="sec" id="allocation" aria-label="Allocation">
    <div class="k-split"><h2><small>03 · Allocation</small>How the flagship is sized</h2>
      <div style="display:grid;gap:20px;min-width:0">
        <div class="k-prose"><p>The flagship portfolio adds no forecasting signals of its own. It holds fixed target sleeves and lets the desks scale them: the stocks desk sizes the stock sleeve, the Bitcoin desk sizes the Bitcoin sleeve, gold is always held, and whatever the sleeves do not hold waits in T-bills.</p></div>
        <div class="tblwrap" id="m-rules"><p class="note">Loading the flagship rules…</p></div>
        <p class="note">A desk’s new call is acted on at the next close, and the portfolio is also rebalanced to its targets at the start of each month. Before 2014, when the Bitcoin desk has no history, the Bitcoin sleeve is added to the stock sleeve. Followers can hold their own stock picks in the stock sleeve, sized up and down with the stocks desk’s calls; their results will differ from the model’s.</p>
      </div></div>
  </section>

  <section class="sec" id="risk" aria-label="Risk management">
    <div class="k-split"><h2><small>04 · Risk</small>How risk is managed</h2>
      <dl class="k-dl">
        <div><dt>Drawdowns first</dt><dd>The models are built to avoid large declines, then to get back in quickly after a bottom. Their scores separate the odds of a 10% decline far better than they separate returns.</dd></div>
        <div><dt>Half before none</dt><dd>On the stocks desk, a cut signal halves exposure; it goes to cash only when the macro signals confirm it, because unconfirmed cut signals were usually dips inside bull markets.</dd></div>
        <div><dt>Confirmation</dt><dd>Scores are smoothed over 5 days and a new signal must hold for 3 straight days, so one noisy session cannot flip a desk.</dd></div>
        <div><dt>Early re-entry</dt><dd>Stocks: after a 20% fall, a close above a rising 50-day average, or a 10% rally off the 20-session low while CPI inflation is under 4%. Bitcoin: once 50% or more below its high, a close above the 20-week average.</dd></div>
        <div><dt>Top signal</dt><dd>On Bitcoin, the Pi-cycle top signal caps exposure at half for 120 days after it fires.</dd></div>
        <div><dt>No leverage</dt><dd>Published states run from 0% to 100%. The stocks desk also shows a 1.25x research variant; the flagship does not use it.</dd></div>
        <div><dt>Separate satellite</dt><dd>The higher-risk high-beta desk is kept outside the flagship portfolio.</dd></div>
      </dl></div>
  </section>

  <section class="sec" id="timing" aria-label="Timing and assumptions">
    <div class="k-split"><h2><small>05 · Timing</small>Updates and assumptions</h2>
      <dl class="k-dl">
        <div><dt>When the models run</dt><dd>Once a day, before the US open, on the latest completed session’s closing data. The Bitcoin desk uses the latest completed day and also runs on weekends.</dd></div>
        <div><dt>When this site updates</dt><dd>Once a day, by about 10:00 a.m. ET. Each update is a timestamped commit in the public GitHub history.</dd></div>
        <div><dt>When trades are assumed</dt><dd>A call made at one close is traded at the next close, in the backtests and in the flagship’s live record.</dd></div>
        <div><dt>Costs and income</dt><dd>Trading costs are included (0.05% per unit traded in the flagship). Cash earns the 3-month T-bill rate. Dividends on SPY and QQQ are approximated. No taxes.</dd></div>
        <div><dt>No look-ahead</dt><dd>Monthly macro data enter only after their publication dates, seasonal tables use only earlier years, and cycle measures use the running high rather than hindsight peaks.</dd></div>
        <div><dt>Backtest windows</dt><dd>Stocks from 2003, Bitcoin from 2015 (desk history from 2014), the flagship from 2005, the high-beta basket from 2018.</dd></div>
      </dl></div>
  </section>

  <section class="sec" id="integrity" aria-label="Research integrity">
    <div class="k-sh"><div><span class="eyebrow">06 · Research integrity</span><h2>Built to be checked</h2></div><a class="feat-link" href="https://github.com/kerdoscapital/kerdos-site" rel="noopener">GitHub repository <span aria-hidden="true">↗</span></a></div>
    <div class="k-pillars">
      <div><h3>A public, <em>timestamped</em> record</h3><p>Every daily update is a commit in the site’s public repository, with each report stamped with the close it used and the time it was generated. What a model said, and when, cannot be revised after the fact.</p><p id="m-upd" class="mono" style="font-size:12px"></p></div>
      <div><h3>Backtests <em>labeled</em> as backtests</h3><p>Backtested results are shown as hypothetical and kept apart from the flagship’s live record. The live record never inherits the backtest’s numbers.</p></div>
      <div><h3>Rejected ideas <em>published</em></h3><p>Each desk page lists the rules that were tested and left out, and why, alongside the ones that were kept, so the method can be judged by its misses as well as its hits.</p></div>
    </div>
  </section>

  <section class="sec" id="archive" aria-label="Signal archive">
    <div class="k-sh"><div><span class="eyebrow">07 · Signal archive</span><h2>Every change of state</h2></div><p>Each desk’s state changes and the flagship’s allocation changes, newest first, from the published daily histories.</p></div>
    <div class="k-arch-ctl"><div class="seg" role="group" aria-label="Desk" id="arch-seg"><button type="button" data-d="all" aria-pressed="true">All</button><button type="button" data-d="Flagship" aria-pressed="false">Flagship</button><button type="button" data-d="US stocks" aria-pressed="false">Stocks</button><button type="button" data-d="Bitcoin" aria-pressed="false">Bitcoin</button><button type="button" data-d="High beta" aria-pressed="false">High beta</button></div><span class="label" id="arch-n"></span></div>
    <div class="tblwrap k-arch" id="arch"><p class="note">The archive loads as you reach it.</p></div>
    <p class="note" id="arch-note">Rows before the flagship’s live start are backtests: the current rules run over past data, not calls published at the time. Every row is computed by the models’ current rules; the GitHub commit history is the record of what was published on each day.</p>
  </section>

  <section class="sec" id="limits" aria-label="Limitations">
    <div class="k-split"><h2><small>08 · Limits</small>What the models cannot do</h2>
      <dl class="k-dl">
        <div><dt>In-sample rules</dt><dd>Factor directions, thresholds, the macro gate and the re-entry rules were chosen with the 2003–2026 stock history and the 2014–2026 Bitcoin history in view, so the backtests are optimistic.</dd></div>
        <div><dt>Few examples</dt><dd>Daily stock data covers three recessions and five bear markets; Bitcoin has had only four full cycles. That is enough to see patterns, not to prove them.</dd></div>
        <div><dt>Bitcoin dominates</dt><dd>Bitcoin accounts for most of the flagship backtest’s lead over the S&amp;P 500 since 2015 and drives about 70% of the portfolio’s swings. Its early gains are unlikely to repeat.</dd></div>
        <div><dt>Slow after V-shaped lows</dt><dd>On its own the stocks score is slow after sharp rebounds; the rebound rule exists for those, and it added little on older data.</dd></div>
        <div><dt>Survivorship bias</dt><dd>The high-beta basket’s history is rebuilt from today’s Nasdaq-100 list, so it overstates what a real-time list would have earned.</dd></div>
        <div><dt>News is not scored</dt><dd>Headlines and catalysts are shown for context only and never change a call.</dd></div>
        <div><dt>Approximations</dt><dd>Dividends are approximated, some macro series are proxies, and prices may be delayed or contain errors.</dd></div>
        <div><dt>Not advice</dt><dd>These are hypothetical research models. They manage no money, and nothing here is a recommendation to buy or sell anything.</dd></div>
      </dl></div>
  </section>
<script>
(()=>{
const $=s=>document.querySelector(s);
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fmtD=d=>{const t=new Date(d.slice(0,10)+'T00:00:00Z');return MON[t.getUTCMonth()]+' '+t.getUTCDate()+', '+t.getUTCFullYear()};
const J=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(r.status);return r.json()});
const T=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(r.status);return r.text()});
const csv=t=>{const[h,...r]=t.trim().split(/\r?\n/);const k=h.split(',');return r.map(x=>{const c=x.split(',');const o={};k.forEach((kk,i)=>o[kk]=c[i]);return o})};
const NM={trend:'Trend',momentum:'Momentum',internals:'Internals',macro:'Macro',volatility:'Volatility & sentiment',calendar:'Calendar',valuation:'Valuation',cycle:'Cycle & seasonality'};
const wbar=(el,gw)=>{if(!el)return;const e=Object.entries(gw||{}).sort((a,b)=>b[1]-a[1]);if(!e.length){el.innerHTML='';return}
  el.innerHTML=e.map(([k,v])=>`<div><span>${NM[k]||k}</span><i style="width:${(v/e[0][1]*100).toFixed(0)}%"></i><span>${Math.round(v*100)}%</span></div>`).join('')};
const gen=t=>t?String(t).replace('T',' ').replace(/:\d\d(\.\d+)?Z$/,' UTC').replace(/Z$/,' UTC'):'—';
let REP=null;
Promise.all([J('stocks/report.json'),J('bitcoin/report.json'),J('highbeta/report.json'),J('flagship/report.json')]).then(([M,B,G,F])=>{
  REP={M,B,G,F};
  wbar($('#w-stocks'),M.group_weights);wbar($('#w-btc'),B.group_weights);
  const up=$('#m-upd');if(up)up.innerHTML=`Latest reports: stocks ${gen(M.generated)} · Bitcoin ${gen(B.generated)} · high beta ${gen(G.generated)} · flagship ${gen(F.generated)}`;
  const RU=F.rules,stk=Math.round((RU.stocks.SPY+RU.stocks.QQQ)*100);
  const rrow=(n,wt,by,m)=>`<tr><td>${n}</td><td class="n">${wt}</td><td>${by}</td><td>${m?'Bullish':'Always'}</td><td>${m?'Neutral':'—'}</td><td>${m?'Bearish':'—'}</td></tr>`;
  $('#m-rules').innerHTML=`<table><thead><tr><th>Sleeve</th><th class="n">Target</th><th>Sized by</th><th>Full (100%)</th><th>Half (50%)</th><th>None (0%)</th></tr></thead><tbody>
    ${rrow(`Stocks: SPY ${Math.round(RU.stocks.SPY*100)}% + QQQ ${Math.round(RU.stocks.QQQ*100)}%`,stk+'%','<a href="stocks.html">Stocks desk</a>',RU.stocks_exposure)}
    ${rrow('Bitcoin',Math.round(RU.btc*100)+'%','<a href="bitcoin.html">Bitcoin desk</a>',RU.btc_exposure)}
    ${rrow('Gold (GLD)',Math.round(RU.gold*100)+'%','Fixed',null)}
    <tr><td>T-bills</td><td class="n">Rest</td><td colspan="4">Whatever the sleeves above don’t hold</td></tr></tbody></table>`;
  const n=$('#arch-note');if(n&&F.live_since)n.innerHTML=`Rows dated before ${fmtD(F.live_since)}, when the flagship’s live record began, are marked <b>Backtest</b>: the current rules run over past data, not calls published at the time. Every row is computed by the models’ current rules; the <a href="https://github.com/kerdoscapital/kerdos-site/commits/main" rel="noopener">GitHub commit history</a> is the record of what was published on each day.`;
}).catch(e=>{['#w-stocks','#w-btc','#m-rules'].forEach(s=>{const el=$(s);if(el)el.innerHTML=`<p class="err">The latest reports did not load (${e.message}). Reload the page to try again.</p>`})});

// ---- signal archive (loads when it nears the screen)
const host=$('#arch');let rows=null,desk='all',shown=40;
const pct=v=>v==null?'—':Math.round(v*100)+'%';
const A=['SPY','QQQ','BTC','GLD','CASH'],AN={SPY:'SPY',QQQ:'QQQ',BTC:'Bitcoin',GLD:'Gold',CASH:'T-bills'};
function build(H){
  const {M,B,G,F}=REP,out=[],live=F.live_since||'9999';
  const states=(name,R,map)=>{let prev=null;R.forEach(r=>{if(!r.regime)return;const s=Kerdos.st(r.regime,map);if(prev&&s!==prev)out.push({date:r.date,desk:name,from:prev,to:s,ex:`${pct(Kerdos.EXPO[prev])} → ${pct(Kerdos.EXPO[s])}`});prev=s})};
  states('US stocks',csv(H[0]),M.exposure_map);states('Bitcoin',csv(H[1]),B.exposure_map);states('High beta',csv(H[2]).filter(r=>r.regime),G.exposure_map);
  let pw=null;csv(H[3]).forEach(r=>{const w=A.map(k=>Math.round(+r[k]*100));const key=w.join('|');if(pw&&key!==pw.key){const ch=A.map((k,i)=>[k,pw.w[i],w[i]]).filter(x=>x[1]!==x[2]).map(([k,a,b])=>`${AN[k]} ${a}% → ${b}%`).join(', ');
    out.push({date:r.date,desk:'Flagship',from:null,to:null,ex:`${100-w[4]}% invested`,txt:ch})}pw={key,w}});
  out.sort((a,b)=>a.date<b.date?1:a.date>b.date?-1:0);
  out.forEach(o=>o.basis=o.date>=live?'live':'bt');
  return out;
}
function draw(){
  const R=rows.filter(r=>desk==='all'||r.desk===desk),V=R.slice(0,shown);
  $('#arch-n').textContent=`${R.length.toLocaleString('en-US')} changes`;
  host.innerHTML=`<table><thead><tr><th>Date</th><th>Desk</th><th>Change</th><th class="n">Exposure</th><th class="n">Basis</th></tr></thead><tbody>${V.map(r=>`<tr><td class="mono" style="white-space:nowrap">${fmtD(r.date)}</td><td>${r.desk}</td><td>${r.txt?r.txt:`<span class="st c-${r.from}">${r.from}</span> → <b class="st c-${r.to}">${r.to}</b>`}</td><td class="n">${r.ex}</td><td class="n"><span class="ph${r.basis==='live'?' live':''}">${r.basis==='live'?'Live period':'Backtest'}</span></td></tr>`).join('')}</tbody></table>`
   +(R.length>shown?`<button class="k-more" type="button" id="arch-more">Show ${Math.min(80,R.length-shown)} more</button>`:'');
  const mb=$('#arch-more');if(mb)mb.addEventListener('click',()=>{shown+=80;draw()});
}
document.querySelectorAll('#arch-seg button').forEach(b=>b.addEventListener('click',()=>{desk=b.dataset.d;shown=40;document.querySelectorAll('#arch-seg button').forEach(x=>x.setAttribute('aria-pressed',x===b));if(rows)draw()}));
let started=false;
const go=()=>{if(started)return;started=true;host.innerHTML='<p class="loading" style="padding:24px 0">Loading the archive…</p>';
  const wait=()=>REP?Promise.resolve():new Promise(r=>setTimeout(()=>r(wait()),120));
  Promise.all([T('stocks/history.csv'),T('bitcoin/history.csv'),T('highbeta/history.csv'),T('flagship/history.csv'),wait()]).then(H=>{rows=build(H);draw()})
  .catch(e=>{host.innerHTML=`<p class="err">The archive did not load (${e.message}). Reload the page to try again.</p>`;started=false})};
if('IntersectionObserver' in window&&location.hash!=='#archive'){const io=new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting)){io.disconnect();go()}},{rootMargin:'600px 0px'});io.observe(host)}else go();
})();
</script>
'''


def main():
    M, B, G = jload('stocks/report.json'), jload('bitcoin/report.json'), jload('highbeta/report.json')
    FL = jload('flagship/report.json'); PF = jload('portfolio_backtest.json')
    global FOOT
    FOOT = ((M or {}).get('asof'), (FL or {}).get('live_since'))
    img_v = (M or {}).get('asof', dt.date.today().isoformat()).replace('-', '')
    try:
        if not exists('favicon.svg') or rd('favicon.svg') != ICON_SVG or not exists('favicon.ico') or not exists('apple-touch-icon.png'): make_icons()
    except Exception as e: print('icons skipped:', e)
    try: make_og(M, B, G, FL, k_img)
    except Exception as e: print('og.png skipped:', e)
    if exists('index.html'):
        idx = unwrap(rd('index.html'))
        a = make_about(idx)
        if a: wr('about.html', a)
        if exists('flagship/report.json'):
            fp = make_shell_page(idx, 'flagship_body.html')
            if fp: wr('flagship.html', fp)
        mp = make_shell_page(idx, 'methodology_body.html', METHOD_BODY)
        if mp: wr('methodology.html', mp)
    for f in PAGES:
        if not exists(f): continue
        s = fix_page(f, rd(f), img_v)
        if f == 'index.html': s = prerender_index(s, M, B, G, FL)
        elif f == 'stocks.html' and M:
            s = prerender_loading(s, summary_line('US stocks', M['regime'], M['exposure'], f"SPY {usd(M['spy'])} ({sg(M['spy_chg']['d1'])}) · QQQ {usd(M['qqq'])}", M['asof']))
        elif f == 'bitcoin.html' and B:
            s = prerender_loading(s, summary_line('Bitcoin', B['regime'], B['exposure'], f"BTC {usd(B.get('price'), 0)}", B['asof']))
        elif f == 'highbeta.html' and G:
            s = prerender_loading(s, summary_line('High beta', G['regime'], G['exposure'], f"basket {G['level']:.2f}", G['asof']))
        elif f == 'flagship.html' and FL:
            s = prerender_loading(s, summary_line('Flagship portfolio', f"stocks desk {FL['stocks_regime']}, Bitcoin desk {FL.get('btc_regime')}", 1 - FL.get('weights', {}).get('CASH', 0), '60% stocks / 30% Bitcoin / 10% gold target', FL['asof']))
        wr(f, s)
    for old, new in RETIRED.items():
        title = PAGES[new][0]
        wr(old, f'<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<title>{E(title)}</title>\n'
                f'<meta http-equiv="refresh" content="0; url={new}">\n<link rel="canonical" href="{SITE}/{new}">\n<meta name="robots" content="noindex">\n'
                f'</head>\n<body style="background:{BG};color:{INK};font-family:Georgia,serif;padding:24px">'
                f'<p>This page has moved to the <a style="color:{SAGE}" href="{new}">Kerdos Flagship Portfolio</a>.</p>\n'
                f'<script>location.replace({json.dumps(new)})</script>\n</body>\n</html>\n')
    today = dt.date.today().isoformat()
    wr('robots.txt', f'User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n')
    urls = ''.join(f'  <url><loc>{SITE}/{"" if f == "index.html" else f}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>\n'
                   for f in NAV_ORDER if exists(f))
    wr('sitemap.xml', f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    print('build ok:', ', '.join(f for f in NAV_ORDER if exists(f)))


if __name__ == '__main__':
    main()
