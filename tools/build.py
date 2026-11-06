#!/usr/bin/env python3
"""Post-sync build for kerdoscapital.xyz.

Run from the repository root after the daily sync has mirrored the claude.ai artifact:
    python3 tools/build.py

What it does (idempotent: running it twice gives the same files):
  1. index.html  - strips the document wrappers the artifact service adds, so <title>, meta, links and styles
                   sit in a real <head>.
  2. every page  - one managed block in <head>: favicon, canonical URL, description, Open Graph / Twitter tags,
                   theme colour; consistent titles; the site's web fonts; one canonical nav
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
FONTS_CSS = ('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;1,400'
             '&family=Instrument+Serif:ital@0;1&family=Cormorant+Garamond:wght@500;600&display=swap')
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
    'notes.html': (f'Weekly Notes · {NAME}',
                   'The Kerdos week in plain words: what moved, what the stock and Bitcoin desks did and why, and the data coming next.', 'Notes'),
    'about.html': (f'About · {NAME}',
                   'What Kerdos Capital is, why it publishes its research in the open, how its models are built and run, and what it is not.', 'About'),
}
NAV_ORDER = ['index.html', 'flagship.html', 'stocks.html', 'bitcoin.html', 'highbeta.html', 'notes.html', 'methodology.html', 'about.html']
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


# Logo (Oct 2026): Bodoni Moda K in a champagne gradient, a rising line with three points, a four-point star.
# The mark's box is viewBox "226 116 338 282".
LOGO_K = 'M318.6 322.0 439.5 165.9H406.8V160.0H479.8V165.9H448.0L327.3 322.0ZM286.6 388.0V382.1H314.1V165.9H286.6V160.0H378.4V165.9H348.1V382.1H377.6V388.0ZM394.9 388.0V382.1H424.7L361.3 269.7L383.7 243.0L466.2 382.1H493.4V388.0Z'
LOGO_LINE = '238,371 276,349 296,358 352,310 376,325 425,272 444,283 478,215 493,226 516,178'
LOGO_DOTS = [[352, 310], [425, 272], [478, 215]]
LOGO_STAR = 'M531.0 124.0L534.2 143.8L554.0 147.0L534.2 150.2L531.0 170.0L527.8 150.2L508.0 147.0L527.8 143.8Z'


def logo_svg(gid, cls='k-mono', lw=2.4, dot=3.8, solid=False, ink='#E7E4DC'):
    star = (f'<path d="{LOGO_STAR}" fill="{ink}"/>' if solid else
            f'<path d="{LOGO_STAR}" fill="none" stroke="{ink}" stroke-width="2" stroke-linejoin="round"/>')
    return (f'<svg class="{cls}" viewBox="226 116 338 282" aria-hidden="true"><defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="1">'
            f'<stop offset="0" stop-color="#DCCFAC"/><stop offset="1" stop-color="#8E7F62"/></linearGradient></defs>'
            f'<path d="{LOGO_K}" fill="url(#{gid})"/><polyline points="{LOGO_LINE}" fill="none" stroke="{ink}" stroke-width="{lw}" stroke-linejoin="round" stroke-linecap="round"/>'
            + ''.join(f'<circle vector-effect="non-scaling-stroke" cx="{x}" cy="{y}" r="{dot}" fill="{ink}"/>' for x, y in LOGO_DOTS) + star + '</svg>')


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
    return (f'<header class="k-nav"><div class="k-bar"><a class="k-word" href="index.html" aria-label="Kerdos Capital, overview">{logo_svg("kgn", lw=3.6, dot=5)}<span class="k-wt">Kerdos Capital</span></a>'
            f'<div class="k-right"><nav class="k-links" aria-label="Site"><span class="k-ind" aria-hidden="true"></span>{nav_links(cur, "site")}</nav>'
            f'{MENU}</div></div></header>')


def footer(asof, live_since):
    year = dt.date.today().year
    ls = fmt_d(live_since) if live_since else None
    col = lambda title, links: (f'<div class="kf-col"><span class="label">{title}</span>' + ''.join(f'<a href="{h}"{r}>{t}</a>' for t, h, r in links) + '</div>')
    research = [(PAGES[f][2], f, '') for f in ['index.html', 'flagship.html', 'stocks.html', 'bitcoin.html', 'highbeta.html', 'notes.html'] if exists(f)]
    firm = [('Methodology', 'methodology.html', ''), ('Signal archive', 'methodology.html#archive', ''), ('Model limitations', 'methodology.html#limits', ''), ('About', 'about.html', '')]
    live = (f' The flagship portfolio’s live record began at the open on {E(ls)}; every result before that date is a backtest.' if ls else '')
    stamp = f'Models as of the {E(fmt_d(asof))} close' if asof else 'Models update daily'
    return (f'<footer class="foot pub">\n    <div class="kf-top">'
            f'<div class="kf-brand"><a class="k-word" href="index.html" aria-label="Kerdos Capital, overview">{logo_svg("kgf", lw=3.2, dot=4.6)}<span class="k-wt">Kerdos Capital</span></a>'
            f'<p class="k-pos">Transparency over promises. <i>Methodology over speculation.</i> Discipline over emotion.</p></div>'
            f'<nav class="kf-col fl" aria-label="Footer"><span class="label">Research</span>' + ''.join(f'<a href="{h}">{t}</a>' for t, h, _ in research) + '</nav>'
            + col('Method', firm) + '</div>\n'
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
    s = s.replace("String(t).replace('T',' ')", "String(t).replace(/T(?=\\d)/,' ')")   # the old form turned 'UTC' into 'U C'
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
            f'<div class="sub">Stocks desk <b>{E(lab(st3(F["stocks_regime"], RU.get("stocks_exposure"))))}</b> · Bitcoin desk <b>{E(lab(st3(F.get("btc_regime"), RU.get("btc_exposure"))) or "—")}</b> · as of the {E(fmt_d(F["asof"]))} close</div>'
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
        return (f'<article class="desk"><div class="top"><h2>{E(name)}</h2></div><div><div class="call c-{E(reg)}">{E(lab(reg))}</div></div>'
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
    'bodoni-moda': ['bodoni-moda-latin-500-normal.woff2'],
    'cormorant-garamond': ['cormorant-garamond-latin-500-normal.woff2'],
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
LAB = {'Bullish': 'Risk On', 'Neutral': 'Balanced', 'Bearish': 'Risk Off', 'Risk-On': 'Risk On', 'Risk-Off': 'Risk Off'}   # what visitors read; the keys above stay (CSS, data)


def lab(s): return LAB.get(s, s)
BODONI = [('bodoni-moda', 'bodoni-moda-latin-500-normal.woff2'), '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf']
CAPS = [('cormorant-garamond', 'cormorant-garamond-latin-500-normal.woff2'), '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf']


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


# Favicon / app icon: the logo on graphite, with a heavier line and a solid star so it reads at small sizes.
ICON_SVG = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#111315"/>'
            f'<g transform="translate(32 33) scale(.168) translate(-397 -257)">' + logo_svg('kf', cls='', lw=11, dot=.01, solid=True)
            .replace('<svg class="" viewBox="226 116 338 282" aria-hidden="true">', '').replace('</svg>', '') + '</g></svg>')


def logo_img(px, box=(226, 116, 338, 282), lw=2.4, dot=3.8, solid=False, ink=INK, star_w=2.0):
    """The logo as an RGBA Pillow image px wide (drawn at 4x, then scaled down), same geometry as logo_svg()."""
    from PIL import Image, ImageDraw
    SS = 4; bx, by, bw, bh = box; k = px * SS / bw; W, H = px * SS, round(bh * k)
    P = lambda x, y: ((x - bx) * k, (y - by) * k)
    im = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    # the K: Bodoni Moda fitted to the box x 286.6-493.4, y 160-388, filled with the champagne gradient
    f = font(BODONI, 400); l, t, r, b = f.getbbox('K')
    g = Image.new('L', (r - l, b - t), 0); ImageDraw.Draw(g).text((-l, -t), 'K', font=f, fill=255)
    (x0, y0), (x1, y1) = P(286.6, 160), P(493.4, 388)
    g = g.resize((max(1, round(x1 - x0)), max(1, round(y1 - y0))), Image.LANCZOS)
    grad = Image.new('RGBA', g.size); gw, gh = g.size; c0, c1 = (0xDC, 0xCF, 0xAC), (0x8E, 0x7F, 0x62)
    gp = grad.load()
    for yy in range(gh):
        for xx in range(gw):
            u = (xx / max(1, gw - 1) + yy / max(1, gh - 1)) / 2
            gp[xx, yy] = tuple(round(a + (b2 - a) * u) for a, b2 in zip(c0, c1)) + (255,)
    im.paste(grad, (round(x0), round(y0)), g)
    d = ImageDraw.Draw(im); w = max(1, round(lw * k))
    pts = [P(*map(float, xy.split(','))) for xy in LOGO_LINE.split()]
    d.line(pts, fill=ink, width=w, joint='curve')
    for x, y in (pts[0], pts[-1]): d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=ink)
    for x, y in LOGO_DOTS:
        cx, cy = P(x, y); rr = dot * k; d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=ink)
    sp = [P(*map(float, q.split())) for q in LOGO_STAR[1:-1].split('L')]
    if solid: d.polygon(sp, fill=ink)
    else: d.line(sp + [sp[0]], fill=ink, width=max(1, round(star_w * k)), joint='curve')
    return im.resize((px, round(H / SS)), Image.LANCZOS)


def icon_img(n, rounded=True):
    from PIL import Image, ImageDraw
    S2 = 4; N = n * S2; im = Image.new('RGBA', (N, N), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if rounded: d.rounded_rectangle([0, 0, N - 1, N - 1], radius=round(N * 12 / 64), fill=BG)
    else: d.rectangle([0, 0, N - 1, N - 1], fill=BG)
    m = logo_img(round(N * .94), lw=8, dot=.01, solid=True)
    im.paste(m, ((N - m.width) // 2, (N - m.height) // 2 + round(N * .02)), m)
    return im.resize((n, n), Image.LANCZOS)


def make_icons():
    wr('favicon.svg', ICON_SVG)
    icon_img(256).save(p('favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
    icon_img(180, rounded=False).convert('RGB').save(p('apple-touch-icon.png'))


def make_og(M, B, G, FL):
    from PIL import Image, ImageDraw
    W, H = 1200, 630
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    for x in range(0, W, 60): d.line([(x, 0), (x, H)], fill='#16191C')     # faint architectural grid
    for y in range(0, H, 60): d.line([(0, y), (W, y)], fill='#16191C')
    try:
        lg = logo_img(104, lw=3.4, dot=4.8); im.paste(lg, (60, 34), lg)
    except Exception as e: print('og logo skipped:', e)
    d.text((176, 78), 'K E R D O S   C A P I T A L', font=font(CAPS, 28), fill=INK)
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
        d.text((x, y + 60), lab(reg), font=font(SERIF, 54 if len(lab(reg)) < 10 else 44), fill=COL.get(reg, INK))
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
      <div><span class="n">04</span><b>State</b><p>Thresholds map the score to Risk On, Balanced or Risk Off. A new signal needs 3 straight days, to cut whipsaw.</p></div>
      <div><span class="n">05</span><b>Exposure</b><p>Risk On holds 100%, Balanced 50%, Risk Off 0%. Money not invested earns the 3-month T-bill rate.</p></div>
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
        <p>Eighteen factors in five groups. Above +0.20 is Risk On, below −0.15 Risk Off, in between Balanced. Bottoming rules apply once Bitcoin is 50% or more below its high, and a top signal caps exposure at half.</p>
        <div class="k-wbar" id="w-btc"><p class="note">Loading weights…</p></div>
        <a class="k-tl" href="bitcoin.html#method">Full method and data <span aria-hidden="true">→</span></a></article>
      <article class="panel"><span class="label">Satellite sleeve</span><h3>High-beta desk</h3>
        <p>The 25 Nasdaq-100 stocks with the highest beta to QQQ over two years, equal weight, re-ranked each quarter. It takes the stocks desk’s state, then its own rules can cut it further; the lowest exposure wins. It is not part of the flagship.</p>
        <dl class="k-dl"><div><dt>Half (50%)</dt><dd>The basket is clearly lagging the S&amp;P 500, or falls 12% or more in 10 sessions.</dd></div><div><dt>None (0%)</dt><dd>The stocks desk is Risk Off, or the basket closes below its 200-day average while the stock score is not firmly positive.</dd></div></dl>
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
        <div><dt>When this site updates</dt><dd>Once a day, by about 10:00 a.m. ET. Each update is saved as a timestamped version.</dd></div>
        <div><dt>When trades are assumed</dt><dd>A call made at one close is traded at the next close, in the backtests and in the flagship’s live record.</dd></div>
        <div><dt>Costs and income</dt><dd>Trading costs are included (0.05% per unit traded in the flagship). Cash earns the 3-month T-bill rate. Dividends on SPY and QQQ are approximated. No taxes.</dd></div>
        <div><dt>No look-ahead</dt><dd>Monthly macro data enter only after their publication dates, seasonal tables use only earlier years, and cycle measures use the running high rather than hindsight peaks.</dd></div>
        <div><dt>Backtest windows</dt><dd>Stocks from 2003, Bitcoin from 2015 (desk history from 2014), the flagship from 2005, the high-beta basket from 2018.</dd></div>
      </dl></div>
  </section>

  <section class="sec" id="integrity" aria-label="Research integrity">
    <div class="k-sh"><div><span class="eyebrow">06 · Research integrity</span><h2>Built to be checked</h2></div></div>
    <div class="k-pillars">
      <div><h3>A public, <em>timestamped</em> record</h3><p>Every daily update is saved as a dated version of the site, with each report stamped with the close it used and the time it was generated. What a model said, and when, cannot be revised after the fact.</p><p id="m-upd" class="mono" style="font-size:12px"></p></div>
      <div><h3>Backtests <em>labeled</em> as backtests</h3><p>Backtested results are shown as hypothetical and kept apart from the flagship’s live record. The live record never inherits the backtest’s numbers.</p></div>
      <div><h3>Rejected ideas <em>published</em></h3><p>Each desk page lists the rules that were tested and left out, and why, alongside the ones that were kept, so the method can be judged by its misses as well as its hits.</p></div>
    </div>
  </section>

  <section class="sec" id="archive" aria-label="Signal archive">
    <div class="k-sh"><div><span class="eyebrow">07 · Signal archive</span><h2>Every change of state</h2></div><p>Each desk’s state changes and the flagship’s allocation changes, newest first, from the published daily histories.</p></div>
    <div class="k-arch-ctl"><div class="seg" role="group" aria-label="Desk" id="arch-seg"><button type="button" data-d="all" aria-pressed="true">All</button><button type="button" data-d="Flagship" aria-pressed="false">Flagship</button><button type="button" data-d="US stocks" aria-pressed="false">Stocks</button><button type="button" data-d="Bitcoin" aria-pressed="false">Bitcoin</button><button type="button" data-d="High beta" aria-pressed="false">High beta</button></div><span class="label" id="arch-n"></span></div>
    <div class="tblwrap k-arch" id="arch"><p class="note">The archive loads as you reach it.</p></div>
    <p class="note" id="arch-note">Rows before the flagship’s live start are backtests: the current rules run over past data, not calls published at the time. Every row is computed by the models’ current rules; the site’s version history is the record of what was published on each day.</p>
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
const gen=t=>t?String(t).replace(/T(?=\d)/,' ').replace(/:\d\d(\.\d+)?Z$/,' UTC').replace(/Z$/,' UTC'):'—';
let REP=null;
Promise.all([J('stocks/report.json'),J('bitcoin/report.json'),J('highbeta/report.json'),J('flagship/report.json')]).then(([M,B,G,F])=>{
  REP={M,B,G,F};
  wbar($('#w-stocks'),M.group_weights);wbar($('#w-btc'),B.group_weights);
  const up=$('#m-upd');if(up)up.innerHTML=`Latest reports: stocks ${gen(M.generated)} · Bitcoin ${gen(B.generated)} · high beta ${gen(G.generated)} · flagship ${gen(F.generated)}`;
  const RU=F.rules,stk=Math.round((RU.stocks.SPY+RU.stocks.QQQ)*100);
  const rrow=(n,wt,by,m)=>`<tr><td>${n}</td><td class="n">${wt}</td><td>${by}</td><td>${m?'Risk On':'Always'}</td><td>${m?'Balanced':'—'}</td><td>${m?'Risk Off':'—'}</td></tr>`;
  $('#m-rules').innerHTML=`<table><thead><tr><th>Sleeve</th><th class="n">Target</th><th>Sized by</th><th>Full (100%)</th><th>Half (50%)</th><th>None (0%)</th></tr></thead><tbody>
    ${rrow(`Stocks: SPY ${Math.round(RU.stocks.SPY*100)}% + QQQ ${Math.round(RU.stocks.QQQ*100)}%`,stk+'%','<a href="stocks.html">Stocks desk</a>',RU.stocks_exposure)}
    ${rrow('Bitcoin',Math.round(RU.btc*100)+'%','<a href="bitcoin.html">Bitcoin desk</a>',RU.btc_exposure)}
    ${rrow('Gold (GLD)',Math.round(RU.gold*100)+'%','Fixed',null)}
    <tr><td>T-bills</td><td class="n">Rest</td><td colspan="4">Whatever the sleeves above don’t hold</td></tr></tbody></table>`;
  const n=$('#arch-note');if(n&&F.live_since)n.innerHTML=`Rows dated before ${fmtD(F.live_since)}, when the flagship’s live record began, are marked <b>Backtest</b>: the current rules run over past data, not calls published at the time. Every row is computed by the models’ current rules; the site’s version history is the record of what was published on each day.`;
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
  host.innerHTML=`<table><thead><tr><th>Date</th><th>Desk</th><th>Change</th><th class="n">Exposure</th><th class="n">Basis</th></tr></thead><tbody>${V.map(r=>`<tr><td class="mono" style="white-space:nowrap">${fmtD(r.date)}</td><td>${r.desk}</td><td>${r.txt?r.txt:`<span class="st c-${r.from}">${Kerdos.lab(r.from)}</span> → <b class="st c-${r.to}">${Kerdos.lab(r.to)}</b>`}</td><td class="n">${r.ex}</td><td class="n"><span class="ph${r.basis==='live'?' live':''}">${r.basis==='live'?'Live period':'Backtest'}</span></td></tr>`).join('')}</tbody></table>`
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


# ---------------------------------------------------------------- 6. retail layer (Nov 2026)
# Today panel (action, levels, next data, share, alerts), scored call record, weekly notes page, RSS feed.
# Inputs, all optional: triggers.json (tools/triggers.py), catalysts.json and weekly/*.json (written by the daily run).
import csv as _csv
import glob as _glob

RETAIL_CSS = '''<style id="k-retail">
.k-strip{display:flex;flex-wrap:wrap;align-items:center;gap:4px 18px;padding:11px 0;border-bottom:1px solid var(--hair);font-family:var(--f-num);font-size:12px;letter-spacing:.02em;color:var(--muted)}
.k-strip b{color:var(--ink);font-weight:400}
.k-strip .dot{width:6px;height:6px;border-radius:50%;background:var(--sage);display:inline-block;margin-right:8px;vertical-align:1px}
.k-strip a{margin-left:auto;color:var(--ink-2);text-decoration:none;border-bottom:1px solid var(--hair)}
.k-strip a:hover{color:var(--ink)}
@media (max-width:640px){.k-strip{font-size:11.5px}.k-strip .x{display:none}.k-strip a{margin-left:0}}
.k-today .t-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin-top:var(--s-5,24px)}
.k-today .t-grid>div{display:grid;gap:8px;align-content:start;padding:0 24px;border-left:1px solid var(--hair)}
.k-today .t-grid>div:first-child{padding-left:0;border-left:0}
@media (max-width:900px){.k-today .t-grid{grid-template-columns:1fr 1fr;gap:28px 0}.k-today .t-grid>div:nth-child(odd){padding-left:0;border-left:0}}
@media (max-width:560px){.k-today .t-grid{grid-template-columns:1fr}.k-today .t-grid>div{padding:20px 0 0;border-left:0;border-top:1px solid var(--hair)}.k-today .t-grid>div:first-child{border-top:0;padding-top:0}}
.k-today .t-st{font-size:14.5px;color:var(--ink)} .k-today .t-st b{font-weight:500}
.k-today p,.k-today li{font-size:13.5px;line-height:1.55;color:var(--ink-2);margin:0}
.k-today ul{list-style:none;margin:0;padding:0;display:grid;gap:7px}
.k-today li .mono{color:var(--ink);margin-right:6px}
.k-today .t-tag{font-family:var(--f-ui);font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-left:6px;white-space:nowrap}
.k-today .t-foot{display:flex;flex-wrap:wrap;gap:8px 22px;align-items:center;margin-top:var(--s-5,24px);padding-top:14px;border-top:1px solid var(--hair)}
.k-today .t-btn{font-family:var(--f-ui);font-size:13px;color:var(--ink-2);background:none;border:0;border-bottom:1px solid var(--hair);padding:0 0 2px;text-decoration:none;cursor:pointer}
.k-today .t-btn:hover{color:var(--ink);border-color:var(--sage)}
.k-today .t-fine{font-size:12px;color:var(--muted)}
.k-today .t-foot .t-fine{margin-left:auto}
.k-calls table{width:100%;border-collapse:collapse;font-size:13.5px}
.k-calls th{font-family:var(--f-ui);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500;text-align:left;padding:8px 10px;border-bottom:1px solid var(--hair)}
.k-calls td{padding:9px 10px;border-bottom:1px solid var(--hair);color:var(--ink-2);white-space:nowrap}
.k-calls td.n,.k-calls th.n{text-align:right;font-family:var(--f-num)}
.k-calls .ok{color:var(--sage)} .k-calls .bad{color:#A9705F}
.k-calls .sum{display:flex;flex-wrap:wrap;gap:8px 28px;margin:16px 0 4px;font-size:14px;color:var(--ink-2)} .k-calls .sum b{color:var(--ink);font-weight:500}
@media (max-width:640px){.k-calls th:nth-child(4),.k-calls td:nth-child(4),.k-calls th:nth-child(6),.k-calls td:nth-child(6){display:none}.k-calls td,.k-calls th{padding:8px 6px}.k-calls td .label{display:block;font-size:10px}}
.k-notes article{border-top:1px solid var(--hair);padding:28px 0;display:grid;gap:12px;max-width:72ch}
.k-notes article h2{font-family:var(--f-serif);font-weight:400;font-size:clamp(26px,3vw,36px);line-height:1.1;margin:0;color:var(--ink)}
.k-notes article p{font-size:15.5px;line-height:1.65;color:var(--ink-2);margin:0}
</style>'''


def _rows(path):
    try:
        with open(p(path), encoding='utf-8') as fh: return list(_csv.DictReader(fh))
    except Exception: return []


def _f(x):
    try: return float(x)
    except Exception: return None


def calls(path, price_col, mp, asset, min_date=None):
    """Every change of display state in a desk's history, with the price at the call and the move until the next change."""
    rows = [r for r in _rows(path) if r.get('regime') and _f(r.get(price_col)) is not None]
    if min_date: rows = [r for r in rows if r['date'] >= min_date]
    runs = []
    for r in rows:
        s = st3(r['regime'], mp)
        if not runs or runs[-1]['state'] != s:
            runs.append({'date': r['date'], 'state': s, 'expo': (mp or {}).get(r['regime'], 0), 'price': _f(r[price_col]), 'asset': asset})
        runs[-1]['end_date'], runs[-1]['end_price'] = r['date'], _f(r[price_col])
    expo = {'Bullish': 1.0, 'Neutral': 0.5, 'Bearish': 0.0}
    out = []
    for i in range(1, len(runs)):
        a, b = runs[i - 1], runs[i]
        b['from'] = a['state']; b['open'] = i == len(runs) - 1
        if not b['open']:                      # the call stands until the next change: measure to that call's price
            b['end_date'], b['end_price'] = runs[i + 1]['date'], runs[i + 1]['price']
        b['move'] = b['end_price'] / b['price'] - 1
        b['delta'] = expo[b['state']] - expo[a['state']]
        b['effect'] = b['delta'] * b['move']   # vs leaving the sleeve where it was: + helped, − cost
        b['helped'] = b['effect'] > 0.0005
        b['flat'] = abs(b['effect']) <= 0.0005
        out.append(b)
    return out


def pct_s(v, d=1): return ('+' if v > 0 else '−' if v < 0 else '') + f'{abs(v) * 100:.{d}f}%'


def money(v, asset): return usd(v, 0) if asset == 'Bitcoin' else usd(v)


def days_between(a, b): return (dt.date.fromisoformat(b[:10]) - dt.date.fromisoformat(a[:10])).days


def today_et():
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('America/New_York')).date().isoformat()
    except Exception:
        return dt.date.today().isoformat()


def flagship_action(FL):
    """What the flagship does at the next close, from the last two rows of flagship/history.csv."""
    h = _rows('flagship/history.csv')
    if len(h) < 2 or not FL: return 'No trade', 'The flagship history did not load.'
    a, b = h[-2], h[-1]; RU = FL.get('rules', {})
    se, be = RU.get('stocks_exposure') or {}, RU.get('btc_exposure') or {}
    bits = []
    def leg(name, old, new, emap, assets):
        eo, en = emap.get(old, 0) if old else 0, emap.get(new, 0) if new else 0
        if eo == en: return
        if en < eo:
            bits.append(f'{name} desk {lab(st3(old, emap))} → {lab(st3(new, emap))}: sell ' + ('all of ' if en == 0 else f'{round((1 - en / eo) * 100)}% of ') + assets)
        else:
            bits.append(f'{name} desk {lab(st3(old, emap))} → {lab(st3(new, emap))}: buy {assets} up to {round(en * 100)}% of the sleeve, using T-bills first')
    leg('Stocks', a.get('stocks'), b.get('stocks'), se, 'SPY and QQQ')
    leg('Bitcoin', a.get('bitcoin'), b.get('bitcoin'), be, 'the Bitcoin sleeve')
    month = a['date'][:7] != b['date'][:7]
    if month: bits.append('Monthly rebalance: SPY, QQQ, gold and Bitcoin reset to target weights')
    if not bits: return 'No trade', 'Neither desk changed state, so the portfolio holds as it is.'
    return ('Trade at the next close', ' · '.join(bits) + '.')


def levels_html(TR, M, B):
    out = []
    def line(name, d, asset, tick):
        if not d: return
        downs, ups = d.get('down') or [], d.get('up') or []
        expo = d.get('exposure', 0); L = lambda e: lab(st3({1.0: 'Bullish', 0.5: 'Neutral', 0.0: 'Bearish'}.get(e, 'Neutral'), {'Bullish': 1, 'Neutral': .5, 'Bearish': 0}))
        for x in downs[:1]:
            out.append(f'<li><span class="mono">{E(tick)} ≤ {money(x["price"], asset)}</span>{E(name)} would likely drop to {E(L(x["exposure"]))} ({round(x["exposure"] * 100)}%) · {pct_s(x["move"] / 100)} from today</li>')
        for x in ups[:1]:
            out.append(f'<li><span class="mono">{E(tick)} ≥ {money(x["price"], asset)}</span>{E(name)} would likely rise to {E(L(x["exposure"]))} ({round(x["exposure"] * 100)}%) · {pct_s(x["move"] / 100)} from today</li>')
        if not downs and expo > 0:
            out.append(f'<li><span class="mono">{E(tick)}</span>A price drop alone would not cut {E(name)} further; the macro inputs would also have to turn.</li>')
        if not ups and expo < 1:
            out.append(f'<li><span class="mono">{E(tick)}</span>A price rise alone would not lift {E(name)}; other inputs would also have to improve.</li>')
    if TR:
        line('the stocks desk', TR.get('stocks'), 'stocks', 'SPY')
        line('the Bitcoin desk', TR.get('bitcoin'), 'Bitcoin', 'BTC')
    if not out: return ''
    hold = (TR or {}).get('hold_sessions', 5)
    return ('<div><span class="label">Levels to watch</span><ul>' + ''.join(out) + '</ul>'
            f'<p class="t-fine">Found by re-running each desk’s own model on hypothetical closes: the price holds at that level for {hold} sessions while every other input stays where it is today. A guide, not a promise: other inputs move too.</p></div>')


def catalysts_html(CAT, today):
    items = sorted([c for c in (CAT or []) if str(c.get('date', '')) >= today], key=lambda c: (c['date'], c.get('time', '')))[:4]
    if not items: return ''
    li = ''.join(f'<li><span class="mono">{E(fmt_d(c["date"])[:-6])}</span>{E(c.get("event", ""))}'
                 + (f'<span class="t-tag">{E(c["feeds"])}</span>' if c.get('feeds') else '') + '</li>' for c in items)
    return f'<div><span class="label">Next data that can move the desks</span><ul>{li}</ul></div>'


def latest_note():
    fs = sorted(_glob.glob(p('weekly', '*.json')))
    for f in reversed(fs):
        try:
            n = json.load(open(f, encoding='utf-8'))
            if n.get('body'): return n
        except Exception: pass
    return None


def today_block(M, B, FL, TR, CAT):
    if not (M and B and FL): return ''
    t = today_et()
    act, why = flagship_action(FL)
    inv = round((1 - FL['weights'].get('CASH', 0)) * 100)
    ss, bs = st_since('stocks/history.csv', M.get('exposure_map')) or M['regime_since'], st_since('bitcoin/history.csv', B.get('exposure_map')) or B['regime_since']
    sl, bl = lab(st3(M['regime'], M.get('exposure_map'))), lab(st3(B['regime'], B.get('exposure_map')))
    dsd = lambda s, a: days_between(s, a)
    st_html = (f'<div><span class="label">Where the model stands</span>'
               f'<div class="t-st">Flagship <b>{inv}% invested</b></div>'
               f'<div class="t-st">Stocks desk <b>{E(sl)}</b> · {round(M["exposure"] * 100)}% · {dsd(ss, M["asof"])} days, since {E(fmt_d(ss))}</div>'
               f'<div class="t-st">Bitcoin desk <b>{E(bl)}</b> · {round(B["exposure"] * 100)}% · {dsd(bs, B["asof"])} days, since {E(fmt_d(bs))}</div>'
               f'<p>SPY {usd(M["spy"])} ({sg(M["spy_chg"]["d1"])}) · BTC {usd(B.get("price"), 0)} ({sg(B.get("chg1"))})</p></div>')
    note = latest_note()
    note_html = (f'<div><span class="label">This week · {E(fmt_d(note["date"]))}</span><p>{E(note["body"][0])}</p>'
                 f'<p><a href="notes.html" style="color:var(--ink)">Read the weekly note →</a></p></div>') if note else ''
    share_txt = f'Kerdos {fmt_d(FL["asof"])}: stocks {sl}, Bitcoin {bl}, flagship {inv}% invested.'
    foot = ('<div class="t-foot"><button class="t-btn" type="button" id="k-share">Share today’s call</button>'
            f'<a class="t-btn" href="https://twitter.com/intent/tweet?text={E(__import__("urllib.parse").parse.quote(share_txt))}&amp;url={E(__import__("urllib.parse").parse.quote(SITE + "/"))}" target="_blank" rel="noopener">Post on X</a>'
            '<a class="t-btn" href="feed.xml" type="application/rss+xml">Follow changes (RSS)</a>'
            '<span class="t-fine">Hypothetical model, not investment advice. Calls are made from the latest close and acted on at the next close.</span></div>'
            '<script>(()=>{const b=document.getElementById("k-share");if(!b)return;b.addEventListener("click",async()=>{const d={title:"Kerdos Capital",text:'
            + json.dumps(share_txt) + ',url:location.origin+"/"};try{if(navigator.share){await navigator.share(d);return}await navigator.clipboard.writeText(d.text+" "+d.url);b.textContent="Link copied"}catch(e){}})})()</script>')
    return (f'<section class="sec k-today" id="today" aria-label="Today">'
            f'<div class="k-sh"><div><span class="eyebrow">Today · from the {E(fmt_d(FL["asof"]))} close</span><h2>{E(act)}</h2></div><p>{E(why)}</p></div>'
            f'<div class="t-grid">{st_html}{levels_html(TR, M, B)}{catalysts_html(CAT, t)}{note_html}</div>{foot}</section>')


def strip_html(M, B, FL):
    """One quiet line under the nav: the call, nothing else. Full detail lives in the Today section further down."""
    if not (M and B and FL): return ''
    act = flagship_action(FL)[0]
    inv = round((1 - FL['weights'].get('CASH', 0)) * 100)
    sl, bl = lab(st3(M['regime'], M.get('exposure_map'))), lab(st3(B['regime'], B.get('exposure_map')))
    return (f'<div class="k-strip" role="status"><span><span class="dot" aria-hidden="true"></span>{E(fmt_d(FL["asof"]))} close</span>'
            f'<span><b>{E(act)}</b></span><span>Flagship <b>{inv}%</b> invested</span>'
            f'<span class="x">Stocks <b>{E(sl)}</b></span><span class="x">Bitcoin <b>{E(bl)}</b></span>'
            f'<a href="index.html#today">Today’s detail ↓</a></div>')


def calls_table(rows, n=None, live_since=None):
    rs = sorted(rows, key=lambda r: r['date'], reverse=True)
    closed = [r for r in rs if not r['open']]
    if n:   # the latest n from each desk, so a busy desk does not crowd out a quiet one
        rs = sorted([r for d in {x['asset'] for x in rs} for r in [x for x in rs if x['asset'] == d][:n]], key=lambda r: r['date'], reverse=True)
    tr = ''
    for r in rs:
        bt = live_since and r['date'] < live_since
        res = ('<span class="label">open</span>' if r['open'] else '<span class="label">flat</span>' if r['flat'] else
               (f'<span class="ok">helped {pct_s(r["effect"])}</span>' if r['helped'] else f'<span class="bad">cost {pct_s(r["effect"])}</span>'))
        tr += (f'<tr><td>{E(fmt_d(r["date"]))}{" <span class=label>backtest</span>" if bt else ""}</td><td>{E(r["asset"])}</td>'
               f'<td>{E(lab(r["from"]))} → <b style="color:var(--ink);font-weight:500">{E(lab(r["state"]))}</b></td>'
               f'<td class="n">{money(r["price"], r["asset"])}</td><td class="n">{pct_s(r["move"])}</td><td class="n">{days_between(r["date"], r["end_date"])}d</td><td>{res}</td></tr>')
    def med(xs):
        xs = sorted(x['effect'] for x in xs); n_ = len(xs)
        return 0 if not n_ else (xs[n_ // 2] if n_ % 2 else (xs[n_ // 2 - 1] + xs[n_ // 2]) / 2)
    summ = ''
    for desk in sorted({r['asset'] for r in closed}, key=lambda d: (not d.startswith('Stocks'), d)):
        c = [r for r in closed if r['asset'] == desk]; H = [r for r in c if r['helped']]; C = [r for r in c if not r['helped'] and not r['flat']]
        summ += (f'<div class="sum"><span><b>{E(desk)}</b> · {len(c)} completed calls since {E(c[-1]["date"][:4])}</span>'
                 f'<span><b>{len(H)}</b> helped · <b>{len(C)}</b> cost · <b>{len(c) - len(H) - len(C)}</b> flat</span>'
                 f'<span>Typical helped call <b>{pct_s(med(H))}</b> · typical costly call <b>{pct_s(med(C))}</b></span></div>')
    return (summ + '<div class="tblwrap"><table><thead><tr><th>Date</th><th>Desk</th><th>Change</th><th class="n">Price at call</th>'
            '<th class="n">Price move until next call</th><th class="n">Lasted</th><th>Effect</th></tr></thead><tbody>' + tr + '</tbody></table></div>')


CALLS_NOTE = ('Each call is scored against leaving the sleeve where it was: the change in exposure times the price move until the next call. '
              'Cutting from 100% to 50% before a 10% fall scores +5%; doing it before a 10% rise scores −5%. Moves under 0.05% count as flat. '
              'Trend models are usually wrong more often than right and earn their keep on a few large moves, so compare the typical (median) size of each, not only the counts. T-bill interest is left out. '
              'Rows marked backtest are the current rules run over past data, not calls published at the time.')


def all_calls(M, B):
    return (calls('stocks/history.csv', 'spy', (M or {}).get('exposure_map'), 'Stocks · SPY', '2003-01-01')
            + calls('bitcoin/history.csv', 'price', (B or {}).get('exposure_map'), 'Bitcoin', '2015-01-01'))


def calls_section(M, B, FL, n=4):
    rows = all_calls(M, B)
    if not rows: return ''
    return ('<section class="sec k-calls" id="calls" aria-label="Recent calls, scored"><div class="k-sh"><div><span class="eyebrow">Accountability</span>'
            '<h2>Recent calls, scored</h2></div><p>Every change of state, the price when it was made, and what the market did before the next change. '
            '<a href="methodology.html#calls" style="color:var(--ink)">Every call since 2003 →</a></p></div>'
            + calls_table(rows, n, (FL or {}).get('live_since')) + f'<p class="note">{CALLS_NOTE}</p></section>')


def notes_body():
    fs = sorted(_glob.glob(p('weekly', '*.json')), reverse=True); arts = ''
    for f in fs:
        try: n = json.load(open(f, encoding='utf-8'))
        except Exception: continue
        arts += (f'<article id="w{E(n["date"])}"><span class="eyebrow">Week to {E(fmt_d(n["date"]))}</span><h2>{E(n.get("title", "Weekly note"))}</h2>'
                 + ''.join(f'<p>{E(x)}</p>' for x in n.get('body', [])) + '</article>')
    if not arts: arts = '<p class="note">The first weekly note will appear here.</p>'
    return ('  <section class="intro"><span class="eyebrow">Weekly notes</span><h1 class="k-display" style="font-size:clamp(44px,6vw,76px);line-height:1;margin:.2em 0">The week in plain words</h1>'
            '<p style="max-width:60ch;color:var(--ink-2)">Each weekend: what moved, what the desks did and why, and what is coming next. Written from the models’ own reports. Not investment advice.</p></section>\n'
            f'  <section class="sec k-notes">{arts}</section>')


def rfc822(d):
    return dt.datetime.combine(dt.date.fromisoformat(d[:10]), dt.time(14, 30)).strftime('%a, %d %b %Y %H:%M:%S +0000')


def make_feed(M, B, FL):
    items = []
    live = (FL or {}).get('live_since') or '2026-10-26'
    for r in all_calls(M, B):
        if r['date'] < live: continue
        items.append((r['date'], f'{r["asset"].split(" ·")[0]} desk: {lab(r["from"])} → {lab(r["state"])}',
                      f'On the {fmt_d(r["date"])} close the {r["asset"]} desk moved from {lab(r["from"])} to {lab(r["state"])} at {money(r["price"], r["asset"])}. '
                      'The flagship acts at the next close. Hypothetical model, not investment advice.', f'{SITE}/', f'call-{r["asset"][:3]}-{r["date"]}'))
    for f in sorted(_glob.glob(p('weekly', '*.json'))):
        try: n = json.load(open(f, encoding='utf-8'))
        except Exception: continue
        items.append((n['date'], 'Weekly note: ' + n.get('title', ''), ' '.join(n.get('body', [])), f'{SITE}/notes.html#w{n["date"]}', f'week-{n["date"]}'))
    if M:
        items.append((M['asof'], f'Daily: stocks {lab(st3(M["regime"], M.get("exposure_map")))}, Bitcoin {lab(st3(B["regime"], B.get("exposure_map"))) if B else "—"}',
                      flagship_action(FL)[0] + '. ' + flagship_action(FL)[1], f'{SITE}/#today', f'daily-{M["asof"]}'))
    items.sort(key=lambda x: x[0], reverse=True)
    body = ''.join(f'<item><title>{E(t)}</title><link>{E(l)}</link><guid isPermaLink="false">{E(g)}</guid><pubDate>{rfc822(d)}</pubDate><description>{E(s)}</description></item>\n'
                   for d, t, s, l, g in items[:40])
    wr('feed.xml', f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{NAME}</title><link>{SITE}/</link>'
       f'<description>Daily rules-based regime calls for US stocks and Bitcoin, the flagship model portfolio, and weekly notes. Hypothetical models, not investment advice.</description>'
       f'<language>en-us</language>\n{body}</channel></rss>\n')


def _spark(vals, lines, w=300, h=64):
    vs = [v for v in vals if v is not None]
    lo, hi = min(vs + [l for l, _ in lines]) - .03, max(vs + [l for l, _ in lines]) + .03
    X = lambda i: i / max(1, len(vals) - 1) * w; Y = lambda v: (1 - (v - lo) / ((hi - lo) or 1)) * h
    pts = ' '.join(f'{X(i):.1f},{Y(v):.1f}' for i, v in enumerate(vals) if v is not None)
    ln = ''.join(f'<line x1="0" x2="{w}" y1="{Y(l):.1f}" y2="{Y(l):.1f}" stroke="#858B90" stroke-width="1" stroke-dasharray="2 3" opacity=".7" vector-effect="non-scaling-stroke"/>' for l, t in lines)
    last = f'<circle vector-effect="non-scaling-stroke" cx="{X(len(vals) - 1):.1f}" cy="{Y(vals[-1]):.1f}" r="3" fill="#B9A98A"/>' if vals and vals[-1] is not None else ''
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" height="{h}" preserveAspectRatio="none" aria-hidden="true" style="overflow:visible">{ln}'
            f'<polyline points="{pts}" fill="none" stroke="#E7E4DC" stroke-width="1.4" vector-effect="non-scaling-stroke"/>{last}</svg>')


def momentum_cards(M, B, TR):
    out = []
    for name, path, R, cut_lines, link in [
        ('US stocks', 'stocks/history.csv', M, None, 'stocks.html'), ('Bitcoin', 'bitcoin/history.csv', B, None, 'bitcoin.html')]:
        if not R: continue
        rows = [r for r in _rows(path) if _f(r.get('score')) is not None]
        if len(rows) < 25: continue
        sc = [_f(r['score']) for r in rows]; now = sc[-1]
        d1, d5, d20 = now - sc[-2], now - sc[-6], now - sc[-21]
        th = R['thresholds']; expo = R['exposure']
        if name == 'US stocks':
            lines = [(th['bear'], f'{th["bear"]:+.2f} cut to 50%')]
            near = [(th['bear'], 'the cut line', 'Balanced (50%)' if expo >= .99 else 'Risk On (100%)')]
        else:
            lines = [(th['bull'], f'{th["bull"]:+.2f} to 100%'), (th['bear'], f'{th["bear"]:+.2f} to 0%')]
            near = ([(th['bull'], 'the Risk On line', 'Risk On (100%)')] if expo < .99 else []) + ([(th['bear'], 'the cut line', 'Risk Off, or 50% in a deep drawdown')] if expo > 0 else [])
        dirn = 'strengthening' if d5 > .02 else 'weakening' if d5 < -.02 else 'holding steady'
        dist = ''.join(f'<li><span class="mono">{now - l:+.3f}</span>from {E(t)} ({l:+.2f}) → {E(to)}</li>' for l, t, to in near)
        pace = ''
        tgt = min(near, key=lambda x: abs(now - x[0])) if near else None
        if tgt and d5 and (tgt[0] - now) * d5 > 0:
            n = abs(tgt[0] - now) / abs(d5 / 5)
            if n < 120: pace = f'<p class="t-fine">At the last five sessions’ pace the score would reach {E(tgt[1])} in about {n:.0f} sessions. Arithmetic, not a forecast: scores rarely move in straight lines.</p>'
        state = lab(st3(R['regime'], R.get('exposure_map')))
        cls = lambda v: 'ok' if v > .005 else 'bad' if v < -.005 else ''
        out.append(f'<div class="km-card"><div class="km-h"><span class="label">{E(name)}</span><a href="{link}">{E(state)} · {round(expo * 100)}%</a></div>'
                   f'<div class="km-now"><b>{now:+.3f}</b><span>score, {E(dirn)}</span></div>'
                   f'<div class="km-d"><span>1 day <b class="{cls(d1)}">{d1:+.3f}</b></span><span>5 days <b class="{cls(d5)}">{d5:+.3f}</b></span><span>20 days <b class="{cls(d20)}">{d20:+.3f}</b></span></div>'
                   f'{_spark(sc[-90:], lines)}<span class="t-fine" style="display:block;margin-top:2px">Last 90 sessions · dashed: ' + ' · '.join(E(t) for _, t in lines) + '</span>'
                   f'<ul class="km-l">{dist}</ul>{pace}</div>')
    return ''.join(out)


MOM_CSS = """<style id="k-mom">
.k-mom .km-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;margin-top:var(--s-5,24px)}
.k-mom .km-card{display:grid;gap:12px;align-content:start;padding:0 32px 0 0}
.k-mom .km-card+.km-card{padding:0 0 0 32px;border-left:1px solid var(--hair)}
@media (max-width:760px){.k-mom .km-grid{grid-template-columns:1fr}.k-mom .km-card+.km-card{padding:24px 0 0;border-left:0;border-top:1px solid var(--hair);margin-top:24px}.k-mom .km-card{padding-right:0}}
.k-mom .km-h{display:flex;justify-content:space-between;align-items:baseline;gap:12px}
.k-mom .km-h a{font-size:13px;color:var(--ink);text-decoration:none;border-bottom:1px solid var(--hair)}
.k-mom .km-now{display:flex;align-items:baseline;gap:12px}
.k-mom .km-now b{font-family:var(--f-serif);font-weight:400;font-size:clamp(36px,4vw,48px);line-height:1;color:var(--ink)}
.k-mom .km-now span{font-size:14px;color:var(--ink-2)}
.k-mom .km-d{display:flex;flex-wrap:wrap;gap:6px 22px;font-size:12.5px;color:var(--muted)}
.k-mom .km-d b{font-family:var(--f-num);font-weight:400;color:var(--ink);margin-left:6px}
.k-mom .km-d b.ok{color:var(--sage)} .k-mom .km-d b.bad{color:#A9705F}
.k-mom ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.k-mom li{font-size:13.5px;color:var(--ink-2)} .k-mom li .mono{color:var(--ink);margin-right:8px}
.k-mom .t-fine{font-size:12px;color:var(--muted);margin:0}
</style>"""


def momentum_section(M, B, TR, eyebrow='Regime momentum'):
    cards = momentum_cards(M, B, TR)
    if not cards: return ''
    return (f'<section class="sec k-mom" id="momentum" aria-label="Regime momentum"><div class="k-sh"><div><span class="eyebrow">{E(eyebrow)}</span>'
            '<h2>Which way the desks are leaning</h2></div><p>How each desk’s score has moved over 1, 5 and 20 sessions, and how far it is from a change in exposure. '
            'A desk can stay in the same state while its score drifts toward a line; this shows the drift before the call changes. Scores are 5-day smoothed.</p></div>'
            f'<div class="km-grid">{cards}</div></section>')


def put_block(s, id_, html_, before_re):
    """Insert (or replace) a pre-rendered block right before the first match of before_re."""
    s = re.sub(r'<!--pre:' + id_ + r'-->.*?<!--/pre:' + id_ + r'-->', '', s, flags=re.S)
    if not html_: return s
    m = re.search(before_re, s)
    return s if not m else s[:m.start()] + pre_block(id_, html_) + s[m.start():]


def retail(s, f, M, B, FL):
    TR, CAT = jload('triggers.json'), jload('catalysts.json')
    s = re.sub(r'\n?<style id="k-retail">.*?</style>', '', s, flags=re.S).replace('</head>', RETAIL_CSS + '\n</head>', 1)
    s = s.replace('<link rel="alternate" type="application/rss+xml" title="Kerdos Capital" href="feed.xml">\n', '')
    s = s.replace('</head>', '<link rel="alternate" type="application/rss+xml" title="Kerdos Capital" href="feed.xml">\n</head>', 1)
    s = re.sub(r'\n?<style id="k-mom">.*?</style>', '', s, flags=re.S)
    if f in ('stocks.html', 'bitcoin.html'):
        s = put_block(s, 'sim', sim_section(f.split('.')[0]), r'<section class="sec ox-wrap"|<footer class="foot pub">')
    if f == 'index.html':
        s = put_block(s, 'strip', strip_html(M, B, FL), r'<section class="k-hero-home"')
        s = put_block(s, 'today', today_block(M, B, FL, TR, CAT), r'<section class="sec" aria-label="The research desks"')
        s = re.sub(r'<!--pre:momentum-->.*?<!--/pre:momentum-->', '', s, flags=re.S)
        s = put_block(s, 'calls', calls_section(M, B, FL), r'<section class="sec" id="integrity"')
    if f == 'flagship.html':
        s = re.sub(r'<!--pre:today-->.*?<!--/pre:today-->', '', s, flags=re.S)
        s = put_block(s, 'strip', strip_html(M, B, FL), r'<section')
    if f == 'methodology.html':
        rows = all_calls(M, B)
        if rows:
            sec = ('<section class="sec k-calls" id="calls" aria-label="Every call, scored"><div class="k-sh"><div><span class="eyebrow">08 · Call record</span>'
                   '<h2>Every call, scored</h2></div><p>Every change of state on the stocks desk since 2003 and the Bitcoin desk since 2015.</p></div>'
                   + calls_table(rows, None, (FL or {}).get('live_since')) + f'<p class="note">{CALLS_NOTE}</p></section>')
            s = put_block(s, 'calls', sec, r'<section class="sec" id="limits"|<footer class="foot pub">')
    return s


# Scenario simulator, placed on stocks.html and bitcoin.html (one desk each). Data: sim/sim.json from tools/triggers.py.
SIM_SECTION = r'''<section class="sec kt" id="sim" aria-label="Scenario simulator">
    <div class="k-sh"><div><span class="eyebrow">Scenario simulator</span><h2>What would it take?</h2></div>
    <p>Move __TK__’s price or one of the desk’s inputs and see how its score, and the exposure it implies, would respond. Prices are run through the desk’s own model each morning; other inputs are recomputed here with the model’s published weights. Hypothetical and educational, not investment advice.</p></div>
    <div class="kt-sim">
      <div class="kt-ctl" id="sim-ctl"><p class="note">Loading the simulator…</p></div>
      <div class="kt-out" id="sim-out"></div>
    </div>
  </section>
<style>
.kt-tabs{display:inline-flex;justify-self:start;width:max-content;gap:0;border:1px solid var(--hair);border-radius:99px;padding:3px;margin:var(--s-5,24px) 0 0}
.kt-tabs button{font-family:var(--f-ui);font-size:13px;color:var(--ink-2);background:none;border:0;border-radius:99px;padding:6px 14px;cursor:pointer}
.kt-tabs button.on{background:var(--panel);color:var(--ink);box-shadow:inset 0 0 0 1px var(--hair)}
.kt-sim{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:0;margin-top:22px;border-top:1px solid var(--hair)}
.kt-ctl{min-width:0;padding:22px 28px 0 0;display:grid;gap:16px;align-content:start}
.kt-out{min-width:0;padding:22px 0 0 28px;border-left:1px solid var(--hair);display:grid;gap:14px;align-content:start}
@media (max-width:820px){.kt-sim{grid-template-columns:1fr}.kt-ctl{padding-right:0}.kt-out{padding-left:0;border-left:0;border-top:1px solid var(--hair);margin-top:22px}}
.kt-in{display:grid;gap:6px;min-width:0}
.kt-in select{width:100%;max-width:100%;min-width:0}
.kt-in .h{display:flex;flex-wrap:wrap;justify-content:space-between;gap:2px 12px;font-size:13.5px;color:var(--ink)}
.kt-in .h span:last-child{font-family:var(--f-num);color:var(--ink-2);white-space:nowrap}
.kt-in .h span.moved{color:var(--sage)}
.kt-in .d{font-size:12px;color:var(--muted);line-height:1.45}
.kt-in input[type=range]{width:100%;accent-color:#B9A98A}
.kt-in select,.kt-f input,.kt-f select{font-family:var(--f-num);font-size:13px;background:var(--panel);color:var(--ink);border:1px solid var(--hair);border-radius:4px;padding:6px 8px}
.kt-big{font-family:var(--f-serif);font-size:clamp(40px,5vw,60px);line-height:1;color:var(--ink)}
.kt-big small{font-family:var(--f-ui);font-size:14px;color:var(--ink-2);margin-left:10px}
.kt-gauge{position:relative;height:36px;margin:6px 0 4px}
.kt-gauge .bar{position:absolute;left:0;right:0;top:16px;height:2px;background:var(--hair)}
.kt-gauge .ln{position:absolute;top:8px;width:1px;height:18px;background:var(--muted)}
.kt-gauge .ln span{position:absolute;top:20px;left:50%;transform:translateX(-50%);font-family:var(--f-num);font-size:10.5px;color:var(--muted);white-space:nowrap}
.kt-gauge .mk{position:absolute;top:11px;width:12px;height:12px;margin-left:-6px;border-radius:50%;background:#B9A98A;box-shadow:0 0 0 3px var(--bg,#111315)}
.kt-gauge .mk.t{background:var(--bg,#111315);border:1.5px solid var(--ink-2);width:10px;height:10px;margin-left:-5px;top:12px}
.kt-tbl{width:100%;border-collapse:collapse;font-size:13px}
.kt-tbl th{font-family:var(--f-ui);font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);font-weight:500;text-align:left;padding:6px 8px;border-bottom:1px solid var(--hair)}
.kt-tbl td{padding:7px 8px;border-bottom:1px solid var(--hair);color:var(--ink-2)}
.kt-tbl td.n,.kt-tbl th.n{text-align:right;font-family:var(--f-num)}
.kt-tbl .up{color:var(--sage)} .kt-tbl .dn{color:#A9705F}
.kt-row{display:flex;flex-wrap:wrap;align-items:center;gap:12px 18px;margin-top:18px}
.kt-f{display:inline-flex;align-items:center;gap:8px;font-size:13px;color:var(--ink-2)}
.kt-f input[type=number]{width:72px}
.kt-btn{font-family:var(--f-ui);font-size:13px;color:var(--ink);background:none;border:1px solid var(--hair);border-radius:99px;padding:6px 14px;cursor:pointer}
.kt-btn:hover{border-color:#B9A98A}
.kt-pre button{font-family:var(--f-ui);font-size:12.5px;color:var(--ink-2);background:none;border:0;border-bottom:1px solid var(--hair);padding:0 0 2px;cursor:pointer}
.kt-pre button:hover{color:var(--ink);border-color:#B9A98A}
.kt-chart{margin-top:16px;border-top:1px solid var(--hair);padding-top:12px}
.kt-chart canvas{width:100%;display:block}
.kt-read{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px 24px;margin-top:16px;padding-top:14px;border-top:1px solid var(--hair)}
.kt-read div{display:grid;gap:4px} .kt-read b{font-family:var(--f-num);font-weight:400;color:var(--ink);font-size:15px}
.kt-badge{grid-column:1/-1;font-size:12.5px;color:var(--ink-2);padding:8px 12px;border-left:2px solid var(--muted)}
.kt-badge.pub{border-color:#B9A98A;color:var(--ink)}
.kt-grid2{display:grid;grid-template-columns:1fr 1fr;gap:0;margin-top:20px;border-top:1px solid var(--hair)}
.kt-grid2>div{padding:18px 24px 0 0}.kt-grid2>div+div{padding:18px 0 0 24px;border-left:1px solid var(--hair)}
@media (max-width:820px){.kt-grid2{grid-template-columns:1fr}.kt-grid2>div+div{padding-left:0;border-left:0;border-top:1px solid var(--hair);margin-top:18px}}
.kt-alloc{display:grid;gap:8px}
.kt-alloc .r{display:grid;grid-template-columns:110px 1fr 54px;gap:10px;align-items:center;font-size:13px;color:var(--ink-2)}
.kt-alloc .r i{display:block;height:6px;background:#B9A98A;border-radius:1px} .kt-alloc .r i.c{background:#555B60}
.kt-alloc .r b{font-family:var(--f-num);font-weight:400;color:var(--ink);text-align:right}
</style>
<script>
(()=>{
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const J=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(u+' '+r.status);return r.json()});
const T=u=>fetch(u).then(r=>{if(!r.ok)throw new Error(u+' '+r.status);return r.text()});
const csv=t=>{const[h,...r]=t.trim().split(/\r?\n/);const k=h.split(',');return r.map(x=>{const c=x.split(',');const o={};k.forEach((kk,i)=>o[kk]=c[i]);return o})};
const MON=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const fd=d=>{const t=new Date(d+'T00:00:00Z');return MON[t.getUTCMonth()]+' '+t.getUTCDate()+', '+t.getUTCFullYear()};
const pc=(v,d=1)=>(v>0?'+':v<0?'−':'')+Math.abs(v*100).toFixed(d)+'%';
const sgn=(v,d=2)=>(v>0?'+':v<0?'−':'')+Math.abs(v).toFixed(d);
const usd=(v,d=2)=>'$'+Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const PUBLISHED='2026-10-28';
const EMAP={stocks:{Bullish:1,Neutral:1,Recovery:1,Correction:.5,Bearish:0},bitcoin:{Bullish:1,Recovery:1,Neutral:.5,Correction:.5,Bearish:0}};
const LAB=e=>e>=.99?'Risk On':e>0?'Balanced':'Risk Off';
const COLS={on:'rgba(185,169,138,.16)',bal:'rgba(133,139,144,.26)',off:'rgba(169,112,95,.16)'};
const cssv=(n,f)=>getComputedStyle(document.documentElement).getPropertyValue(n).trim()||f;
const INK=cssv('--ink','#E7E4DC'),INK2=cssv('--ink-2','#A3A5A3'),MUT=cssv('--muted','#858B90'),HAIR='rgba(85,91,96,.45)',SAGE='#B9A98A',RUST='#A9705F';
function canvas(cv){const r=window.devicePixelRatio||1,w=cv.clientWidth,h=+cv.getAttribute('height');cv.width=w*r;cv.height=h*r;cv.style.height=h+'px';const c=cv.getContext('2d');c.setTransform(r,0,0,r,0,0);c.font='11px '+cssv('--f-num','monospace');return [c,w,h]}

// ---------------------------------------------------------------- 2. scenario simulator
const tanh=Math.tanh;
const INPUTS={
 stocks:[
  {id:'mom',label:'Momentum: 3- and 6-month SPY return',keys:['f_mom63','f_mom126'],type:'range',min:-30,max:30,step:1,unit:'%',
   to:v=>[tanh(v/100/.06),tanh(v/100*1.6/.08)],from:s=>Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*6,fmt:v=>`${v>0?'+':''}${v.toFixed(0)}% over 3 months`,
   d:'Sets both momentum readings (the 6-month return is taken as 1.6× the 3-month). Overrides what the price slider implies.'},
  {id:'infl',label:'Inflation (CPI, year over year)',keys:['f_infl'],type:'select',opts:[['Under 4%',0],['4% to 6%',-.5],['Over 6%',-1]],d:'The model only penalizes inflation above 4%.'},
  {id:'fed',label:'Fed: change in the 3-month T-bill over 6 months',keys:['f_fed'],type:'select',opts:[['Steady, or cut less than 0.30 pt',0],['Cut 0.30 to 0.75 pt',-.5],['Cut more than 0.75 pt',-1]],d:'Fast cuts read as bearish: historically they have come with slowdowns.'},
  {id:'curve',label:'Yield curve (10-year minus 3-month)',keys:['f_curve'],type:'select',opts:[['Normal, no recent inversion',0],['Inverted',-.25],['Un-inverted within the last 2 years',-1]],d:'The model reads the un-inversion after an inverted curve as the warning.'},
  {id:'spread',label:'Corporate credit spreads, change over 3 months',keys:['f_spread'],type:'range',min:-.75,max:.75,step:.05,unit:'pt',
   to:v=>[tanh(-v/.25)],from:s=>-Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*.25,fmt:v=>`${v>0?'+':''}${v.toFixed(2)} pt (Baa − 10y)`,d:'Widening spreads (positive) are bearish.'},
  {id:'labor',label:'Unemployment trend (Sahm-style gap)',keys:['f_labor'],type:'select',opts:[['Under 0.3 pt',0],['0.3 to 0.5 pt',-.5],['0.5 pt or more',-1]],d:'A rising jobless rate is the classic recession signal.'},
  {id:'vol',label:'Realized volatility (21-day, annualized)',keys:['f_rvol'],type:'range',min:6,max:60,step:1,unit:'%',
   to:v=>[tanh(-(v/100-.17)/.08)],from:s=>(.17-Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*.08)*100,fmt:v=>`${v.toFixed(0)}%`,d:'Calm markets score positive; turbulent ones negative.'}
 ],
 bitcoin:[
  {id:'mom',label:'Momentum: 30- and 90-day Bitcoin return',keys:['f_mom30','f_mom90'],type:'range',min:-50,max:80,step:1,unit:'%',
   to:v=>[tanh(v/100/.15),tanh(v/100*1.5/.30)],from:s=>Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*15,fmt:v=>`${v>0?'+':''}${v.toFixed(0)}% over 30 days`,
   d:'Sets both momentum readings (the 90-day return is taken as 1.5× the 30-day). Overrides what the price slider implies.'},
  {id:'dollar',label:'US dollar (UUP), change over 3 months',keys:['f_dollar'],type:'range',min:-8,max:8,step:.5,unit:'%',
   to:v=>[tanh(-v/100/.03)],from:s=>-Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*3,fmt:v=>`${v>0?'+':''}${v.toFixed(1)}%`,d:'A falling dollar has been good for Bitcoin.'},
  {id:'rates',label:'Long Treasuries (TLT), change over 3 months',keys:['f_rates'],type:'range',min:-15,max:15,step:.5,unit:'%',
   to:v=>[tanh(v/100/.06)],from:s=>Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*6,fmt:v=>`${v>0?'+':''}${v.toFixed(1)}%`,d:'TLT rises when long-term interest rates fall.'},
  {id:'credit',label:'High-yield credit (HYG), change over 3 months',keys:['f_credit'],type:'range',min:-10,max:6,step:.5,unit:'%',
   to:v=>[tanh(v/100/.03)],from:s=>Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*3,fmt:v=>`${v>0?'+':''}${v.toFixed(1)}%`,d:'Risk appetite in credit tends to lead crypto.'},
  {id:'liq',label:'Fed net liquidity, change over 3 months',keys:['f_liq'],type:'range',min:-10,max:10,step:.5,unit:'%',
   to:v=>[tanh(v/100/.04)],from:s=>Math.atanh(Math.max(-.999,Math.min(.999,s[0])))*4,fmt:v=>`${v>0?'+':''}${v.toFixed(1)}%`,d:'Balance sheet minus the Treasury account and reverse repos.'}
 ]};
let SIM=null, sdesk='__DESK__', S={}, RS=null, RB=null;
function groupsOf(spec,f){const g={};for(const k in spec.factors){const v=f[k];if(v==null||isNaN(v))continue;const G=spec.factors[k].group;(g[G]=g[G]||[0,0]);g[G][0]+=v*spec.factors[k].w;g[G][1]+=spec.factors[k].w}
  const o={};for(const G in g)o[G]=g[G][1]?g[G][0]/g[G][1]:null;return o}
function scoreOf(spec,g){let n=0,d=0;for(const G in spec.groups){if(g[G]==null)continue;n+=g[G]*spec.groups[G];d+=spec.groups[G]}return d?n/d:null}
function steady(desk,spec,raw,g,pt){ // the state rules with smoothing and confirmation left out
  if(raw==null)return null;
  if(desk==='stocks'){if(raw>=spec.dn)return 1;return (g.macro!=null&&g.macro<=spec.gate)?0:.5}
  if(raw>spec.up)return 1;if(raw<spec.dn)return pt.deep?.5:0;return .5}
function simUI(){
  const D=SIM[sdesk];if(!D){$('#sim-ctl').innerHTML='<p class="note">No scenario data for this desk yet.</p>';$('#sim-out').innerHTML='';return}
  const G=D.grid,i0=G.findIndex(p=>Math.abs(p.r-1)<1e-6);S={pi:i0,set:{}};
  const tk=sdesk==='stocks'?'SPY':'BTC',dd=sdesk==='stocks'?2:0;
  let h=`<div class="kt-in"><div class="h"><span>${tk} price, held for ${SIM.hold_sessions} sessions</span><span id="sim-pv"></span></div>
    <input type="range" id="sim-p" min="0" max="${G.length-1}" step="1" value="${i0}" aria-label="${tk} price">
    <div class="d">Each step is a full run of the desk’s model at that price, with every other market input held at today’s reading.</div></div>`;
  for(const q of INPUTS[sdesk]){
    const cur=q.keys.map(k=>G[i0].factors[k]);
    if(q.type==='select'){const near=q.opts.reduce((b,o,j)=>Math.abs(o[1]-(cur[0]??0))<Math.abs(q.opts[b][1]-(cur[0]??0))?j:b,0);
      h+=`<div class="kt-in"><div class="h"><span>${q.label}</span><span id="v-${q.id}">today</span></div><select id="i-${q.id}">${q.opts.map((o,j)=>`<option value="${j}"${j===near?' selected':''}>${o[0]}${j===near?' (today)':''}</option>`).join('')}</select><div class="d">${q.d}</div></div>`}
    else{const v0=Math.max(q.min,Math.min(q.max,q.from(cur)));
      h+=`<div class="kt-in"><div class="h"><span>${q.label}</span><span id="v-${q.id}">${q.fmt(v0)} · today</span></div><input type="range" id="i-${q.id}" min="${q.min}" max="${q.max}" step="${q.step}" value="${v0}"><div class="d">${q.d}</div></div>`}}
  h+=`<div><button class="kt-btn" id="sim-reset">Reset to today</button></div>`;
  $('#sim-ctl').innerHTML=h;
  $('#sim-p').oninput=e=>{S.pi=+e.target.value;simRun()};
  for(const q of INPUTS[sdesk]){const el=$('#i-'+q.id);el.oninput=()=>{S.set[q.id]=q.type==='select'?q.opts[+el.value][1]:+el.value;
    const lab=$('#v-'+q.id);lab.textContent=q.type==='select'?'changed':q.fmt(+el.value);lab.classList.add('moved');simRun()}}
  $('#sim-reset').onclick=simUI;simRun()}
function simRun(){
  const D=SIM[sdesk],spec=D.spec,G=D.grid,pt=G[S.pi],t0=G.find(p=>Math.abs(p.r-1)<1e-6)||pt,dd=sdesk==='stocks'?2:0;
  $('#sim-pv').textContent=`${usd(pt.price,dd)} · ${pt.r===1?'today':pc(pt.r-1)}`;$('#sim-pv').classList.toggle('moved',pt.r!==1);
  const f={...pt.factors};let touched=false;
  for(const q of INPUTS[sdesk]){if(!(q.id in S.set))continue;touched=true;const v=S.set[q.id];const s=q.type==='select'?[v]:q.to(v);q.keys.forEach((k,j)=>f[k]=s[Math.min(j,s.length-1)])}
  const g=touched?groupsOf(spec,f):pt.groups, raw=touched?scoreOf(spec,g):pt.raw;
  const expo=touched?steady(sdesk,spec,raw,g,pt):pt.exposure, today=t0.exposure;
  const lo=Math.min(-.6,spec.dn-.15),hi=Math.max(.6,spec.up+.15),X=v=>((Math.max(lo,Math.min(hi,v))-lo)/(hi-lo)*100).toFixed(2)+'%';
  const how=touched?'Steady-state estimate: these readings held long enough for the model’s 5-day smoothing and 3-day confirmation to catch up. Recovery and rebound rules are left out.'
    :`Exact: the desk’s own model run with ${pt.r===1?'today’s close':'this close'} held for ${SIM.hold_sessions} sessions and every other input at today’s reading.`;
  const chg=expo===today?'Same as today':expo<today?`Down from ${Math.round(today*100)}% today`:`Up from ${Math.round(today*100)}% today`;
  const NM={trend:'Trend',momentum:'Momentum',internals:'Internals',macro:'Macro',volatility:'Volatility',calendar:'Calendar',valuation:'Valuation',cycle:'Cycle'};
  const rows=Object.keys(spec.groups).map(k=>{const a=t0.groups[k],b=g[k];const d=(b??0)-(a??0);return `<tr><td>${NM[k]||k}</td><td class="n">${Math.round(spec.groups[k]*100)}%</td><td class="n">${a==null?'—':sgn(a)}</td><td class="n ${Math.abs(d)<.005?'':d>0?'up':'dn'}">${b==null?'—':sgn(b)}</td></tr>`}).join('');
  const pubS=(sdesk==='stocks'?RS:RB)?.score;const smoothNote=(!touched&&pt.smooth!=null?` · smoothed ${sgn(pt.smooth,3)}`:'')+(pubS!=null?` · today’s published score ${sgn(pubS,3)}`:'');
  $('#sim-out').innerHTML=`<span class="label">Implied exposure</span><div class="kt-big">${Math.round(expo*100)}%<small>${LAB(expo)} · ${chg}</small></div>
   <div><span class="label">Score ${sgn(raw,3)}${smoothNote}</span><div class="kt-gauge"><div class="bar"></div>
   <div class="ln" style="left:${X(spec.dn)}"><span>${sgn(spec.dn)} cut</span></div><div class="ln" style="left:${X(spec.up)}"><span>${sgn(spec.up)}${sdesk==='bitcoin'?' full':' bull'}</span></div>
   <div class="mk t" style="left:${X((sdesk==='stocks'?RS:RB)?.score??t0.raw)}" title="today"></div><div class="mk" style="left:${X(raw)}" title="scenario"></div></div></div>
   <p class="note" style="margin:0">${how}${sdesk==='stocks'?' Below the cut line the stocks desk goes to 50%, and to 0% only if the macro group is at or below '+spec.gate+'.':' Below the cut line Bitcoin goes to 0%, or holds 50% during a deep drawdown.'}</p>
   <table class="kt-tbl"><thead><tr><th>Group</th><th class="n">Weight</th><th class="n">At today’s price</th><th class="n">Scenario</th></tr></thead><tbody>${rows}</tbody></table>`}

// ---------------------------------------------------------------- load
Promise.all([J('sim/sim.json'),J('__DESK__/report.json')]).then(([sim,rep])=>{SIM=sim||{};if(sdesk==='stocks')RS=rep;else RB=rep;simUI()})
.catch(e=>{const el=$('#sim-ctl');if(el)el.innerHTML=`<p class="note">The simulator data did not load (${e.message}). Reload the page to try again.</p>`});
})();
</script>'''


def sim_section(desk):
    return SIM_SECTION.replace('__DESK__', desk).replace('__TK__', 'SPY' if desk == 'stocks' else 'Bitcoin')


def main():
    M, B, G = jload('stocks/report.json'), jload('bitcoin/report.json'), jload('highbeta/report.json')
    FL = jload('flagship/report.json'); PF = jload('portfolio_backtest.json')
    global FOOT
    FOOT = ((M or {}).get('asof'), (FL or {}).get('live_since'))
    img_v = (M or {}).get('asof', dt.date.today().isoformat()).replace('-', '')
    try:
        if not exists('favicon.svg') or rd('favicon.svg') != ICON_SVG or not exists('favicon.ico') or not exists('apple-touch-icon.png'): make_icons()
    except Exception as e: print('icons skipped:', e)
    try: make_og(M, B, G, FL)
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
        npg = make_shell_page(idx, 'notes_body.html', notes_body())
        if npg: wr('notes.html', npg)
    for f in PAGES:
        if not exists(f): continue
        s = fix_page(f, rd(f), img_v)
        if f == 'index.html': s = prerender_index(s, M, B, G, FL)
        elif f == 'stocks.html' and M:
            s = prerender_loading(s, summary_line('US stocks', lab(st3(M['regime'], M.get('exposure_map'))), M['exposure'], f"SPY {usd(M['spy'])} ({sg(M['spy_chg']['d1'])}) · QQQ {usd(M['qqq'])}", M['asof']))
        elif f == 'bitcoin.html' and B:
            s = prerender_loading(s, summary_line('Bitcoin', lab(st3(B['regime'], B.get('exposure_map'))), B['exposure'], f"BTC {usd(B.get('price'), 0)}", B['asof']))
        elif f == 'highbeta.html' and G:
            s = prerender_loading(s, summary_line('High beta', lab(st3(G['regime'], G.get('exposure_map'))), G['exposure'], f"basket {G['level']:.2f}", G['asof']))
        elif f == 'flagship.html' and FL:
            s = prerender_loading(s, summary_line('Flagship portfolio', f"stocks desk {lab(st3(FL['stocks_regime'], FL.get('rules', {}).get('stocks_exposure')))}, Bitcoin desk {lab(st3(FL.get('btc_regime'), FL.get('rules', {}).get('btc_exposure'))) or '—'}", 1 - FL.get('weights', {}).get('CASH', 0), '60% stocks / 30% Bitcoin / 10% gold target', FL['asof']))
        try: s = retail(s, f, M, B, FL)
        except Exception as e: print(f'retail layer skipped on {f}:', type(e).__name__, e)
        wr(f, s)
    try: make_feed(M, B, FL)
    except Exception as e: print('feed.xml skipped:', e)
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
