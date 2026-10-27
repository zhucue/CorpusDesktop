/* 语料研究平台 · 设计稿共享脚本（无依赖） */
(function () {
  'use strict';

  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ---------- 图标 ---------- */
  var P = {
    db: '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    chart: '<path d="M4 20V10M10 20V4M16 20v-8M22 20H2"/>',
    pen: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
    book: '<path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H20v17H6.5A2.5 2.5 0 0 0 4 21.5z"/><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/>',
    spark: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    down: '<path d="m6 9 6 6 6-6"/>',
    right: '<path d="m9 6 6 6-6 6"/>',
    left: '<path d="m15 6-6 6 6 6"/>',
    up: '<path d="m6 15 6-6 6 6"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    upload: '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    download: '<path d="M12 4v12M7 11l5 5 5-5"/><path d="M4 16v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3"/>',
    retry: '<path d="M3 12a9 9 0 0 1 15.5-6.3L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15.5 6.3L3 16"/><path d="M3 21v-5h5"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
    file: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
    filetext: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/>',
    users: '<circle cx="9" cy="8" r="4"/><path d="M2 21a7 7 0 0 1 14 0"/><path d="M16 4a4 4 0 0 1 0 8M22 21a7 7 0 0 0-4-6.3"/>',
    key: '<circle cx="8" cy="15" r="4"/><path d="m10.8 12.2 9.2-9.2M17 6l3 3M14 9l2 2"/>',
    cpu: '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    filter: '<path d="M3 5h18l-7 8v6l-4 2v-8z"/>',
    sort: '<path d="M7 4v16M3 8l4-4 4 4M17 20V4M13 16l4 4 4-4"/>',
    copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M4 16V5a2 2 0 0 1 2-2h11"/>',
    external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>',
    note: '<path d="M4 4h16v12l-4 4H4z"/><path d="M16 20v-4h4M8 9h8M8 13h5"/>',
    quote: '<path d="M7 7h4v5c0 2.5-1.5 4.5-4 5M14 7h4v5c0 2.5-1.5 4.5-4 5"/>',
    link: '<path d="M10 14a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 10a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/>',
    alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.5"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    play: '<path d="M7 4v16l13-8z"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
    lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    more: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
    layers: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 13 9 5 9-5"/>',
    tool: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>',
    globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M10 4v16"/>',
    tree: '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><circle cx="12" cy="19" r="2"/><path d="M12 7v10M12 9 5.8 17.4M12 9l6.2 8.4"/>',
    align: '<path d="M4 5h6M4 12h6M4 19h6M14 5h6M14 12h6M14 19h6"/><path d="m10 5 4 7M10 12l4-7M10 19h4"/>',
    term: '<path d="M4 7V5h16v2M9 19h6M12 5v14"/>',
    folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    edit: '<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/>',
    keyboard: '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/>',
    scatter: '<path d="M3 3v18h18"/><circle cx="8" cy="15" r="1.5"/><circle cx="12" cy="10" r="1.5"/><circle cx="17" cy="7" r="1.5"/><circle cx="15" cy="14" r="1.5"/>',
    shield: '<path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6z"/>',
    hash: '<path d="M5 9h14M5 15h14M10 3 8 21M16 3l-2 18"/>'
  };
  function svg(name, cls) {
    return '<svg class="' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + (P[name] || '') + '</svg>';
  }
  function hydrateIcons(root) {
    (root || document).querySelectorAll('[data-icon]').forEach(function (el) {
      if (el.firstChild) return;
      el.classList.add('ic');
      el.innerHTML = svg(el.getAttribute('data-icon'));
    });
  }

  /* ---------- 外壳：左侧导航 ---------- */
  var NAV = [
    ['corpora', '语料库', 'db'], ['search', '检索', 'search'], ['stats', '统计', 'chart'], ['annotate', '标注', 'pen'],
    ['knowledge', '知识库', 'book'], ['assistant', '助手', 'spark'], ['jobs', '任务', 'clock']
  ];
  function renderNav() {
    var side = document.querySelector('.side[data-active]');
    if (!side) return;
    var active = side.getAttribute('data-active');
    var link = function (n) {
      return '<a href="' + n[0] + '.html"' + (n[0] === active ? ' aria-current="page"' : '') + ' data-nav="' + n[0] + '">' + svg(n[2], 'ic ic-18') + n[1] + '</a>';
    };
    side.innerHTML =
      '<a class="brand" href="index.html"><span class="brand-mark">' + svg('hash', 'ic') + '</span>语料研究平台</a>' +
      '<button class="btn project-switch" type="button" data-cmdk data-cmdk-q="项目"><span class="row" style="gap:8px">' + monogram('翻译对等研究', 'lg') + '翻译对等研究</span>' + svg('down', 'ic ic-14') + '</button>' +
      '<nav class="nav" aria-label="主导航"><span class="nav-ink" aria-hidden="true"></span>' + NAV.map(link).join('') + '</nav>' +
      '<div class="side-spacer"></div>' +
      '<nav class="nav" aria-label="设置"><span class="nav-ink" aria-hidden="true" style="opacity:0"></span>' + link(['settings', '项目设置', 'sliders']) + '</nav>' +
      '<div class="me"><span class="avatar" data-avatar="林云">林</span><div class="sm grow"><div style="font-weight:500">林云</div><div class="muted small">负责人</div></div>' +
      '<a class="btn ghost icon" href="login.html" aria-label="退出登录" title="退出登录">' + svg('logout', 'ic') + '</a></div>';

    side.querySelectorAll('.nav').forEach(function (nav) {
      var ink = nav.querySelector('.nav-ink');
      var cur = nav.querySelector('[aria-current="page"]');
      if (!cur) { ink.style.opacity = '0'; return; }
      ink.style.opacity = '1';
      var links = Array.prototype.slice.call(nav.querySelectorAll('a'));
      var idx = links.indexOf(cur);
      var prev = null;
      try { prev = sessionStorage.getItem('nav-prev'); } catch (e) { /* 无存储 */ }
      var from = prev !== null ? links.filter(function (a) { return a.getAttribute('data-nav') === prev; })[0] : null;
      var place = function (a) { ink.style.transform = 'translateY(' + a.offsetTop + 'px)'; ink.style.height = a.offsetHeight + 'px'; };
      ink.style.transition = 'none';
      place(from || cur);
      void ink.offsetWidth;
      ink.style.transition = '';
      requestAnimationFrame(function () { place(cur); });
      if (window === window.top) { try { sessionStorage.setItem('nav-prev', cur.getAttribute('data-nav')); } catch (e) { /* 无存储 */ } }
      void idx;
    });
  }

  /* ---------- 数字滚动 ---------- */
  var fmt = function (n, d) { return Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d }); };
  function countUp(root) {
    (root || document).querySelectorAll('[data-count]').forEach(function (el) {
      var out = el.querySelector(':scope > .n') || el;
      var to = parseFloat(el.getAttribute('data-count'));
      var dec = parseInt(el.getAttribute('data-dec') || '0', 10);
      var suffix = el.getAttribute('data-suffix') || '';
      var dur = parseInt(el.getAttribute('data-dur') || '900', 10);
      if (reduced) { out.textContent = fmt(to, dec) + suffix; return; }
      var t0 = performance.now();
      var ease = function (x) { return 1 - Math.pow(1 - x, 3); };
      (function tick(now) {
        var k = Math.min(1, (now - t0) / dur);
        out.textContent = fmt(to * ease(k), dec) + suffix;
        if (k < 1) requestAnimationFrame(tick);
      })(t0);
    });
  }

  /* ---------- 标签页（下划线 / 分段） ---------- */
  function moveInk(list, btn, instant) {
    var ink = list.querySelector('.tab-ink');
    if (!ink || !btn) return;
    if (instant) ink.style.transition = 'none';
    ink.style.width = btn.offsetWidth + 'px';
    ink.style.transform = 'translateX(' + btn.offsetLeft + 'px)';
    if (instant) { void ink.offsetWidth; ink.style.transition = ''; }
  }
  function initTabs() {
    document.querySelectorAll('[role="tablist"]').forEach(function (list) {
      if (!list.querySelector('.tab-ink')) {
        var ink = document.createElement('span');
        ink.className = 'tab-ink';
        ink.setAttribute('aria-hidden', 'true');
        list.appendChild(ink);
      }
      var cur = list.querySelector('[aria-selected="true"]') || list.querySelector('[role="tab"]');
      moveInk(list, cur, true);
    });
  }
  function selectTab(btn) {
    var list = btn.closest('[role="tablist"]');
    list.querySelectorAll('[role="tab"]').forEach(function (b) {
      var on = b === btn;
      b.setAttribute('aria-selected', on ? 'true' : 'false');
      b.tabIndex = on ? 0 : -1;
      var id = b.getAttribute('aria-controls');
      var panel = id && document.getElementById(id);
      if (panel) {
        panel.hidden = !on;
        if (on) {
          panel.classList.remove('panel-in'); void panel.offsetWidth; panel.classList.add('panel-in');
          countUp(panel);
        }
      }
    });
    moveInk(list, btn);
    list.dispatchEvent(new CustomEvent('tabchange', { bubbles: true, detail: { tab: btn } }));
  }

  /* ---------- 抽屉 ---------- */
  var lastFocus = null;
  function backdropFor(drawer) {
    var id = drawer.id;
    var bd = document.querySelector('.backdrop[data-for="' + id + '"]');
    if (!bd) {
      bd = document.createElement('div');
      bd.className = 'backdrop';
      bd.setAttribute('data-for', id);
      bd.addEventListener('click', function () { closeDrawer(drawer); });
      drawer.parentNode.insertBefore(bd, drawer);
    }
    return bd;
  }
  function openDrawer(drawer) {
    if (typeof drawer === 'string') drawer = document.getElementById(drawer);
    if (!drawer) return;
    lastFocus = document.activeElement;
    var bd = backdropFor(drawer);
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    requestAnimationFrame(function () { bd.classList.add('open'); });
    countUp(drawer);
    var f = drawer.querySelector('[data-drawer-close]');
    if (f) setTimeout(function () { f.focus(); }, 60);
  }
  function closeDrawer(drawer) {
    if (typeof drawer === 'string') drawer = document.getElementById(drawer);
    if (!drawer) return;
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    var bd = document.querySelector('.backdrop[data-for="' + drawer.id + '"]');
    if (bd) bd.classList.remove('open');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  /* ---------- 提示 ---------- */
  function toast(msg, icon) {
    var box = document.querySelector('.toasts');
    if (!box) { box = document.createElement('div'); box.className = 'toasts'; box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
    var t = document.createElement('div');
    t.className = 'toast';
    t.setAttribute('role', 'status');
    t.innerHTML = svg(icon || 'check', 'ic') + '<span>' + msg + '</span>';
    box.appendChild(t);
    setTimeout(function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 240); }, 2600);
  }

  /* ---------- 顶部进度线 ---------- */
  function busy(on) {
    var bar = document.querySelector('.topbar');
    if (bar) bar.classList.toggle('busy', !!on);
  }

  /* ---------- 重放子树动画 ---------- */
  function replay(el) {
    if (typeof el === 'string') el = document.querySelector(el);
    if (!el) return null;
    var c = el.cloneNode(true);
    el.parentNode.replaceChild(c, el);
    countUp(c);
    return c;
  }

  /* ---------- 事件委托 ---------- */
  document.addEventListener('click', function (e) {
    var t = e.target.closest('[role="tab"]');
    if (t) { selectTab(t); return; }
    var o = e.target.closest('[data-drawer-open]');
    if (o) { e.preventDefault(); openDrawer(o.getAttribute('data-drawer-open')); return; }
    var c = e.target.closest('[data-drawer-close]');
    if (c) { closeDrawer(c.closest('.drawer')); return; }
    var s = e.target.closest('.switch');
    if (s) { s.setAttribute('aria-checked', s.getAttribute('aria-checked') === 'true' ? 'false' : 'true'); }
    var tt = e.target.closest('[data-toast]');
    if (tt) { toast(tt.getAttribute('data-toast'), tt.getAttribute('data-toast-icon')); }
    var rp = e.target.closest('[data-replay]');
    if (rp) { replay(rp.getAttribute('data-replay')); }
    var ch = e.target.closest('.chip[data-insert]');
    if (ch) {
      var input = document.getElementById(ch.getAttribute('data-target') || 'q');
      if (input) {
        var ins = ch.getAttribute('data-insert');
        var pos = input.selectionStart != null ? input.selectionStart : input.value.length;
        input.value = input.value.slice(0, pos) + ins + input.value.slice(pos);
        input.focus();
        input.setSelectionRange(pos + ins.length, pos + ins.length);
        input.dispatchEvent(new Event('input', { bubbles: true }));
      }
    }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      var d = document.querySelector('.drawer.open[data-modal]');
      if (d) closeDrawer(d);
    }
    var tab = e.target.closest && e.target.closest('[role="tab"]');
    if (tab && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      var tabs = Array.prototype.slice.call(tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]'));
      var i = tabs.indexOf(tab) + (e.key === 'ArrowRight' ? 1 : -1);
      var n = tabs[(i + tabs.length) % tabs.length];
      n.focus(); selectTab(n);
    }
  });
  window.addEventListener('resize', function () {
    document.querySelectorAll('[role="tablist"]').forEach(function (l) { moveInk(l, l.querySelector('[aria-selected="true"]'), true); });
  });

  /* ---------- 助手：思考链与流式回答 ---------- */
  var sleep = function (ms, run) {
    return new Promise(function (res, rej) {
      var t = setTimeout(res, reduced ? 0 : ms);
      if (run) run.timers.push(t);
    }).then(function () { if (run && run.stopped) throw new Error('stopped'); });
  };

  function thinkBlock() {
    var el = document.createElement('div');
    el.className = 'think running';
    el.setAttribute('data-open', 'true');
    el.innerHTML =
      '<button class="think-head" type="button" aria-expanded="true">' + svg('spark', 'spark') +
      '<span class="think-label shimmer-text">正在思考…</span><span class="think-meta"></span>' + svg('down', 'chev') + '</button>' +
      '<div class="think-body"><div class="think-inner"><div class="think-flow"><div class="think-text"></div><ol class="steps"></ol></div></div></div>';
    el.querySelector('.think-head').addEventListener('click', function () {
      var open = el.getAttribute('data-open') !== 'true';
      el.setAttribute('data-open', open ? 'true' : 'false');
      this.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    return el;
  }
  function setLabel(block, text, shimmer) {
    var l = block.querySelector('.think-label');
    l.textContent = text;
    l.classList.toggle('shimmer-text', shimmer !== false);
    l.classList.remove('swap'); void l.offsetWidth; l.classList.add('swap');
  }

  /* 逐字流式写入：保留 HTML 结构，元素整体插入、文本逐字追加 */
  function streamHTML(target, html, run, speed) {
    var tpl = document.createElement('template');
    tpl.innerHTML = html;
    var caret = document.createElement('span');
    caret.className = 'caret';
    caret.setAttribute('aria-hidden', 'true');
    var walk = function (src, dst) {
      var nodes = Array.prototype.slice.call(src.childNodes);
      return nodes.reduce(function (p, node) {
        return p.then(function () {
          if (node.nodeType === 3) {
            var tn = document.createTextNode('');
            dst.appendChild(tn);
            dst.appendChild(caret);
            var text = node.nodeValue, i = 0;
            return new Promise(function (res, rej) {
              (function step() {
                if (run.stopped) { tn.nodeValue = text; return rej(new Error('stopped')); }
                var n = reduced ? text.length : (Math.random() < .3 ? 3 : 2);
                i = Math.min(text.length, i + n);
                tn.nodeValue = text.slice(0, i);
                if (i >= text.length) return res();
                run.timers.push(setTimeout(step, speed + Math.random() * speed));
              })();
            });
          }
          if (node.nodeType === 1) {
            var el = node.cloneNode(false);
            dst.appendChild(el);
            if (el.classList && (el.classList.contains('cite') || el.tagName === 'CODE')) { el.innerHTML = node.innerHTML; return Promise.resolve(); }
            return walk(node, el);
          }
          return Promise.resolve();
        });
      }, Promise.resolve());
    };
    return walk(tpl.content, target).then(function () { caret.remove(); }, function (e) { caret.remove(); throw e; });
  }

  /* 剧本驱动的演示：user / think / reason / label / tool / done / say / card / call / wait / hold */
  function agentDemo(opts) {
    var run = { stopped: false, timers: [] };
    var log = opts.log;
    var cur = { block: null, flow: null, answer: null, tools: 0, t0: 0 };
    var stepIcon = function (name) {
      return '<span class="step-node">' + svg(name) + '</span>';
    };
    var ops = {
      user: function (op) {
        var m = document.createElement('div');
        m.className = 'msg-user';
        m.innerHTML = op.html;
        log.appendChild(m);
        return sleep(op.after || 500, run);
      },
      think: function () {
        var wrap = document.createElement('div');
        wrap.className = 'msg-ai';
        cur.block = thinkBlock();
        cur.answer = document.createElement('div');
        cur.answer.className = 'answer col gap-12';
        wrap.appendChild(cur.block);
        wrap.appendChild(cur.answer);
        log.appendChild(wrap);
        cur.t0 = performance.now();
        if (opts.onBusy) opts.onBusy(true);
        return sleep(300, run);
      },
      label: function (op) { setLabel(cur.block, op.text); return sleep(op.after || 120, run); },
      reason: function (op) {
        var p = document.createElement('div');
        cur.block.querySelector('.think-text').appendChild(p);
        return streamHTML(p, op.text, run, 14).then(function () { return sleep(op.after || 200, run); });
      },
      tool: function (op) {
        var li = document.createElement('li');
        li.className = 'step active';
        li.innerHTML = stepIcon(op.icon || 'tool') +
          '<div class="step-card"><div class="step-top"><span class="step-tool">' + op.tool + '</span><span class="step-title">' + op.title + '</span><span class="step-res">运行中</span></div>' +
          '<div class="step-args">' + op.args + '</div></div>';
        cur.block.querySelector('.steps').appendChild(li);
        cur.tools++;
        if (op.label) setLabel(cur.block, op.label);
        if (op.hold) return new Promise(function () { /* 保持运行态，用于静态的“运行中”截面 */ });
        return sleep(op.dur || 1400, run).then(function () {
          li.className = 'step done';
          li.querySelector('.step-node').innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path class="chk" pathLength="1" d="M20 6 9 17l-5-5"/></svg>';
          li.querySelector('.step-res').textContent = op.res;
          if (op.onDone) op.onDone();
          return sleep(op.after || 350, run);
        });
      },
      done: function () {
        var secs = ((performance.now() - cur.t0) / 1000).toFixed(1);
        cur.block.classList.remove('running');
        setLabel(cur.block, '已思考 ' + secs + ' 秒 · ' + cur.tools + ' 次工具调用', false);
        cur.block.setAttribute('data-open', 'false');
        cur.block.querySelector('.think-head').setAttribute('aria-expanded', 'false');
        return sleep(380, run);
      },
      say: function (op) {
        var p = document.createElement('p');
        cur.answer.appendChild(p);
        return streamHTML(p, op.html, run, op.speed || 16).then(function () { return sleep(op.after || 160, run); });
      },
      card: function (op) {
        var tpl = document.getElementById(op.tpl);
        var node = tpl.content.firstElementChild.cloneNode(true);
        node.style.setProperty('--i', op.i || 0);
        hydrateIcons(node);
        hydrateDeps(node);
        cur.answer.appendChild(node);
        countUp(node);
        requestAnimationFrame(function () { hydrateAligns(node); });
        if (opts.onCard) opts.onCard(node);
        return sleep(op.after || 450, run);
      },
      call: function (op) { op.fn(); return sleep(op.after || 0, run); },
      wait: function (op) { return sleep(op.ms, run); }
    };
    var p = opts.script.reduce(function (chain, op) {
      return chain.then(function () {
        if (run.stopped) throw new Error('stopped');
        return ops[op.t](op);
      });
    }, Promise.resolve());
    p.then(function () {
      if (run.stopped) return;
      if (opts.onBusy) opts.onBusy(false);
      if (opts.onEnd) opts.onEnd(false);
    }, function () { /* 停止时由 stop() 收尾 */ });
    return {
      stop: function () {
        if (run.stopped) return;
        run.stopped = true;
        run.timers.forEach(clearTimeout);
        log.querySelectorAll('.caret').forEach(function (c) { c.remove(); });
        if (opts.onBusy) opts.onBusy(false);
        if (opts.onEnd) opts.onEnd(true);
        if (cur.block && cur.block.classList.contains('running')) {
          cur.block.classList.remove('running');
          setLabel(cur.block, '已停止 · ' + cur.tools + ' 次工具调用', false);
          cur.block.querySelectorAll('.step.active').forEach(function (s) {
            s.className = 'step failed';
            s.querySelector('.step-res').textContent = '已取消';
          });
        }
      },
      state: run
    };
  }

  /* ---------- 依存树（SVG 弧线，stroke-dashoffset 绘制） ----------
     data-dep="他/PRON 把/ADP …"  data-arcs="1>6:nsubj …"（依存词>中心词:关系，1 起）
     data-sugg="2,5" 为预标建议的弧（虚线） */
  function buildDep(el) {
    var toks = el.getAttribute('data-dep').split(/\s+/).map(function (t) { var p = t.split('/'); return { w: p[0], pos: p[1] || '' }; });
    var sugg = (el.getAttribute('data-sugg') || '').split(',').filter(Boolean).map(Number);
    var arcs = el.getAttribute('data-arcs').split(/\s+/).map(function (a) {
      var m = a.match(/^(\d+)>(\d+):(.+)$/);
      return { d: +m[1], h: +m[2], rel: m[3] };
    });
    var gap = 14, x = 8, xs = [];
    toks.forEach(function (t) {
      var w = Math.max(48, t.w.length * 17 + 20, t.pos.length * 7.5 + 14);
      xs.push(x + w / 2); t.wd = w; x += w + gap;
    });
    var width = x - gap + 8;
    /* 分层：外层弧高于其内部的弧；同层关系名重叠时上移一层 */
    arcs.forEach(function (a) {
      a.span = Math.abs(a.d - a.h); a.lo = Math.min(a.d, a.h); a.hi = Math.max(a.d, a.h);
      a.xd = xs[a.d - 1] + (a.d < a.h ? 5 : -5); a.xh = xs[a.h - 1] + (a.d < a.h ? -5 : 5);
      a.mx = (a.xd + a.xh) / 2; a.lw = a.rel.length * 6.8 + 8;
    });
    var placed = [];
    arcs.slice().sort(function (a, b) { return a.span - b.span; }).forEach(function (a) {
      var lvl = 1;
      placed.forEach(function (p) { if (p.lo >= a.lo && p.hi <= a.hi) lvl = Math.max(lvl, p.lvl + 1); });
      var clash = function (l) { return placed.some(function (p) { return p.lvl === l && Math.abs(p.mx - a.mx) < (p.lw + a.lw) / 2 + 4; }); };
      while (clash(lvl)) lvl++;
      a.lvl = lvl; placed.push(a);
    });
    var maxSpan = Math.max.apply(null, arcs.map(function (a) { return a.lvl; }).concat([1]));
    var root = +(el.getAttribute('data-root') || 0);
    var unit = 24, base = (root ? 52 : 30) + maxSpan * unit, top = 8;
    var out = '<svg width="' + width + '" height="' + (base + 46) + '" viewBox="0 0 ' + width + ' ' + (base + 46) + '" role="img" aria-label="依存树：' + toks.map(function (t) { return t.w; }).join(' ') + '">';
    var y0 = base;
    arcs.slice().sort(function (a, b) { return b.lvl - a.lvl; }).forEach(function (a, i) {
      var xd = a.xd, xh = a.xh;
      var h = 14 + a.lvl * unit;
      var cy = y0 - h * 1.33;
      var isS = sugg.indexOf(a.d) >= 0;
      var o = arcs.length - 1 - i;
      out += '<path class="arc draw' + (isS ? ' sugg' : '') + '" style="--i:' + o + '" pathLength="1" d="M' + xd + ' ' + (y0 - 2) + ' C' + xd + ' ' + cy + ' ' + xh + ' ' + cy + ' ' + xh + ' ' + (y0 - 2) + '"/>';
      out += '<polygon class="arrow" style="--i:' + o + '" points="' + (xd - 4) + ',' + (y0 - 9) + ' ' + (xd + 4) + ',' + (y0 - 9) + ' ' + xd + ',' + (y0 - 1) + '"/>';
      var mx = a.mx, my = y0 - h - 2, lw = a.lw;
      out += '<rect class="rel-bg rel" style="--i:' + o + '" x="' + (mx - lw / 2) + '" y="' + (my - 9) + '" width="' + lw + '" height="14" rx="3"/>';
      out += '<text class="rel" style="--i:' + o + '" x="' + mx + '" y="' + (my + 2) + '" text-anchor="middle">' + a.rel + '</text>';
    });
    if (root) {
      var xr = xs[root - 1];
      out += '<path class="arc draw" style="--i:' + arcs.length + '" pathLength="1" d="M' + xr + ' ' + top + ' L' + xr + ' ' + (y0 - 2) + '"/>';
      out += '<polygon class="arrow" style="--i:' + arcs.length + '" points="' + (xr - 4) + ',' + (y0 - 9) + ' ' + (xr + 4) + ',' + (y0 - 9) + ' ' + xr + ',' + (y0 - 1) + '"/>';
      out += '<rect class="rel-bg rel" style="--i:' + arcs.length + '" x="' + (xr + 4) + '" y="' + (top + 2) + '" width="34" height="14" rx="3"/><text class="rel" style="--i:' + arcs.length + '" x="' + (xr + 8) + '" y="' + (top + 13) + '">root</text>';
    }
    var chips = el.hasAttribute('data-chips');
    var conf = (el.getAttribute('data-conf') || '').split(',').filter(Boolean).map(Number);
    var sel = +(el.getAttribute('data-sel') || 0);
    toks.forEach(function (t, i) {
      if (chips) {
        var cw = t.pos.length * 7.6 + 14, k = i + 1;
        out += '<g class="tokg' + (k === sel ? ' sel' : '') + '" data-k="' + k + '" tabindex="-1">' +
          '<rect class="tokbg" x="' + (xs[i] - t.wd / 2) + '" y="' + (y0 + 2) + '" width="' + t.wd + '" height="54" rx="8"/>' +
          '<text class="tok" x="' + xs[i] + '" y="' + (y0 + 22) + '" text-anchor="middle">' + t.w + '</text>' +
          '<g class="pchip' + (conf.indexOf(k) >= 0 ? ' conf' : '') + '" data-c="' + posCat(t.pos) + '"><rect x="' + (xs[i] - cw / 2) + '" y="' + (y0 + 31) + '" width="' + cw + '" height="19" rx="5"/>' +
          '<text x="' + xs[i] + '" y="' + (y0 + 44.5) + '" text-anchor="middle">' + t.pos + '</text></g></g>';
      } else {
        out += '<text class="tok" x="' + xs[i] + '" y="' + (y0 + 20) + '" text-anchor="middle">' + t.w + '</text>';
        out += '<text class="pos" x="' + xs[i] + '" y="' + (y0 + 38) + '" text-anchor="middle">' + t.pos + '</text>';
      }
    });
    if (chips) out = out.replace(/height="(\d+(?:\.\d+)?)" viewBox="0 0 ([\d.]+) ([\d.]+)"/, function (m, h, w, vh) { return 'height="' + (+h + 14) + '" viewBox="0 0 ' + w + ' ' + (+vh + 14) + '"'; });
    el.innerHTML = out + '</svg>';
  }
  function hydrateDeps(root) { (root || document).querySelectorAll('[data-dep]').forEach(buildDep); }

  /* ---------- 对齐连线：按 DOM 位置画曲线 ----------
     容器 data-links="a1:b1 a2:b2:sugg …"；左/上侧元素 data-a="id"，右/下侧 data-b="id"；data-orient="v" 为左右两栏 */
  function drawAlign(box) {
    if (!box.offsetWidth) return;
    var old = box.querySelector(':scope > svg.align-svg');
    var r0 = box.getBoundingClientRect();
    var vert = box.getAttribute('data-orient') === 'v';
    var ns = 'http://www.w3.org/2000/svg';
    var s = old || document.createElementNS(ns, 'svg');
    var existing = old ? old.querySelectorAll('path') : null;
    s.setAttribute('class', 'align-svg');
    s.setAttribute('aria-hidden', 'true');
    s.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible';
    box.getAttribute('data-links').split(/\s+/).forEach(function (l, i) {
      var p = l.split(':');
      var a = box.querySelector('[data-a="' + p[0] + '"]'), b = box.querySelector('[data-b="' + p[1] + '"]');
      if (!a || !b) return;
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect(), d;
      if (vert) {
        var x1 = ra.right - r0.left + 4, y1 = ra.top + ra.height / 2 - r0.top, x2 = rb.left - r0.left - 4, y2 = rb.top + rb.height / 2 - r0.top, mx = (x1 + x2) / 2;
        d = 'M' + x1 + ' ' + y1 + ' C' + mx + ' ' + y1 + ' ' + mx + ' ' + y2 + ' ' + x2 + ' ' + y2;
      } else {
        var ax = ra.left + ra.width / 2 - r0.left, ay = ra.bottom - r0.top + 3, bx = rb.left + rb.width / 2 - r0.left, by = rb.top - r0.top - 3, my = (ay + by) / 2;
        d = 'M' + ax + ' ' + ay + ' C' + ax + ' ' + my + ' ' + bx + ' ' + my + ' ' + bx + ' ' + by;
      }
      if (existing && existing[i]) { existing[i].setAttribute('d', d); return; } // 已绘制：只更新位置，不重播
      var path = document.createElementNS(ns, 'path');
      path.setAttribute('d', d);
      path.setAttribute('pathLength', '1');
      path.setAttribute('class', 'align-line draw ' + (p[2] || ''));
      path.setAttribute('data-la', p[0]); path.setAttribute('data-lb', p[1]);
      path.style.setProperty('--i', i);
      s.appendChild(path);
    });
    if (!old) box.appendChild(s);
  }
  function hydrateAligns(root) { (root || document).querySelectorAll('[data-links]').forEach(drawAlign); }
  document.addEventListener('tabchange', function (e) {
    var id = e.detail.tab.getAttribute('aria-controls');
    var panel = id && document.getElementById(id);
    if (panel) { hydrateAligns(panel); }
  });
  var rz;
  window.addEventListener('resize', function () { clearTimeout(rz); rz = setTimeout(function () { hydrateAligns(); }, 150); });

  /* ===================== 全局能力（设计系统 + 跨页功能） ===================== */
  P.pin = '<path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/><path d="M12 14v7"/>';
  P.sun = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>';
  P.moon = '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>';
  P.history = '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>';
  P.compass = '<circle cx="12" cy="12" r="9"/><path d="m15.5 8.5-2 5-5 2 2-5z"/>';
  P.network = '<circle cx="12" cy="12" r="3"/><circle cx="4" cy="6" r="2"/><circle cx="20" cy="6" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="18" r="2"/><path d="m6 7 4 3M18 7l-4 3M7 18l3-4M17 17l-3-3"/>';
  P.palette = '<circle cx="12" cy="12" r="9"/><circle cx="8" cy="10" r="1.2"/><circle cx="12" cy="7.5" r="1.2"/><circle cx="16" cy="10" r="1.2"/><path d="M12 21a3 3 0 0 1 0-6h2"/>';
  P.diff = '<path d="M6 3v12M18 9v12M3 6h6M15 18h6"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/>';
  P.columns = '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>';
  P.basket = '<path d="M3 9h18l-2 11H5z"/><path d="m8 9 4-6 4 6"/>';
  P.box = '<path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5M12 13v8"/>';

  function pageId() { var s = document.querySelector('.side[data-active]'); return s ? s.getAttribute('data-active') : (document.body.getAttribute('data-page') || ''); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function typing(t) { return t && t.closest && t.closest('input, textarea, select, [contenteditable="true"]'); }

  /* 词性 → 8 色分类 */
  var POS_CAT = { NOUN: 1, PROPN: 1, VERB: 2, ADJ: 3, ADV: 4, PRON: 5, ADP: 6, AUX: 7, PART: 7, DET: 8, NUM: 8, CCONJ: 8, SCONJ: 8, PUNCT: 8, X: 8 };
  function posCat(p) { return POS_CAT[p] || 8; }

  /* 主题：localStorage 记忆；页面 <head> 中已提前应用，避免闪烁 */
  function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('theme', t); } catch (e) { /* 无存储 */ }
    document.dispatchEvent(new CustomEvent('themechange', { detail: t }));
  }
  function themeBtn() {
    return '<button class="btn ghost icon theme-btn" type="button" data-theme-toggle aria-label="切换深色模式" data-tip="深色 / 浅色">' + svg('sun', 'ic sun') + svg('moon', 'ic moon') + '</button>';
  }

  /* 名字取色：8 个低饱和色相 */
  var HUES = [212, 168, 38, 350, 256, 96, 22, 196];
  function hueOf(name) { var h = 0; for (var i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0; return HUES[h % HUES.length]; }
  function monogram(name, cls) { return '<span class="monogram ' + (cls || '') + '" style="--h:' + hueOf(name) + '" aria-hidden="true">' + esc(name.charAt(0)) + '</span>'; }
  function hydrateAvatars(root) {
    (root || document).querySelectorAll('[data-avatar]').forEach(function (el) {
      if (el.style.getPropertyValue('--h')) return;
      var n = el.getAttribute('data-avatar');
      el.style.setProperty('--h', hueOf(n));
      if (!el.textContent.trim()) el.textContent = n.charAt(0);
    });
  }

  /* 顶栏工具：命令面板、快捷键、主题 */
  function injectTools() {
    var bar = document.querySelector('.topbar'), head = document.querySelector('.doc-head');
    var tools = document.createElement('div');
    tools.className = 'tb-tools';
    if (bar || head) {
      tools.innerHTML = '<button class="cmdk-trigger" type="button" data-cmdk aria-label="打开命令面板">' + svg('search', 'ic ic-14') + '<span class="grow">搜索或跳转</span><kbd>Ctrl K</kbd></button>' +
        '<button class="btn ghost icon" type="button" data-keys aria-label="快捷键" data-tip="快捷键（?）">' + svg('keyboard', 'ic') + '</button>' + themeBtn();
      if (bar) bar.insertBefore(tools, bar.querySelector('.topbar-prog')); else head.appendChild(tools);
    } else {
      tools.classList.add('theme-float');
      tools.innerHTML = themeBtn();
      document.body.appendChild(tools);
    }
  }

  /* 面包屑范围栏：data-scope="项目|语料库|子库" */
  function hydrateCrumbs(root) {
    (root || document).querySelectorAll('.crumbs[data-scope]').forEach(function (c) {
      if (c.firstChild) return;
      var parts = c.getAttribute('data-scope').split('|');
      var labels = (c.getAttribute('data-labels') || '项目|语料库|子库').split('|');
      if (!c.getAttribute('aria-label')) c.setAttribute('aria-label', '范围');
      c.innerHTML = parts.map(function (p, i) {
        return (i ? svg('right', 'sep') : '') + '<button class="crumb" type="button" data-cmdk data-cmdk-q="' + esc(labels[i] || '') + '" data-tip="切换' + esc(labels[i] || '') + '">' + (i === 0 ? monogram(p) : '') + esc(p) + '</button>';
      }).join('');
    });
  }

  /* 深色提示：300ms 延迟 */
  var tipEl = null, tipTimer = null, tipFor = null;
  function hideTip() { clearTimeout(tipTimer); if (tipEl) { tipEl.remove(); tipEl = null; } }
  function showTip(el) {
    hideTip();
    tipTimer = setTimeout(function () {
      if (!document.body.contains(el)) return;
      tipEl = document.createElement('div');
      tipEl.className = 'tip';
      tipEl.setAttribute('role', 'tooltip');
      tipEl.textContent = el.getAttribute('data-tip');
      document.body.appendChild(tipEl);
      var r = el.getBoundingClientRect(), w = tipEl.offsetWidth, h = tipEl.offsetHeight;
      var x = Math.min(window.innerWidth - w - 8, Math.max(8, r.left + r.width / 2 - w / 2)), y = r.bottom + 8;
      if (y + h > window.innerHeight - 8) y = r.top - h - 8;
      tipEl.style.left = x + 'px'; tipEl.style.top = y + 'px';
    }, 300);
  }
  document.addEventListener('mouseover', function (e) {
    var t = e.target.closest && e.target.closest('[data-tip]');
    if (t === tipFor) return;
    tipFor = t;
    if (t) showTip(t); else hideTip();
  });
  document.addEventListener('focusin', function (e) { var t = e.target.closest && e.target.closest('[data-tip]'); if (t) { tipFor = t; showTip(t); } });
  document.addEventListener('focusout', function () { tipFor = null; hideTip(); });
  document.addEventListener('mousedown', function () { hideTip(); });

  /* 查询式着色：词 / 词性 / 间隔 $N / 条件 +- / 引号 / 属性 */
  function qhl(str) {
    return String(str).split(/(\s+)/).map(function (tok) {
      if (!tok || /^\s+$/.test(tok)) return tok;
      var pre = '';
      if (/^[+-]./.test(tok)) { pre = '<span class="' + (tok[0] === '+' ? 'qc' : 'qn') + '">' + tok[0] + '</span>'; tok = tok.slice(1); }
      if (/^\$\d+(-\d+)?$/.test(tok) || tok === '*' || tok === '?') return pre + '<span class="qg">' + esc(tok) + '</span>';
      if (/^".*"$/.test(tok)) return pre + '<span class="qs">' + esc(tok) + '</span>';
      if (/^[{\[].*[}\]]$/.test(tok)) return pre + '<span class="qa">' + esc(tok) + '</span>';
      if (tok === '|') return '<span class="qc">|</span>';
      return pre + tok.split('|').map(function (alt) {
        if (/^".*"$/.test(alt)) return '<span class="qs">' + esc(alt) + '</span>';
        var m = alt.split('/');
        return '<span class="qw">' + esc(m[0]) + '</span>' + (m.length > 1 ? '<span class="qp">/' + esc(m[1]) + '</span>' : '');
      }).join('<span class="qc">|</span>');
    }).join('');
  }
  function hydrateQ(root) {
    (root || document).querySelectorAll('[data-q]').forEach(function (el) {
      if (el.getAttribute('data-qd') === el.getAttribute('data-q')) return;
      el.setAttribute('data-qd', el.getAttribute('data-q'));
      el.classList.add('q');
      el.innerHTML = qhl(el.getAttribute('data-q'));
    });
  }

  /* 迷你趋势线：data-spark="3,5,4,8" */
  function hydrateSparks(root) {
    (root || document).querySelectorAll('[data-spark]').forEach(function (el) {
      if (el.firstChild) return;
      var v = el.getAttribute('data-spark').split(',').map(Number);
      var w = +(el.getAttribute('data-w') || 64), h = +(el.getAttribute('data-h') || 18);
      var mn = Math.min.apply(null, v), mx = Math.max.apply(null, v);
      var pts = v.map(function (y, i) { return [(i / (v.length - 1)) * w, h - 2 - ((y - mn) / ((mx - mn) || 1)) * (h - 4)]; });
      var line = pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ');
      var last = pts[pts.length - 1];
      el.setAttribute('role', 'img');
      if (!el.getAttribute('aria-label')) el.setAttribute('aria-label', '趋势 ' + v.join('、'));
      el.innerHTML = '<svg class="spark" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" aria-hidden="true"><polygon class="ar" points="0,' + h + ' ' + line + ' ' + w + ',' + h + '"/><polyline class="ln draw" pathLength="1" points="' + line + '"/><circle class="pt" r="2" cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) + '"/></svg>';
    });
  }

  /* ---------- 右下角：任务托盘 + 证据篮 ---------- */
  var EV_PAGES = ['search', 'stats', 'assistant', 'annotate', 'knowledge'];
  var EV_SEED = [{ k: 'hit', t: '很多文化负载词很难翻译。', s: 'zh#5730218 · Tatoeba 中英' }, { k: 'num', t: '成 · logDice 11.4', s: '搭配 · 翻译/v ±5' }];
  function loadEv() { try { var s = localStorage.getItem('evidence'); if (s) return JSON.parse(s); } catch (e) { /* 无存储 */ } return EV_SEED.slice(); }
  function saveEv(a) { try { localStorage.setItem('evidence', JSON.stringify(a)); } catch (e) { /* 无存储 */ } }
  var evItems = [];
  var trayJobs = [
    { id: 2241, name: '建索引 · 翻译课程作业 2026', cur: 5512, tot: 8610, unit: '句', spark: '120,118,131,126,140,137,144' },
    { id: 2231, name: '预标注 · 翻译策略', cur: 864, tot: 4800, unit: '句', spark: '36,41,38,44,40,46,43' }
  ];
  function renderDock() {
    if (!document.querySelector('.side[data-active]')) return;
    var dock = document.createElement('div');
    dock.className = 'dock';
    var html = '<div class="dock-item"><div class="dock-panel" id="tray-panel" role="dialog" aria-label="运行中的任务"><div class="dp-head"><b class="grow" style="font-weight:600;font-size:13px">运行中的任务</b><a class="btn xs ghost" href="jobs.html">全部任务</a></div><div class="dp-body" id="tray-list"></div></div>' +
      '<button class="capsule" type="button" id="tray-cap" aria-expanded="false" aria-controls="tray-panel"><svg class="ring" viewBox="0 0 24 24" aria-hidden="true"><circle class="bg" cx="12" cy="12" r="9"/><circle class="fg" id="tray-ring" cx="12" cy="12" r="9" pathLength="100" stroke-dasharray="100" stroke-dashoffset="100"/></svg><span id="tray-label">2 个任务运行中</span></button></div>';
    if (EV_PAGES.indexOf(pageId()) >= 0) {
      evItems = loadEv();
      html += '<div class="dock-item"><div class="dock-panel" id="ev-panel" role="dialog" aria-label="证据篮"><div class="dp-head">' + svg('basket', 'ic ic-14') + '<b class="grow" style="font-weight:600;font-size:13px">证据篮</b><span class="small muted num" id="ev-n2"></span></div><div class="dp-body" id="ev-list"></div>' +
        '<div class="dp-foot"><button class="btn xs p" type="button" id="ev-note">' + svg('note', 'ic ic-14') + '拖入笔记</button><button class="btn xs" type="button" id="ev-export">' + svg('download', 'ic ic-14') + '导出</button><div class="grow"></div><button class="btn xs ghost danger" type="button" id="ev-clear">清空</button></div></div>' +
        '<button class="capsule" type="button" id="ev-cap" aria-expanded="false" aria-controls="ev-panel">' + svg('basket', 'ic') + '证据篮<span class="cnt" id="ev-cnt">' + evItems.length + '</span></button></div>';
    }
    dock.innerHTML = html;
    document.body.appendChild(dock);
    renderTray();
    setInterval(function () {
      trayJobs.forEach(function (j) { j.cur = Math.min(j.tot, j.cur + Math.ceil(j.tot / 500)); });
      renderTray();
    }, 1200);
    if (evItems.length || document.getElementById('ev-cap')) renderEv();
  }
  function renderTray() {
    var list = document.getElementById('tray-list');
    if (!list) return;
    var running = trayJobs.filter(function (j) { return j.cur < j.tot; });
    var pct = trayJobs.reduce(function (s, j) { return s + j.cur / j.tot; }, 0) / trayJobs.length * 100;
    document.getElementById('tray-ring').setAttribute('stroke-dashoffset', (100 - pct).toFixed(1));
    document.getElementById('tray-label').textContent = running.length ? running.length + ' 个任务运行中' : '任务已完成';
    list.innerHTML = trayJobs.map(function (j) {
      var p = Math.round(j.cur / j.tot * 100);
      return '<div class="job-mini"><div class="row"><span class="grow">' + esc(j.name) + '</span><span class="mono small muted">#' + j.id + '</span></div>' +
        '<span class="prog thin ' + (p >= 100 ? 'ok' : 'striped') + '"><i style="--v:' + p + '%;animation:none' + (p < 100 ? ',stripes .7s linear infinite' : '') + '"></i></span>' +
        '<div class="row small muted"><span class="num grow">' + j.cur.toLocaleString('en-US') + ' / ' + j.tot.toLocaleString('en-US') + ' ' + j.unit + '</span><span data-spark="' + j.spark + '" data-w="48" data-h="14" aria-label="处理速度"></span><span class="num">' + p + '%</span></div></div>';
    }).join('');
    hydrateSparks(list);
  }
  var EV_ICON = { hit: 'quote', num: 'chart', card: 'spark' };
  function renderEv() {
    var list = document.getElementById('ev-list');
    if (!list) return;
    document.getElementById('ev-cnt').textContent = evItems.length;
    document.getElementById('ev-n2').textContent = evItems.length + ' 条';
    list.innerHTML = evItems.length ? evItems.map(function (it, i) {
      return '<div class="ev-item" draggable="true" data-i="' + i + '" style="animation-delay:' + i * 30 + 'ms"><span class="ev-k">' + svg(EV_ICON[it.k] || 'quote', 'ic') + '</span><span class="ev-t" title="' + esc(it.t) + '">' + esc(it.t) + '</span>' +
        '<button class="pin-btn" type="button" data-ev-del="' + i + '" aria-label="移出证据篮">' + svg('x', 'ic') + '</button><span class="ev-s">' + esc(it.s) + '</span></div>';
    }).join('') : '<div class="empty" style="padding:24px 12px">' + svg('pin', 'ic') + '<span class="sm">暂无证据，点行尾的钉住图标添加</span></div>';
    markPinned();
  }
  function closePanels(except) {
    document.querySelectorAll('.dock-panel.open').forEach(function (p) {
      if (p === except) return;
      p.classList.remove('open');
      var b = document.querySelector('[aria-controls="' + p.id + '"]'); if (b) b.setAttribute('aria-expanded', 'false');
    });
  }
  function togglePanel(cap) {
    var p = document.getElementById(cap.getAttribute('aria-controls'));
    var open = !p.classList.contains('open');
    closePanels(p);
    p.classList.toggle('open', open);
    cap.setAttribute('aria-expanded', open ? 'true' : 'false');
  }

  /* 钉住：KWIC 行、统计表行（table[data-pin]）、助手结果卡、[data-pinnable] */
  function pinBtn() { return '<button class="pin-btn" type="button" data-pin-btn aria-label="钉住到证据篮" data-tip="钉住到证据篮">' + svg('pin', 'ic') + '</button>'; }
  function hydratePins(root) {
    if (!document.getElementById('ev-cap')) return;
    root = root || document;
    root.querySelectorAll('table.kwic tbody tr, table[data-pin] tbody tr').forEach(function (tr) {
      if (tr.querySelector('[data-pin-btn]') || tr.querySelector('.skel') || !tr.cells.length || tr.cells[0].colSpan > 1) return;
      tr.cells[tr.cells.length - 1].insertAdjacentHTML('beforeend', pinBtn());
    });
    root.querySelectorAll('.ou > .ou-head').forEach(function (h) { if (!h.querySelector('[data-pin-btn]')) h.insertAdjacentHTML('beforeend', pinBtn()); });
    root.querySelectorAll('[data-pinnable]').forEach(function (el) {
      if (el.querySelector('[data-pin-btn]')) return;
      (el.querySelector('.pin-slot') || el).insertAdjacentHTML('beforeend', pinBtn());
    });
    markPinned();
  }
  function itemFor(btn) {
    var pn = btn.closest('[data-pinnable]'), tr = btn.closest('tr'), ou = btn.closest('.ou');
    if (pn && pn.getAttribute('data-pin-text')) return { k: pn.getAttribute('data-pin-kind') || 'hit', t: pn.getAttribute('data-pin-text'), s: pn.getAttribute('data-pin-src') || '' };
    if (tr && tr.closest('table.kwic')) {
      var c = tr.cells, right = c[2] ? c[2].cloneNode(true) : null;
      if (right) { var al = right.querySelector('.al'); if (al) al.remove(); }
      var src = tr.querySelector('.src');
      return { k: 'hit', t: (c[0].textContent + c[1].textContent + (right ? right.textContent : '')).replace(/\s+/g, ''), s: src ? src.textContent.trim() : '' };
    }
    if (tr) {
      var cells = tr.cells, label = cells[0].textContent.trim(), num = '';
      if (/^\d+$/.test(label) && cells[1]) label = cells[1].textContent.trim();
      for (var i = 1; i < cells.length; i++) { var tx = cells[i].textContent.trim(); if (/^[−+-]?[\d,]+(\.\d+)?$/.test(tx)) { num = tx; break; } }
      return { k: 'num', t: label.replace(/\s+/g, ' ') + (num ? ' · ' + num : ''), s: tr.closest('table').getAttribute('data-pin') || '' };
    }
    if (ou) return { k: 'card', t: ou.querySelector('.ou-title').textContent + ((ou.querySelector('.ou-meta') || {}).textContent ? ' · ' + ou.querySelector('.ou-meta').textContent : ''), s: '助手 · ' + (ou.getAttribute('data-component') || '') };
    return { k: 'hit', t: btn.parentNode.textContent.trim().slice(0, 40), s: '' };
  }
  function markPinned() {
    var set = evItems.map(function (it) { return it.t; });
    document.querySelectorAll('[data-pin-btn]').forEach(function (b) {
      var on = set.indexOf(itemFor(b).t) >= 0;
      if (b.classList.contains('on') !== on) b.classList.toggle('on', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }
  function flyTo(btn, text) {
    var cap = document.getElementById('ev-cap');
    if (!cap || reduced || !btn.animate) return Promise.resolve();
    var a = btn.getBoundingClientRect(), b = cap.getBoundingClientRect();
    var f = document.createElement('div');
    f.className = 'fly';
    f.textContent = text;
    f.style.left = a.left + 'px'; f.style.top = a.top + 'px';
    document.body.appendChild(f);
    var dx = b.left + 30 - a.left, dy = b.top + 10 - a.top;
    var an = f.animate([
      { transform: 'translate(0,0) scale(1)', opacity: 1 },
      { transform: 'translate(' + (dx * 0.55) + 'px,' + (dy * 0.45 - 70) + 'px) scale(.85)', opacity: 1, offset: 0.55 },
      { transform: 'translate(' + dx + 'px,' + dy + 'px) scale(.3)', opacity: 0.2 }
    ], { duration: 650, easing: 'cubic-bezier(.45,0,.25,1)' });
    return an.finished.then(function () { f.remove(); }, function () { f.remove(); });
  }
  function bump() { var c = document.getElementById('ev-cnt'); if (!c) return; c.classList.remove('bump'); void c.offsetWidth; c.classList.add('bump'); }
  function pinToggle(btn) {
    var it = itemFor(btn);
    var idx = evItems.map(function (x) { return x.t; }).indexOf(it.t);
    if (idx >= 0) { evItems.splice(idx, 1); saveEv(evItems); renderEv(); toast('已移出证据篮', 'x'); return; }
    evItems.push(it); saveEv(evItems);
    btn.classList.add('on');
    flyTo(btn, it.t).then(function () { renderEv(); bump(); });
  }

  /* ---------- 命令面板 Ctrl+K ---------- */
  var CMD = [
    ['页面', '语料库', 'corpora.html', 'db', ''], ['页面', '检索', 'search.html', 'search', ''], ['页面', '统计', 'stats.html', 'chart', ''],
    ['页面', '标注', 'annotate.html', 'pen', ''], ['页面', '知识库', 'knowledge.html', 'book', ''], ['页面', '助手', 'assistant.html', 'spark', ''],
    ['页面', '任务', 'jobs.html', 'clock', ''], ['页面', '项目设置', 'settings.html', 'sliders', ''], ['页面', '打开引导', 'onboarding.html', 'compass', '新项目'],
    ['页面', '组件规范', 'components.html', 'grid', '设计稿'], ['页面', '设计稿总览', 'index.html', 'grid', '设计稿'],
    ['项目', '翻译对等研究', 'search.html', 'folder', '当前 · 5 人'], ['项目', '学习者语料偏误', 'corpora.html', 'folder', '3 人'], ['项目', '个人空间', 'corpora.html#new', 'folder', '仅自己'],
    ['语料库', 'Tatoeba 中英', 'corpora.html#detail', 'db', '800,546 词'], ['语料库', 'LCMC 兰卡斯特汉语语料库', 'corpora.html#detail', 'db', '1,001,826 词'],
    ['语料库', '翻译课程作业 2026', 'corpora.html#detail', 'db', '建索引 64%'], ['语料库', '学习者英语作文', 'corpora.html#detail', 'db', '302,118 词'],
    ['保存的查询', '翻译/v +文化', 'search.html', 'search', '1,284', 1], ['保存的查询', '把 $3 翻译/v 成', 'search.html', 'search', '312', 1],
    ['保存的查询', '"文化负载词"|俗语/n', 'search.html', 'search', '96', 1], ['保存的查询', '进行/v -了', 'search.html', 'search', '2,041', 1],
    ['助手工具', 'corpus.search', 'assistant.html', 'tool', '检索语料'], ['助手工具', 'stats.collocations', 'assistant.html', 'tool', '搭配'],
    ['助手工具', 'stats.keywords', 'assistant.html', 'tool', '关键词'], ['助手工具', 'kb.search', 'assistant.html', 'tool', '知识库'], ['助手工具', 'annot.preannotate', 'assistant.html', 'tool', '预标注'],
    ['最近', '把字句英译策略对比', 'assistant.html', 'chat', '10:42'], ['最近', '访谈转写', 'corpora.html', 'db', '导入中'], ['最近', '任务 #2241 建索引', 'jobs.html', 'clock', '64%']
  ];
  var cmdkEl = null, cmdkReturn = null;
  function openCmdk(q) {
    if (cmdkEl) return;
    closeKeys();
    cmdkReturn = document.activeElement;
    cmdkEl = document.createElement('div');
    cmdkEl.className = 'overlay';
    cmdkEl.innerHTML = '<div class="dialog" role="dialog" aria-modal="true" aria-label="命令面板"><div class="cmdk-in">' + svg('search', 'ic ic-18') + '<input id="cmdk-q" type="text" placeholder="搜索页面、语料库、查询、工具" autocomplete="off" aria-label="搜索" aria-controls="cmdk-list" aria-autocomplete="list"><kbd>Esc</kbd></div>' +
      '<div class="cmdk-list" id="cmdk-list" role="listbox"></div><div class="dlg-foot"><span><kbd>↑</kbd> <kbd>↓</kbd> 选择</span><span><kbd>Enter</kbd> 打开</span><span><kbd>Esc</kbd> 关闭</span></div></div>';
    document.body.appendChild(cmdkEl);
    var input = cmdkEl.querySelector('input');
    input.value = q || '';
    renderCmdk();
    input.addEventListener('input', renderCmdk);
    input.addEventListener('keydown', cmdkKeys);
    cmdkEl.addEventListener('mousedown', function (e) { if (e.target === cmdkEl) closeCmdk(); });
    cmdkEl.addEventListener('mousemove', function (e) { var it = e.target.closest('.cmdk-item'); if (it) setOn(it); });
    cmdkEl.addEventListener('click', function (e) { var it = e.target.closest('.cmdk-item'); if (it) go(it); });
    setTimeout(function () { input.focus(); input.select(); }, 0);
  }
  function renderCmdk() {
    var q = cmdkEl.querySelector('input').value.trim().toLowerCase();
    var groups = {}, order = [];
    CMD.forEach(function (c, i) {
      if (q && (c[0] + ' ' + c[1] + ' ' + c[4]).toLowerCase().indexOf(q) < 0) return;
      if (!groups[c[0]]) { groups[c[0]] = []; order.push(c[0]); }
      groups[c[0]].push(i);
    });
    var list = cmdkEl.querySelector('.cmdk-list');
    list.innerHTML = order.length ? order.map(function (g) {
      return '<div class="cmdk-group">' + g + '</div>' + groups[g].map(function (i) {
        var c = CMD[i];
        return '<div class="cmdk-item" role="option" id="cmd-' + i + '" data-href="' + c[2] + '">' + svg(c[3], 'ic') + (c[5] ? '<span class="q">' + qhl(c[1]) + '</span>' : '<span>' + esc(c[1]) + '</span>') + '<span class="meta">' + esc(c[4]) + '</span></div>';
      }).join('');
    }).join('') : '<div class="cmdk-empty">没有匹配“' + esc(q) + '”的结果</div>';
    var first = list.querySelector('.cmdk-item');
    if (first) setOn(first);
  }
  function setOn(it) {
    cmdkEl.querySelectorAll('.cmdk-item.on').forEach(function (x) { x.classList.remove('on'); x.setAttribute('aria-selected', 'false'); });
    it.classList.add('on'); it.setAttribute('aria-selected', 'true');
    cmdkEl.querySelector('input').setAttribute('aria-activedescendant', it.id);
  }
  function go(it) { var h = it.getAttribute('data-href'); closeCmdk(); location.href = h; if (h.indexOf('#') >= 0 && location.pathname.indexOf(h.split('#')[0]) >= 0) location.reload(); }
  function cmdkKeys(e) {
    var items = Array.prototype.slice.call(cmdkEl.querySelectorAll('.cmdk-item'));
    var cur = items.indexOf(cmdkEl.querySelector('.cmdk-item.on'));
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Tab') {
      e.preventDefault();
      if (!items.length) return;
      var n = items[(cur + ((e.key === 'ArrowUp' || (e.key === 'Tab' && e.shiftKey)) ? -1 : 1) + items.length) % items.length];
      setOn(n); n.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') { e.preventDefault(); if (items[cur]) go(items[cur]); }
    else if (e.key === 'Escape') { e.preventDefault(); closeCmdk(); }
  }
  function closeCmdk() {
    if (!cmdkEl) return;
    var el = cmdkEl; cmdkEl = null;
    el.classList.add('out');
    setTimeout(function () { el.remove(); }, reduced ? 0 : 150);
    if (cmdkReturn && cmdkReturn.focus) cmdkReturn.focus();
  }

  /* ---------- 快捷键浮层 ? ---------- */
  var PAGE_KEYS = {
    search: [['检索', ['Enter']], ['聚焦查询框', ['/']], ['查询历史', ['H']], ['词性着色', ['P']]],
    stats: [['切换统计方法', ['1', '–', '5']]],
    annotate: [['确认', ['Enter']], ['拒绝', ['Del']], ['选词', ['←', '→']], ['选标签', ['1', '–', '7']], ['上一句 / 下一句', ['K', 'J']], ['词性着色', ['P']]],
    assistant: [['发送', ['Enter']], ['换行', ['Shift', 'Enter']], ['停止运行', ['Esc']], ['聚焦输入框', ['/']]],
    knowledge: [['聚焦检索框', ['/']]]
  };
  var PAGE_NAMES = { search: '检索', stats: '统计', annotate: '标注', assistant: '助手', knowledge: '知识库' };
  var keysEl = null;
  function keyRow(r) { return '<div class="key-row"><span>' + r[0] + '</span><span>' + r[1].map(function (k) { return k === '–' ? '–' : '<kbd>' + k + '</kbd>'; }).join('') + '</span></div>'; }
  function openKeys() {
    if (keysEl) return;
    closeCmdk();
    var pk = PAGE_KEYS[pageId()];
    keysEl = document.createElement('div');
    keysEl.className = 'overlay';
    keysEl.innerHTML = '<div class="dialog" role="dialog" aria-modal="true" aria-labelledby="keys-t" style="width:560px"><div class="cmdk-in">' + svg('keyboard', 'ic ic-18') + '<b id="keys-t" class="grow" style="color:var(--text);font-weight:600">快捷键</b><kbd>Esc</kbd></div><div class="keys-grid">' +
      '<h3>全局</h3>' + [['命令面板', ['Ctrl', 'K']], ['快捷键', ['?']], ['关闭浮层', ['Esc']], ['聚焦输入框', ['/']]].map(keyRow).join('') +
      (pk ? '<h3>' + PAGE_NAMES[pageId()] + '</h3>' + pk.map(keyRow).join('') : '') + '</div></div>';
    document.body.appendChild(keysEl);
    keysEl.addEventListener('mousedown', function (e) { if (e.target === keysEl) closeKeys(); });
    keysEl.querySelector('.dialog').setAttribute('tabindex', '-1');
    keysEl.querySelector('.dialog').focus();
  }
  function closeKeys() { if (!keysEl) return; var el = keysEl; keysEl = null; el.classList.add('out'); setTimeout(function () { el.remove(); }, reduced ? 0 : 150); }

  /* 全局快捷键与点击 */
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); if (cmdkEl) closeCmdk(); else openCmdk(); return; }
    if (e.key === 'Escape') { if (keysEl) { closeKeys(); return; } closePanels(); document.querySelectorAll('.popover:not([hidden])').forEach(function (p) { p.hidden = true; }); return; }
    if (typing(e.target) || cmdkEl) return;
    if (e.key === '?') { e.preventDefault(); if (keysEl) closeKeys(); else openKeys(); return; }
    if (e.key === '/' && !keysEl) { var f = document.querySelector('[data-slash]'); if (f) { e.preventDefault(); f.focus(); } }
  });
  document.addEventListener('click', function (e) {
    var c = e.target.closest('[data-cmdk]');
    if (c) { openCmdk(c.getAttribute('data-cmdk-q') || ''); return; }
    if (e.target.closest('[data-keys]')) { openKeys(); return; }
    var th = e.target.closest('[data-theme-toggle]');
    if (th) {
      setTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
      th.classList.toggle('spin-once');
      return;
    }
    var pb = e.target.closest('[data-pin-btn]');
    if (pb) { e.stopPropagation(); pinToggle(pb); return; }
    var del = e.target.closest('[data-ev-del]');
    if (del) {
      var row = del.closest('.ev-item'); row.classList.add('out');
      setTimeout(function () { evItems.splice(+del.getAttribute('data-ev-del'), 1); saveEv(evItems); renderEv(); }, reduced ? 0 : 200);
      return;
    }
    var cap = e.target.closest('#ev-cap, #tray-cap');
    if (cap) { togglePanel(cap); return; }
    if (e.target.closest('#ev-note')) { toast('已加入笔记草稿「翻译 + 文化：搭配与译法」· ' + evItems.length + ' 条证据', 'note'); return; }
    if (e.target.closest('#ev-export')) { toast('已导出 ' + evItems.length + ' 条证据（XLSX，含出处）', 'download'); return; }
    if (e.target.closest('#ev-clear')) {
      document.querySelectorAll('#ev-list .ev-item').forEach(function (r) { r.classList.add('out'); });
      setTimeout(function () { evItems = []; saveEv(evItems); renderEv(); bump(); }, reduced ? 0 : 220);
      return;
    }
    if (!e.target.closest('.dock')) closePanels();
  }, true);
  document.addEventListener('dragstart', function (e) {
    var it = e.target.closest && e.target.closest('.ev-item');
    if (it && e.dataTransfer) { var x = evItems[+it.getAttribute('data-i')]; e.dataTransfer.setData('text/plain', x.t + '（' + x.s + '）'); }
  });

  /* 对齐图悬停：高亮相关连线与对应词 */
  document.addEventListener('mouseover', function (e) {
    var sp = e.target.closest && e.target.closest('.algraph [data-a], .algraph [data-b]');
    document.querySelectorAll('.algraph.hovering').forEach(function (g) {
      if (sp && g.contains(sp)) return;
      g.classList.remove('hovering');
      g.querySelectorAll('.hl').forEach(function (x) { x.classList.remove('hl'); });
    });
    if (!sp) return;
    var g = sp.closest('.algraph');
    g.querySelectorAll('.hl').forEach(function (x) { x.classList.remove('hl'); });
    g.classList.add('hovering');
    sp.classList.add('hl');
    var isA = sp.hasAttribute('data-a'), key = sp.getAttribute(isA ? 'data-a' : 'data-b');
    g.querySelectorAll('.align-line').forEach(function (p) {
      if (p.getAttribute(isA ? 'data-la' : 'data-lb') !== key) return;
      p.classList.add('hl');
      var o = g.querySelector(isA ? '[data-b="' + p.getAttribute('data-lb') + '"]' : '[data-a="' + p.getAttribute('data-la') + '"]');
      if (o) o.classList.add('hl');
    });
  });

  /* 动态内容统一补全（新插入的行、卡片） */
  function hydrateAll(root) { hydrateIcons(root); hydrateQ(root); hydrateSparks(root); hydrateAvatars(root); hydrateCrumbs(root); hydratePins(root); }
  function watch() {
    var pend = false;
    new MutationObserver(function () {
      if (pend) return;
      pend = true;
      requestAnimationFrame(function () { pend = false; hydrateAll(document); });
    }).observe(document.body, { childList: true, subtree: true });
  }

  /* ---------- 启动 ---------- */
  function boot() {
    renderNav();
    injectTools();
    renderDock();
    hydrateIcons();
    hydrateDeps();
    hydrateAll(document);
    initTabs();
    countUp();
    hydrateAligns();
    watch();
    // 网络字体到达后只修正位置（离线时 fonts.ready 可能迟迟不返回）
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { hydrateAligns(); });
    document.querySelectorAll('.drawer').forEach(function (d) { if (!d.classList.contains('open')) d.setAttribute('aria-hidden', 'true'); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();

  window.UI = {
    svg: svg, hydrateIcons: hydrateIcons, countUp: countUp, toast: toast, busy: busy, openDrawer: openDrawer, closeDrawer: closeDrawer,
    replay: replay, selectTab: selectTab, agentDemo: agentDemo, reduced: reduced, sleep: sleep,
    hydrateDeps: hydrateDeps, drawAlign: drawAlign, hydrateAligns: hydrateAligns,
    hydrate: hydrateAll, qhl: qhl, posCat: posCat, setTheme: setTheme, openCmdk: openCmdk, openKeys: openKeys,
    monogram: monogram, hueOf: hueOf, flyTo: flyTo, toastIcon: svg
  };
})();
