const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2 });
  const p = await ctx.newPage();
  const meta = {};
  const caixa = async (sel) => { const e = await p.$(sel); const r = await e.boundingBox(); return [r.x, r.y, r.width, r.height]; };
  const tira = async (nome, extra) => {
    await p.waitForTimeout(1600);
    const h = await p.evaluate(() => document.documentElement.scrollHeight);
    await p.screenshot({ path: `cap/${nome}.jpg`, type: 'jpeg', quality: 92, fullPage: true });
    meta[nome] = { w: 1920, h, ...(extra ? await extra() : {}) };
  };
  await p.goto('http://localhost:8090/'); await p.evaluate(() => localStorage.setItem('hub-tema', 'escuro'));
  // 1. visão geral escura
  await p.goto('http://localhost:8090/');
  await tira('geral', async () => ({ kpis: await caixa('.grade4'), grafico: await caixa('section[aria-labelledby="t-graf"]'),
    ranking: await caixa('section[aria-labelledby="t-rank"]'), medidor: await caixa('section[aria-labelledby="t-meta"]'),
    acoes: await caixa('section[aria-labelledby="t-eco"]'), abas: await caixa('#abas'), rosca: await caixa('#card-rosca') }));
  // 2. gráfico diário com o cursor sobre 06/11
  await p.click('[data-modo="diario"]'); await p.waitForTimeout(1200);
  const g = await (await p.$('#graf')).boundingBox();
  await p.mouse.move(g.x + g.width * 16 / 29, g.y + 60);
  await tira('diario', async () => ({ grafico: await caixa('section[aria-labelledby="t-graf"]') }));
  await p.mouse.move(5, 5);
  // 3. ranking por app (barras divididas por ambiente)
  await p.goto('http://localhost:8090/'); await p.selectOption('#rank-por', 'app');
  await tira('ranking_app', async () => ({ ranking: await caixa('section[aria-labelledby="t-rank"]'), rosca: await caixa('#card-rosca') }));
  // 4. página do tenant de desenvolvimento
  await p.goto('http://localhost:8090/ambiente/desenvolvimento');
  await tira('dev', async () => ({ topo: await caixa('main .topo'), aviso: await caixa('#aviso'), abas: await caixa('#abas'),
    acoes: await caixa('section[aria-labelledby="t-eco"]'), medidor: await caixa('section[aria-labelledby="t-meta"]'), kpis: await caixa('.grade4') }));
  // 5. evidência aberta
  await p.click('.acao'); await p.waitForTimeout(300);
  await tira('dev_evidencia', async () => ({ acoes: await caixa('section[aria-labelledby="t-eco"]') }));
  // 6. produção e integração
  await p.goto('http://localhost:8090/ambiente/producao'); await tira('prod', async () => ({ topo: await caixa('main .topo'), abas: await caixa('#abas') }));
  await p.goto('http://localhost:8090/ambiente/integracao'); await tira('int', async () => ({ topo: await caixa('main .topo'), abas: await caixa('#abas'), contas: await caixa('#card-contas') }));
  // 7. modo claro
  await p.evaluate(() => localStorage.setItem('hub-tema', 'claro'));
  await p.goto('http://localhost:8090/'); await tira('geral_claro');
  await p.goto('http://localhost:8090/ambiente/desenvolvimento'); await tira('dev_claro');
  fs.writeFileSync('cap/meta.json', JSON.stringify(meta, null, 1));
  await b.close();
})();
