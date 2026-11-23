// Tour por todas as telas do Hub FinOps, gravado quadro a quadro (30 fps) com relógio controlado.
// Uso: node demo.js [saida.mp4]   (hub em http://localhost:8090)
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const path = require('path');
const FPS = 30, BASE = 'http://localhost:8090', SAIDA = process.argv[2] || 'demo_mudo.mp4';
const ease = (t) => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await ctx.clock.install({ time: new Date('2026-11-23T17:45:00-03:00') });
  await ctx.addInitScript(() => { try { if (!localStorage.getItem('hub-tema')) localStorage.setItem('hub-tema', 'escuro'); } catch (e) {} });
  const p = await ctx.newPage();
  const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(FPS), SAIDA + '.tmp.mp4']);
  const fimFF = new Promise((ok, erro) => ff.on('close', (c) => c === 0 ? ok() : erro(new Error('ffmpeg ' + c))));
  let cur = { x: 960, y: 600 }, legenda = '', ripple = 0, total = 0;

  async function overlay() {
    // durante a troca de página o documento ainda não existe: espera carregar
    await p.waitForLoadState('domcontentloaded').catch(() => {});
    await p.evaluate(([x, y, leg, rip]) => {
      if (!document.documentElement || !document.body) return;
      let c = document.getElementById('demo-cursor');
      if (!c) {
        const st = document.createElement('style');
        st.textContent = `#demo-cursor{position:fixed;z-index:2147483647;pointer-events:none;width:30px;height:30px;margin:-3px 0 0 -3px}
          #demo-rip{position:fixed;z-index:2147483646;pointer-events:none;border-radius:50%;border:3px solid #FBBF24}
          #demo-leg{position:fixed;z-index:2147483645;left:50%;bottom:38px;transform:translateX(-50%);max-width:1500px;padding:13px 28px;border-radius:14px;
            background:rgba(8,9,11,.86);border:1px solid rgba(255,255,255,.12);color:#fff;font:600 30px/1.35 Inter,'Segoe UI',sans-serif;text-align:center;
            box-shadow:0 12px 40px rgba(0,0,0,.35)}`;
        document.documentElement.appendChild(st);
        c = document.createElement('div'); c.id = 'demo-cursor';
        c.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24"><path d="M4 2l15 11-6.5 1.2L16 21l-3 1.3-3.4-6.8L4 19z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
        document.documentElement.appendChild(c);
        const r = document.createElement('div'); r.id = 'demo-rip'; document.documentElement.appendChild(r);
        const l = document.createElement('div'); l.id = 'demo-leg'; document.documentElement.appendChild(l);
      }
      c.style.left = x + 'px'; c.style.top = y + 'px';
      const r = document.getElementById('demo-rip'), tam = 18 + 46 * rip;
      r.style.display = rip > 0 && rip < 1 ? 'block' : 'none';
      r.style.left = (x - tam / 2) + 'px'; r.style.top = (y - tam / 2) + 'px'; r.style.width = tam + 'px'; r.style.height = tam + 'px';
      r.style.opacity = String(1 - rip);
      const l = document.getElementById('demo-leg'); l.style.display = leg ? 'block' : 'none'; if (l.textContent !== leg) l.textContent = leg;
    }, [cur.x, cur.y, legenda, ripple]);
  }
  async function quadro() {
    await p.clock.runFor(1000 / FPS);
    await overlay();
    const buf = await p.screenshot({ type: 'jpeg', quality: 90 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
    total++;
  }
  async function espera(seg) { for (let i = 0; i < Math.round(seg * FPS); i++) await quadro(); }
  async function move(x, y, seg = .8) {
    const a = { ...cur }, n = Math.max(1, Math.round(seg * FPS));
    for (let i = 1; i <= n; i++) {
      const k = ease(i / n); cur = { x: a.x + (x - a.x) * k, y: a.y + (y - a.y) * k };
      await p.mouse.move(cur.x, cur.y); await quadro();
    }
  }
  async function alvo(sel) {
    const e = p.locator(sel).first(); await e.scrollIntoViewIfNeeded().catch(() => {});
    const r = await e.boundingBox(); return [r.x + r.width / 2, r.y + r.height / 2];
  }
  async function clica(sel, seg = .8, depois = null) {
    const [x, y] = await alvo(sel); await move(x, y, seg);
    if (depois) await depois(); else await p.mouse.click(x, y);
    for (let i = 1; i <= 12; i++) { ripple = i / 12; await quadro(); } ripple = 0;
  }
  async function pronto() {
    // painel FinOps: espera os números chegarem (/api/finops) antes de gravar
    if (await p.locator('#kpis').count()) await p.waitForFunction(() => document.querySelectorAll('#kpis .val').length > 0, null, { timeout: 15000 });
    await p.waitForTimeout(400);
  }
  async function vai(url, seg = 0) {
    await p.goto(BASE + url, { waitUntil: 'load' });
    await pronto();
    if (seg) await espera(seg);
  }
  async function rola(y, seg = 1) {
    const a = await p.evaluate(() => window.scrollY), n = Math.round(seg * FPS);
    for (let i = 1; i <= n; i++) { await p.evaluate((v) => window.scrollTo(0, v), a + (y - a) * ease(i / n)); await quadro(); }
  }
  async function varre(sel, seg = 2.5) {
    const r = await p.locator(sel).boundingBox(), n = Math.round(seg * FPS), yy = r.y + r.height * .45;
    await move(r.x + 10, yy, .6);
    for (let i = 1; i <= n; i++) { cur = { x: r.x + 10 + (r.width - 20) * (i / n), y: yy }; await p.mouse.move(cur.x, cur.y); await quadro(); }
  }

  // ------------------------------------------------------------------ roteiro do tour
  legenda = 'Visão geral: custo, previsão e economia de todos os tenants';
  await vai('/', 3.2);
  legenda = 'Custo acumulado no mês × orçamento, com projeção até o fim do mês';
  await varre('#graf', 2.8);
  legenda = 'Modo diário: passe o mouse para ver o custo de cada dia, por ambiente';
  await clica('[data-modo="diario"]'); await varre('#graf', 3);
  legenda = 'Ranking por recurso, app ou centro de custo: cada cor é um ambiente';
  await clica('#rank-por', .8, () => p.selectOption('#rank-por', 'app')); await espera(1.8);
  await clica('#rank-por', .4, () => p.selectOption('#rank-por', 'cc')); await espera(1.6);
  await clica('#rank-por', .4, () => p.selectOption('#rank-por', 'recursos')); await espera(.8);
  legenda = 'Filtre os ambientes: o painel inteiro se recalcula';
  await clica('input[data-amb="producao"]'); await espera(.6);
  await clica('input[data-amb="integracao"]'); await espera(2.4);
  await clica('input[data-amb="producao"]'); await clica('input[data-amb="integracao"]'); await espera(1);
  legenda = 'Representatividade de cada ambiente e previsão × orçamento';
  await rola(300, 1); await move(...(await alvo('#rosca svg')), .7); await espera(1); await move(...(await alvo('#medidor svg')), .7); await espera(1.2);
  legenda = 'Onde economizar: cada ação com a evidência, o que fazer e o dono';
  await clica('.acao'); await espera(2.6);
  await rola(0, .8);
  legenda = 'Uma página por tenant: Produção';
  await clica('a.aba:has-text("Produção")'); await pronto(); await espera(2.6);
  legenda = 'Desenvolvimento: o painel aponta a causa do estouro do orçamento';
  await clica('a.aba:has-text("Desenvolvimento")'); await pronto(); await espera(1.2);
  await move(...(await alvo('#aviso')), .8); await espera(2.4);
  legenda = 'Prestação de contas: tags, economia já feita e relatório executivo do tenant';
  await rola(400, 1); await espera(1.4);
  legenda = 'Relatório executivo de uma página, gerado em código';
  await clica('#card-contas a.botao'); await p.waitForTimeout(700); await espera(1.4); await rola(500, 2.2); await espera(.8);
  legenda = 'Integração: dentro do orçamento e com economia já comprovada';
  await vai('/ambiente/integracao', 2.8);
  legenda = 'Modo claro e escuro, salvo no navegador de cada usuário';
  await clica('#tema-topo'); await espera(1.6);
  await clica('a.aba:has-text("Visão geral")'); await pronto(); await espera(2.4);
  legenda = 'Operação: testes, tarefas e tudo o que já rodou, num lugar só';
  await clica('a.ico[href="/operacao#visao"]'); await p.waitForTimeout(900); await espera(3);
  legenda = 'Executar: qualquer tarefa com um clique e o log ao vivo';
  await clica('nav.icones a[data-s="executar"]'); await espera(1.2);
  await clica('#tarefas button:has-text("Executar") >> nth=6'); await p.waitForTimeout(300); await espera(.8);
  await rola(await p.evaluate(() => document.getElementById('log').getBoundingClientRect().top + window.scrollY - 380), 1.2); await espera(3.6);
  await rola(0, .5);
  legenda = 'Histórico: de onde veio cada execução e o resultado';
  await clica('nav.icones a[data-s="historico"]'); await espera(2.8);
  legenda = 'Resultados: anomalias de custo e documentação das Logic Apps';
  await clica('nav.icones a[data-s="resultados"]'); await espera(1.2); await rola(500, 1.6); await espera(.8); await rola(0, .6);
  legenda = 'Chamados abertos sozinhos pelos alertas do Grafana, com diagnóstico';
  await clica('nav.icones a[data-s="chamados"]'); await espera(3);
  legenda = 'Painéis do Grafana dentro do hub';
  await clica('nav.icones a[data-s="grafana"]'); await p.waitForTimeout(4500);
  await rola(await p.evaluate(() => { const d = [...document.querySelectorAll('#grafana-conteudo div')].find((x) => x.textContent.trim().startsWith('FinOps: custos')); return d.getBoundingClientRect().top + window.scrollY - 20; }), .6);
  await p.waitForTimeout(2500); await espera(3.6);
  legenda = 'Métodos de teste: como cada resultado é conferido';
  await clica('nav.icones a[data-s="metodos"]'); await p.evaluate(() => window.scrollTo(0, 0)); await espera(2.8);
  legenda = 'Documentos: relatórios, documentação e PDFs';
  await clica('nav.icones a[data-s="documentos"]'); await espera(2.8);
  // encerramento
  legenda = '';
  await p.goto('file://' + path.join(process.cwd(), 'fim_demo.html')); await p.waitForTimeout(500);
  cur = { x: -100, y: -100 }; await espera(5);

  ff.stdin.end(); await fimFF;
  require('fs').renameSync(SAIDA + '.tmp.mp4', SAIDA);
  console.log('ok', total, 'quadros', (total / FPS).toFixed(1), 's');
  await b.close();
})().catch((e) => { console.error(e); process.exit(1); });
