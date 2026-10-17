// Regenera los agentes 3D con un solo comando: Blender/Cycles (<agente>.py) y despues los contact sheets capturados con Chrome.
// Salida en assets/agents3d/, por agente: <agente>-<expr>.png (512), -128, -64, -48, -32, review/<agente>-angle-<grados>.png,
// review/<agente>-done_alt*.png (la otra pose de manos), <agente>-strip.png (64/48/32 de las seis expresiones),
// contact-sheet-<agente>.html y contact-sheet-<agente>-{light,dark}.png. Ademas contact-sheet-team.html y
// contact-sheet-team-{light,dark}.png con todos los agentes juntos (los que ya tengan sus PNG).
// Uso: node tooling/avatars3d/blender/render.mjs [--quick] [nicole] [alfred]   (sin nombres: todos)
//   Solo se vuelven a renderizar los agentes nombrados; las hojas se regeneran siempre para todos.
//   BLENDER=ruta/a/blender.exe (por defecto el portable 5.2 de D:/Documentos/Projects/assets/_tools)
//   CHROME=ruta/a/chrome.exe
// Tarda unos 4-5 min por agente en una RTX 5070 (OptiX: ~20 s por expresion a 1536 px y 384 muestras); sin GPU Cycles cae a CPU
// y tarda bastante mas.
import { spawn, spawnSync } from 'node:child_process';
import { writeFileSync, mkdtempSync, existsSync } from 'node:fs';
import { join, dirname, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath, pathToFileURL } from 'node:url';

const BLENDER = process.env.BLENDER ?? 'D:/Documentos/Projects/assets/_tools/blender-5.2.2-windows-x64/blender.exe';
const CHROME = process.env.CHROME ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const DEVTOOLS_PORT = 9232;
const EXPRESSIONS = ['neutral', 'thinking', 'working', 'happy', 'error', 'done'];
const AGENTS = { nicole: 'Nicole', alfred: 'Alfred', bob: 'Bob', hugo: 'Hugo', ines: 'Ines', conan: 'Conan', sami: 'Sami', dani: 'Dani' };

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, '..', '..', '..');
const out = join(repo, 'assets', 'agents3d');
const quick = process.argv.includes('--quick');
const named = process.argv.slice(2).filter((a) => !a.startsWith('--'));
for (const a of named) if (!(a in AGENTS)) throw new Error(`Agente desconocido: ${a} (hay: ${Object.keys(AGENTS).join(', ')})`);
const toRender = named.length ? named : Object.keys(AGENTS);

const t0 = Date.now();
for (const agent of toRender) {
  const t = Date.now();
  const args = ['-b', '--factory-startup', '-P', join(here, `${agent}.py`), '--', '--out', out, '--review'];
  if (quick) args.push('--quick');
  const run = spawnSync(BLENDER, args, { stdio: ['ignore', 'pipe', 'inherit'], encoding: 'utf8', maxBuffer: 1 << 28 });
  const lines = run.stdout.split('\n');
  for (const line of lines) if (line.startsWith(`[${agent}]`) || line.startsWith('[check] AVISO')) console.log(line);
  const checks = lines.filter((line) => line.startsWith('[check]'));
  const warned = checks.filter((line) => line.includes('AVISO')).length;
  console.log(`[check] ${agent}: interpenetracion ${checks.length - warned}/${checks.length} pares OK`);
  if (run.status !== 0) throw new Error(`Blender (${agent}) salio con codigo ${run.status}`);
  console.log(`Blender ${agent}: ${((Date.now() - t) / 1000).toFixed(1)} s`);
}
// hojas: un agente entra si ya tiene sus PNG
const ready = Object.keys(AGENTS).filter((a) => existsSync(join(out, `${a}-done-32.png`)));

function sheetHtml(agents, title) {
  const name = (a) => AGENTS[a];
  const card = (a, e) => `<figure><img src="${a}-${e}.png" width="200" height="200" alt="${name(a)} ${e}"><figcaption>${e}</figcaption></figure>`;
  const strip = (a, e) => `<tr><th>${e}</th>` + [64, 48, 32].map((s) =>
    `<td><img src="${a}-${e}-${s}.png" width="${s}" height="${s}" alt="${name(a)} ${e} ${s}px"><small>${s} px</small></td>`).join('') + '</tr>';
  // hoja de equipo: una fila de tarjetas por agente y, por expresion, los iconos de todos lado a lado
  const teamStrip = (e) => `<tr><th>${e}</th>` + agents.map((a) => [48, 32].map((s) =>
    `<td><img src="${a}-${e}-${s}.png" width="${s}" height="${s}" alt="${name(a)} ${e} ${s}px"><small>${name(a)} ${s}</small></td>`).join('')).join('') + '</tr>';
  const cards = agents.map((a) => `${agents.length > 1 ? `<h3>${name(a)}</h3>` : ''}<div class="cards">${EXPRESSIONS.map((e) => card(a, e)).join('')}</div>`).join('\n');
  const strips = agents.length > 1
    ? `<h3>Iconos a 48 y 32 px juntos (encuadre de cabeza, sin reescalar en el navegador)</h3>
<table class="strip"><tbody>${EXPRESSIONS.map(teamStrip).join('')}</tbody></table>`
    : `<h3>Iconos a 64, 48 y 32 px (encuadre de cabeza, sin reescalar en el navegador)</h3>
<table class="strip"><tbody>${EXPRESSIONS.map((e) => strip(agents[0], e)).join('')}</tbody></table>`;
  const section = (id, label) => `<section id="${id}"><h2>${label}</h2>
${cards}
${strips}
</section>`;
  return `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${title}</title>
<style>
body { margin: 0; font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
section { padding: 24px 28px; }
#light { background: #F8FAFC; color: #0F172A; }
#dark { background: #0F172A; color: #E2E8F0; }
h2 { margin: 0 0 12px; font-size: 18px; font-weight: 600; }
h3 { margin: 24px 0 8px; font-size: 14px; font-weight: 600; }
.cards { display: flex; gap: 18px; flex-wrap: wrap; }
figure { margin: 0; text-align: center; }
figure img { display: block; margin: 0 auto; }
figcaption { font-size: 12px; opacity: .7; margin-top: 4px; }
table.strip { border-collapse: collapse; }
table.strip th { text-align: left; padding: 4px 16px 4px 0; font-weight: 500; font-size: 12px; opacity: .7; }
table.strip td { padding: 4px 16px 4px 0; text-align: center; vertical-align: bottom; }
table.strip img { display: block; margin: 0 auto; image-rendering: auto; }
table.strip small { display: block; font-size: 11px; opacity: .6; margin-top: 2px; }
</style></head>
<body>
${section('light', 'Tema claro')}
${section('dark', 'Tema oscuro')}
<script>
// #light muestra solo el tema claro, #dark solo el oscuro; sin hash se ven los dos.
function apply() {
  const h = location.hash;
  document.getElementById('light').hidden = h === '#dark';
  document.getElementById('dark').hidden = h === '#light';
}
addEventListener('hashchange', apply);
apply();
</script>
</body></html>
`;
}
const sheets = ready.map((a) => [`contact-sheet-${a}`, sheetHtml([a], `${AGENTS[a]} 3D: contact sheet`)]);
if (ready.length > 1) sheets.push(['contact-sheet-team', sheetHtml(ready, 'Agentes 3D: equipo')]);
for (const [base, html] of sheets) writeFileSync(join(out, `${base}.html`), html);

// Captura cada tema con Chrome headless por DevTools (WebSocket global de Node 22+).
const profile = mkdtempSync(join(tmpdir(), 'agents3d-chrome-'));
const chrome = spawn(CHROME, ['--headless=new', '--no-first-run', '--no-default-browser-check', '--allow-file-access-from-files',
  `--remote-debugging-port=${DEVTOOLS_PORT}`, `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });

async function pageTarget() {
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${DEVTOOLS_PORT}/json/list`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* Chrome aun arrancando */ }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error('Chrome no expuso el puerto de DevTools');
}

function connect(url) {
  const ws = new WebSocket(url);
  let seq = 0;
  const pending = new Map();
  const waiters = new Map();
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id) {
      const p = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error.message));
      else p.resolve(msg.result);
    } else if (waiters.has(msg.method)) {
      waiters.get(msg.method)(msg.params);
      waiters.delete(msg.method);
    }
  });
  return new Promise((ok, fail) => {
    ws.addEventListener('error', fail);
    ws.addEventListener('open', () => ok({
      send: (method, params = {}) => new Promise((res, rej) => {
        const id = ++seq;
        pending.set(id, { resolve: res, reject: rej });
        ws.send(JSON.stringify({ id, method, params }));
      }),
      once: (method) => new Promise((res) => waiters.set(method, res)),
      close: () => ws.close(),
    }));
  });
}

const c = await connect(await pageTarget());
try {
  await c.send('Page.enable');
  await c.send('Runtime.enable');
  for (const [base] of sheets) {
    const sheet = pathToFileURL(join(out, `${base}.html`)).href;
    for (const theme of ['light', 'dark']) {
      for (const url of ['about:blank', `${sheet}#${theme}`]) {
        const loaded = c.once('Page.loadEventFired');
        await c.send('Page.navigate', { url });
        await loaded;
      }
      await c.send('Emulation.setDeviceMetricsOverride', { width: 1180, height: 800, deviceScaleFactor: 1, mobile: false });
      const { result } = await c.send('Runtime.evaluate', { expression: 'document.documentElement.scrollHeight', returnByValue: true });
      const height = Math.ceil(result.value);
      await c.send('Emulation.setDeviceMetricsOverride', { width: 1180, height, deviceScaleFactor: 1, mobile: false });
      const { data } = await c.send('Page.captureScreenshot', { format: 'png', clip: { x: 0, y: 0, width: 1180, height, scale: 1 } });
      writeFileSync(join(out, `${base}-${theme}.png`), Buffer.from(data, 'base64'));
      console.log(`${base}-${theme}.png (${height}px alto)`);
    }
  }
} finally {
  c.close();
  chrome.kill();
}
console.log(`Total: ${((Date.now() - t0) / 1000).toFixed(1)} s`);
