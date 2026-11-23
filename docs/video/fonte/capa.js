const { chromium } = require('playwright'); const fs = require('fs');
(async () => {
  const rot = JSON.parse(fs.readFileSync('roteiro_final.json', 'utf8')), meta = JSON.parse(fs.readFileSync('cap/meta.json', 'utf8'));
  const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 1920, height: 1080 } });
  await p.goto('file://' + process.cwd() + '/palco.html'); await p.evaluate(([m, r]) => window.preparar(m, r), [meta, rot]);
  await p.evaluate(() => { window.quadro(3, 0); document.getElementById('cena').insertAdjacentHTML('beforeend', `
    <div style="position:absolute;left:0;right:0;bottom:0;height:300px;background:linear-gradient(transparent,rgba(5,6,8,.92))"></div>
    <div style="position:absolute;left:50%;top:430px;transform:translate(-50%,-50%);width:180px;height:180px;border-radius:90px;background:rgba(11,12,14,.85);border:5px solid #F3F4F6;display:flex;align-items:center;justify-content:center">
      <svg width="80" height="80" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" fill="#F3F4F6"/></svg></div>
    <div style="position:absolute;left:0;right:0;bottom:70px;text-align:center;font-size:64px;font-weight:900;letter-spacing:-2px">Hub FinOps <span style="color:#A1A5B0;font-weight:700">· vídeo de apresentação (1:52)</span></div>`); });
  await p.waitForTimeout(300); await p.screenshot({ path: 'capa.jpg', type: 'jpeg', quality: 86 }); await b.close();
})();
