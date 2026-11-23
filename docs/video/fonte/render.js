// node render.js stills            -> quadros de conferência em stills/
// node render.js cenas [ids...]    -> um MP4 por cena em cenas/
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const FPS = 30;
const rot = JSON.parse(fs.readFileSync('roteiro_tempos.json', 'utf8'));
const CAUDA = { s01_gancho: .9, s12_fecho: 2.8 };
rot.forEach((s) => { s.voz_ini = .35; s.dur = +(s.voz_ini + s.dur_voz + (CAUDA[s.id] ?? .7)).toFixed(3); });
fs.writeFileSync('roteiro_final.json', JSON.stringify(rot, null, 1));
const meta = JSON.parse(fs.readFileSync('cap/meta.json', 'utf8'));
(async () => {
  const modo = process.argv[2], ids = process.argv.slice(3);
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await p.goto('file://' + process.cwd() + '/palco.html');
  await p.evaluate(([m, r]) => window.preparar(m, r), [meta, rot]);
  const PASTA = process.env.PASTA_CENAS || 'cenas';
  if (process.env.CREDITO) await p.evaluate((c) => { window.CREDITO = c; }, process.env.CREDITO);
  if (modo === 'stills') {
    fs.mkdirSync('stills', { recursive: true });
    for (let i = 0; i < rot.length; i++) {
      if (ids.length && !ids.includes(rot[i].id)) continue;
      for (const f of [.15, .45, .8]) {
        await p.evaluate(([i, t]) => window.quadro(i, t), [i, rot[i].dur * f]);
        await p.screenshot({ path: `stills/${rot[i].id}-${Math.round(f * 100)}.jpg`, type: 'jpeg', quality: 80 });
      }
    }
  } else {
    fs.mkdirSync(PASTA, { recursive: true });
    for (let i = 0; i < rot.length; i++) {
      const s = rot[i];
      if (ids.length && !ids.includes(s.id)) continue;
      const n = Math.round(s.dur * FPS), tmp = `${PASTA}/${s.id}.tmp.mp4`;
      const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(FPS), tmp]);
      const fim = new Promise((ok, erro) => ff.on('close', (c) => c === 0 ? ok() : erro(new Error('ffmpeg ' + c))));
      for (let q = 0; q < n; q++) {
        await p.evaluate(([i, t]) => window.quadro(i, t), [i, q / FPS]);
        const buf = await p.screenshot({ type: 'jpeg', quality: 92 });
        if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once('drain', r));
      }
      ff.stdin.end(); await fim;
      fs.renameSync(tmp, `${PASTA}/${s.id}.mp4`);
      console.log('ok', s.id, n, 'quadros');
    }
  }
  await b.close();
})();
