#!/usr/bin/env python3
"""Post-sync build for kerdoscapital.xyz.

Run from the repository root after the daily sync has mirrored the claude.ai artifact:
    python3 tools/build.py

What it does (idempotent: running it twice gives the same files):
  1. index.html  - strips the document wrappers the artifact service adds, so <title>, meta, links and styles
                   sit in a real <head>.
  2. every page  - one managed block in <head>: favicon, canonical URL, description, Open Graph / Twitter tags,
                   theme colour; consistent titles; "Flagship" and "About" links in the nav and footer.
  3. first paint - today's numbers are written into the HTML (desk cards, portfolio table, track record, page
                   summaries), so the page shows real content before JavaScript loads and search engines can read
                   it. The page scripts still replace these with the full, live versions.
  4. assets      - og.png (share card with today's calls), robots.txt, sitemap.xml, favicons.
Only the Python standard library and Pillow are needed.
"""
import html, json, os, re, sys, datetime as dt

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
SITE = 'https://kerdoscapital.xyz'
NAME = 'Kerdos Capital'
TAG = 'Independent Quantitative Investment Research'
PAGES = {   # file: (title, description, nav label)
    'index.html': (f'{NAME} · {TAG}',
                   'Systematic strategies, market regime analysis and multi-asset portfolio construction. Rules-based models for US stocks, Bitcoin and high-beta tech, updated after every close, with their rules, backtests and limits published.', 'Overview'),
    'flagship.html': (f'Flagship Model · {NAME}',
                      'The Kerdos flagship multi-asset model: stocks, Treasuries, gold, Bitcoin and cash, allocated by market regime, compared with SPY and a 60/40 portfolio.', 'Flagship'),
    'portfolio.html': (f'Model Portfolio · {NAME}',
                       'A hypothetical 60/40 stocks and Bitcoin portfolio that follows the Kerdos desks, with its rules, an allocation calculator and a backtest.', 'Portfolio'),
    'stocks.html': (f'US Stocks Desk · {NAME}',
                    'Daily regime model for US stocks (SPY and QQQ): trend, momentum, internals, macro and volatility, with a backtest since 2003.', 'Stocks'),
    'bitcoin.html': (f'Bitcoin Desk · {NAME}',
                     'Daily regime model for Bitcoin: trend, momentum and macro signals, with a backtest since 2015.', 'Bitcoin'),
    'highbeta.html': (f'High Beta Desk · {NAME}',
                      'Daily regime model for the 25 highest-beta Nasdaq-100 stocks, a satellite sleeve outside the model portfolio, with a backtest against SPHB.', 'High Beta'),
    'about.html': (f'About · {NAME}',
                   'What Kerdos Capital is, how its models are built and run, and what it is not.', 'About'),
}
NAV_ORDER = ['index.html', 'flagship.html', 'portfolio.html', 'stocks.html', 'bitcoin.html', 'highbeta.html', 'about.html']
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
<meta name="theme-color" content="#131621">
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


def nav_links(cur, cls_attr):
    out = []
    for f in NAV_ORDER:
        if not exists(f): continue
        a = ' aria-current="page"' if (f == cur and cls_attr == 'site') else ''
        out.append(f'<a href="{f}"{a}>{PAGES[f][2]}</a>')
    return ''.join(out)


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
    # site nav: keep the sliding indicator span, rebuild the links
    s = re.sub(r'(<nav class="k-links" aria-label="Site"><span class="k-ind" aria-hidden="true"></span>).*?(</nav>)',
               lambda m: m.group(1) + nav_links(f, 'site') + m.group(2), s, count=1, flags=re.S)
    s = re.sub(r'(<nav class="fl" aria-label="Footer">).*?(</nav>)', lambda m: m.group(1) + nav_links(f, 'foot') + m.group(2), s, count=1, flags=re.S)
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


def prerender_index(s, M, B, G, PF):
    if M and B:
        s = re.sub(r'(<div class="label" id="asof">)[^<]*(</div>)',
                   lambda m: m.group(1) + E(f'Stocks and high beta as of {fmt_d(M["asof"])} close · Bitcoin as of {fmt_d(B["asof"])} close') + m.group(2), s, count=1)
    cards = []
    def card(name, reg, expo, since, quote, href, short):
        return (f'<article class="desk"><div class="top"><h2>{E(name)}</h2></div><div><div class="call c-{E(reg)}">{E(reg)}</div></div>'
                f'<div class="expo"><span>Exposure</span><b>{round(expo * 100)}%</b><span>since {E(fmt_d(since))}</span></div>'
                f'<div class="meter" aria-hidden="true"><i style="width:{expo * 100:.0f}%"></i></div><div class="quotes">{quote}</div>'
                f'<a class="go" href="{href}">Open the {short} desk <span aria-hidden="true">→</span></a></article>')
    q = lambda tk, px, d1: f'<div class="q"><div class="tk">{tk}</div><div class="px">{px}</div><div class="ch"><span>{sg(d1)} 1d</span></div></div>'
    if M: cards.append(card('US stocks · SPY & QQQ', M['regime'], M['exposure'], M['regime_since'], q('SPY', usd(M['spy']), M['spy_chg']['d1']) + q('QQQ', usd(M['qqq']), M['qqq_chg']['d1']), 'stocks.html', 'stocks'))
    if B: cards.append(card('Bitcoin', B['regime'], B['exposure'], B['regime_since'], q('BTC', usd(B.get('price'), 0), B.get('chg1')), 'bitcoin.html', 'Bitcoin'))
    if G: cards.append(card('High beta · satellite sleeve', G['regime'], G['exposure'], G['regime_since'], q('Basket', f"{G['level']:.2f}", (G.get('chg') or {}).get('d1', 0) * 100), 'highbeta.html', 'high-beta'))
    if cards: s = put_inside(s, r'<section class="desks" id="desks"[^>]*>', 'desks', ''.join(cards))
    if M and B:
        ts, tb = .6 * M['exposure'], .4 * B['exposure']; cash = 1 - ts - tb
        f1 = lambda v: f'{v * 100:.1f}'.rstrip('0').rstrip('.') + '%'
        tbl = ('<div class="tblwrap"><table><thead><tr><th>Slice</th><th class="n">Weight</th><th>Desk call</th><th class="n">Target now</th></tr></thead><tbody>'
               f'<tr><td>US stocks</td><td class="n">60%</td><td class="c-{E(M["regime"])}" style="font-weight:600">{E(M["regime"])}</td><td class="n hl">{f1(ts)}</td></tr>'
               f'<tr><td>Bitcoin</td><td class="n">40%</td><td class="c-{E(B["regime"])}" style="font-weight:600">{E(B["regime"])}</td><td class="n hl">{f1(tb)}</td></tr>'
               f'<tr><td>Cash (T-bills)</td><td class="n">—</td><td class="muted">what is left</td><td class="n hl">{f1(cash)}</td></tr></tbody></table></div>')
        s = put_inside(s, r'<div id="mport">', 'mport', tbl)
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


SANS_B = ['/usr/share/fonts/truetype/google-fonts/Poppins-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
SANS_M = ['/usr/share/fonts/truetype/google-fonts/Poppins-Medium.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
SANS_R = ['/usr/share/fonts/truetype/google-fonts/Poppins-Regular.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
MONO = ['/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf']
COL = {'Bullish': '#a58ee4', 'Recovery': '#a58ee4', 'Neutral': '#d1d4dc', 'Correction': '#9aa0ae', 'Lagging': '#9aa0ae',
       'Crash': '#e0904a', 'Bearish': '#ef5a62', 'Breakdown': '#ef5a62', 'Risk-On': '#a58ee4', 'Risk-Off': '#ef5a62'}


def make_icons():
    from PIL import Image, ImageDraw
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#131621"/>'
           '<path d="M21 15v34M21 33l19-18M27 28l15 21" fill="none" stroke="#a58ee4" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/></svg>')
    wr('favicon.svg', svg)
    def k_img(n):
        im = Image.new('RGBA', (n, n), (0, 0, 0, 0)); d = ImageDraw.Draw(im); s = n / 64
        d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(14 * s), fill='#131621')
        w = max(2, int(7 * s)); c = '#a58ee4'
        for a, b in [((21, 15), (21, 49)), ((21, 33), (40, 15)), ((27, 28), (42, 49))]:
            d.line([(a[0] * s, a[1] * s), (b[0] * s, b[1] * s)], fill=c, width=w)
            for pt in (a, b): d.ellipse([pt[0] * s - w / 2, pt[1] * s - w / 2, pt[0] * s + w / 2, pt[1] * s + w / 2], fill=c)
        return im
    k_img(256).save(p('favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
    big = Image.new('RGB', (180, 180), '#131621'); big.paste(k_img(180), (0, 0), k_img(180)); big.save(p('apple-touch-icon.png'))


def make_og(M, B, G, FL):
    from PIL import Image, ImageDraw
    W, H = 1200, 630
    im = Image.new('RGB', (W, H), '#131621'); d = ImageDraw.Draw(im)
    for i in range(H):   # faint lavender glow at the top left
        a = max(0, 1 - i / 420) * 0.10
        d.line([(0, i), (W, i)], fill=tuple(int(x * (1 - a) + y * a) for x, y in zip((19, 22, 33), (165, 142, 228))))
    d.text((72, 66), 'K E R D O S   C A P I T A L', font=font(SANS_M, 26), fill='#ffffff')
    d.text((72, 128), 'Independent Quantitative', font=font(SANS_B, 58), fill='#ffffff')
    d.text((72, 196), 'Investment Research', font=font(SANS_B, 58), fill='#ffffff')
    rows = []
    if FL: rows.append(('Flagship model', FL.get('regime', '—'), f"{round(FL.get('equity_weight', 0) * 100)}% stocks"))
    if M: rows.append(('US stocks', M['regime'], f"{round(M['exposure'] * 100)}% invested"))
    if B: rows.append(('Bitcoin', B['regime'], f"{round(B['exposure'] * 100)}% invested"))
    if G: rows.append(('High beta', G['regime'], f"{round(G['exposure'] * 100)}% invested"))
    y = 310
    for name, reg, ex in rows[:4]:
        d.rounded_rectangle([72, y, W - 72, y + 56], radius=14, fill='#1e2230')
        d.text((100, y + 12), name, font=font(SANS_R, 26), fill='#a9adb8')
        d.text((470, y + 10), reg, font=font(SANS_B, 28), fill=COL.get(reg, '#d1d4dc'))
        d.text((W - 100, y + 14), ex, font=font(MONO, 24), fill='#d1d4dc', anchor='ra')
        y += 68
    asof = fmt_d(M['asof']) if M else ''
    d.text((72, H - 52), f'kerdoscapital.xyz · as of the {asof} close · hypothetical models, not investment advice', font=font(SANS_R, 20), fill='#7a7e8a')
    im.save(p('og.png'), optimize=True)


def make_about(index_html):
    """about.html shares the overview's head, nav and footer; its body comes from tools/about_body.html."""
    body = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'about_body.html'), encoding='utf-8').read()
    i_nav = index_html.find('class="k-nav"'); i_end = index_html.find('</header>', i_nav) + len('</header>')
    i_ft = index_html.find('<footer class="foot pub">'); i_fe = index_html.find('</footer>', i_ft) + len('</footer>')
    if min(i_nav, i_ft) < 0: return None
    extra = ('<style>.about .prose{display:grid;gap:12px;max-width:72ch;color:var(--ink2,#a9adb8);font-size:.98rem;line-height:1.6}'
             '.about .prose p{margin:0}.about .prose a{color:var(--accent,#a58ee4)}</style>\n')
    head_end = index_html.find('</head>')
    return (index_html[:head_end] + extra + index_html[head_end:i_end] + '\n' + body + '\n  ' + index_html[i_ft:i_fe] + '\n</div>\n</body>\n</html>\n')


def main():
    M, B, G = jload('stocks/report.json'), jload('bitcoin/report.json'), jload('highbeta/report.json')
    FL = jload('flagship/report.json'); PF = jload('portfolio_backtest.json')
    img_v = (M or {}).get('asof', dt.date.today().isoformat()).replace('-', '')
    if not exists('favicon.svg') or not exists('favicon.ico') or not exists('apple-touch-icon.png'): make_icons()
    try: make_og(M, B, G, FL)
    except Exception as e: print('og.png skipped:', e)
    if exists('index.html'):
        a = make_about(unwrap(rd('index.html')))
        if a: wr('about.html', a)
    for f in PAGES:
        if not exists(f): continue
        s = fix_page(f, rd(f), img_v)
        if f == 'index.html': s = prerender_index(s, M, B, G, PF)
        elif f == 'stocks.html' and M:
            s = prerender_loading(s, summary_line('US stocks', M['regime'], M['exposure'], f"SPY {usd(M['spy'])} ({sg(M['spy_chg']['d1'])}) · QQQ {usd(M['qqq'])}", M['asof']))
        elif f == 'bitcoin.html' and B:
            s = prerender_loading(s, summary_line('Bitcoin', B['regime'], B['exposure'], f"BTC {usd(B.get('price'), 0)}", B['asof']))
        elif f == 'highbeta.html' and G:
            s = prerender_loading(s, summary_line('High beta', G['regime'], G['exposure'], f"basket {G['level']:.2f}", G['asof']))
        elif f == 'portfolio.html' and M and B:
            s = prerender_loading(s, summary_line('Model portfolio', f"stocks {M['regime']}, Bitcoin {B['regime']}", .6 * M['exposure'] + .4 * B['exposure'], 'of a 60% stocks / 40% Bitcoin target', M['asof']))
        elif f == 'flagship.html' and FL:
            s = prerender_loading(s, summary_line('Flagship model', FL['regime'], 1 - FL.get('weights', {}).get('cash', 0), 'multi-asset allocation', FL['asof']))
        wr(f, s)
    today = dt.date.today().isoformat()
    wr('robots.txt', f'User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n')
    urls = ''.join(f'  <url><loc>{SITE}/{"" if f == "index.html" else f}</loc><lastmod>{today}</lastmod><changefreq>daily</changefreq></url>\n'
                   for f in NAV_ORDER if exists(f))
    wr('sitemap.xml', f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
    print('build ok:', ', '.join(f for f in NAV_ORDER if exists(f)))


if __name__ == '__main__':
    main()
