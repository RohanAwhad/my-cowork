import { spawn } from 'node:child_process';
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const PORT = 10087;
const BASE = `http://127.0.0.1:${PORT}`;
const EXT_DIR = path.join(ROOT, 'extension');
const PROFILE = '/tmp/my-webbridge-profile';
const SESSION = 'demo-music';
const SEARCH_QUERY = process.env.SEARCH_QUERY || 'Rick Rubin';
const ARTIFACTS = '/tmp/my-webbridge';
const FAILURES = [];

const daemon = spawn(path.join(ROOT, 'daemon', '.venv', 'bin', 'python'), [
  path.join(ROOT, 'daemon', 'daemon.py'), '--port', String(PORT),
], { stdio: 'inherit' });

function step(name) {
  console.log(`\n== ${name}`);
}

async function poll(fn, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  let lastErr;
  while (Date.now() < deadline) {
    try { return await fn(); } catch (err) { lastErr = err; await new Promise((r) => setTimeout(r, 500)); }
  }
  throw new Error(`poll timeout: ${label} (last: ${lastErr && lastErr.message})`);
}

async function daemonUp() {
  await poll(async () => {
    const r = await fetch(`${BASE}/status`);
    if (!r.ok) throw new Error(`status ${r.status}`);
  }, 20000, 'daemon /status');
}

async function command(action, args = {}, session = SESSION) {
  const r = await fetch(`${BASE}/command`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ action, args, session }),
  });
  const j = await r.json();
  if (!j.ok) {
    throw new Error(`command ${action} failed: ${JSON.stringify(j)}`);
  }
  return j.data;
}

async function assert(cond, label) {
  if (cond) { console.log(`PASS ${label}`); } else { console.log(`FAIL ${label}`); FAILURES.push(label); }
}

async function waitForExtension(context) {
  const sw = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker', { timeout: 20000 });
  console.log(`service worker: ${sw.url()}`);
  sw.on('console', (msg) => console.log(`[sw console ${msg.type()}] ${msg.text()}`));
  sw.on('close', () => console.log('[sw] service worker CLOSED'));
  await poll(async () => {
    const r = await fetch(`${BASE}/status`);
    const j = await r.json();
    if (!j.extension_connected) throw new Error('extension not connected');
    return j;
  }, 20000, 'extension_connected');
  console.log('extension connected to daemon');
}

async function findYoutubePage(context) {
  for (let i = 0; i < 20; i++) {
    for (const p of context.pages()) {
      if (p.url().includes('youtube.com')) return p;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error('no youtube page found');
}

async function dismissConsent(page) {
  try {
    await page.locator('button[aria-label^="Accept"], button[aria-label*="accept all"], button[aria-label*="Accept all"]').first().click({ timeout: 4000 });
    console.log('dismissed cookie consent');
  } catch (err) { /* none present */ }
}

async function main() {
  fs.rmSync(PROFILE, { recursive: true, force: true });
  fs.rmSync(ARTIFACTS, { recursive: true, force: true });
  fs.mkdirSync(ARTIFACTS, { recursive: true });

  await daemonUp();
  step('launching Chromium with extension loaded');
  const context = await chromium.launchPersistentContext(PROFILE, {
    channel: 'chromium',
    headless: false,
    args: [
      `--disable-extensions-except=${EXT_DIR}`,
      `--load-extension=${EXT_DIR}`,
    ],
  });
  try {
    await waitForExtension(context);

    step('navigate to YouTube (new tab, tab group "My WebBridge demo")');
    const nav = await command('navigate', {
      url: 'https://www.youtube.com', newTab: true, group_title: 'My WebBridge demo',
    });
    assert(nav.success && nav.groupTitle === 'My WebBridge demo', 'navigate created tab with group title');
    const page = await findYoutubePage(context);
    await page.waitForLoadState('domcontentloaded');
    await dismissConsent(page);

    step('snapshot: read the page as an accessibility tree');
    const snap1 = await command('snapshot');
    console.log(snap1.tree.rows.slice(0, 25).join('\n'));
    assert(snap1.tree.count > 0, `snapshot produced ${snap1.tree.count} nodes`);
    const searchRef = snap1.tree.rows
      .map((r) => r      .match(/^\s*(@e\d+) (searchbox|combobox) "(.*)"/))
      .find((m) => m && /search/i.test(m[3]));
    assert(!!searchRef, 'search box found in snapshot');

    step('fill search box + submit search');
    const fillRes = await command('fill', { selector: searchRef[1], value: SEARCH_QUERY });
    console.log('fill result:', JSON.stringify(fillRes));
    assert(fillRes.success, `fill returned ${fillRes.mode}`);
    const valCheck = await command('evaluate', {
      code: `document.querySelector('input#search') ? document.querySelector('input#search').value : null`,
    });
    console.log('search input value:', JSON.stringify(valCheck.value));
    assert(valCheck.value === SEARCH_QUERY, 'search box contains the query');
    await command('evaluate', {
      code: `(() => { const f = document.querySelector('form#search-form'); if (!f) return {ok:false}; f.requestSubmit(); return {ok:true}; })()`,
    });
    await page.waitForURL(/results/, { timeout: 15000 });

    step('snapshot results, click first video');
    await page.waitForSelector('a#video-title', { timeout: 15000 });
    const snap2 = await command('snapshot');
    const videoRef = snap2.tree.rows
      .map((r) => r.match(/^(@e\d+) link "([^"]*)"/))
      .find((m) => m && /Rick/i.test(m[2]));
    const clickTarget = videoRef ? videoRef[1] : 'a#video-title';
    const clickRes = videoRef
      ? await command('click', { selector: clickTarget })
      : await command('evaluate', { code: `(() => { const a = document.querySelector('a#video-title'); if (!a) return {ok:false}; a.click(); return {ok:true}; })()` });
    assert(clickRes.success, `clicked first video${videoRef ? ` (${videoRef[2]})` : ''}`);

    step('wait for video, then play');
    await page.waitForURL(/watch/, { timeout: 20000 });
    await page.waitForSelector('video', { timeout: 20000 });
    await new Promise((r) => setTimeout(r, 3000));
    await command('cdp', { method: 'Emulation.setAutoplayPolicy', params: { policy: 'no-user-gesture-required' } });
    const playRes = await command('evaluate', {
      code: `(() => { const v = document.querySelector('video'); if (!v) return {ok:false}; v.play(); return {ok:true, paused: v.paused}; })()`,
    });
    assert(playRes.value && playRes.value.ok, 'video.play() called');
    await new Promise((r) => setTimeout(r, 5000));

    step('verify video is actually playing');
    const state = await command('evaluate', {
      code: `(() => { const v = document.querySelector('video'); if (!v) return null; return { paused: v.paused, currentTime: v.currentTime, src: v.currentSrc, title: document.title }; })()`,
    });
    console.log('video state:', JSON.stringify(state.value, null, 2));
    assert(state.value && state.value.paused === false, 'video not paused');
    assert(state.value && state.value.currentTime > 0, `video advancing (t=${state.value.currentTime}s)`);

    step('screenshot evidence');
    const shot = await command('screenshot', { format: 'png' });
    fs.writeFileSync(path.join(ARTIFACTS, 'youtube-playing.png'), Buffer.from(shot.data, 'base64'));
    fs.writeFileSync(path.join(ARTIFACTS, 'video-state.json'), JSON.stringify(state.value, null, 2));
    assert(shot.sizeBytes > 10000, `screenshot ${shot.sizeBytes} bytes`);

    step('tab group verified');
    const tabs = await command('list_tabs');
    console.log('tabs:', JSON.stringify(tabs.tabs.map((t) => ({ url: t.url.slice(0, 60) }))));
    assert(tabs.groupId !== null, 'tabs are in a tab group');
    assert(tabs.tabs.length >= 1, 'session tabs tracked');

    step('close_session: close the whole tab group');
    const closed = await command('close_session');
    assert(closed.closed >= 1, `close_session closed ${closed.closed} tab(s)`);
    await poll(() => {
      if (context.pages().length !== 0) throw new Error('pages still open');
    }, 10000, 'all pages closed');
    assert(context.pages().length === 0, 'browser window has no pages left');
  } finally {
    await context.close();
    daemon.kill();
  }

  console.log('\n================');
  if (FAILURES.length === 0) {
    console.log('ALL TESTS PASSED');
  } else {
    console.log(`${FAILURES.length} FAILURE(S): ${FAILURES.join('; ')}`);
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error('TEST CRASHED:', err.message);
  daemon.kill();
  process.exitCode = 1;
});
