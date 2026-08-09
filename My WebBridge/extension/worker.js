const DAEMON_URL = 'ws://127.0.0.1:10087/ws';
const CDP_VERSION = '1.3';
const SNAPSHOT_NODE_CAP = 250;
const INTERESTING_ROLES = new Set([
  'rootWebArea', 'button', 'link', 'textbox', 'searchbox', 'combobox', 'heading',
  'checkbox', 'radio', 'img', 'tab', 'menuitem', 'option', 'listbox', 'list',
  'text', 'staticText', 'paragraph', 'switch', 'slider', 'treeitem',
]);

const sessionState = new Map();
const refs = new Map();
let refCounter = 0;
const attachedTabs = new Set();
const waiters = new Map();
let ws = null;
let reconnectMs = 1000;

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  ws = new WebSocket(DAEMON_URL);
  ws.onopen = () => {
    reconnectMs = 1000;
    send({ type: 'hello', payload: { version: '0.1.0', extension_version: '0.1.0' } });
  };
  ws.onmessage = (ev) => handleDaemonMessage(JSON.parse(ev.data));
  ws.onclose = () => {
    ws = null;
    setTimeout(connect, reconnectMs);
    reconnectMs = Math.min(reconnectMs * 2, 15000);
  };
  ws.onerror = () => ws.close();
}

chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();

setInterval(() => {
  chrome.runtime.getPlatformInfo().catch(() => {});
}, 15000);

self.addEventListener('unhandledrejection', (ev) => {
  console.error('SW unhandled rejection:', ev.reason);
});
self.addEventListener('error', (ev) => {
  console.error('SW error:', ev.message);
});

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

async function handleDaemonMessage(msg) {
  switch (msg.type) {
    case 'hello_ack':
      break;
    case 'ping':
      send({ type: 'pong' });
      break;
    case 'tool_call': {
      try {
        const result = await executeTool(msg.payload);
        send({ type: 'tool_result', responseToRequestId: msg.requestId, payload: result });
      } catch (err) {
        send({ type: 'tool_result', responseToRequestId: msg.requestId, payload: { error: String(err && err.message ? err.message : err) } });
      }
      break;
    }
  }
}

async function executeTool({ tool, args, session }) {
  switch (tool) {
    case 'navigate': return navigate(args, session);
    case 'find_tab': return findTab(args);
    case 'list_tabs': return listTabs(session);
    case 'close_tab': return closeTab(session);
    case 'close_session': return closeSession(session);
    case 'snapshot': return snapshot(session);
    case 'click': return click(args, session);
    case 'fill': return fill(args, session);
    case 'evaluate': return evaluate(args, session);
    case 'cdp': return cdpTool(args, session);
    case 'screenshot': return screenshot(args, session);
    case 'mouse': return mouse(args, session);
    case 'type': return typeText(args, session);
    default: throw new Error(`unknown tool: ${tool}`);
  }
}

function getSession(session) {
  if (!sessionState.has(session)) {
    sessionState.set(session, { tabs: new Set(), groupId: null, currentTabId: null });
  }
  return sessionState.get(session);
}

function requireCurrentTab(session) {
  const st = getSession(session);
  if (st.currentTabId === null) throw new Error('navigate or find_tab first');
  return st.currentTabId;
}

async function attach(tabId) {
  if (attachedTabs.has(tabId)) return;
  try {
    await chrome.debugger.attach({ tabId }, CDP_VERSION);
    attachedTabs.add(tabId);
  } catch (err) {
    if (String(err && err.message || err).includes('already attached')) {
      attachedTabs.add(tabId);
      return;
    }
    throw err;
  }
  for (const domain of ['Page', 'Runtime', 'DOM', 'Accessibility']) {
    try { await cdp(tabId, `${domain}.enable`); } catch (err) { /* non-fatal */ }
  }
}

function cdp(tabId, method, params = {}) {
  return chrome.debugger.sendCommand({ tabId }, method, params);
}

chrome.debugger.onEvent.addListener((source, method) => {
  if (method === 'Page.loadEventFired' && waiters.has(source.tabId)) {
    const w = waiters.get(source.tabId);
    waiters.delete(source.tabId);
    w.resolve();
  }
});

function waitForLoad(tabId, timeoutMs = 20000) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => { waiters.delete(tabId); resolve(); }, timeoutMs);
    waiters.set(tabId, { resolve: () => { clearTimeout(timer); resolve(); } });
  });
}

async function getTabMeta(tabId) {
  const tab = await chrome.tabs.get(tabId);
  return { url: tab.url, title: tab.title };
}

async function navigate(args, session) {
  const { url, newTab = true, group_title } = args;
  const st = getSession(session);
  let tab;
  if (newTab) {
    tab = await chrome.tabs.create({ url });
  } else {
    const first = st.tabs.values().next().value;
    if (first !== undefined) {
      tab = await chrome.tabs.update(first, { url });
    } else {
      tab = await chrome.tabs.create({ url });
    }
  }
  await attach(tab.id);
  const loaded = waitForLoad(tab.id);
  await cdp(tab.id, 'Page.navigate', { url });
  await loaded;
  if (st.groupId === null) {
    const groupId = await chrome.tabs.group({ tabIds: [tab.id] });
    st.groupId = groupId;
    if (group_title) {
      try { await chrome.tabGroups.update(groupId, { title: group_title }); } catch (err) { /* non-fatal */ }
    }
  } else {
    try { await chrome.tabs.group({ tabIds: [tab.id], groupId: st.groupId }); } catch (err) { /* non-fatal */ }
  }
  st.tabs.add(tab.id);
  st.currentTabId = tab.id;
  const meta = await getTabMeta(tab.id);
  return { success: true, url: meta.url, tabId: tab.id, groupTitle: group_title || null };
}

async function findTab(args) {
  const { url, active } = args;
  const tabs = active
    ? await chrome.tabs.query({ active: true, currentWindow: true })
    : await chrome.tabs.query({ url });
  if (tabs.length === 0) throw new Error(`no tab matching ${url}`);
  const tab = tabs[0];
  await attach(tab.id);
  return { success: true, url: tab.url, tabId: tab.id, borrowed: !!active };
}

async function listTabs(session) {
  const st = getSession(session);
  const tabs = [];
  for (const id of st.tabs) {
    const t = await chrome.tabs.get(id);
    tabs.push({ tabId: t.id, url: t.url, title: t.title, active: t.active });
  }
  return { success: true, groupId: st.groupId, tabs };
}

async function closeTab(session) {
  const st = getSession(session);
  const first = st.tabs.values().next().value;
  if (first === undefined) return { success: true, closed: false };
  await chrome.tabs.remove(first);
  st.tabs.delete(first);
  if (st.tabs.size === 0) st.currentTabId = null;
  return { success: true, closed: true };
}

async function closeSession(session) {
  const st = getSession(session);
  let closed = 0;
  for (const id of [...st.tabs]) {
    try { await chrome.tabs.remove(id); closed++; } catch (err) { /* tab already gone */ }
  }
  sessionState.delete(session);
  return { success: true, closed };
}

function buildTree(nodes) {
  const byId = new Map(nodes.map((n) => [n.nodeId, n]));
  const roots = [];
  for (const n of nodes) {
    if (n.parentId && byId.has(n.parentId)) continue;
    roots.push(n);
  }
  const rows = [];
  let count = 0;
  let truncated = false;
  function visit(node, depth) {
    if (count >= SNAPSHOT_NODE_CAP) { truncated = true; return; }
    const role = node.role ? node.role.value : 'generic';
    const name = node.name ? node.name.value : '';
    if (INTERESTING_ROLES.has(role) || name) {
      const ref = `@e${refCounter++}`;
      refs.set(ref, { backendDOMNodeId: node.backendDOMNodeId, role, name });
      count++;
      rows.push(`${'  '.repeat(depth)}${ref} ${role} "${name}"`);
    }
    for (const child of nodes.filter((n) => n.parentId === node.nodeId)) {
      visit(child, depth + 1);
    }
  }
  for (const r of roots) visit(r, 0);
  return { rows, count, truncated };
}

async function snapshot(session) {
  const tabId = requireCurrentTab(session);
  await attach(tabId);
  const { nodes } = await cdp(tabId, 'Accessibility.getFullAXTree');
  refs.clear();
  refCounter = 0;
  const tree = buildTree(nodes);
  const meta = await getTabMeta(tabId);
  return { url: meta.url, title: meta.title, tree };
}

async function resolveObjectId(tabId, selector) {
  if (selector.startsWith('@e')) {
    const ref = refs.get(selector);
    if (!ref) throw new Error(`unknown ref ${selector}`);
    const { object } = await cdp(tabId, 'DOM.resolveNode', { backendNodeId: ref.backendDOMNodeId });
    if (!object) throw new Error(`ref ${selector} resolved to nothing`);
    return object.objectId;
  }
  const { root } = await cdp(tabId, 'DOM.getDocument', { depth: -1 });
  const { nodeId } = await cdp(tabId, 'DOM.querySelector', { nodeId: root.nodeId, selector });
  if (nodeId === 0) throw new Error(`no element matches ${selector}`);
  const { object } = await cdp(tabId, 'DOM.resolveNode', { nodeId });
  return object.objectId;
}

async function click(args, session) {
  const tabId = requireCurrentTab(session);
  const { selector } = args;
  const objectId = await resolveObjectId(tabId, selector);
  const res = await cdp(tabId, 'Runtime.callFunctionOn', {
    objectId,
    returnByValue: true,
    functionDeclaration: `function() { this.click(); return { tag: this.tagName, text: (this.textContent || this.getAttribute('aria-label') || '').trim().slice(0, 100) }; }`,
  });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text);
  return { success: true, ...res.result.value };
}

async function fill(args, session) {
  const tabId = requireCurrentTab(session);
  const { selector, value } = args;
  const objectId = await resolveObjectId(tabId, selector);
  const res = await cdp(tabId, 'Runtime.callFunctionOn', {
    objectId,
    awaitPromise: true,
    returnByValue: true,
    functionDeclaration: `async function(v) {
      const el = (this.tagName === 'INPUT' || this.tagName === 'TEXTAREA')
        ? this
        : (this.querySelector ? this.querySelector('input, textarea') : null);
      if (!el) {
        this.focus();
        document.execCommand('selectAll', false, null);
        document.execCommand('insertText', false, v);
        return { mode: 'contenteditable', tag: this.tagName, id: this.id || null };
      }
      el.focus();
      const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, v);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      return { mode: 'value', tag: el.tagName, id: el.id || null, value: el.value };
    }`,
    arguments: [{ value }],
  });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.text);
  return { success: true, ...res.result.value };
}

async function evaluate(args, session) {
  const tabId = requireCurrentTab(session);
  const { code } = args;
  const res = await cdp(tabId, 'Runtime.evaluate', {
    expression: code,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  });
  if (res.exceptionDetails) {
    throw new Error(res.exceptionDetails.exception ? res.exceptionDetails.exception.description : res.exceptionDetails.text);
  }
  return { type: typeof res.result.value, value: res.result.value };
}

async function cdpTool(args, session) {
  const tabId = requireCurrentTab(session);
  const { method, params } = args;
  return await cdp(tabId, method, params || {});
}

async function screenshot(args, session) {
  const tabId = requireCurrentTab(session);
  const { format = 'png', quality } = args;
  const { data } = await cdp(tabId, 'Page.captureScreenshot', {
    format,
    quality: format === 'jpeg' ? (quality || 80) : undefined,
  });
  return { format, data, sizeBytes: Math.floor((data.length * 3) / 4) };
}

async function mouse(args, session) {
  const tabId = requireCurrentTab(session);
  const { type = 'move', x, y, button = 'left', deltaX = 0, deltaY = 0 } = args;
  if (type === 'wheel') {
    await cdp(tabId, 'Input.dispatchMouseEvent', {
      type: 'mouseWheel', x, y, deltaX, deltaY, button: 'none',
    });
    return { success: true, type, x, y, deltaX, deltaY };
  }
  const events = type === 'click'
    ? ['mousePressed', 'mouseReleased']
    : type === 'press' ? ['mousePressed']
    : type === 'release' ? ['mouseReleased']
    : ['mouseMoved'];
  for (const e of events) {
    await cdp(tabId, 'Input.dispatchMouseEvent', {
      type: e, x, y,
      button: e === 'mouseMoved' ? 'none' : button,
      clickCount: 1,
    });
  }
  return { success: true, type, x, y };
}

async function typeText(args, session) {
  const tabId = requireCurrentTab(session);
  await cdp(tabId, 'Input.insertText', { text: args.text });
  return { success: true, text: args.text };
}
