/* Kerdos Capital — shared interaction layer.
   Fixed nav with a sliding underline, scroll reveals, count-up numbers,
   plus the shared chart kit (gauge, sparkline, regime track). No dependencies; safe to load with defer. */
(() => {
  const d = document, root = d.documentElement;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const fine = matchMedia('(hover: hover) and (pointer: fine)').matches;
  root.classList.add('k-js');
  const K = (window.Kerdos = window.Kerdos || {});
  const boot = () => {

  /* ---------- nav ---------- */
  const nav = d.querySelector('.k-nav');
  if (nav) {
    const links = [...nav.querySelectorAll('.k-links a')];
    const ind = nav.querySelector('.k-ind');
    const cur = links.find(a => a.getAttribute('aria-current') === 'page');
    const place = (a, animate) => {
      if (!ind || !a || getComputedStyle(ind).display === 'none') return;
      const r = a.getBoundingClientRect(), pr = a.parentElement.getBoundingClientRect();
      if (!animate) ind.style.transition = 'none';
      ind.style.width = r.width + 'px';
      ind.style.transform = `translate3d(${r.left - pr.left}px,0,0)`;
      ind.style.opacity = 1;
      if (!animate) { void ind.offsetWidth; ind.style.transition = ''; }
    };
    let from = null;
    try { from = sessionStorage.getItem('k-nav-from'); sessionStorage.removeItem('k-nav-from'); } catch (e) {}
    const prev = links.find(a => a.getAttribute('href') === from);
    const init = () => {
      if (prev && cur && prev !== cur && !reduce) {
        place(prev, false);
        requestAnimationFrame(() => requestAnimationFrame(() => place(cur, true)));
      } else place(cur, false);
    };
    init();
    (d.fonts && d.fonts.ready ? d.fonts.ready : Promise.resolve()).then(() => place(cur, false));
    addEventListener('resize', () => place(cur, false));
    links.forEach(a => a.addEventListener('click', e => {
      try { if (cur) sessionStorage.setItem('k-nav-from', cur.getAttribute('href')); } catch (_) {}
      if (reduce || a === cur || e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;
      if (getComputedStyle(ind).display === 'none') return;
      e.preventDefault(); place(a, true);
      setTimeout(() => { location.href = a.href; }, 240);
    }));
    const onScroll = () => nav.classList.toggle('is-scrolled', scrollY > 8);
    onScroll(); addEventListener('scroll', onScroll, { passive: true });
    const btn = nav.querySelector('.k-menu-btn');
    if (btn) {
      btn.addEventListener('click', () => { const o = nav.classList.toggle('is-open'); btn.setAttribute('aria-expanded', o); });
      d.addEventListener('keydown', e => { if (e.key === 'Escape') { nav.classList.remove('is-open'); btn.setAttribute('aria-expanded', false); } });
      d.addEventListener('click', e => { if (!nav.contains(e.target)) { nav.classList.remove('is-open'); btn.setAttribute('aria-expanded', false); } });
    }
  }

  /* ---------- number formats for count-up ---------- */
  const sign = v => (v > 0 ? '+' : v < 0 ? '−' : '');
  const FMT = {
    usd: (v, n) => '$' + v.toLocaleString('en-US', { minimumFractionDigits: n, maximumFractionDigits: n }),
    pct: (v, n) => v.toFixed(n) + '%',
    spct: (v, n) => sign(+v.toFixed(n)) + Math.abs(v).toFixed(n) + '%',
    snum: (v, n) => sign(+v.toFixed(n)) + Math.abs(v).toFixed(n),
    num: (v, n) => v.toLocaleString('en-US', { minimumFractionDigits: n, maximumFractionDigits: n }),
    pm: (v, n) => '±' + v.toFixed(n) + '%'
  };
  const count = el => {
    const to = parseFloat(el.dataset.cu), n = +(el.dataset.dec || 0), f = FMT[el.dataset.fmt || 'num'];
    const final = el.textContent;
    if (reduce || !isFinite(to) || !f) return;
    const from = el.dataset.from != null ? parseFloat(el.dataset.from) : 0;
    const t0 = performance.now(), dur = parseFloat(getComputedStyle(root).getPropertyValue('--dur-count')) || 950;
    const step = t => {
      const p = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = f(from + (to - from) * e, n);
      if (p < 1) requestAnimationFrame(step); else el.textContent = final;
    };
    requestAnimationFrame(step);
  };

  /* ---------- reveals ---------- */
  const SEL = '.panel,.desk,.ox .oxp,.k-reveal,.sec>h2,.mast.sub';
  const done = el => setTimeout(() => el.classList.add('k-done'), 1400);
  const io = ('IntersectionObserver' in window && !reduce) ? new IntersectionObserver(es => {
    let i = 0;
    es.forEach(e => {
      if (!e.isIntersecting) return;
      const el = e.target;
      el.style.setProperty('--k-i', i++);
      el.classList.add('k-in'); done(el); io.unobserve(el);
      el.querySelectorAll('[data-cu]').forEach(count);
      el.querySelectorAll('.k-gauge .mk').forEach(m => m.classList.add('k-go'));
    });
  }, { rootMargin: '0px 0px -6% 0px', threshold: 0.04 }) : null;
  K.scan = () => {
    d.querySelectorAll(SEL).forEach(el => {
      if (el.dataset.kr) return; el.dataset.kr = '1';
      if (el.parentElement && el.parentElement.closest('.k-rv')) { el.classList.add('k-nested'); return; }
      el.classList.add('k-rv');
      if (io) io.observe(el); else { el.classList.add('k-in', 'k-done'); el.querySelectorAll('.k-gauge .mk').forEach(m => m.classList.add('k-go')); }
    });
  };
  K.scan();
  let mt; new MutationObserver(() => { clearTimeout(mt); mt = setTimeout(K.scan, 30); }).observe(d.body, { childList: true, subtree: true });

  /* ---------- line charts draw themselves in as they scroll into view ----------
     Every stroked, unfilled path in a .chart is revealed by a left-to-right sweep the first time the chart is a third on screen,
     after its panel has faded in. The animation is driven per chart, not per svg, so when the page redraws a chart
     mid-trace (a phone's address bar showing or hiding fires a resize) the new drawing carries on from the same point
     instead of popping in whole. A redraw from a tap (ticker or range toggle) traces again; other redraws of a
     finished chart stay as they are. */
  if (!reduce && 'IntersectionObserver' in window) {
    let tap = -1e9; const DUR = 2000;
    const mark = () => { tap = performance.now(); };
    d.addEventListener('pointerdown', mark, true); d.addEventListener('keydown', mark, true);
    const strokes = svg => [...svg.querySelectorAll('path')].filter(p => p.getAttribute('fill') === 'none' && (p.getAttribute('stroke') || 'none') !== 'none');
    const dots = svg => svg.querySelectorAll('circle:not(.hd)');
    const ease = p => .5 - Math.cos(Math.PI * p) / 2;   // steady pen speed with soft start and finish
    const ST = new WeakMap(), live = new Set();
    let cid = 0;
    const clipOf = svg => {   // a rect that sweeps left to right; the lines show only inside it
      if (svg._kc) return svg._kc;
      const ns = 'http://www.w3.org/2000/svg', vb = svg.viewBox.baseVal, id = 'kdraw' + (++cid);
      const cp = d.createElementNS(ns, 'clipPath'); cp.setAttribute('id', id);
      const r = d.createElementNS(ns, 'rect'); r.setAttribute('x', vb.x - 4); r.setAttribute('y', vb.y - 20);
      r.setAttribute('height', vb.height + 40); r.setAttribute('width', 0); cp.append(r); svg.prepend(cp);
      strokes(svg).forEach(p => p.setAttribute('clip-path', `url(#${id})`));
      return (svg._kc = { r, w: vb.width + 8 });
    };
    const setP = (host, f) => {
      const svg = host.querySelector('svg'); if (!svg) return;
      const c = clipOf(svg); c.r.setAttribute('width', (c.w * f).toFixed(1));
      dots(svg).forEach(c => { c.style.opacity = f >= 1 ? '' : 0; });
    };
    const clear = host => {
      const svg = host.querySelector('svg'); if (!svg) return;
      strokes(svg).forEach(p => p.removeAttribute('clip-path'));
      if (svg._kc) { svg._kc.r.parentNode.remove(); svg._kc = null; }
      dots(svg).forEach(c => { c.style.transition = 'opacity .35s ease'; c.style.opacity = ''; });
    };
    const prog = s => { const t = performance.now(); return t < s.t0 ? 0 : ease(Math.min(1, (t - s.t0) / DUR)); };
    const tick = () => {
      live.forEach(host => {
        const s = ST.get(host);
        if (!host.isConnected) { live.delete(host); return; }
        const f = prog(s); setP(host, f);
        if (f >= 1) { s.state = 'done'; clear(host); live.delete(host); }
      });
      if (live.size) requestAnimationFrame(tick);
    };
    const start = (host, delay) => {
      const s = ST.get(host); s.state = 'play'; s.t0 = performance.now() + delay;
      if (!live.size) requestAnimationFrame(tick);
      live.add(host);
    };
    const lio = new IntersectionObserver(es => es.forEach(e => {
      if (!e.isIntersecting) return; lio.unobserve(e.target);
      const s = ST.get(e.target); if (!s || s.state !== 'wait') return;
      const panel = e.target.closest('.k-rv');
      start(e.target, panel && !panel.classList.contains('k-done') ? 700 : 200);   // let the panel finish fading in first
    }), { threshold: 0.3, rootMargin: '0px 0px -6% 0px' });
    const scan = () => d.querySelectorAll('.chart').forEach(host => {
      const svg = host.querySelector('svg'); if (!svg || svg._ks) return; svg._ks = 1;
      const s = ST.get(host);
      if (!s) { if (!strokes(svg).length) return; ST.set(host, { state: 'wait' }); setP(host, 0); lio.observe(host); return; }
      if (s.state === 'wait') { setP(host, 0); return; }
      if (s.state === 'play') { setP(host, prog(s)); return; }
      if (performance.now() - tap < 1200 && strokes(svg).length) { setP(host, 0); start(host, 120); }
    });
    scan();
    new MutationObserver(scan).observe(d.body, { childList: true, subtree: true });
  }
  };
  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', boot); else boot();
  /* ================= shared chart kit ================= */
  const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const ds = s => { const t = new Date(s + 'T00:00:00Z'); return MON[t.getUTCMonth()] + ' ' + t.getUTCDate(); };
  const dy = s => ds(s) + ' ’' + s.slice(2, 4);
  const cssv = n => getComputedStyle(root).getPropertyValue(n).trim();
  const sn = (v, n) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(n);
  /* Three display states. Each desk keeps its own internal rules; the site shows them by exposure:
     Bullish = 100% invested, Neutral = 50%, Bearish = 0% (T-bills). map = the desk's exposure_map. */
  K.STATES = ['Bullish', 'Neutral', 'Bearish'];
  K.EXPO = { Bullish: 1, Neutral: .5, Bearish: 0 };
  /* What visitors read: Bullish / Neutral / Bearish are shown as Risk On / Balanced / Risk Off. The keys stay as they are (CSS classes, data). */
  K.LBL = { Bullish: 'Risk On', Neutral: 'Balanced', Bearish: 'Risk Off', 'Risk-On': 'Risk On', 'Risk-Off': 'Risk Off' };
  K.lab = s => (s && K.LBL[s]) || s;
  K.st = (reg, map) => {
    if (!reg) return reg;
    const e = map && map[reg] != null ? +map[reg] : null;
    if (e == null) return reg;
    return e >= .99 ? 'Bullish' : e > 0 ? 'Neutral' : 'Bearish';
  };
  /* Current state run from a history (rows with .date and .regime): {state, since, n, prev} */
  K.stl = (reg, map) => K.lab(K.st(reg, map));
  K.stRun = (rows, map) => {
    const s = rows.filter(r => r.regime).map(r => ({ d: r.date, s: K.st(r.regime, map) }));
    if (!s.length) return null;
    let i = s.length - 1; const c = s[i].s;
    while (i > 0 && s[i - 1].s === c) i--;
    return { state: c, since: s[i].d, n: s.length - i, prev: i > 0 ? s[i - 1].s : null };
  };
  K.esc = t => String(t).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  K.sn = sn;
  const redraws = new Set(); let rt;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => redraws.forEach(f => f()), 150); });

  /* Gauge on a −1…+1 (or custom) scale.
     o = {value, min, max, ghost, ticks:[{v,label,side:'l'|'r'}], label} */
  K.gauge = (host, o) => {
    const min = o.min ?? -1, max = o.max ?? 1;
    const P = v => ((Math.max(min, Math.min(max, v)) - min) / (max - min) * 100).toFixed(2) + '%';
    host.classList.add('k-gauge'); host.setAttribute('role', 'img');
    host.setAttribute('aria-label', o.label || `Score ${sn(o.value, 2)}`);
    host.innerHTML = `<div class="trk"><span class="fill"${o.fill ? ` style="background:${o.fill}"` : ''}></span>
      ${(o.ticks || []).map(t => `<span class="tick" style="left:${P(t.v)}"></span><span class="tlab${t.side === 'l' ? ' l' : ''}" style="left:${P(t.v)}">${t.label}</span>`).join('')}
      <span class="ax l">${o.minLabel ?? sn(min, 0)}</span><span class="ax r">${o.maxLabel ?? sn(max, 0)}</span>
      ${o.ghost != null ? `<span class="mk ghost" style="--p:${P(o.ghost)}"><i></i></span>` : ''}
      <span class="mk" style="--p:${P(o.value)}"><i></i><em>${o.valueLabel ?? sn(o.value, 2)}</em></span></div>`;
    const panel = host.closest('.k-rv');
    if (!panel || panel.classList.contains('k-in') || reduce) host.querySelectorAll('.mk').forEach(m => m.classList.add('k-go'));
  };

  /* Sparkline with threshold lines. pts = [{date, v}] */
  K.spark = (host, pts, o = {}) => {
    const draw = () => {
      if (pts.length < 2) { host.remove(); return; }
      const ys = pts.map(p => p.v), lines = o.lines || [];
      const W = Math.max(240, (host.clientWidth || 520) - 32), H = o.h || 104, m = { t: 10, b: 10, l: 0, r: 50 };
      let lo = Math.min(...ys, ...lines.map(l => l.v)), hi = Math.max(...ys, ...lines.map(l => l.v));
      const pad = (hi - lo) * .08 || .05; lo -= pad; hi += pad;
      const X = i => m.l + i / (ys.length - 1) * (W - m.l - m.r), Y = v => m.t + (hi - v) / (hi - lo) * (H - m.t - m.b);
      const line = 'M' + ys.map((v, i) => X(i).toFixed(1) + ',' + Y(v).toFixed(1)).join('L');
      const area = line + `L${X(ys.length - 1).toFixed(1)},${H - m.b}L${X(0)},${H - m.b}Z`;
      const ac = o.color || cssv('--accent') || '#B9A98A', last = ys[ys.length - 1], id = 'k' + Math.random().toString(36).slice(2, 7);
      const fmt = o.fmt || (v => sn(v, 2));
      host.classList.add('k-spark');
      host.innerHTML = `<div class="hd"><span class="label">${o.title || ''}</span><span class="mono" style="font-size:12px;color:var(--ink-2)">${ds(pts[0].date)} – ${ds(pts[pts.length - 1].date)}</span></div>
        <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${K.esc(o.title || 'Trend')}: from ${fmt(ys[0])} to ${fmt(last)}">
        <defs><linearGradient id="${id}a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${ac}" stop-opacity=".16"/><stop offset="1" stop-color="${ac}" stop-opacity="0"/></linearGradient>
        </defs>
        ${lines.map(l => `<line class="thr" x1="0" x2="${W - m.r}" y1="${Y(l.v).toFixed(1)}" y2="${Y(l.v).toFixed(1)}" stroke="${l.color}" opacity=".6"/><text class="tx" x="${W - m.r + 8}" y="${(Y(l.v) + 3.5).toFixed(1)}">${l.label ?? fmt(l.v)}</text>`).join('')}
        <path class="area" d="${area}" fill="url(#${id}a)"/><path class="ln" d="${line}" stroke="${ac}" pathLength="1"/>
        <circle cx="${X(ys.length - 1).toFixed(1)}" cy="${Y(last).toFixed(1)}" r="3.5" fill="${cssv('--ink') || '#E7E4DC'}" stroke="${cssv('--panel') || '#191C1F'}" stroke-width="2"/></svg>`;
    };
    draw(); redraws.add(() => host.isConnected && draw());
  };

  /* Regime history as one continuous track. rows = [{date, regime}] */
  const RC = { Bullish: 'var(--c-bull)', Neutral: '#5E6468', Bearish: '#33373B' };
  K.hist = (rows, o = {}) => {
    rows = rows.filter(r => r.regime).map(r => ({ date: r.date, regime: o.map ? K.st(r.regime, o.map) : r.regime }));
    if (!rows.length) return '';
    const end = Date.parse(rows[rows.length - 1].date);
    rows = rows.filter(r => Date.parse(r.date) > end - (o.days || 365) * 864e5);
    const segs = []; let c = null;
    rows.forEach(r => { if (!c || c.g !== r.regime) { c = { g: r.regime, n: 0, from: r.date }; segs.push(c); } c.n++; c.to = r.date; });
    const n = rows.length, b = 0; let pos = 0; const stops = [];
    segs.forEach((s, i) => {
      const a = pos / n * 100, e = (pos + s.n) / n * 100, col = RC[s.g] || '#4A5055';
      stops.push(`${col} ${(i ? Math.min(a + b, (a + e) / 2) : 0).toFixed(2)}%`, `${col} ${(i < segs.length - 1 ? Math.max(e - b, (a + e) / 2) : 100).toFixed(2)}%`);
      pos += s.n;
    });
    const days = {}; segs.forEach(s => days[s.g] = (days[s.g] || 0) + s.n);
    const top = Object.entries(days).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([g, k]) => `${K.lab(g)} ${Math.round(k / n * 100)}%`).join(' · ');
    return `<div class="k-hist"><div class="hd"><span class="label">${o.title || 'State · last 12 months'}</span><span class="mono">${top}</span></div>
      <div class="trk" role="img" aria-label="State over the last 12 months: ${top}"><span class="fill" style="background:linear-gradient(90deg,${stops.join(',')})"></span>
      <span class="hits">${segs.map(s => `<i style="flex:${s.n}" title="${K.lab(s.g)} · ${ds(s.from)} – ${ds(s.to)} (${s.n} ${o.unit || 'days'})"></i>`).join('')}</span><span class="end"></span></div>
      <div class="ax"><span>${dy(rows[0].date)}</span><span>${dy(rows[n - 1].date)}</span></div></div>`;
  };

  /* ================= desk report (layout A) =================
     One continuous report: a row of serif key figures, the score (or level) history as the centrepiece,
     then "why it reads" beside the supporting figures. o = {
       kpis:[{l,b,i,c}], chart:{title,sub,rows:[{date,y,p,st,ref}],lines:[{v,label}],mode:'score'|'level',yfmt,pfmt,yName,pName,refName,unit},
       why:{title,tag}, side:{title,tag,html} }  Returns {el, why, side}. */
  const BANDS = { Bullish: 'rgba(185,169,138,.10)', Neutral: 'rgba(133,139,144,.065)', Bearish: 'rgba(169,112,95,.11)' };
  K.report = o => {
    const el = d.createElement('section'); el.className = 'k-rp'; el.setAttribute('aria-label', 'Today’s call');
    const C = o.chart, kp = x => `<div class="k-rp-kpi"><span>${x.l}</span><b class="${x.c || ''}">${x.b}</b><i>${x.i || ''}</i></div>`;
    const R = [[90, '90D'], [180, '6M'], [365, '1Y'], [1095, '3Y']].filter(([n]) => n <= C.rows.length + 30);
    const sw = (c, t, b) => `<span><i class="${b ? 'b' : ''}" style="background:${c}"></i>${t}</span>`;
    el.innerHTML = `<div class="k-rp-kpis">${o.kpis.map(kp).join('')}</div>
      <div class="k-rp-chart"><div class="k-rp-sub"><h2>${C.title}</h2><span class="label">${C.sub || ''}</span></div>
        <div class="k-rp-ctl"><div class="k-rp-leg">${sw('var(--sage)', C.yName)}${C.pName ? sw('#858B90', C.pName) : ''}${C.refName ? sw('repeating-linear-gradient(90deg,#858B90 0 4px,transparent 4px 7px)', C.refName) : ''}${sw('rgba(185,169,138,.55)', 'Risk On', 1)}${sw('rgba(133,139,144,.45)', 'Balanced', 1)}${sw('rgba(169,112,95,.6)', 'Risk Off', 1)}</div>
        <div class="seg" role="group" aria-label="Time range">${R.map(([n, t], i) => `<button type="button" data-n="${n}" aria-pressed="${i === 0}">${t}</button>`).join('')}</div></div>
        <div class="chart k-rp-svg"></div></div>
      <div class="k-rp-two"><div class="k-rp-col"><div class="k-rp-sub"><h2>${o.why.title}</h2><span class="label">${o.why.tag || ''}</span></div><div data-why></div></div>
        <div class="k-rp-col"><div class="k-rp-sub"><h2>${o.side.title}</h2><span class="label">${o.side.tag || ''}</span></div>${o.side.html}</div></div>`;
    const host = el.querySelector('.k-rp-svg'); let N = R.length ? R[0][0] : 90;
    const draw = () => {
      const D = C.rows.slice(-N); if (D.length < 2) return;
      const W = Math.max(320, host.clientWidth || 900), small = W < 600, Ht = small ? 260 : 380, m = { t: 16, r: C.pName ? (small ? 46 : 62) : 12, b: 26, l: small ? 44 : 54 };
      const X = i => m.l + i / (D.length - 1) * (W - m.l - m.r);
      const ys = D.map(r => r.y).concat((C.lines || []).map(l => l.v)).concat(D.map(r => r.ref).filter(v => v != null));
      let y0 = Math.min(...ys), y1 = Math.max(...ys); const pad = (y1 - y0) * .1 || .05; y0 -= pad; y1 += pad;
      const Y = v => m.t + (y1 - v) / (y1 - y0) * (Ht - m.t - m.b);
      let g = '', i0 = 0;
      for (let i = 1; i <= D.length; i++) if (i === D.length || D[i].st !== D[i0].st) {
        const a = i0 ? (X(i0 - 1) + X(i0)) / 2 : m.l, b = i < D.length ? (X(i - 1) + X(i)) / 2 : W - m.r;
        g += `<rect x="${a.toFixed(1)}" y="${m.t}" width="${(b - a).toFixed(1)}" height="${Ht - m.t - m.b}" fill="${BANDS[D[i0].st] || 'transparent'}"/>`; i0 = i; }
      const rng = y1 - y0, raw = rng / 5, mag = 10 ** Math.floor(Math.log10(raw)), stp = [1, 2, 2.5, 5, 10].map(k => k * mag).find(k => k >= raw);
      for (let v = Math.ceil(y0 / stp) * stp; v <= y1; v += stp) g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}" stroke="rgba(231,228,220,.05)"/><text class="ax" x="${m.l - 10}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end">${C.yfmt(v)}</text>`;
      (C.lines || []).forEach(l => { g += `<line x1="${m.l}" x2="${W - m.r}" y1="${Y(l.v).toFixed(1)}" y2="${Y(l.v).toFixed(1)}" stroke="#555B60" stroke-dasharray="3 4"/><text class="ax" x="${m.l + 6}" y="${(Y(l.v) - 6).toFixed(1)}" style="fill:var(--ink-2)">${l.label}</text>`; });
      let YP = null;
      if (C.pName) { const ps = D.map(r => r.p).filter(v => v != null), p0 = Math.min(...ps) * .97, p1 = Math.max(...ps) * 1.02; YP = v => m.t + (p1 - v) / (p1 - p0) * (Ht - m.t - m.b);
        [.1, .5, .9].forEach(f => { const v = p0 + (p1 - p0) * f; g += `<text class="ax" x="${W - m.r + 10}" y="${(YP(v) + 3.5).toFixed(1)}">${C.pfmt(v)}</text>`; });
        g += `<path d="M${D.map((r, i) => X(i).toFixed(1) + ',' + YP(r.p).toFixed(1)).join('L')}" fill="none" stroke="#858B90" stroke-width="1.1" opacity=".75"/>`; }
      if (C.refName) { let dd = '', on = false; D.forEach((r, i) => { if (r.ref == null) { on = false; return; } dd += (on ? 'L' : 'M') + X(i).toFixed(1) + ',' + Y(r.ref).toFixed(1); on = true; });
        g += `<path d="${dd}" fill="none" stroke="#858B90" stroke-width="1.2" stroke-dasharray="4 3"/>`; }
      const every = Math.ceil(D.length / (small ? 4 : 7)), yr = N > 300;
      D.forEach((r, i) => { if (i % every === 0 && i < D.length - every / 2) g += `<text class="ax" x="${X(i).toFixed(1)}" y="${Ht - 6}" text-anchor="middle">${ds(r.date)}${yr ? ' ’' + r.date.slice(2, 4) : ''}</text>`; });
      g += `<path d="M${D.map((r, i) => X(i).toFixed(1) + ',' + Y(r.y).toFixed(1)).join('L')}" fill="none" stroke="#B9A98A" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      const L = D[D.length - 1];
      g += `<circle cx="${X(D.length - 1).toFixed(1)}" cy="${Y(L.y).toFixed(1)}" r="4" fill="#B9A98A" stroke="#111315" stroke-width="2"/>`;
      g += `<line class="hx" x1="0" x2="0" y1="${m.t}" y2="${Ht - m.b}" stroke="#858B90" opacity="0"/><rect x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${Ht - m.t - m.b}" fill="transparent"/>`;
      host.innerHTML = `<svg viewBox="0 0 ${W} ${Ht}" role="img" aria-label="${K.esc(C.title)}: ${C.yName} ${C.yfmt(L.y)} on ${ds(L.date)}">${g}</svg><div class="tip" hidden></div>`;
      const svg = host.querySelector('svg'), tip = host.querySelector('.tip'), hx = svg.querySelector('.hx');
      svg.addEventListener('pointermove', e => { const b = svg.getBoundingClientRect(), xv = (e.clientX - b.left) * W / b.width;
        const i = Math.max(0, Math.min(D.length - 1, Math.round((xv - m.l) / (W - m.l - m.r) * (D.length - 1)))), r = D[i];
        hx.setAttribute('x1', X(i)); hx.setAttribute('x2', X(i)); hx.setAttribute('opacity', .5);
        tip.innerHTML = `<div class="h">${ds(r.date)}, ${r.date.slice(0, 4)}</div><div class="r"><span>${C.yName}</span><b class="mono">${C.yfmt(r.y, 1)}</b></div>${C.pName && r.p != null ? `<div class="r"><span>${C.pName}</span><b class="mono">${C.pfmt(r.p, 1)}</b></div>` : ''}${C.refName && r.ref != null ? `<div class="r"><span>${C.refName}</span><b class="mono">${C.yfmt(r.ref, 1)}</b></div>` : ''}<div class="r"><span>State</span><b class="c-${r.st}">${r.st}</b></div>`;
        tip.hidden = false; const tx = X(i) / W * b.width; tip.style.top = '8px'; tip.style.left = (tx > b.width / 2 ? Math.max(0, tx - tip.offsetWidth - 14) : tx + 14) + 'px'; });
      svg.addEventListener('pointerleave', () => { tip.hidden = true; hx.setAttribute('opacity', 0); });
    };
    el.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => { el.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', x === b)); N = +b.dataset.n; draw(); }));
    requestAnimationFrame(draw); redraws.add(() => el.isConnected && draw());
    return { el, why: el.querySelector('[data-why]'), side: el };
  };

})();
