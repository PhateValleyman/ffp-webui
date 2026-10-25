const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
let currentView = 'overview';
let currentFilePath = '/';
let editorPath = '';
let editorService = null;
let envRevealed = false;
let accountData = null;
let editingUser = null;
let passwordUser = '';
let luantiSnapshot = null;
let toastTimer;
const FRONTEND_VERSION = '0.12.0';
let backendVersion = '';

const themeToggle = $('#theme-toggle');
function setTheme(theme, persist = true) {
  const selected = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = selected;
  themeToggle.textContent = `Motiv: ${selected === 'dark' ? 'tmavý' : 'světlý'}`;
  themeToggle.setAttribute('aria-pressed', String(selected === 'dark'));
  if (persist) {
    try { localStorage.setItem('ffp-webui-theme', selected); } catch (_) {}
  }
}
let initialTheme = 'light';
try {
  initialTheme = localStorage.getItem('ffp-webui-theme') ||
    (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
} catch (_) {}
setTheme(initialTheme, false);
themeToggle.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));

function toast(message, error = false) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.toggle('error', error);
  el.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('visible'), 3600);
}

async function api(path, options = {}) {
  const { timeoutMs: requestedTimeout, ...fetchOptions } = options;
  const method = (fetchOptions.method || 'GET').toUpperCase();
  const timeoutMs = requestedTimeout === undefined ? (method === 'GET' ? 12000 : 0) : requestedTimeout;
  const controller = !fetchOptions.signal && typeof AbortController === 'function' ? new AbortController() : null;
  const timer = controller && timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;
  try {
    const response = await fetch(path, {
      cache: 'no-store', ...fetchOptions,
      ...(controller ? { signal: controller.signal } : {})
    });
    const type = response.headers.get('content-type') || '';
    const data = type.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      if (response.status === 405 && path.startsWith('/api/')) {
        const requestPath = new URL(path, location.href).pathname;
        const server = data?.server_version || backendVersion || 'neznámá';
        throw new Error(`API nenalezlo ${method} ${requestPath} (backend ${server}, UI ${FRONTEND_VERSION}). Zkontrolujte shodu verzí a restartujte službu.`);
      }
      throw new Error(data?.error || data?.message || `HTTP ${response.status}`);
    }
    return data;
  } catch (error) {
    if (controller?.signal.aborted) throw new Error(`Server neodpověděl do ${Math.ceil(timeoutMs / 1000)} sekund.`);
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}
function post(path, data) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
}
async function checkBackendVersion() {
  const warning = $('#backend-version-warning');
  try {
    const health = await api('/api/health');
    backendVersion = String(health.version || '');
    if (backendVersion !== FRONTEND_VERSION) {
      warning.textContent = `Nesouhlasí verze rozhraní a serveru (UI ${FRONTEND_VERSION}, backend ${backendVersion || 'neznámý'}). Po instalaci balíku restartujte /ffp/start/ffp-webui.sh; do té doby mohou některé API trasy selhávat.`;
      warning.hidden = false;
    } else {
      warning.hidden = true;
    }
  } catch (_) {
    warning.textContent = 'Verzi běžícího backendu nelze ověřit. Pokud se zobrazí chyba API trasy, zkontrolujte, zda po aktualizaci běží server ze stejného balíku jako statické soubory.';
    warning.hidden = false;
  }
}
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined && text !== null) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function statCard(label, value, meta = '') {
  const card = node('div', undefined, 'stat-card');
  card.append(node('div', label, 'label'), node('div', value || '—', 'value'));
  if (meta) card.append(node('div', meta, 'meta'));
  return card;
}
function setView(name) {
  currentView = name;
  if (name !== 'adb') stopAdbScreen();
  $$('.nav-item').forEach(button => button.classList.toggle('active', button.dataset.view === name));
  $$('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
  $('#main-content').focus({ preventScroll: true });
}
$$('.nav-item').forEach(button => button.addEventListener('click', () => {
  setView(button.dataset.view);
  refreshView(button.dataset.view);
}));
$('#refresh').addEventListener('click', () => refreshView(currentView));
$$('[data-refresh]').forEach(button => button.addEventListener('click', () => refreshView(button.dataset.refresh)));

async function loadOverview() {
  try {
    const system = await api('/api/system');
    $('#connection-status').textContent = system.demo ? 'Demo režim' : 'Připojeno';
    $('#system-badge').textContent = system.demo ? 'Ukázka' : 'Systém dostupný';
    $('#system-badge').className = `badge ${system.demo ? 'badge-neutral' : 'badge-green'}`;
    $('#demo-notice').hidden = !system.demo;
    const memory = system.memory || {};
    const storage = (system.storage || [])[0] || {};
    $('#system-cards').replaceChildren(
      statCard('Název zařízení', system.hostname, system.arch),
      statCard('Kernel', short(system.kernel, 54), system.demo ? 'Profil neověřen' : '/proc/version'),
      statCard('Uptime', system.uptime || '—', 'od posledního startu'),
      statCard('Volné místo', formatBytes(Number(storage.free)), storage.path || 'úložiště neověřeno')
    );
    const details = $('#system-details');
    details.replaceChildren();
    for (const [label, value] of [
      ['Architektura', system.arch],
      ['IP adresy', (system.ips || []).join(', ') || '—'],
      ['Paměť', memory.MemTotal || memory.total || '—'],
      ['Volná paměť', memory.MemAvailable || memory.MemFree || memory.free || '—'],
      ['Stav', system.demo ? 'Ukázkový náhled' : 'Živý systém']
    ]) {
      const row = node('div');
      row.append(node('dt', label), node('dd', value || '—'));
      details.append(row);
    }
    const checks = $('#quick-checks');
    checks.replaceChildren();
    for (const [label, state] of [
      ['WebUI odpovídá', true],
      ['FFP 0.7', system.demo ? 'Cílové zařízení neověřeno' : 'Zjištěno ze systému'],
      ['Cílová IP', location.hostname]
    ]) {
      const row = node('div', undefined, 'check-row');
      row.append(node('span', state === true ? '✓' : '•', 'check-mark'), node('span', label));
      checks.append(row);
    }
    $('#server-address').textContent = location.host;
  } catch (error) {
    $('#connection-status').textContent = 'Chyba spojení';
    $('#system-badge').textContent = 'Nedostupné';
    $('#system-badge').className = 'badge badge-red';
    $('#system-cards').replaceChildren(statCard('Přehled', 'Nedostupný', error.message));
    $('#system-details').replaceChildren();
    $('#quick-checks').replaceChildren(node('div', `API systému neodpovídá: ${error.message}`, 'notice notice-danger'));
    toast(error.message, true);
  }
}
function short(value, max) {
  const text = String(value || '—');
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

async function loadServices() {
  const box = $('#services-list');
  box.replaceChildren();
  try {
    const services = await api('/api/services');
    if (!services.length) {
      box.textContent = 'Nebyly nalezeny žádné /ffp/start/*.sh skripty.';
      return;
    }
    for (const service of services) {
      const row = node('div', undefined, 'service-row');
      const status = node('div', undefined, 'status');
      const runningClass = service.status === 'running' ? 'badge-green' : (service.enabled ? 'badge-amber' : 'badge-red');
      status.append(
        node('span', service.status, `badge ${runningClass}`),
        node('span', service.enabled ? 'Autostart zapnut' : 'Autostart vypnut', `badge ${service.enabled ? 'badge-blue' : 'badge-neutral'}`)
      );
      const actions = node('div', undefined, 'actions');
      for (const [action, label] of [['start', 'Start'], ['kill', 'Kill / stop'], ['restart', 'Restart']]) {
        const button = node('button', label, 'button');
        button.type = 'button';
        button.addEventListener('click', () => serviceAction(service.name, action));
        actions.append(button);
      }
      const toggle = node('button', service.enabled ? 'Vypnout autostart' : 'Zapnout autostart', 'button button-quiet');
      toggle.addEventListener('click', () => serviceAction(service.name, service.enabled ? 'autostart-off' : 'autostart-on'));
      const edit = node('button', 'Upravit skript', 'button');
      edit.addEventListener('click', () => openEditor(service.script, { name: service.name, enabled: service.enabled }));
      const remove = node('button', 'Smazat službu', 'button button-danger');
      remove.addEventListener('click', () => manageService('delete', service.name));
      actions.append(toggle, edit, remove);
      row.append(node('div', service.name, 'service-title'), status, actions);
      box.append(row);
    }
  } catch (error) {
    box.textContent = error.message;
  }
}
async function serviceAction(name, action) {
  if (!confirm(`${action.toUpperCase()} službu ${name}?`)) return;
  const phrase = action === 'kill' ? 'STOP' : action.toUpperCase();
  try {
    await post('/api/services/action', { name, action, confirm: `${phrase} ${name}` });
    toast(`Požadavek ${action} odeslán.`);
    await loadServices();
  } catch (error) {
    toast(error.message, true);
  }
}

$('#service-new').addEventListener('click', async () => {
  const name = prompt('Název nového start skriptu (např. moje-aplikace.sh):');
  if (name === null) return;
  if (!/^[A-Za-z0-9_.+-]{1,200}\.sh$/.test(name) || name === 'ffp-webui.sh') {
    toast('Zadejte bezpečný název *.sh; ffp-webui.sh je chráněný.', true);
    return;
  }
  const enabled = confirm('Zapnout autostart hned po vytvoření? Skript se při bootu spustí jako root.');
  const phrase = `CREATE SERVICE ${name}`;
  if (prompt(`Vytvoří se start skript, který se nyní nespustí. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try {
    const result = await post('/api/services/manage', { action: 'create', name, content: '#!/ffp/bin/sh\n\n', enabled, confirm: phrase });
    toast(`Skript ${name} vytvořen. Nebyl spuštěn.`);
    await loadServices();
    if (result.path) openEditor(result.path, { name, enabled });
  } catch (error) { toast(error.message, true); }
});
async function manageService(action, name) {
  const phrase = `DELETE SERVICE ${name}`;
  if (prompt(`Skript bude před smazáním zazálohován. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try {
    await post('/api/services/manage', { action, name, confirm: phrase });
    toast(`Služba ${name} smazána; záloha je uložena.`);
    await loadServices();
  } catch (error) { toast(error.message, true); }
}

function luantiRequest(action, confirmText) {
  return post('/api/luanti/action', { action, confirm: confirmText });
}
async function loadLuanti() {
  const notice = $('#luanti-notice');
  try {
    const data = await api('/api/luanti');
    const firstLoad = !luantiSnapshot;
    luantiSnapshot = data;
    const status = data.status || {};
    const running = !!status.running;
    const demo = !!data.demo;
    const noticeParts = [data.note, status.note, demo ? 'Demo režim je pouze pro čtení.' : '',
      !status.account_valid && !demo ? 'Pro spuštění vyberte existující účet operačního systému.' : ''].filter(Boolean);
    notice.className = `notice ${demo ? 'notice-warn' : (!status.account_valid ? 'notice-warn' : 'notice-info')}`;
    notice.textContent = noticeParts.join(' ');
    $('#luanti-status').replaceChildren(
      statCard('Proces', running ? 'Běží' : 'Vypnutý', running ? `PID ${status.pid || '—'}` : 'Luanti server'),
      statCard('Binárka', status.binary_available ? 'Nalezena' : 'Nenalezena', status.binary_path || 'Cesta není nastavena'),
      statCard('Svět', status.selected_world || 'Nevybrán', status.world_exists ? 'Existuje' : 'Není připraven'),
      statCard('Síť', String(status.port || data.config?.port || '—'), status.bind_address || 'bind: všechny adresy')
    );
    $('#luanti-server-meta').textContent = running ? `Spravovaný proces PID ${status.pid}; log ${status.log_path || 'nedostupný'}.` : 'Server je vypnutý; změny konfigurace, importy a zálohy lze provádět.';
    $('#luanti-start').disabled = demo || running || !status.binary_available || !status.world_exists || !status.account_valid;
    $('#luanti-stop').disabled = demo || !running;
    $('#luanti-restart').disabled = demo || !running;
    const form = $('#luanti-settings-form');
    const canEdit = !demo && !running;
    $('#luanti-settings-form button[type="submit"]').disabled = !canEdit;
    $('#luanti-paths-save').disabled = !canEdit;
    $('#luanti-prepare-owner').disabled = !canEdit || !status.selected_world || !status.run_as_user;
    if (firstLoad || !form.contains(document.activeElement)) {
      for (const [field, id] of Object.entries({
        binary_path: 'luanti-binary-path', config_path: 'luanti-config-path', games_path: 'luanti-games-path',
        worlds_path: 'luanti-worlds-path', mods_path: 'luanti-mods-path', skins_path: 'luanti-skins-path', user_path: 'luanti-user-path'
      })) $(`#${id}`).value = data.paths?.[field] || '';
      $('#luanti-port').value = data.config?.port || 30000;
      $('#luanti-bind').value = data.config?.bind_address || '';
      $('#luanti-config-content').value = data.config?.content || '';
      const runAs = $('#luanti-run-as'); runAs.replaceChildren(new Option('Vyberte existující účet', ''));
      for (const account of (data.run_as_users || [])) runAs.add(new Option(`${account.name} (UID ${account.uid})`, account.name));
      const selectedRunAs = data.paths?.run_as_user || '';
      if (selectedRunAs && ![...runAs.options].some(option => option.value === selectedRunAs)) runAs.add(new Option(`${selectedRunAs} (nedostupný účet)`, selectedRunAs));
      runAs.value = selectedRunAs;
    }
    const worldSelect = $('#luanti-world-select');
    const selectedWorld = data.paths?.selected_world || '';
    worldSelect.replaceChildren(new Option('Vyberte svět', ''));
    for (const world of (data.worlds || [])) worldSelect.add(new Option(`${world.name}${world.gameid ? ` · ${world.gameid}` : ''}`, world.name));
    worldSelect.value = selectedWorld;
    const gameSelect = $('#luanti-new-world-game'); gameSelect.replaceChildren();
    for (const game of (data.games || []).filter(item => item.gameid)) gameSelect.add(new Option(`${game.title || game.gameid} (${game.gameid})`, game.gameid));
    const frozen = demo || running;
    for (const selector of ['#luanti-world-form button', '#luanti-import-form button', '#luanti-player-form button']) $(selector).disabled = frozen;
    worldSelect.disabled = demo || running;
    renderLuantiItems('games', data.games || []);
    renderLuantiItems('worlds', data.worlds || []);
    renderLuantiItems('mods', data.mods || []);
    renderLuantiItems('skins', data.skins || []);
    renderLuantiItems('userdata', data.userdata || []);
    $('#luanti-games-note').textContent = `${(data.games || []).length} her`;
    $('#luanti-worlds-note').textContent = `${(data.worlds || []).length} světů`;
    await Promise.all([loadLuantiPlayers(), loadLuantiBackups()]);
  } catch (error) {
    notice.className = 'notice notice-danger'; notice.textContent = error.message;
    toast(error.message, true);
  }
}
function renderLuantiItems(kind, items) {
  const ids = { games: 'luanti-games-list', worlds: 'luanti-worlds-list', mods: 'luanti-mods-list', skins: 'luanti-skins-list', userdata: 'luanti-userdata-list' };
  const box = $(`#${ids[kind]}`); box.replaceChildren();
  if (!items.length) { box.append(node('div', 'Žádné položky v nastavené cestě.', 'empty-state')); return; }
  for (const item of items) {
    const row = node('div', undefined, 'luanti-row');
    const info = node('div', undefined, 'luanti-item-info');
    info.append(node('strong', item.title || item.name));
    const metadata = [item.gameid ? `hra: ${item.gameid}` : '', item.enabled === true ? 'mod povolen' : item.enabled === false ? 'mod vypnut' : '', item.has_readme ? 'README dostupné' : '', item.kind === 'file' ? formatBytes(item.size) : ''].filter(Boolean).join(' · ');
    if (metadata) info.append(node('span', metadata, 'muted'));
    info.append(node('code', item.path || item.name, 'luanti-item-path'));
    const actions = node('div', undefined, 'actions');
    if (item.has_readme) {
      const readme = node('button', 'README', 'button button-quiet'); readme.type = 'button'; readme.addEventListener('click', () => openLuantiReadme(kind, item.name)); actions.append(readme);
    }
    if (kind === 'worlds') {
      const select = node('button', item.name === luantiSnapshot?.paths?.selected_world ? 'Aktivní svět' : 'Vybrat', 'button button-quiet');
      select.type = 'button'; select.disabled = item.name === luantiSnapshot?.paths?.selected_world || luantiSnapshot?.status?.running || luantiSnapshot?.demo;
      select.addEventListener('click', () => chooseLuantiWorld(item.name)); actions.append(select);
      const game = node('select'); game.setAttribute('aria-label', `Hra pro svět ${item.name}`);
      for (const gameItem of (luantiSnapshot?.games || []).filter(candidate => candidate.gameid)) game.add(new Option(`${gameItem.title || gameItem.gameid} (${gameItem.gameid})`, gameItem.gameid));
      game.value = item.resolved_gameid || item.gameid || '';
      const setGame = node('button', 'Nastavit hru', 'button button-quiet'); setGame.type = 'button'; setGame.disabled = luantiSnapshot?.status?.running || luantiSnapshot?.demo;
      setGame.addEventListener('click', () => setLuantiWorldGame(item.name, game.value)); actions.append(game, setGame);
    }
    if (kind === 'mods') {
      const toggle = node('button', item.enabled ? 'Zakázat' : 'Povolit', 'button button-quiet'); toggle.type = 'button'; toggle.disabled = luantiSnapshot?.status?.running || luantiSnapshot?.demo || !luantiSnapshot?.paths?.selected_world;
      toggle.addEventListener('click', () => toggleLuantiMod(item.name, !item.enabled)); actions.append(toggle);
    }
    if (kind !== 'userdata') {
      const backup = node('button', 'Zálohovat', 'button button-quiet'); backup.type = 'button'; backup.disabled = luantiSnapshot?.status?.running || luantiSnapshot?.demo; backup.addEventListener('click', () => backupLuantiItem(kind, item.name)); actions.append(backup);
      const remove = node('button', 'Smazat', 'button button-danger'); remove.type = 'button'; remove.disabled = luantiSnapshot?.status?.running || luantiSnapshot?.demo || (kind === 'worlds' && item.name === luantiSnapshot?.paths?.selected_world); remove.addEventListener('click', () => deleteLuantiItem(kind, item.name)); actions.append(remove);
    }
    row.append(info, actions); box.append(row);
  }
}
async function loadLuantiPlayers() {
  const box = $('#luanti-players-list'); box.replaceChildren();
  try {
    const data = await api('/api/luanti/players');
    const actionsDisabled = !!luantiSnapshot?.demo || !!luantiSnapshot?.status?.running || !data.available;
    $('#luanti-player-form button[type="submit"]').disabled = actionsDisabled;
    $('#luanti-players-note').textContent = `${data.backend || 'Auth databáze není dostupná'}${data.available ? ` · ${(data.players || []).length} záznamů` : ''}${data.note ? ` · ${data.note}` : ''}`;
    if (!data.players?.length) { box.append(node('div', data.note || 'Ve vybraném světě nejsou hráči.', 'empty-state')); return; }
    for (const player of data.players) {
      const row = node('div', undefined, 'luanti-row'); const info = node('div', undefined, 'luanti-item-info');
      info.append(node('strong', player.name));
      const meta = [player.password_set ? 'heslo nastaveno' : 'bez hesla', player.last_login ? `poslední přihlášení: ${new Date(player.last_login * 1000).toLocaleString()}` : 'offline / čas není v tomto backendu dostupný', (player.privileges || []).length ? `práva: ${player.privileges.join(', ')}` : 'bez zvláštních práv'].join(' · ');
      info.append(node('span', meta, 'muted'));
      const actions = node('div', undefined, 'actions'); const remove = node('button', 'Odebrat účet', 'button button-danger'); remove.type = 'button'; remove.disabled = actionsDisabled;
      remove.addEventListener('click', () => deleteLuantiPlayer(player.name)); actions.append(remove); row.append(info, actions); box.append(row);
    }
  } catch (error) { $('#luanti-players-note').textContent = error.message; }
}
async function loadLuantiBackups() {
  const box = $('#luanti-backups-list'); box.replaceChildren();
  try {
    const data = await api('/api/luanti/backups');
    if (!data.backups?.length) { box.append(node('div', 'Zatím nejsou vytvořené zálohy.', 'empty-state')); return; }
    box.append(node('strong', 'Dostupné zálohy'));
    for (const backup of data.backups) {
      const row = node('div', undefined, 'luanti-row');
      const info = node('div', undefined, 'luanti-item-info'); info.append(node('strong', backup.name), node('span', `${formatBytes(backup.size)} · ${new Date(backup.modified * 1000).toLocaleString()}`, 'muted'));
      const download = node('a', 'Stáhnout', 'button button-quiet'); download.href = `/api/luanti/backup?name=${encodeURIComponent(backup.name)}`; download.setAttribute('download', backup.name);
      row.append(info, download); box.append(row);
    }
  } catch (error) { box.append(node('div', error.message, 'empty-state')); }
}
async function chooseLuantiWorld(name) {
  try { await post('/api/luanti/world', { action: 'select', name }); toast(`Vybrán svět ${name}.`); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
}
async function setLuantiWorldGame(world, gameid) {
  if (!gameid) return toast('Vyberte hru.', true);
  try { await post('/api/luanti/world', { action: 'game', world, gameid }); toast(`Svět ${world} nyní používá hru ${gameid}.`); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
}
async function toggleLuantiMod(name, enabled) {
  try { await post('/api/luanti/mod', { name, enabled }); toast(`Mod ${name} ${enabled ? 'povolen' : 'zakázán'}.`); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
}
async function backupLuantiItem(kind, name) {
  if (!confirm(`Vytvořit tar.gz zálohu ${kind}/${name}? Server musí být vypnutý.`)) return;
  try { const data = await post('/api/luanti/item/backup', { kind, name }); toast(`Záloha ${data.result.name} vytvořena.`); await loadLuantiBackups(); }
  catch (error) { toast(error.message, true); }
}
async function deleteLuantiItem(kind, name) {
  const phrase = `DELETE ${kind} ${name}`;
  if (prompt(`Položka bude před smazáním zazálohována. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try { await post('/api/luanti/item/delete', { kind, name, confirm: phrase }); toast(`${kind}/${name} smazáno; záloha je dostupná.`); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
}
async function deleteLuantiPlayer(name) {
  const phrase = `DELETE PLAYER ${name}`;
  if (prompt(`Smaže auth a oprávňovací záznam; inventář a poloha zůstanou pro obnovu. Zadejte: ${phrase}`) !== phrase) return;
  try { await post('/api/luanti/player', { action: 'delete', name, confirm: phrase }); toast(`Auth účet ${name} odebrán; světová data zůstala.`); await loadLuantiPlayers(); await loadLuantiBackups(); }
  catch (error) { toast(error.message, true); }
}
function appendMarkdownInline(parent, text) {
  const pattern = /(\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|`([^`]+)`|\*\*([^*]+)\*\*)/g;
  let cursor = 0; let match;
  while ((match = pattern.exec(text))) {
    if (match.index > cursor) parent.append(document.createTextNode(text.slice(cursor, match.index)));
    if (match[2] && match[3]) {
      try { const url = new URL(match[3]); if (url.protocol === 'http:' || url.protocol === 'https:') { const link = node('a', match[2]); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; parent.append(link); } else parent.append(document.createTextNode(match[0])); }
      catch (_) { parent.append(document.createTextNode(match[0])); }
    } else if (match[4]) parent.append(node('code', match[4]));
    else if (match[5]) parent.append(node('strong', match[5]));
    cursor = pattern.lastIndex;
  }
  if (cursor < text.length) parent.append(document.createTextNode(text.slice(cursor)));
}
function renderLuantiMarkdown(text) {
  const box = $('#luanti-readme-body'); box.replaceChildren();
  const lines = String(text || '').split(/\r?\n/); let paragraph = []; let list = null; let code = null;
  const flushParagraph = () => { if (!paragraph.length) return; const p = node('p'); appendMarkdownInline(p, paragraph.join(' ')); box.append(p); paragraph = []; };
  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      flushParagraph(); list = null;
      if (code) { box.append(code); code = null; } else code = node('pre');
      continue;
    }
    if (code) { code.textContent += `${line}\n`; continue; }
    if (!line.trim()) { flushParagraph(); list = null; continue; }
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) { flushParagraph(); list = null; box.append(node(`h${heading[1].length}`, heading[2])); continue; }
    const item = /^\s*[-*+]\s+(.+)$/.exec(line);
    if (item) { flushParagraph(); if (!list) { list = node('ul'); box.append(list); } const li = node('li'); appendMarkdownInline(li, item[1]); list.append(li); continue; }
    const quote = /^>\s?(.*)$/.exec(line);
    if (quote) { flushParagraph(); list = null; const block = node('blockquote'); appendMarkdownInline(block, quote[1]); box.append(block); continue; }
    list = null; paragraph.push(line.trim());
  }
  flushParagraph();
  if (code) box.append(code);
}
async function openLuantiReadme(kind, name) {
  try {
    const data = await api(`/api/luanti/readme?kind=${encodeURIComponent(kind)}&name=${encodeURIComponent(name)}`);
    $('#luanti-readme-title').textContent = `${name} · README`;
    $('#luanti-readme-meta').textContent = `${data.filename} · zobrazení bez spouštění HTML`;
    renderLuantiMarkdown(data.content);
    $('#luanti-readme-card').hidden = false;
    $('#luanti-readme-card').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) { toast(error.message, true); }
}
$('#luanti-readme-close').addEventListener('click', () => { $('#luanti-readme-card').hidden = true; });
$('#luanti-start').addEventListener('click', async () => {
  const phrase = 'START LUANTI';
  if (prompt(`Spustí Luanti jako vybraný účet. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try { await luantiRequest('start', phrase); toast('Luanti server spuštěn.'); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-stop').addEventListener('click', async () => {
  const phrase = 'STOP LUANTI';
  if (prompt(`Zastavit Luanti server? Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try { await luantiRequest('stop', phrase); toast('Luanti server zastaven.'); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-restart').addEventListener('click', async () => {
  const phrase = 'RESTART LUANTI';
  if (prompt(`Server se zastaví a znovu spustí. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try { await luantiRequest('restart', phrase); toast('Luanti server restartován.'); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-log-refresh').addEventListener('click', async () => {
  try { $('#luanti-log').textContent = await api('/api/luanti/log'); }
  catch (error) { $('#luanti-log').textContent = error.message; }
});
async function saveLuantiPaths() {
  const paths = {
    binary_path: $('#luanti-binary-path').value.trim(), config_path: $('#luanti-config-path').value.trim(),
    games_path: $('#luanti-games-path').value.trim(), worlds_path: $('#luanti-worlds-path').value.trim(),
    mods_path: $('#luanti-mods-path').value.trim(), skins_path: $('#luanti-skins-path').value.trim(),
    user_path: $('#luanti-user-path').value.trim()
  };
  try {
    await post('/api/luanti/paths', { paths });
    toast('Cesty uloženy. Nyní lze načíst dostupné hry a světy.');
    await loadLuanti();
  } catch (error) { toast(error.message, true); }
}
$('#luanti-paths-save').addEventListener('click', saveLuantiPaths);
$('#luanti-settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  const paths = {
    binary_path: $('#luanti-binary-path').value.trim(), config_path: $('#luanti-config-path').value.trim(),
    games_path: $('#luanti-games-path').value.trim(), worlds_path: $('#luanti-worlds-path').value.trim(),
    mods_path: $('#luanti-mods-path').value.trim(), skins_path: $('#luanti-skins-path').value.trim(),
    user_path: $('#luanti-user-path').value.trim(), run_as_user: $('#luanti-run-as').value,
    selected_world: $('#luanti-world-select').value
  };
  try {
    await post('/api/luanti/config', { paths, content: $('#luanti-config-content').value,
      port: Number($('#luanti-port').value), bind_address: $('#luanti-bind').value.trim() });
    toast('Nastavení Luanti uloženo; server před startem ověří cestu a oprávnění.'); await loadLuanti();
  } catch (error) { toast(error.message, true); }
});
$('#luanti-prepare-owner').addEventListener('click', async () => {
  const world = $('#luanti-world-select').value; if (!world) return toast('Vyberte svět.', true);
  const phrase = `PREPARE WORLD OWNER ${world}`;
  if (prompt(`Rekurzivně změní vlastníka všech souborů světa na vybraný servisní účet. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try { const result = await post('/api/luanti/permissions', { confirm: phrase }); toast(`Vlastník nastaven u ${result.result.entries} položek světa.`); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-world-select').addEventListener('change', async event => {
  const name = event.currentTarget.value;
  try { await post('/api/luanti/world', { action: 'select', name }); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-world-form').addEventListener('submit', async event => {
  event.preventDefault();
  try { await post('/api/luanti/world', { action: 'create', name: $('#luanti-new-world').value.trim(), gameid: $('#luanti-new-world-game').value }); event.currentTarget.reset(); toast('Svět vytvořen a vybrán.'); await loadLuanti(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-import-form').addEventListener('submit', async event => {
  event.preventDefault(); const file = $('#luanti-import-file').files[0]; if (!file) return;
  const kind = $('#luanti-import-kind').value; const name = $('#luanti-import-name').value.trim();
  if (!confirm(`Importovat ${file.name} jako ${kind}/${name}? Server musí být vypnutý a archiv může obsahovat spustitelný mod/game kód.`)) return;
  try {
    await api(`/api/luanti/item/upload?kind=${encodeURIComponent(kind)}&name=${encodeURIComponent(name)}`, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file, timeoutMs: 0 });
    event.currentTarget.reset(); toast('Archiv bezpečně rozbalen a importován.'); await loadLuanti();
  } catch (error) { toast(error.message, true); }
});
$('#luanti-player-form').addEventListener('submit', async event => {
  event.preventDefault(); const name = $('#luanti-player-name').value.trim(); const phrase = `CREATE PLAYER ${name} WITHOUT PASSWORD`;
  if (prompt(`Vytvoří offline auth záznam bez hesla. Nastavte heslo v Luanti před veřejným přístupem. Zadejte: ${phrase}`) !== phrase) return;
  try { await post('/api/luanti/player', { action: 'add', name, confirm: phrase }); event.currentTarget.reset(); toast(`Hráč ${name} přidán bez hesla.`); await loadLuantiPlayers(); await loadLuantiBackups(); }
  catch (error) { toast(error.message, true); }
});
$('#luanti-players-refresh').addEventListener('click', loadLuantiPlayers);

async function loadEnv() {
  loadEnvProfiles();
  loadRootLoginEnv();
  const box = $('#env-list');
  box.replaceChildren();
  try {
    const data = await api('/api/env' + (envRevealed ? '?reveal=1' : ''));
    if (!data.entries.length) {
      box.textContent = 'Zatím není uložena žádná proměnná.';
      return;
    }
    for (const entry of data.entries) {
      const row = node('div', undefined, 'env-row');
      row.append(node('div', entry.key, 'service-title'), node('div', envRevealed ? entry.value : '••••••••', 'env-value service-meta'));
      const actions = node('div', undefined, 'actions');
      const edit = node('button', 'Upravit', 'button button-quiet');
      edit.addEventListener('click', async () => {
        let value = entry.value;
        if (!envRevealed) {
          try {
            const revealed = await api('/api/env?reveal=1');
            value = (revealed.entries.find(item => item.key === entry.key) || {}).value || '';
          } catch (error) {
            toast(error.message, true);
            return;
          }
        }
        const next = prompt(`Nová hodnota pro ${entry.key}:`, value);
        if (next === null) return;
        try {
          await post('/api/env', { action: 'set', key: entry.key, value: next });
          toast('Proměnná uložena. Restartujte WebUI, aby ji načetlo.');
          loadEnv();
        } catch (error) { toast(error.message, true); }
      });
      const remove = node('button', 'Smazat', 'button button-danger');
      remove.addEventListener('click', async () => {
        const confirmText = `DELETE ${entry.key}`;
        if (prompt(`Pro potvrzení smazání zadejte: ${confirmText}`) !== confirmText) return;
        try {
          await post('/api/env', { action: 'delete', key: entry.key, confirm: confirmText });
          toast('Proměnná smazána.');
          loadEnv();
        } catch (error) { toast(error.message, true); }
      });
      actions.append(edit, remove);
      row.append(actions);
      box.append(row);
    }
  } catch (error) {
    box.textContent = error.message;
  }
}
let rootEnvRevealed = false;
async function loadRootLoginEnv() {
  const box = $('#root-env-list');
  if (!box) return;
  box.replaceChildren();
  try {
    const data = await api('/api/env/login' + (rootEnvRevealed ? '?reveal=1' : ''));
    $('#root-env-note').className = data.available ? 'notice notice-info' : 'notice notice-warn';
    $('#root-env-note').textContent = data.note || data.scope || 'Prostředí není dostupné.';
    if (!data.entries?.length) { box.textContent = 'Proměnné nebyly načteny.'; return; }
    for (const entry of data.entries) {
      const row = node('div', undefined, 'env-login-row');
      row.append(node('code', entry.key, 'env-login-key'));
      row.append(node('code', entry.masked ? '••••••••' : (entry.value ?? ''), 'env-login-value'));
      box.append(row);
    }
  } catch (error) {
    $('#root-env-note').className = 'notice notice-danger';
    $('#root-env-note').textContent = error.message;
    box.textContent = '';
  }
}
$('#root-env-refresh').addEventListener('click', loadRootLoginEnv);
$('#root-env-reveal').addEventListener('click', () => {
  rootEnvRevealed = !rootEnvRevealed;
  $('#root-env-reveal').textContent = rootEnvRevealed ? 'Skrýt citlivé hodnoty' : 'Zobrazit citlivé hodnoty';
  loadRootLoginEnv();
});

async function loadEnvProfiles() {
  const box = $('#env-profiles-list');
  if (!box) return;
  box.replaceChildren();
  try {
    const data = await api('/api/env/profiles');
    if (!data.files?.length) {
      box.textContent = 'Nebyly nalezeny žádné shell profily.';
      return;
    }
    for (const profile of data.files) {
      const row = node('div', undefined, 'env-row');
      const details = node('div', undefined, 'profile-details');
      details.append(node('div', profile.path, 'service-title'));
      const state = profile.exists ? `${profile.status} · ${formatBytes(profile.size || 0)} · ${profile.mode || ''}` : `${profile.status}${profile.editable ? ' · lze vytvořit' : ''}`;
      details.append(node('div', state, 'env-value service-meta'));
      const actions = node('div', undefined, 'actions');
      const edit = node('button', profile.exists ? 'Načíst / upravit' : 'Vytvořit', 'button button-quiet');
      edit.disabled = !profile.editable;
      edit.addEventListener('click', () => openEditor(profile.path));
      actions.append(edit);
      row.append(details, actions);
      box.append(row);
    }
    if (data.note) box.append(node('p', data.note, 'muted'));
  } catch (error) {
    box.textContent = error.message;
  }
}
$('#env-form').addEventListener('submit', async event => {
  event.preventDefault();
  const key = $('#env-key').value.trim();
  const value = $('#env-value').value;
  try {
    await post('/api/env', { action: 'set', key, value });
    $('#env-form').reset();
    toast('Proměnná uložena. Restartujte WebUI, aby ji načetlo.');
    loadEnv();
  } catch (error) { toast(error.message, true); }
});
$('#env-backup').addEventListener('click', async () => {
  try {
    const result = await post('/api/env', { action: 'backup' });
    toast(`Záloha vytvořena: ${result.backup}`);
  } catch (error) { toast(error.message, true); }
});
$('#env-reveal').addEventListener('click', () => {
  envRevealed = !envRevealed;
  $('#env-reveal').textContent = envRevealed ? 'Skrýt hodnoty' : 'Zobrazit hodnoty';
  loadEnv();
});
$('#env-profiles-refresh').addEventListener('click', loadEnvProfiles);

function fillGroupSelect(select, groups, placeholder = '') {
  select.replaceChildren();
  if (placeholder) {
    const option = node('option', placeholder);
    option.value = '';
    select.append(option);
  }
  for (const group of groups || []) {
    const option = node('option', `${group.name} · GID ${group.gid}`);
    option.value = String(group.gid);
    select.append(option);
  }
  if (!select.options.length) {
    const option = node('option', 'Žádné dostupné skupiny');
    option.value = '';
    select.append(option);
  }
}

function fillShellSelect(select, shells, current = null) {
  select.replaceChildren();
  if (current === null) {
    const placeholder = node('option', '— vyberte shell —');
    placeholder.value = '';
    select.append(placeholder);
  } else if (!current) {
    const option = node('option', '(stávající prázdný shell)');
    option.value = '';
    select.append(option);
  } else if (!(shells || []).includes(current)) {
    const option = node('option', `${current} (stávající)`);
    option.value = current;
    select.append(option);
  }
  for (const shell of shells || []) {
    const option = node('option', shell);
    option.value = shell;
    select.append(option);
  }
  if (current !== null) select.value = current;
}

async function loadUsers() {
  const box = $('#users-list');
  box.replaceChildren();
  try {
    const data = await api('/api/users');
    accountData = data;
    const policy = data.policy || {};
    const bases = data.home_bases || [];
    const groups = data.groups || [];
    const shells = data.shells || [];
    const policyParts = [
      `UID ${policy.uid_min ?? '—'}–${policy.uid_max ?? '—'}`,
      `GID ${policy.gid_min ?? '—'}–${policy.gid_max ?? '—'}`,
      `Home: ${bases.join(', ') || 'žádný dostupný základní adresář'}`,
      `Výchozí skupina useradd: ${policy.default_group || 'neuvedena'}${policy.default_group_exists ? '' : ' (neexistuje; vyberte skupinu)'}`,
      `Shell: ${shells.join(', ') || 'žádný ověřený shell'}`,
      `chpasswd: ${policy.password_method || 'metoda nebyla zjištěna'}`
    ];
    $('#users-policy').textContent = policyParts.join(' · ');
    $('#users-note').textContent = data.note || '';
    $('#user-add-note').textContent = `UID se jinak přidělí automaticky. Zvolte existující primární skupinu nebo vytvořte soukromou; home základ: ${bases.join(', ') || 'není k dispozici'}.`;

    fillGroupSelect($('#user-add-primary'), groups, '— vyberte primární skupinu —');
    fillGroupSelect($('#user-add-groups'), groups);
    fillShellSelect($('#user-add-shell'), shells);
    $('#user-add-primary').disabled = !!data.demo || $('#user-add-private').checked || !groups.length;
    $('#user-add-private').disabled = !!data.demo;
    $('#user-add-home').disabled = !!data.demo || !bases.length;
    $('#user-add-shell').disabled = !!data.demo || !shells.length;
    $('#user-add-uid').disabled = !!data.demo;
    $('#user-add-name').disabled = !!data.demo;
    $('#user-add-comment').disabled = !!data.demo;
    $('#user-add-groups').disabled = !!data.demo;
    $('#user-add-create-home').disabled = !!data.demo;
    $('#user-add-form').querySelector('button[type="submit"]').disabled = !!data.demo || !bases.length || !shells.length;

    if (!data.users?.length) {
      box.textContent = data.demo ? 'Demo režim nečte žádné místní účty.' : 'V /etc/passwd nebyly nalezeny žádné účty.';
    } else {
      for (const user of data.users) {
        const row = node('div', undefined, 'account-row');
        const heading = node('div', undefined, 'account-heading');
        heading.append(node('span', user.username, 'service-title'));
        heading.append(node('span', `UID ${user.uid}${user.primary_group ? ` · ${user.primary_group}` : ` · GID ${user.gid}`}`, 'badge badge-neutral'));
        const details = node('div', undefined, 'account-details');
        details.append(node('div', `Home: ${user.home || '—'} · Shell: ${user.shell || '—'}`, 'service-meta'));
        details.append(node('div', `Popis: ${user.gecos || '—'} · Doplňkové skupiny: ${(user.supplementary_groups || []).join(', ') || '—'}`, 'service-meta'));
        const actions = node('div', undefined, 'actions account-actions');
        if (!data.demo && user.can_manage) {
          const edit = node('button', 'Upravit', 'button');
          edit.type = 'button';
          edit.addEventListener('click', () => openUserEdit(user));
          actions.append(edit);
        }
        if (!data.demo && user.can_password) {
          const password = node('button', 'Heslo', 'button button-quiet');
          password.type = 'button';
          password.addEventListener('click', () => openUserPassword(user));
          actions.append(password);
        }
        if (!data.demo && user.can_manage) {
          for (const [action, label] of [['lock', 'Zamknout'], ['unlock', 'Odemknout']]) {
            const button = node('button', label, 'button button-quiet');
            button.type = 'button';
            button.addEventListener('click', () => accountAction(user, action));
            actions.append(button);
          }
          const remove = node('button', 'Smazat', 'button button-danger');
          remove.type = 'button';
          remove.addEventListener('click', () => deleteUser(user));
          actions.append(remove);
        }
        if (data.demo) actions.append(node('span', 'Demo režim', 'badge badge-neutral'));
        else if (!user.can_manage) actions.append(node('span', user.username === 'root' && user.can_password ? 'Root · pouze heslo' : 'Systémový účet chráněn', 'badge badge-neutral'));
        row.append(heading, details, actions);
        box.append(row);
      }
    }
  } catch (error) {
    accountData = null;
    box.append(node('div', error.message, 'notice notice-danger'));
    $('#user-add-note').textContent = 'Účetní inventář není dostupný; změny nelze provést.';
    $('#user-add-form').querySelectorAll('input,select,button').forEach(control => { control.disabled = true; });
  }
}

function openUserEdit(user) {
  editingUser = user;
  $('#user-edit-title').textContent = `Upravit účet ${user.username}`;
  $('#user-edit-comment').value = user.gecos || '';
  $('#user-edit-home').value = user.home || '';
  $('#user-edit-move-home').checked = false;
  const primary = $('#user-edit-primary');
  primary.replaceChildren();
  const current = node('option', `${user.primary_group || 'Stávající skupina'} · GID ${user.gid}`);
  current.value = String(user.gid);
  primary.append(current);
  for (const group of accountData.groups || []) {
    if (group.gid === user.gid) continue;
    const option = node('option', `${group.name} · GID ${group.gid}`);
    option.value = String(group.gid);
    primary.append(option);
  }
  primary.value = String(user.gid);
  fillShellSelect($('#user-edit-shell'), accountData.shells || [], user.shell || '');
  const extra = $('#user-edit-groups');
  extra.replaceChildren();
  const existing = new Set(user.supplementary_groups || []);
  for (const group of accountData.groups || []) {
    if (group.gid === user.gid || existing.has(group.name)) continue;
    const option = node('option', `${group.name} · GID ${group.gid}`);
    option.value = String(group.gid);
    extra.append(option);
  }
  $('#user-edit-dialog').showModal();
}

function openUserPassword(user) {
  passwordUser = user.username;
  $('#user-password-title').textContent = `Změnit heslo: ${user.username}`;
  const policy = accountData?.policy || {};
  const desNote = policy.password_algorithm === 'DES'
    ? ' DES může podle místního manuálu ignorovat znaky po osmém; WebUI proto delší heslo odmítne.'
    : '';
  $('#user-password-policy').textContent = `Použije se NAS chpasswd a metoda ${policy.password_method || 'NAS default (nezjištěna)'}; WebUI jinou metodu nevynucuje.${desNote} Heslo se neposílá v argumentech ani auditním záznamu.`;
  $('#user-password-value').value = '';
  $('#user-password-repeat').value = '';
  $('#user-password-dialog').showModal();
  $('#user-password-value').focus();
}

async function accountAction(user, action) {
  const phrase = `${action.toUpperCase()} ${user.username}`;
  if (prompt(`Pro potvrzení zadejte přesně: ${phrase}`) !== phrase) return;
  try {
    await post('/api/users/action', { username: user.username, action, confirm: phrase });
    toast(`Akce ${action} dokončena pro ${user.username}.`);
    await loadUsers();
  } catch (error) { toast(error.message, true); }
}

async function deleteUser(user) {
  const phrase = `DELETE ${user.username}`;
  if (prompt(`Účet bude odstraněn bez -r (home se nemaže). Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try {
    await post('/api/users/delete', { username: user.username, confirm: phrase });
    toast(`Účet ${user.username} odstraněn; home zůstává.`);
    await loadUsers();
  } catch (error) { toast(error.message, true); }
}

$('#user-add-private').addEventListener('change', () => {
  $('#user-add-primary').disabled = $('#user-add-private').checked || !accountData || !!accountData.demo || !(accountData.groups || []).length;
});
$('#user-add-name').addEventListener('input', () => {
  const home = $('#user-add-home');
  const base = accountData?.home_bases?.[0] || '/home';
  if (!home.dataset.userEdited && $('#user-add-name').value) home.value = `${base}/${$('#user-add-name').value}`;
});
$('#user-add-home').addEventListener('input', event => { event.currentTarget.dataset.userEdited = '1'; });
$('#user-add-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!accountData || accountData.demo) return;
  const username = $('#user-add-name').value.trim();
  const phrase = `CREATE ${username}`;
  if (prompt(`Pro potvrzení zadejte přesně: ${phrase}`) !== phrase) return;
  const privateGroup = $('#user-add-private').checked;
  const payload = {
    username,
    uid: $('#user-add-uid').value.trim(),
    home: $('#user-add-home').value,
    shell: $('#user-add-shell').value,
    comment: $('#user-add-comment').value,
    private_group: privateGroup,
    create_home: $('#user-add-create-home').checked,
    extra_gids: [...$('#user-add-groups').selectedOptions].map(option => option.value),
    confirm: phrase
  };
  if (!privateGroup) payload.primary_gid = $('#user-add-primary').value;
  try {
    const result = await post('/api/users/add', payload);
    toast(result.message || `Účet ${username} vytvořen.`);
    $('#user-add-form').reset();
    $('#user-add-home').dataset.userEdited = '';
    await loadUsers();
  } catch (error) { toast(error.message, true); }
});

$('#user-edit-save').addEventListener('click', async () => {
  if (!editingUser || !accountData || accountData.demo) return;
  const user = editingUser;
  const phrase = `UPDATE ${user.username}`;
  if (prompt(`Pro potvrzení zadejte přesně: ${phrase}`) !== phrase) return;
  const payload = {
    username: user.username,
    confirm: phrase,
    comment: $('#user-edit-comment').value,
    primary_gid: $('#user-edit-primary').value,
    home: $('#user-edit-home').value,
    shell: $('#user-edit-shell').value,
    move_home: $('#user-edit-move-home').checked,
    add_gids: [...$('#user-edit-groups').selectedOptions].map(option => option.value)
  };
  try {
    const result = await post('/api/users/edit', payload);
    $('#user-edit-dialog').close();
    toast(result.message || `Účet ${user.username} upraven.`);
    await loadUsers();
  } catch (error) { toast(error.message, true); }
});

$('#user-password-save').addEventListener('click', async () => {
  const username = passwordUser;
  const field = $('#user-password-value');
  const repeatField = $('#user-password-repeat');
  if (!username || !field.value || field.value !== repeatField.value) {
    toast('Zadejte stejné neprázdné heslo dvakrát.', true);
    field.value = '';
    repeatField.value = '';
    return;
  }
  const phrase = `SET PASSWORD ${username}`;
  if (prompt(`Pro potvrzení zadejte přesně: ${phrase}`) !== phrase) {
    field.value = '';
    repeatField.value = '';
    return;
  }
  const payload = { username, password: field.value, password_confirm: repeatField.value, confirm: phrase };
  try {
    const result = await post('/api/users/password', payload);
    $('#user-password-dialog').close();
    toast(result.message || `Heslo pro ${username} nastaveno.`);
    await loadUsers();
  } catch (error) { toast(error.message, true); }
  finally {
    payload.password = '';
    payload.password_confirm = '';
    field.value = '';
    repeatField.value = '';
  }
});
$('#user-password-dialog').addEventListener('close', () => {
  $('#user-password-value').value = '';
  $('#user-password-repeat').value = '';
  passwordUser = '';
});

$('#users-refresh').addEventListener('click', loadUsers);

async function loadPackages() {
  void loadPackageCatalog();
  try {
    const data = await api('/api/packages');
    packageArchives = data.archives || [];
    void loadSelfUpdate();
    $('#package-manager').textContent = `Správce: ${data.manager} · Inventář: ${data.inventory_source}`;
    const installed = $('#package-inventory');
    installed.replaceChildren();
    if (data.inventory_status === 'error') installed.append(node('div', data.inventory_error || 'Inventář balíčků není dostupný.', 'notice notice-danger'));
    else if (data.inventory_status === 'demo') installed.textContent = 'Demo režim seznam balíčků cílového NASu nečte.';
    else if (!data.installed?.length) installed.textContent = 'Funpkg nevrátil žádné nainstalované balíčky.';
    else data.installed.forEach(name => {
      const row = node('div', undefined, 'package-row');
      row.append(node('div', name, 'service-title'));
      const actions = node('div', undefined, 'actions');
      const detail = node('button', 'Info / soubory', 'button');
      detail.type = 'button'; detail.addEventListener('click', () => showPackageDetails(name));
      const remove = node('button', 'Odinstalovat', 'button button-danger');
      remove.type = 'button';
      remove.disabled = !/^[A-Za-z0-9_.+-]{1,240}$/.test(name);
      remove.title = remove.disabled ? 'Název neodpovídá bezpečnému formátu pro funpkg.' : '';
      remove.addEventListener('click', () => uninstallInstalledPackage(name));
      actions.append(detail, remove);
      row.append(actions);
      installed.append(row);
    });
    const archives = $('#package-archives');
    archives.replaceChildren();
    if (!data.archives?.length) {
      archives.textContent = 'V povolených úložištích nejsou dostupné žádné archivy.';
      return;
    }
    for (const archive of data.archives) {
      const row = node('div', undefined, 'archive-row');
      row.append(node('div', archive.name, 'service-title'));
      const info = node('div', undefined, 'archive-info');
      info.append(node('div', `${formatBytes(archive.size)} · ${archive.source}`, 'service-meta'), node('code', `SHA-256 ${archive.sha256}`));
      row.append(info);
      const actions = node('div', undefined, 'actions');
      for (const [action, label, className] of [
        ['install', 'Instalovat', 'button button-primary'],
        ['reinstall', 'Přeinstalovat', 'button'],
        ['upgrade', 'Aktualizovat', 'button'],
        ['remove', 'Odstranit', 'button button-danger'],
        ['backup', 'Zálohovat archiv', 'button button-quiet']
      ]) {
        const button = node('button', label, className);
        button.addEventListener('click', () => packageAction(archive, action));
        actions.append(button);
      }
      row.append(actions);
      archives.append(row);
    }
  } catch (error) {
    $('#package-manager').textContent = error.message;
  }
}
async function queryZypkg(view, value = '') {
  const params = new URLSearchParams({ view });
  if (view === 'package') params.set('name', value);
  if (view === 'group') params.set('group', value);
  const target = view === 'package' || view === 'group'
    ? $('#zypkg-lookup-output') : $(`#zypkg-${view}`);
  try {
    const data = await api(`/api/zypkg?${params.toString()}`, { timeoutMs: 45000 });
    if (target) target.textContent = data.available ? (data.output || '(bez výstupu)') : (data.error || 'Dotaz není dostupný.');
    if (view === 'package' || view === 'group') {
      $('#zypkg-lookup-title').textContent = `${view === 'package' ? 'Balíček' : 'Skupina'}: ${value}`;
      $('#zypkg-lookup-result').hidden = false;
    }
    if (data.available) {
      $('#zypkg-note').textContent = `Poslední úspěšný dotaz: ${data.command}`;
      $('#zypkg-note').className = 'muted';
    } else {
      $('#zypkg-note').textContent = data.error || 'Dotaz na Zysh se nezdařil.';
      $('#zypkg-note').className = 'notice notice-warn';
    }
    return data;
  } catch (error) {
    if (target) target.textContent = error.message;
    $('#zypkg-note').textContent = error.message;
    $('#zypkg-note').className = 'notice notice-danger';
    return null;
  }
}
async function loadZypkg() {
  await queryZypkg('all');
  await queryZypkg('newver');
}
$('#zypkg-refresh').addEventListener('click', loadZypkg);
$$('[data-zypkg-query]').forEach(button => button.addEventListener('click', () => queryZypkg(button.dataset.zypkgQuery)));
$('#zypkg-progress-refresh').addEventListener('click', async () => {
  const output = $('#zypkg-progress');
  output.hidden = false;
  await queryZypkg('progress');
  output.textContent = $('#zypkg-progress').textContent;
});
$('#zypkg-lookup-form').addEventListener('submit', async event => {
  event.preventDefault();
  const name = $('#zypkg-lookup-name').value.trim();
  await queryZypkg($('#zypkg-lookup-kind').value, name);
});
function updateZypkgVersionField() {
  const needsVersion = ['install', 'uninstall'].includes($('#zypkg-action').value);
  $('#zypkg-version-field').hidden = !needsVersion;
  $('#zypkg-action-version').required = needsVersion;
  if (!needsVersion) $('#zypkg-action-version').value = '';
}
$('#zypkg-action').addEventListener('change', updateZypkgVersionField);
updateZypkgVersionField();
$('#zypkg-action-form').addEventListener('submit', async event => {
  event.preventDefault();
  const action = $('#zypkg-action').value;
  const name = $('#zypkg-action-name').value.trim();
  const version = ['install', 'uninstall'].includes(action) ? $('#zypkg-action-version').value.trim() : '';
  const confirmText = ['install', 'uninstall'].includes(action)
    ? `${action.toUpperCase()} ${name} ${version}` : `${action.toUpperCase()} ${name}`;
  const warning = `Příkaz bude spuštěn jako správce NASu. Instalace nebo odebrání může ovlivnit firmware a závislosti; automatický návrat ani záloha nejsou k dispozici.\n\nPro pokračování zadejte přesně:\n${confirmText}`;
  if (prompt(warning) !== confirmText) return;
  const button = $('#zypkg-action-submit');
  button.disabled = true;
  try {
    const job = await post('/api/zypkg/action', { action, name, version, confirm: confirmText });
    toast(`Zypkg operace spuštěna (úloha ${job.id}).`);
    pollJob(job.id, `Zypkg operace dokončena: ${name}`, loadZypkg);
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
$('#zypkg-update-list').addEventListener('click', async () => {
  const confirmText = 'UPDATE ZYPKG LISTS';
  if (prompt(`Aktualizace seznamu může kontaktovat nastavené Zypkg repozitáře. Pro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
  const button = $('#zypkg-update-list');
  button.disabled = true;
  try {
    const job = await post('/api/zypkg/update-list', { confirm: confirmText });
    $('#zypkg-progress').hidden = false;
    $('#zypkg-progress').textContent = 'Obnova seznamu byla spuštěna. Průběh lze načíst tlačítkem „Stav obnovy seznamu“.';
    toast(`Obnova Zypkg seznamu spuštěna (úloha ${job.id}).`);
    pollJob(job.id, 'Příkaz k obnově Zypkg seznamu dokončen.', async () => { await queryZypkg('progress'); await loadZypkg(); });
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
let packageCatalogRows = [];
let packageArchives = [];
let selfUpdateStatus = null;
async function loadPackageCatalog() {
  const note = $('#package-catalog-note'); const box = $('#package-catalog-list');
  if (!box) return;
  try {
    const data = await api('/api/packages/catalog');
    packageCatalogRows = data.rows || [];
    note.textContent = data.note || (data.available ? 'Katalog načten.' : 'Katalog není dostupný.');
    note.className = data.available ? 'muted' : 'notice notice-warn';
    $('#package-catalog-update').disabled = Boolean(data.demo);
    renderPackageCatalog();
  } catch (error) { note.textContent = error.message; note.className = 'notice notice-danger'; box.replaceChildren(); }
}
async function loadSelfUpdate() {
  const status = $('#self-update-status');
  const detail = $('#self-update-detail');
  const release = $('#self-update-release');
  const install = $('#self-update-install');
  const check = $('#self-update-check');
  if (!status) return;
  try {
    const data = await api('/api/self-update');
    selfUpdateStatus = data;
    install.hidden = data.state !== 'available';
    const stagedArchive = packageArchives.find(item => item.path === data.staged_path && item.sha256 === data.sha256);
    install.disabled = data.state !== 'available' || !stagedArchive;
    check.disabled = data.state === 'demo';
    const releaseUrl = String(data.release_url || '');
    const safeReleaseUrl = /^https:\/\/github\.com\/PhateValleyman\/ffp-webui\/releases\/tag\/v[0-9]+\.[0-9]+\.[0-9]+$/.test(releaseUrl);
    release.hidden = !safeReleaseUrl;
    if (safeReleaseUrl) release.href = releaseUrl;
    if (data.state === 'available') {
      status.textContent = `Je dostupná verze ${data.latest_version}; běží ${data.current_version}.`;
      detail.textContent = install.disabled
        ? 'Ověřený instalátor se připravuje nebo seznam archivů potřebuje obnovit. Instalace se nikdy nespouští automaticky.'
        : `Ověřený archiv ${data.asset_name} je připraven. Instalaci spustíte tlačítkem a potvrzením v prohlížeči.`;
      detail.className = 'notice notice-warn';
    } else if (data.state === 'current') {
      status.textContent = `FFP-WebUI ${data.current_version} je aktuální (GitHub: ${data.latest_version}).`;
      detail.textContent = 'Automatická kontrola se opakuje každých 24 hodin, pokud je NAS online.';
      detail.className = 'notice notice-info';
    } else if (data.state === 'checking' || data.state === 'waiting') {
      status.textContent = data.state === 'checking' ? 'Kontroluji GitHub…' : 'Čekám na první kontrolu GitHubu…';
    } else if (data.state === 'demo') {
      status.textContent = 'Demo režim — aktualizace se nekontrolují.';
      detail.textContent = data.notes || 'Demo režim nekontaktuje GitHub.';
    } else {
      status.textContent = data.error || 'Kontrola GitHubu se nezdařila.';
      detail.textContent = 'Ověřte připojení NASu k internetu nebo použijte ruční přenos instalačního .txz.';
      detail.className = 'notice notice-warn';
    }
  } catch (error) {
    status.textContent = error.message;
    detail.textContent = 'Stav GitHub aktualizací není dostupný; lze pokračovat ručním přenosem instalačního .txz.';
    detail.className = 'notice notice-warn';
    install.hidden = true;
    release.hidden = true;
  }
}
$('#self-update-check').addEventListener('click', async () => {
  const button = $('#self-update-check');
  button.disabled = true;
  try {
    const job = await post('/api/self-update/check', {});
    toast(`Kontrola GitHubu spuštěna (úloha ${job.id}).`);
    pollJob(job.id, 'Kontrola FFP-WebUI dokončena.', async () => { await loadPackages(); await loadSelfUpdate(); });
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
$('#self-update-install').addEventListener('click', async () => {
  const update = selfUpdateStatus;
  const archive = packageArchives.find(item => item.path === update?.staged_path && item.sha256 === update?.sha256);
  if (!archive || update?.state !== 'available') {
    toast('Ověřený archiv není v seznamu. Obnovuji seznam balíčků.', true);
    void loadPackages();
    return;
  }
  const confirmText = `UPGRADE ${update.asset_name}`;
  const safetyNote = 'Aktualizujete výhradně FFP-WebUI z ověřeného GitHub stagingu. WebUI samo nevytváří zálohu ani rollback: před instalací zazálohujte soubory uvedené v /ffp/funpkg/installed/ffp-webui-* a konfiguraci /ffp/etc/ffp-webui/. Po instalaci restartujte službu FFP-WebUI.';
  if (prompt(`${safetyNote}\n\nPro potvrzení zadejte přesně:\n${confirmText}`) !== confirmText) return;
  const button = $('#self-update-install');
  button.disabled = true;
  try {
    const job = await post('/api/self-update/install', { confirm: confirmText });
    toast(`Ověřená aktualizace spuštěna (úloha ${job.id}).`);
    pollJob(job.id, 'Instalace dokončena. Restartujte službu FFP-WebUI.', async () => {
      await loadPackages();
      $('#self-update-status').textContent = 'Instalační úloha dokončena; restartujte službu FFP-WebUI.';
      $('#self-update-detail').textContent = 'Nové soubory se načtou až po restartu služby.';
      $('#self-update-detail').className = 'notice notice-info';
      button.disabled = true;
    });
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
});
function renderPackageCatalog() {
  const box = $('#package-catalog-list'); box.replaceChildren();
  const query = $('#package-catalog-search').value.trim().toLowerCase(); const filter = $('#package-catalog-filter').value;
  const rows = packageCatalogRows.filter(row => {
    const text = `${row.name} ${row.location} ${row.installed} ${row.available}`.toLowerCase();
    const state = filter === 'install' ? row.status === 'i' : filter === 'upgrade' ? row.status === 'u' : filter === 'installed' ? ['I','u'].includes(row.status) : filter === 'orphan' ? row.status === 'o' : true;
    return state && (!query || text.includes(query));
  });
  if (!rows.length) { box.append(node('div', packageCatalogRows.length ? 'Filtr nic nenašel.' : 'Katalog neobsahuje žádné položky, nebo není dostupný.', 'empty-state')); return; }
  for (const item of rows) {
    const card = node('article', undefined, `catalog-package status-${item.status.toLowerCase()}`);
    const head = node('div', undefined, 'catalog-package-head');
    head.append(node('strong', item.name, 'catalog-package-name'));
    const statusText = item.status === 'I' ? 'Nainstalováno' : item.status === 'u' ? 'Je dostupná aktualizace' : item.status === 'i' ? 'K instalaci' : 'Nainstalováno · mimo katalog';
    head.append(node('span', statusText, `badge ${item.status === 'u' ? 'badge-amber' : item.status === 'i' ? 'badge-blue' : item.status === 'o' ? 'badge-red' : 'badge-green'}`));
    const versions = node('div', undefined, 'catalog-package-versions');
    versions.append(node('span', `Instalováno: ${item.installed && item.installed !== '0' ? item.installed : '—'}`), node('span', `Dostupné: ${item.available || '—'}`));
    const meta = node('div', item.location ? `Repozitář: ${item.location}` : 'Zdroj: balíček již není v dostupných indexech.', 'catalog-package-meta');
    const actions = node('div', undefined, 'actions');
    const choices = item.status === 'i' ? [['install','Instalovat','button button-primary']] : item.status === 'u' ? [['upgrade','Aktualizovat','button button-primary'],['reinstall','Přeinstalovat','button'],['remove','Odinstalovat','button button-danger']] : item.status === 'I' ? [['reinstall','Přeinstalovat','button'],['remove','Odinstalovat','button button-danger']] : item.status === 'o' ? [['remove','Odinstalovat','button button-danger']] : [];
    for (const [action,label,klass] of choices) { const button = node('button', label, klass); button.type = 'button'; button.addEventListener('click', () => packageCatalogAction(item, action)); actions.append(button); }
    card.append(head, versions, meta, actions); box.append(card);
  }
}
async function packageCatalogAction(item, action) {
  const confirmText = action === 'remove' ? `REMOVE ${item.installed}` : `${action.toUpperCase()} ${item.name} ${item.available}`;
  const explanation = action === 'remove' ? 'Funpkg odebere soubory instalovaného balíčku a neřeší závislosti.' : 'Balíček bude stažen z aktuálního katalogu, kontrolován podle FFP CHECKSUMS.md5 a předán funpkg.';
  if (prompt(`${explanation}\n\nPro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
  try {
    const job = await post('/api/packages/catalog/action', { action, name: item.name, installed: item.installed, available: item.available, location: item.location, confirm: confirmText });
    toast(`Balíčková akce spuštěna (úloha ${job.id}).`);
    pollJob(job.id, `Balíčková akce dokončena: ${item.name}`, async () => { await loadPackages(); await loadPackageCatalog(); });
  } catch (error) { toast(error.message, true); }
}
$('#package-catalog-refresh').addEventListener('click', loadPackageCatalog);
$('#package-catalog-search').addEventListener('input', renderPackageCatalog);
$('#package-catalog-filter').addEventListener('change', renderPackageCatalog);
$('#package-catalog-update').addEventListener('click', async () => {
  const confirmText = 'UPDATE FFP PACKAGE LISTS';
  if (prompt(`Obnovení indexů kontaktuje repozitáře uvedené v /ffp/etc/funpkg/sites. Pro potvrzení zadejte: ${confirmText}`) !== confirmText) return;
  try {
    const job = await post('/api/packages/catalog/update', { confirm: confirmText });
    toast(`Obnovení indexů spuštěno (úloha ${job.id}).`);
    pollJob(job.id, 'Indexy FFP obnoveny.', async () => { await loadPackageCatalog(); await loadPackages(); });
  } catch (error) { toast(error.message, true); }
});

function formatBytes(number) {
  if (!number) return '—';
  let value = number;
  let unit = 'B';
  if (value > 1024) { value /= 1024; unit = 'KiB'; }
  if (value > 1024) { value /= 1024; unit = 'MiB'; }
  return `${value.toFixed(1)} ${unit}`;
}
async function packageAction(archive, action) {
  const confirmText = `${action.toUpperCase()} ${archive.name}`;
  const selfUpdate = archive.name.startsWith('ffp-webui-');
  const safetyNote = selfUpdate
    ? 'Aktualizujete samotné FFP-WebUI. Zálohujte /ffp/etc/ffp-webui/config.json; tento balík nebyl ověřen na NSA320. Po dokončení restartujte službu FFP-WebUI.'
    : 'Zkontrolujte název a hash balíčku.';
  if (prompt(`${safetyNote}\n\nPro akci zadejte přesně:\n${confirmText}`) !== confirmText) return;
  try {
    const result = await post('/api/packages/action', { action, path: archive.path, sha256: archive.sha256, confirm: confirmText });
    if (result.id) {
      toast(`Úloha ${result.id} spuštěna.`);
      pollJob(result.id);
    } else {
      toast(`Akce dokončena. ${result.backup || ''}`);
      loadPackages();
    }
  } catch (error) { toast(error.message, true); }
}
async function showPackageDetails(name) {
  const card = $('#package-details-card');
  card.hidden = false;
  $('#package-details-title').textContent = name;
  $('#package-details-meta').textContent = 'Načítám informace…';
  $('#package-details-note').textContent = '';
  $('#package-details-files').replaceChildren();
  try {
    const query = new URLSearchParams({ name });
    const data = await api(`/api/packages/detail?${query}`);
    $('#package-details-meta').textContent = data.available ? `${data.file_count} evidovaných souborů · ${data.source}` : 'Instalovaný balíček';
    $('#package-details-note').textContent = data.note || (data.available ? 'Manifest načten.' : 'Manifest není dostupný.');
    const files = $('#package-details-files');
    if (!data.available || !data.files?.length) files.append(node('div', 'Databáze balíčků neposkytla seznam souborů.', 'empty-state'));
    else for (const path of data.files) files.append(node('code', path, 'package-file-path'));
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  } catch (error) {
    $('#package-details-meta').textContent = 'Detaily nejsou dostupné.';
    $('#package-details-note').textContent = error.message;
    $('#package-details-note').className = 'notice notice-danger';
  }
}
async function uninstallInstalledPackage(name) {
  const confirmText = `REMOVE ${name}`;
  const message = `Funpkg odstraní instalované soubory balíčku. Závislosti automaticky nekontroluje.\n\nPro potvrzení zadejte přesně:\n${confirmText}`;
  if (prompt(message) !== confirmText) return;
  try {
    const job = await post('/api/packages/uninstall', { name, confirm: confirmText });
    toast(`Odinstalace spuštěna (úloha ${job.id}).`);
    pollJob(job.id, `Balíček ${name} odebrán.`);
  } catch (error) { toast(error.message, true); }
}
$('#package-details-close').addEventListener('click', () => { $('#package-details-card').hidden = true; });
async function pollJob(id, successMessage = 'Balíčková operace dokončena.', onComplete = loadPackages) {
  for (let attempt = 0; attempt < 300; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 1500));
    try {
      const job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      if (job.state === 'completed') { toast(successMessage); if (onComplete) await onComplete(); return; }
      if (job.state === 'failed') { toast(job.error || 'Operace balíčku selhala.', true); return; }
    } catch (error) { toast(error.message, true); return; }
  }
  toast('Kontrola úlohy vypršela; zkontrolujte log.', true);
}
$('#package-upload').addEventListener('submit', async event => {
  event.preventDefault();
  const file = event.currentTarget.querySelector('input[type="file"]').files[0];
  if (!file) { toast('Vyberte balíček.', true); return; }
  const query = new URLSearchParams({ name: file.name });
  try {
    const result = await api('/api/packages/upload?' + query.toString(), { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
    toast(`Nahráno do stagingu. SHA-256: ${result.sha256}`);
    event.currentTarget.reset();
    loadPackages();
  } catch (error) { toast(error.message, true); }
});
$('#package-fetch').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    const result = await post('/api/packages/fetch', { url: $('#package-url').value, sha256: $('#package-sha').value.trim() });
    toast(`Staženo a hash ověřen: ${result.sha256}`);
    event.currentTarget.reset();
    loadPackages();
  } catch (error) { toast(error.message, true); }
});

function mediaKind(name) {
  const ext = name.toLowerCase().split('.').pop();
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(ext)) return 'image';
  if (['mp4', 'm4v', 'webm', 'mov', 'ogv', 'ogg', 'mkv'].includes(ext)) return 'video';
  return '';
}
function mediaPreviewUrl(state, path) {
  if (state?.source === 'adb') return `/api/adb/preview?${adbQuery({ serial: state.serial, path })}`;
  if (['rclone','sftp'].includes(state?.source)) return `/api/rclone/preview?${adbQuery({ remote: state.remote, path })}`;
  return '/api/files/preview?path=' + encodeURIComponent(path);
}
function buildFileThumbnail(side, entry, path) {
  const state = dualFiles[side];
  if (!entry.directory && !entry.symlink && mediaKind(entry.name) === 'image') {
    const image = node('img', undefined, 'file-icon file-thumbnail');
    image.alt = ''; image.loading = 'lazy'; image.decoding = 'async';
    image.src = mediaPreviewUrl(state, path); image.title = 'Náhled ' + entry.name;
    image.addEventListener('error', () => { image.hidden = true; });
    return image;
  }
  return node('span', '', 'file-icon');
}
async function loadFiles(path = currentFilePath) {
  currentFilePath = path;
  if (typeof loadDualFiles === 'function') await loadDualFiles();
  $('#file-current-path').textContent = path;
  const box = $('#files-list');
  box.replaceChildren();
  try {
    const data = await api('/api/files?path=' + encodeURIComponent(path));
    currentFilePath = data.path;
    $('#file-current-path').textContent = data.path;
    $('#files-up').disabled = !data.parent;
    $('#files-up').dataset.parent = data.parent || '';
    const folderDownload = $('#files-download-dir');
    folderDownload.href = '/api/files/archive?path=' + encodeURIComponent(data.path);
    folderDownload.hidden = data.path === '/';
    if (!data.entries.length) { box.textContent = 'Tato složka je prázdná.'; return; }
    for (const entry of data.entries) {
      const row = node('div', undefined, 'file-row');
      const name = node('div', undefined, 'file-name');
      name.append(node('span', entry.directory ? '▰' : entry.symlink ? '↗' : '▤', entry.directory ? 'folder-icon' : ''));
      if (entry.directory && !entry.symlink) {
        const button = node('button', entry.name);
        button.addEventListener('click', () => loadFiles(entry.path));
        name.append(button);
      } else name.append(node('span', entry.name, 'service-title'));
      const regular = entry.regular !== false;
      const infoText = entry.symlink ? 'symlink blokován' : entry.directory ? 'Adresář' : regular ? formatBytes(entry.size) : 'Speciální soubor';
      const info = node('div', `${infoText} · ${entry.mode}`, 'file-info service-meta');
      const actions = node('div', undefined, 'actions');
      if (entry.directory && !entry.symlink) {
        const archive = node('a', 'Stáhnout .tar.gz', 'button button-quiet');
        archive.href = '/api/files/archive?path=' + encodeURIComponent(entry.path);
        actions.append(archive);
      } else if (regular && !entry.symlink) {
        const download = node('a', 'Stáhnout', 'button button-quiet');
        download.href = '/api/files/download?path=' + encodeURIComponent(entry.path);
        download.download = entry.name;
        actions.append(download);
        if (mediaKind(entry.name)) {
          const preview = node('button', 'Náhled', 'button button-quiet');
          preview.addEventListener('click', () => previewMedia(entry.path, entry.name));
          actions.append(preview);
        }
        if (entry.editable) {
          const edit = node('button', 'Upravit', 'button');
          edit.addEventListener('click', () => openEditor(entry.path));
          actions.append(edit);
        }
        if (entry.name.toLowerCase().endsWith('.sh')) {
          const run = node('button', 'Spustit skript', 'button button-warning');
          run.addEventListener('click', () => runScript(entry.path));
          actions.append(run);
        }
      }
      if (!entry.symlink && (entry.directory || regular) && !['/ffp/etc/ssh/sshd_config', '/ffp/etc/ssh/ssh_config'].includes(entry.path)) {
        const rename = node('button', 'Přejmenovat', 'button button-quiet');
        rename.addEventListener('click', () => renameFile(entry.path));
        const chmod = node('button', 'Práva', 'button button-quiet');
        chmod.addEventListener('click', () => changeMode(entry.path, entry.directory ? '755' : '644'));
        const remove = node('button', 'Smazat', 'button button-danger');
        remove.addEventListener('click', () => deleteFile(entry.path, entry.directory));
        actions.append(rename, chmod, remove);
      }
      row.append(name, info, actions);
      box.append(row);
    }
  } catch (error) { box.textContent = error.message; }
}
$('#files-refresh').addEventListener('click', async () => {
  await Promise.all([loadSSH(), loadAdb(), loadRcloneRemotes()]);
  await loadFiles();
});
$('#files-up').addEventListener('click', () => {
  if ($('#files-up').dataset.parent) loadFiles($('#files-up').dataset.parent);
});
$('#files-new-dir').addEventListener('click', () => createFileEntry('directory'));
$('#files-new-file').addEventListener('click', () => createFileEntry('file'));
async function createFileEntry(kind) {
  const label = kind === 'directory' ? 'Název nové složky:' : 'Název nového souboru:';
  const name = prompt(label);
  if (name === null) return;
  try {
    await post('/api/files/create', { path: currentFilePath, name, kind });
    toast(kind === 'directory' ? 'Složka vytvořena.' : 'Soubor vytvořen.');
    loadFiles();
  } catch (error) { toast(error.message, true); }
}
$('#file-upload').addEventListener('submit', async event => {
  event.preventDefault();
  const file = event.currentTarget.querySelector('input[type="file"]').files[0];
  if (!file) { toast('Vyberte soubor.', true); return; }
  const query = new URLSearchParams({ path: currentFilePath, name: file.name });
  try {
    await api('/api/files/upload?' + query.toString(), { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
    event.currentTarget.reset();
    toast('Soubor nahrán.');
    loadFiles();
  } catch (error) { toast(error.message, true); }
});
$('#file-archive-upload').addEventListener('submit', async event => {
  event.preventDefault();
  const file = event.currentTarget.querySelector('input[type="file"]').files[0];
  if (!file) { toast('Vyberte archiv.', true); return; }
  const query = new URLSearchParams({ path: currentFilePath, name: file.name });
  try {
    const result = await api('/api/files/archive-upload?' + query.toString(), { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
    event.currentTarget.reset();
    toast(`Archiv rozbalen: ${result.extracted.files} souborů.`);
    loadFiles();
  } catch (error) { toast(error.message, true); }
});
const dualFiles = {
  left: { source: 'nas', serial: '', remote: '', mountpoint: '', path: '/', entries: [], selected: new Set() },
  right: { source: 'nas', serial: '', remote: '', mountpoint: '', path: '/', entries: [], selected: new Set() }
};
let adbKnownDevices = [];
let rcloneKnownRemotes = [];
let rcloneProviderCache = [];
let rcloneConfigSession = '';
let rcloneEditProfile = null;
let rcloneOAuthPollTimer = null;
let sshfsKnownMounts = [];
function joinPanelPath(path, name) { return `${path === '/' ? '' : path}/${name}` || '/'; }
function panelEntryPath(side, entry) { return entry.path || joinPanelPath(dualFiles[side].path, entry.name); }
function fileTypeClass(entry) {
  if (entry.directory) return 'file-type-folder';
  if (entry.symlink) return 'file-type-link';
  const ext = String(entry.name || '').toLowerCase().split('.').pop();
  if (['png','jpg','jpeg','gif','webp','bmp'].includes(ext)) return 'file-type-image';
  if (['mp4','m4v','webm','mov','ogv','ogg','mkv'].includes(ext)) return 'file-type-video';
  if (ext === 'sh' || ext === 'py' || ext === 'pl' || ext === 'lua') return 'file-type-script';
  if (['txz','tgz','tar','gz','zip','xz','7z'].includes(ext)) return 'file-type-archive';
  if (TEXT_EXTENSIONS_FRONTEND.has(ext)) return 'file-type-text';
  return 'file-type-binary';
}
const TEXT_EXTENSIONS_FRONTEND = new Set(['txt','conf','cfg','ini','json','xml','html','htm','css','js','md','sh','py','pl','lua','log','yaml','yml','csv','profile','bashrc']);
function renderDualPanel(side) {
  const state = dualFiles[side];
  const box = $(`#file-${side}-list`);
  box.replaceChildren();
  const query = $(`#file-${side}-search`).value.trim().toLocaleLowerCase();
  const sort = $(`#file-${side}-sort`).value;
  let entries = state.entries.filter(entry => !query || entry.name.toLocaleLowerCase().includes(query));
  const cmp = (a, b) => String(a.name).localeCompare(String(b.name), undefined, { numeric: true, sensitivity: 'base' });
  if (sort === 'name') entries.sort((a,b) => Number(!a.directory) - Number(!b.directory) || cmp(a,b));
  else if (sort === 'type') entries.sort((a,b) => fileTypeClass(a).localeCompare(fileTypeClass(b)) || cmp(a,b));
  else if (sort === 'size') entries.sort((a,b) => Number(b.size || 0) - Number(a.size || 0) || cmp(a,b));
  else if (sort === 'modified') entries.sort((a,b) => Date.parse(b.modified || 0) - Date.parse(a.modified || 0) || cmp(a,b));
  if (!entries.length) box.append(node('div', state.entries.length ? 'Vyhledávání nic nenašlo.' : 'Složka je prázdná.', 'empty-state'));
  for (const entry of entries) {
    const path = panelEntryPath(side, entry);
    const row = node('div', undefined, `file-entry ${fileTypeClass(entry)}${state.selected.has(path) ? ' is-selected' : ''}`);
    const pick = node('input');
    pick.type = 'checkbox'; pick.checked = state.selected.has(path); pick.setAttribute('aria-label', `Vybrat ${entry.name}`);
    pick.addEventListener('change', () => { if (pick.checked) state.selected.add(path); else state.selected.delete(path); renderDualPanel(side); });
    const icon = buildFileThumbnail(side, entry, path);
    const title = entry.directory && !entry.symlink ? node('button', entry.name, 'file-entry-name') : node('span', entry.name, 'file-entry-name');
    if (entry.directory && !entry.symlink) title.addEventListener('click', () => loadDualPanel(side, path));
    const detailBits = [];
    detailBits.push(entry.directory ? 'Složka' : entry.symlink ? 'Symlink' : (entry.size === undefined ? 'Soubor' : formatBytes(entry.size)));
    if (entry.mode) detailBits.push(entry.mode);
    if (entry.modified) detailBits.push(new Date(entry.modified).toLocaleString());
    const details = node('div', detailBits.join(' · '), 'file-entry-meta');
    const actions = node('div', undefined, 'file-entry-actions');
    if (state.source === 'nas' || state.source === 'sshfs') {
      if (entry.directory && !entry.symlink && path !== '/') {
        const archive = node('a', 'Archiv', 'button button-quiet');
        archive.href = '/api/files/archive?path=' + encodeURIComponent(path);
        actions.append(archive);
      } else if (!entry.directory && entry.regular !== false && !entry.symlink) {
        const download = node('a', 'Stáhnout', 'button button-quiet');
        download.href = '/api/files/download?path=' + encodeURIComponent(path); download.setAttribute('download', entry.name);
        actions.append(download);
        if (mediaKind(entry.name)) {
          const preview = node('button', 'Náhled', 'button button-quiet');
          preview.addEventListener('click', () => previewMedia(path, entry.name, state)); actions.append(preview);
        }
        if (state.source === 'nas' && entry.editable) { const edit = node('button', 'Upravit', 'button'); edit.addEventListener('click', () => openEditor(path)); actions.append(edit); }
        if (state.source === 'nas' && entry.name.toLowerCase().endsWith('.sh')) { const run = node('button', 'Spustit', 'button button-warning'); run.addEventListener('click', () => runScript(path)); actions.append(run); }
      }
      if (entry.directory && !entry.symlink) {
        const terminal = node('button', 'Terminál zde', 'button button-quiet');
        terminal.addEventListener('click', () => state.source === 'nas' ? openTerminalHere('local', '', path) : openTerminalHere('sshfs', state.mountpoint, path));
        actions.append(terminal);
      }
      if (state.source === 'nas' && !entry.symlink && (entry.directory || entry.regular !== false) && !['/ffp/etc/ssh/sshd_config','/ffp/etc/ssh/ssh_config'].includes(path)) {
        const rename = node('button', 'Přejmenovat', 'button button-quiet'); rename.addEventListener('click', () => renameFile(path));
        const chmod = node('button', 'Práva', 'button button-quiet'); chmod.addEventListener('click', () => changeMode(path, entry.directory ? '755' : '644'));
        const remove = node('button', 'Smazat', 'button button-danger'); remove.addEventListener('click', () => deleteFile(path, entry.directory));
        actions.append(rename, chmod, remove);
      }
    } else if (state.source === 'adb' && !entry.directory) {
      const download = node('a', 'Stáhnout', 'button button-quiet');
      download.href = `/api/adb/download?${adbQuery({ serial: state.serial, path })}`; download.setAttribute('download', entry.name); actions.append(download);
      if (mediaKind(entry.name)) { const preview = node('button', 'Náhled', 'button button-quiet'); preview.addEventListener('click', () => previewMedia(path, entry.name, state)); actions.append(preview); }
      if (entry.text) { const edit = node('button', 'Upravit', 'button'); edit.addEventListener('click', () => openAdbEditor(path, state.serial)); actions.append(edit); }
      if (entry.name.toLowerCase().endsWith('.sh')) { const run = node('button', 'Spustit skript', 'button button-warning'); run.addEventListener('click', () => runAdbScript(path, state.serial)); actions.append(run); }
    } else if (state.source === 'adb' && entry.directory) {
      const terminal = node('button', 'Terminál zde', 'button button-quiet'); terminal.addEventListener('click', () => openTerminalHere('adb', state.serial, path)); actions.append(terminal);
    } else if (['rclone', 'sftp'].includes(state.source)) {
      if (!entry.directory && mediaKind(entry.name)) {
        const preview = node('button', 'Náhled', 'button button-quiet');
        preview.addEventListener('click', () => previewMedia(path, entry.name, state)); actions.append(preview);
      }
      if (entry.directory && state.source === 'sftp') {
        const terminal = node('button', 'Terminál zde', 'button button-quiet'); terminal.addEventListener('click', () => openTerminalHere('sftp', state.remote, path)); actions.append(terminal);
      }
    }
    row.append(pick, icon, title, details, actions);
    box.append(row);
  }
  $(`#file-${side}-count`).textContent = `Vybráno: ${state.selected.size} · ${entries.length} položek`;
  $(`#file-${side}-copy`).disabled = state.selected.size === 0;
  $(`#file-${side}-up`).disabled = state.source === 'sshfs' ? state.path === state.mountpoint : state.path === '/';
  const remoteSource = ['rclone', 'sftp'].includes(state.source);
  $(`#file-${side}-download`).disabled = state.selected.size === 0 || remoteSource;
  $(`#file-${side}-download`).hidden = remoteSource;
  $(`#file-${side}-delete`).disabled = !state.selected.size || state.source !== 'nas';
  const folderLink = $(`#file-${side}-download-dir`);
  folderLink.href = '/api/files/archive?path=' + encodeURIComponent(state.path);
  folderLink.hidden = !['nas', 'sshfs'].includes(state.source) || (state.source === 'nas' && state.path === '/') || (state.source === 'sshfs' && state.path === state.mountpoint);
}
function panelSourceValue(state) {
  if (state.source === 'adb') return 'adb:' + state.serial;
  if (['rclone', 'sftp'].includes(state.source)) return state.source + ':' + encodeURIComponent(state.remote);
  if (state.source === 'sshfs') return 'sshfs:' + encodeURIComponent(state.mountpoint);
  return 'nas';
}
function panelParentPath(state) {
  const parent = state.path.split('/').slice(0, -1).join('/') || '/';
  if (state.source !== 'sshfs') return parent;
  return parent === state.mountpoint || parent.startsWith(state.mountpoint.replace(/\/$/, '') + '/') ? parent : state.mountpoint;
}
async function loadDualPanel(side, path = dualFiles[side].path) {
  const state = dualFiles[side];
  const box = $(`#file-${side}-list`);
  state.path = path;
  state.selected.clear();
  $(`#file-${side}-path`).value = path;
  box.replaceChildren(node('div', 'Načítám…', 'empty-state'));
  try {
    let data;
    if (state.source === 'nas') data = await api('/api/files?path=' + encodeURIComponent(path));
    else if (state.source === 'adb') data = await api(`/api/adb/files?${adbQuery({ serial: state.serial, path })}`);
    else if (['rclone', 'sftp'].includes(state.source)) data = await api(`/api/rclone/files?${adbQuery({ remote: state.remote, path })}`);
    else data = await api(`/api/sshfs/files?${adbQuery({ mountpoint: state.mountpoint, path })}`);
    state.path = data.path;
    state.entries = data.entries || [];
    $(`#file-${side}-path`).value = state.path;
    $(`#file-${side}-up`).disabled = state.path === '/';
    renderDualPanel(side);
  } catch (error) { box.replaceChildren(node('div', error.message, 'notice notice-danger')); }
}
async function loadDualFiles() { await Promise.all(['left','right'].map(side => loadDualPanel(side))); }
function refreshFileSources() {
  for (const side of ['left','right']) {
    const select = $(`#file-${side}-source`);
    const state = dualFiles[side];
    const current = panelSourceValue(state);
    select.replaceChildren(new Option('NAS', 'nas'));
    for (const device of adbKnownDevices.filter(d => d.state === 'device')) select.add(new Option('ADB · ' + device.serial, 'adb:' + device.serial));
    for (const mount of sshfsKnownMounts.filter(item => item.manageable)) {
      select.add(new Option('SSHFS · ' + mount.source + ' @ ' + mount.mountpoint, 'sshfs:' + encodeURIComponent(mount.mountpoint)));
    }
    for (const remote of rcloneKnownRemotes) {
      const sourceType = remote.kind === 'sftp' ? 'sftp' : 'rclone';
      select.add(new Option((sourceType === 'sftp' ? 'SFTP · ' : 'rclone · ') + remote.name, sourceType + ':' + encodeURIComponent(remote.name)));
    }
    if (![...select.options].some(option => option.value === current) && current !== 'nas') {
      const missing = new Option(current.slice(0, current.indexOf(':')) + ' · zdroj nedostupný', current);
      missing.disabled = true; select.add(missing);
    }
    select.value = current;
    const nasOnly = $(`[data-file-panel="${side}"]`).querySelectorAll('.nas-only');
    nasOnly.forEach(el => { el.hidden = dualFiles[side].source !== 'nas'; });
    $(`#file-${side}-upload`).hidden = ['rclone', 'sftp'].includes(state.source);
    $(`#file-${side}-archive-upload`).hidden = ['rclone', 'sftp'].includes(state.source);
  }
}
const fileBookmarkStorageKey = 'ffp-webui-file-bookmarks-v1';
function readFileBookmarks() {
  try {
    const parsed = JSON.parse(localStorage.getItem(fileBookmarkStorageKey) || '[]');
    return Array.isArray(parsed) ? parsed.filter(item => item && typeof item.id === 'string' && typeof item.path === 'string') : [];
  } catch (_) { return []; }
}
let fileBookmarks = readFileBookmarks();
function storeFileBookmarks() {
  try { localStorage.setItem(fileBookmarkStorageKey, JSON.stringify(fileBookmarks)); renderFileBookmarks(); }
  catch (_) { toast('Záložky nelze uložit do úložiště tohoto prohlížeče.', true); }
}
function bookmarkDescription(bookmark) {
  if (bookmark.source === 'adb') return `ADB · ${bookmark.serial} · ${bookmark.path}`;
  if (bookmark.source === 'sftp') return `SFTP · ${bookmark.remote} · ${bookmark.path}`;
  if (bookmark.source === 'rclone') return `rclone · ${bookmark.remote} · ${bookmark.path}`;
  if (bookmark.source === 'sshfs') return `SSHFS · ${bookmark.mountpoint} · ${bookmark.path}`;
  return `NAS · ${bookmark.path}`;
}
function renderFileBookmarks() {
  const box = $('#file-bookmarks-list'); box.replaceChildren();
  if (!fileBookmarks.length) { box.append(node('div', 'Zatím nejsou uložené žádné cesty.', 'muted')); return; }
  for (const bookmark of fileBookmarks) {
    const row = node('div', undefined, 'file-bookmark-row');
    const details = node('div', undefined, 'file-bookmark-details');
    details.append(node('strong', bookmark.label || 'Uložená cesta'), node('span', bookmarkDescription(bookmark), 'muted'));
    const actions = node('div', undefined, 'actions');
    for (const side of ['left','right']) {
      const open = node('button', `Otevřít ${side === 'left' ? 'A' : 'B'}`, 'button button-quiet');
      open.type = 'button'; open.addEventListener('click', () => openFileBookmark(bookmark, side)); actions.append(open);
    }
    if (mediaKind(bookmark.path)) {
      const preview = node('button', 'Náhled', 'button button-quiet'); preview.type = 'button';
      preview.addEventListener('click', () => previewMedia(bookmark.path, bookmark.path.split('/').pop(), bookmark)); actions.append(preview);
    }
    if (['nas','adb','sshfs','sftp'].includes(bookmark.source)) {
      const terminal = node('button', 'Terminál zde', 'button button-quiet'); terminal.type = 'button';
      terminal.addEventListener('click', () => terminalForBookmark(bookmark)); actions.append(terminal);
    }
    const edit = node('button', 'Upravit', 'button button-quiet'); edit.type = 'button'; edit.addEventListener('click', () => editFileBookmark(bookmark));
    const remove = node('button', 'Smazat', 'button button-danger'); remove.type = 'button'; remove.addEventListener('click', () => deleteFileBookmark(bookmark));
    actions.append(edit, remove); row.append(details, actions); box.append(row);
  }
}
function saveFileBookmark(side) {
  const state = dualFiles[side];
  const label = prompt('Název záložky:', `${state.source.toUpperCase()} ${state.path}`);
  if (label === null || !label.trim()) return;
  const bookmark = { id: (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`),
    label: label.trim().slice(0, 100), source: state.source, path: state.path };
  if (state.source === 'adb') bookmark.serial = state.serial;
  if (['rclone','sftp'].includes(state.source)) bookmark.remote = state.remote;
  if (state.source === 'sshfs') bookmark.mountpoint = state.mountpoint;
  fileBookmarks.push(bookmark); storeFileBookmarks(); toast('Záložka uložena v tomto prohlížeči.');
}
function saveTerminalBookmark() {
  const session = terminalSessions.get(terminalId); const context = session?.context || terminalContext;
  if (!context || !['nas','adb','sshfs','sftp'].includes(context.source)) return toast('Aktivní terminál nemá složku propojenou se správcem souborů.', true);
  let path = context.source === 'sshfs' ? context.path : context.cwd;
  if (!path) return toast('Terminál zatím neposkytl pracovní cestu.', true);
  if (context.source !== 'nas') {
    const promptText = context.source === 'sshfs'
      ? `Cesta v souborovém panelu pod mountem ${context.mountpoint} (upravte, pokud jste změnili složku):`
      : 'Aktuální cesta pro záložku (po změně složky ji zde upravte):';
    const entered = prompt(promptText, path);
    if (entered === null || !entered.trim()) return;
    path = entered.trim();
  }
  path = path.replace(/\/+$/, '') || '/';
  const components = path === '/' ? [] : path.slice(1).split('/');
  if (!path.startsWith('/') || path.includes('\\') || /[\x00-\x1f\x7f]/.test(path) ||
      components.some(part => !part || part === '.' || part === '..')) {
    return toast('Cesta záložky musí být absolutní a bez `.` nebo `..` komponent.', true);
  }
  if (context.source === 'sshfs' && path !== context.mountpoint && !path.startsWith(context.mountpoint.replace(/\/$/, '') + '/')) {
    return toast('SSHFS záložka musí zůstat uvnitř aktivního mountpointu.', true);
  }
  const bookmark = { id: (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`),
    label: '', source: context.source, path };
  if (context.source === 'adb') bookmark.serial = context.serial || session.serial;
  if (context.source === 'sftp') bookmark.remote = context.remote;
  if (context.source === 'sshfs') bookmark.mountpoint = context.mountpoint;
  const identity = bookmark.serial || bookmark.remote || bookmark.mountpoint || '';
  const label = prompt('Název záložky terminálu:', `${context.source.toUpperCase()} ${identity} ${path}`.trim());
  if (label === null || !label.trim()) return;
  bookmark.label = label.trim().slice(0, 100);
  fileBookmarks.push(bookmark); storeFileBookmarks(); toast('Pracovní složka terminálu uložena do záložek.');
}
function editFileBookmark(bookmark) {
  const label = prompt('Název záložky:', bookmark.label || ''); if (label === null || !label.trim()) return;
  const path = prompt('Cesta:', bookmark.path); if (path === null || !path.trim()) return;
  bookmark.label = label.trim().slice(0, 100); bookmark.path = path.trim(); storeFileBookmarks();
}
function deleteFileBookmark(bookmark) {
  if (!confirm(`Smazat záložku „${bookmark.label}“?`)) return;
  fileBookmarks = fileBookmarks.filter(item => item.id !== bookmark.id); storeFileBookmarks();
}
async function openFileBookmark(bookmark, side) {
  const state = dualFiles[side];
  state.source = bookmark.source; state.path = bookmark.path; state.serial = bookmark.serial || '';
  state.remote = bookmark.remote || ''; state.mountpoint = bookmark.mountpoint || ''; state.selected.clear();
  refreshFileSources(); setView('files'); await loadDualPanel(side);
}
function terminalForBookmark(bookmark) {
  if (bookmark.source === 'nas') return startTerminal('local', '', bookmark.path);
  if (bookmark.source === 'adb') return startTerminal('adb', bookmark.serial, bookmark.path);
  if (bookmark.source === 'sftp') return startTerminal('ssh', '', bookmark.path, { remote: bookmark.remote });
  if (bookmark.source === 'sshfs') return openTerminalHere('sshfs', bookmark.mountpoint, bookmark.path);
}
$('#file-bookmark-save-left').addEventListener('click', () => saveFileBookmark('left'));
$('#file-bookmark-save-right').addEventListener('click', () => saveFileBookmark('right'));
$('#terminal-save-bookmark').addEventListener('click', saveTerminalBookmark);
renderFileBookmarks();
async function loadRcloneRemotes() {
  const note = $('#rclone-status-note'); const list = $('#rclone-remotes-list');
  try {
    const [status, data] = await Promise.all([api('/api/rclone/status'), api('/api/rclone/remotes')]);
    rcloneKnownRemotes = data.remotes || [];
    note.textContent = status.available
      ? `rclone ${status.version || ''} · ${rcloneKnownRemotes.length} úložišť (včetně SFTP) · RC pouze na localhost.`
      : `rclone není dostupný: ${status.error || data.error || 'neznámá chyba'}`;
    note.className = status.available ? 'muted' : 'notice notice-warning';
    $('#rclone-connect').disabled = !status.available || !!data.demo;
    list.replaceChildren();
    if (!rcloneKnownRemotes.length) list.append(node('div', 'Zatím nejsou nakonfigurovaná žádná rclone úložiště.', 'muted'));
    const names = new Set(rcloneKnownRemotes.map(remote => remote.name));
    for (const side of ['left', 'right']) {
      const state = dualFiles[side];
      if (['rclone', 'sftp'].includes(state.source) && !names.has(state.remote)) {
        state.source = 'nas'; state.remote = ''; state.path = '/'; state.selected.clear();
      }
    }
    for (const remote of rcloneKnownRemotes) {
      const row = node('div', undefined, 'rclone-remote-row');
      const info = node('div', undefined, 'rclone-remote-info');
      info.append(node('strong', `${remote.kind === 'sftp' ? 'SFTP' : 'rclone'} · ${remote.name}`));
      info.append(node('small', remote.type || 'typ nezjištěn', 'muted'));
      const actions = node('div', undefined, 'actions');
      const edit = node('button', 'Upravit', 'button button-quiet');
      edit.type = 'button'; edit.disabled = !!data.demo;
      edit.addEventListener('click', () => openRcloneConfig(remote.name));
      const remove = node('button', 'Odebrat', 'button button-danger');
      remove.type = 'button'; remove.disabled = !!data.demo;
      remove.addEventListener('click', () => deleteRcloneRemote(remote.name));
      actions.append(edit, remove); row.append(info, actions); list.append(row);
    }
    refreshFileSources(); refreshTerminalTargets();
  } catch (error) {
    rcloneKnownRemotes = [];
    note.textContent = error.message; note.className = 'notice notice-warning';
    $('#rclone-connect').disabled = true; list.replaceChildren(); refreshFileSources(); refreshTerminalTargets();
  }
}
$('#rclone-refresh').addEventListener('click', loadRcloneRemotes);
$('#rclone-connect').addEventListener('click', () => openRcloneConfig());
function rcloneSelectedProvider() { return rcloneProviderCache.find(provider => provider.name === $('#rclone-config-provider').value); }
function renderRcloneProviderFields() {
  const box = $('#rclone-config-fields');
  const previous = new Map([...box.querySelectorAll('[data-rclone-option]')].map(field => [field.dataset.rcloneOption, field.value]));
  const cleared = new Set([...box.querySelectorAll('[data-rclone-clear]:checked')].map(field => field.dataset.rcloneClear));
  box.replaceChildren();
  const provider = rcloneSelectedProvider(); if (!provider) return;
  for (const option of provider.options || []) {
    if (option.advanced && !$('#rclone-config-advanced').checked) continue;
    const hasValue = Object.prototype.hasOwnProperty.call(rcloneEditProfile?.values || {}, option.name);
    const storedValue = hasValue ? String(rcloneEditProfile.values[option.name]) : '';
    const hasSecret = (rcloneEditProfile?.secret_fields || []).includes(option.name);
    const isSecret = !!(option.password || option.sensitive);
    const initial = hasValue ? storedValue : (option.default || '');
    const label = node('label', option.name + (option.required && !(isSecret && hasSecret) ? ' *' : ''));
    if (option.help) label.title = option.help;
    let field;
    if (option.exclusive && option.examples?.length) {
      field = node('select');
      if (!option.required) field.add(new Option('— vyberte —', ''));
      for (const example of option.examples) field.add(new Option(example.value + (example.help ? ' · ' + example.help : ''), example.value));
      if (initial && ![...field.options].some(item => item.value === initial)) field.add(new Option(initial, initial));
      field.value = initial;
    } else if (['bool','boolean'].includes(option.type)) {
      field = node('select'); field.add(new Option('Ano', 'true')); field.add(new Option('Ne', 'false'));
      if (initial !== '') field.value = initial === 'true' ? 'true' : 'false';
    } else if (isSecret) {
      field = node('input'); field.type = 'password'; field.autocomplete = 'new-password';
    } else if (['token','credentials_json'].includes(option.name.toLowerCase())) {
      field = node('textarea'); field.rows = 3; field.spellcheck = false; field.autocomplete = 'off';
    } else {
      field = node('input'); field.type = 'text'; field.autocomplete = 'off';
    }
    field.dataset.rcloneOption = option.name;
    field.dataset.rcloneInitial = initial;
    field.dataset.rcloneSecret = String(isSecret);
    field.dataset.rcloneHasSecret = String(hasSecret);
    if (option.required && !(isSecret && hasSecret)) field.required = true;
    field.value = previous.has(option.name) ? previous.get(option.name) : (isSecret && rcloneEditProfile ? '' : initial);
    if (option.help) field.setAttribute('aria-label', option.help);
    label.append(field);
    if (option.help) label.append(node('small', option.help, 'muted'));
    label.classList.add('rclone-config-field');
    if (option.advanced) label.classList.add('rclone-field-advanced');
    box.append(label);
    if (isSecret && rcloneEditProfile && hasSecret) {
      const clearLabel = node('label', 'Vymazat hodnotu (uložit prázdný řetězec)', 'check-label rclone-clear-secret');
      const clear = node('input'); clear.type = 'checkbox'; clear.dataset.rcloneClear = option.name;
      clear.checked = cleared.has(option.name); clearLabel.prepend(clear);
      box.append(clearLabel);
    } else if (isSecret && rcloneEditProfile) {
      box.append(node('small', 'Nová hodnota se uloží; prázdné pole ponechá nastavení beze změny.', 'muted rclone-secret-note'));
    }
  }
}
async function openRcloneConfig(name = '') {
  try {
    const requests = [api('/api/rclone/providers')];
    if (name) requests.push(api('/api/rclone/remote?name=' + encodeURIComponent(name)));
    const [data, profile] = await Promise.all(requests);
    if (!data.available) throw new Error(data.error || 'Seznam typů úložišť není dostupný.');
    rcloneProviderCache = data.providers || [];
    const select = $('#rclone-config-provider'); select.replaceChildren(new Option('Vyberte typ úložiště', ''));
    for (const provider of rcloneProviderCache) select.add(new Option(provider.name + (provider.description ? ' · ' + provider.description : ''), provider.name));
    if (!rcloneProviderCache.length) throw new Error('Rclone nevrátil žádné typy úložišť.');
    rcloneEditProfile = profile || null;
    rcloneConfigSession = ''; $('#rclone-config-main').hidden = false; $('#rclone-config-question').hidden = true;
    $('#rclone-oauth-status').hidden = true; $('#rclone-oauth-status').replaceChildren();
    $('#rclone-config-name').value = profile?.name || ''; $('#rclone-config-name').readOnly = !!profile;
    select.value = profile?.type || ''; select.disabled = !!profile;
    $('#rclone-config-title').textContent = profile ? `Upravit úložiště ${profile.name}` : 'Připojit úložiště';
    $('#rclone-config-submit').textContent = profile ? 'Uložit změny' : 'Připojit';
    $('#rclone-config-advanced').checked = false;
    const note = $('#rclone-config-note'); note.className = 'notice notice-info';
    note.textContent = profile
      ? 'Citlivé hodnoty se nikdy nevracejí do prohlížeče. Uložené tajné pole ponechte prázdné pro zachování, nebo zadejte náhradu.'
      : 'Citlivé hodnoty se ukládají pouze do rclone konfigurace a nevracejí se zpět do prohlížeče.';
    renderRcloneProviderFields(); $('#rclone-config-dialog').showModal();
  } catch (error) { toast(error.message, true); }
}
async function deleteRcloneRemote(name) {
  const phrase = `DELETE RCLONE REMOTE ${name}`;
  if (prompt(`Odebere pouze konfiguraci remote „${name}“, nikoli soubory v cloudu. Pro potvrzení zadejte přesně:\n${phrase}`) !== phrase) return;
  try {
    await post('/api/rclone/config/delete', { name, confirm: phrase });
    toast(`Konfigurace remote ${name} byla odebrána.`);
    await loadRcloneRemotes(); await Promise.all(['left', 'right'].map(side => loadDualPanel(side)));
  } catch (error) { toast(error.message, true); }
}
$('#rclone-config-provider').addEventListener('change', renderRcloneProviderFields);
$('#rclone-config-advanced').addEventListener('change', renderRcloneProviderFields);
async function closeRcloneConfig() {
  if (rcloneOAuthPollTimer) clearInterval(rcloneOAuthPollTimer);
  rcloneOAuthPollTimer = null;
  if (rcloneConfigSession) { try { await post('/api/rclone/config/cancel', { session_id: rcloneConfigSession }); } catch (_) {} }
  rcloneConfigSession = ''; rcloneEditProfile = null;
  $('#rclone-config-dialog').close();
}
$('#rclone-config-close').addEventListener('click', closeRcloneConfig);
$('#rclone-config-cancel').addEventListener('click', closeRcloneConfig);
$('#rclone-config-dialog').addEventListener('cancel', event => { event.preventDefault(); closeRcloneConfig(); });
async function refreshRcloneOAuthStatus() {
  const box = $('#rclone-oauth-status');
  try {
    const status = await api('/api/rclone/oauth');
    if (!status.supported) {
      if (rcloneOAuthPollTimer) clearInterval(rcloneOAuthPollTimer); rcloneOAuthPollTimer = null;
      box.hidden = false; box.className = 'notice notice-info';
      box.textContent = 'Tato verze rclone nemá nový OAuth status endpoint. Pro bezobslužný NAS zvolte v průvodci „Ne“ u místního prohlížeče a použijte rclone authorize na počítači s prohlížečem.';
      return status;
    }
    if (status.status !== 'running' || !status.auth_url) {
      if (rcloneOAuthPollTimer) clearInterval(rcloneOAuthPollTimer); rcloneOAuthPollTimer = null;
      box.hidden = true; box.replaceChildren(); return status;
    }
    box.hidden = false; box.className = 'notice notice-warning rclone-oauth-box'; box.replaceChildren();
    box.append(node('strong', 'OAuth čeká na autorizaci.'));
    box.append(node('p', 'Odkaz používá loopback callback. Z jiného zařízení otevření 127.0.0.1 nevede na NAS; použijte SSH tunel nebo postup rclone authorize.'));
    const code = node('code', status.auth_url, 'rclone-oauth-url'); box.append(code);
    const copy = node('button', 'Kopírovat odkaz', 'button button-quiet'); copy.type = 'button';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(status.auth_url); toast('OAuth odkaz zkopírován.'); }
      catch (_) { toast('Odkaz označte a zkopírujte ručně.', true); }
    });
    box.append(copy);
    const stop = node('button', 'Zastavit OAuth čekání', 'button button-quiet'); stop.type = 'button';
    stop.addEventListener('click', async () => {
      try { await post('/api/rclone/oauth/stop', {}); toast('OAuth čekání bylo ukončeno.'); await refreshRcloneOAuthStatus(); }
      catch (error) { toast(error.message, true); }
    });
    box.append(stop);
    box.append(node('small', `Přes SSH: ssh -L 53682:localhost:53682 uzivatel@${location.hostname} · poté otevřete odkaz v prohlížeči tohoto počítače.`, 'muted'));
    return status;
  } catch (error) {
    box.hidden = false; box.className = 'notice notice-warning'; box.textContent = `OAuth stav nelze načíst: ${error.message}`;
    return null;
  }
}
function showRcloneQuestion(result) {
  const question = result.option; const box = $('#rclone-config-question'); box.replaceChildren();
  $('#rclone-config-main').hidden = true; box.hidden = false; rcloneConfigSession = result.session_id || '';
  if (!question) {
    box.append(node('div', result.error || 'Rclone vyžaduje interaktivní krok, který tento průvodce nedokáže zobrazit.', 'notice notice-warning'));
    $('#rclone-config-submit').disabled = true; return;
  }
  $('#rclone-config-submit').disabled = false;
  box.append(node('h3', question.name));
  if (question.help) box.append(node('p', question.help, 'muted'));
  if (question.name === 'config_is_local') {
    box.append(node('p', 'NAS nemá běžný desktopový prohlížeč. Pro cílové zařízení je obvykle vhodnější „Ne“; následně spusťte rclone authorize na počítači s prohlížečem a vložte vrácený token.', 'notice notice-info'));
  }
  if (/token|credentials_json/i.test(question.name)) {
    const provider = rcloneEditProfile?.type || rcloneSelectedProvider()?.name || '';
    box.append(node('p', `Tento údaj může být OAuth token nebo JSON přihlašovací blob; nezveřejňuje se v auditním záznamu. Na počítači s prohlížečem použijte rclone authorize "${provider}" (nejlépe stejnou verzi Rclone) a vložte celý výstup.`, 'notice notice-info'));
  }
  let field;
  if (question.exclusive && question.examples?.length) {
    field = node('select'); if (!question.required) field.add(new Option('— vyberte —', ''));
    for (const example of question.examples) field.add(new Option(example.value + (example.help ? ' · ' + example.help : ''), example.value));
  } else if (['bool','boolean'].includes(question.type)) {
    field = node('select'); field.add(new Option('Ano', 'true')); field.add(new Option('Ne', 'false'));
    if (question.name === 'config_is_local' && !question.default) field.value = 'false';
  } else if (/token|credentials_json/i.test(question.name)) { field = node('input'); field.type = 'password'; field.autocomplete = 'new-password'; field.maxLength = 8192; }
  else if (question.password) { field = node('input'); field.type = 'password'; field.autocomplete = 'new-password'; }
  else { field = node('input'); field.type = 'text'; field.autocomplete = 'off'; }
  field.id = 'rclone-question-answer';
  field.value = question.name === 'config_is_local' && ['bool','boolean'].includes(question.type) ? 'false' : (question.default || '');
  field.required = !!question.required;
  box.append(field);
  const note = $('#rclone-config-note'); note.className = result.error ? 'notice notice-warning' : 'notice notice-info';
  note.textContent = result.error || 'Rclone požaduje doplňující údaj pro dokončení konfigurace.';
  refreshRcloneOAuthStatus().then(status => {
    if (status?.supported && status.status === 'running') {
      if (rcloneOAuthPollTimer) clearInterval(rcloneOAuthPollTimer);
      rcloneOAuthPollTimer = setInterval(refreshRcloneOAuthStatus, 5000);
    }
  });
}
$('#rclone-config-form').addEventListener('submit', async event => {
  event.preventDefault();
  const button = $('#rclone-config-submit'); button.disabled = true;
  try {
    let result;
    if (rcloneConfigSession) {
      const field = $('#rclone-question-answer');
      if (field?.required && !field.value) { field.reportValidity(); button.disabled = false; return; }
      result = await post('/api/rclone/config/continue', { session_id: rcloneConfigSession, result: field?.value || '' });
    } else {
      const form = $('#rclone-config-form');
      const name = $('#rclone-config-name').value.trim(); const provider = rcloneSelectedProvider();
      if (!provider || !form.reportValidity()) { button.disabled = false; return; }
      const parameters = {};
      for (const field of $('#rclone-config-fields').querySelectorAll('[data-rclone-option]')) {
        const key = field.dataset.rcloneOption;
        const clear = $('#rclone-config-fields').querySelector(`[data-rclone-clear="${key}"]`)?.checked;
        if (field.dataset.rcloneSecret === 'true') {
          if (clear) parameters[key] = '';
          else if (field.value !== '') parameters[key] = field.value;
        } else if (!rcloneEditProfile || field.value !== field.dataset.rcloneInitial) {
          parameters[key] = field.value;
        }
      }
      result = rcloneEditProfile
        ? await post('/api/rclone/config/update', { name, type: provider.name, parameters })
        : await post('/api/rclone/config/create', { name, type: provider.name, parameters });
    }
    if (result.complete) {
      if (rcloneOAuthPollTimer) clearInterval(rcloneOAuthPollTimer); rcloneOAuthPollTimer = null;
      const updated = result.action === 'update' || !!rcloneEditProfile;
      rcloneConfigSession = ''; rcloneEditProfile = null; $('#rclone-config-dialog').close();
      toast(updated ? `Úložiště ${result.remote} upraveno.` : `Úložiště ${result.remote} připojeno.`); await loadRcloneRemotes();
    } else if (result.session_id) showRcloneQuestion(result);
    else throw new Error(result.error || 'Rclone konfiguraci nedokončil.');
  } catch (error) {
    $('#rclone-config-note').textContent = error.message; $('#rclone-config-note').className = 'notice notice-danger';
  } finally { if (!$('#rclone-config-dialog').hidden) button.disabled = false; }
});
for (const side of ['left','right']) {
  $(`#file-${side}-source`).addEventListener('change', event => {
    const value = event.currentTarget.value;
    const state = dualFiles[side];
    state.serial = ''; state.remote = ''; state.mountpoint = '';
    if (value === 'nas') { state.source = 'nas'; state.path = '/'; }
    else if (value.startsWith('adb:')) { state.source = 'adb'; state.serial = value.slice(4); state.path = '/sdcard'; }
    else if (value.startsWith('rclone:') || value.startsWith('sftp:')) { state.source = value.startsWith('sftp:') ? 'sftp' : 'rclone'; state.remote = decodeURIComponent(value.slice(value.indexOf(':') + 1)); state.path = '/'; }
    else if (value.startsWith('sshfs:')) { state.source = 'sshfs'; state.mountpoint = decodeURIComponent(value.slice(6)); state.path = state.mountpoint; }
    dualFiles[side].selected.clear(); refreshFileSources(); loadDualPanel(side);
  });
  $(`#file-${side}-go`).addEventListener('click', () => loadDualPanel(side, $(`#file-${side}-path`).value.trim()));
  $(`#file-${side}-path`).addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); loadDualPanel(side, event.currentTarget.value.trim()); } });
  $(`#file-${side}-up`).addEventListener('click', () => loadDualPanel(side, panelParentPath(dualFiles[side])));
  $(`#file-${side}-search`).addEventListener('input', () => renderDualPanel(side));
  $(`#file-${side}-sort`).addEventListener('change', () => renderDualPanel(side));
  $(`#file-${side}-select-all`).addEventListener('click', () => {
    const search = $(`#file-${side}-search`).value.trim().toLocaleLowerCase();
    const visible = dualFiles[side].entries.filter(entry => !search || entry.name.toLocaleLowerCase().includes(search)).map(entry => panelEntryPath(side, entry));
    if (visible.length && visible.every(path => dualFiles[side].selected.has(path))) visible.forEach(path => dualFiles[side].selected.delete(path));
    else visible.forEach(path => dualFiles[side].selected.add(path));
    renderDualPanel(side);
  });
  $(`#file-${side}-download`).addEventListener('click', () => downloadPanelSelection(side));
  $(`#file-${side}-copy`).addEventListener('click', () => copyPanelSelection(side));
  $(`#file-${side}-delete`).addEventListener('click', () => deletePanelSelection(side));
  $(`#file-${side}-new-dir`).addEventListener('click', () => createPanelEntry(side, 'directory'));
  $(`#file-${side}-new-file`).addEventListener('click', () => createPanelEntry(side, 'file'));
  $(`#file-${side}-upload`).addEventListener('submit', event => uploadPanelFiles(event, side));
  $(`#file-${side}-archive-upload`).addEventListener('submit', event => uploadPanelArchive(event, side));
}
async function createPanelEntry(side, kind) {
  const name = prompt(kind === 'directory' ? 'Název nové složky:' : 'Název nového souboru:');
  if (name === null) return;
  try { await post('/api/files/create', { path: dualFiles[side].path, name, kind }); toast(kind === 'directory' ? 'Složka vytvořena.' : 'Soubor vytvořen.'); await loadDualPanel(side); }
  catch (error) { toast(error.message, true); }
}
async function uploadPanelFiles(event, side) {
  event.preventDefault();
  const state = dualFiles[side]; const input = event.currentTarget.querySelector('input[type="file"]');
  const files = [...input.files]; if (!files.length) return;
  try {
    for (const file of files) {
      if (state.source === 'nas' || state.source === 'sshfs') {
        const query = new URLSearchParams({ path: state.path, name: file.name });
        await api('/api/files/upload?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      } else {
        const remote = joinPanelPath(state.path, file.name);
        if (!confirm(`Nahrát ${file.name} do ${remote}? Existující soubor může být přepsán.`)) continue;
        const query = adbQuery({ serial: state.serial, path: state.path, filename: file.name, confirm: `UPLOAD ${remote}` });
        await api('/api/adb/upload?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      }
    }
    event.currentTarget.reset(); toast('Upload dokončen.'); await loadDualPanel(side);
  } catch (error) { toast(error.message, true); }
}
async function uploadPanelArchive(event, side) {
  event.preventDefault();
  const file = event.currentTarget.querySelector('input[type="file"]').files[0]; if (!file) return;
  const state = dualFiles[side];
  try {
    if (state.source === 'nas' || state.source === 'sshfs') {
      const query = new URLSearchParams({ path: state.path, name: file.name });
      const result = await api('/api/files/archive-upload?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file });
      event.currentTarget.reset(); toast(`Archiv rozbalen: ${result.extracted.files} souborů.`); await loadDualPanel(side);
    } else {
      const confirmText = `UPLOAD ARCHIVE ${file.name} TO ${state.path}`;
      if (prompt(`Obsah archivu se bezpečně rozbalí a nahraje do ${state.path}; existující cíle mohou být nahrazeny. Pro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
      const query = adbQuery({ serial: state.serial, path: state.path, name: file.name, confirm: confirmText });
      const job = await api('/api/adb/archive-upload?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file, timeoutMs: 0 });
      event.currentTarget.reset(); toast(`ADB archiv se nahrává (úloha ${job.id}).`); pollJob(job.id, 'Archiv byl nahrán do zařízení.', () => loadDualPanel(side));
    }
  }
  catch (error) { toast(error.message, true); }
}
async function downloadSelectionArchive(endpoint, payload, filename) {
  const response = await fetch(endpoint, { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  if (!response.ok) { let message = `HTTP ${response.status}`; try { message = (await response.json()).error || message; } catch (_) {} throw new Error(message); }
  const blob = await response.blob(); const url = URL.createObjectURL(blob); const link = node('a'); link.href = url; link.download = filename; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 30000);
}
async function copyPanelSelection(side) {
  const other = side === 'left' ? 'right' : 'left';
  const source = dualFiles[side], destination = dualFiles[other];
  const paths = [...source.selected];
  if (!paths.length) return;
  const sameSource = source.source === destination.source &&
    (source.source !== 'adb' || source.serial === destination.serial) &&
    (!['rclone', 'sftp'].includes(source.source) || source.remote === destination.remote) &&
    (source.source !== 'sshfs' || source.mountpoint === destination.mountpoint);
  if (sameSource && source.path === destination.path) {
    toast('Zdroj a cíl jsou ve stejné složce.', true); return;
  }
  const selectedDirectories = paths.filter(path => source.entries.find(entry => panelEntryPath(side, entry) === path)?.directory);
  if (sameSource &&
      selectedDirectories.some(path => destination.path === path || destination.path.startsWith(path.replace(/\/$/, '') + '/'))) {
    toast('Cílová složka nesmí být uvnitř kopírované složky.', true); return;
  }
  const sourceLabel = source.source === 'nas' ? `NAS:${source.path}` : source.source === 'adb' ? `ADB(${source.serial}):${source.path}` : ['rclone', 'sftp'].includes(source.source) ? `${source.source === 'sftp' ? 'SFTP' : 'rclone'} ${source.remote}:${source.path}` : `SSHFS ${source.mountpoint}:${source.path}`;
  const destinationLabel = destination.source === 'nas' ? `NAS:${destination.path}` : destination.source === 'adb' ? `ADB(${destination.serial}):${destination.path}` : ['rclone', 'sftp'].includes(destination.source) ? `${destination.source === 'sftp' ? 'SFTP' : 'rclone'} ${destination.remote}:${destination.path}` : `SSHFS ${destination.mountpoint}:${destination.path}`;
  if (['rclone', 'sftp'].includes(source.source) || ['rclone', 'sftp'].includes(destination.source)) {
    if (source.source === 'adb' || destination.source === 'adb') {
      toast('Přímý přenos ADB ↔ rclone není dostupný; použijte NAS jako mezikrok.', true); return;
    }
    const phrase = `RCLONE COPY ${paths.length}`;
    if (prompt(`Rclone přenese ${paths.length} položek z ${sourceLabel} do ${destinationLabel}. Při shodě názvů může cílový soubor aktualizovat/přepsat; kopírování nemaže jiné cílové soubory. Potvrďte přesně: ${phrase}`) !== phrase) return;
    const descriptor = state => ['rclone', 'sftp'].includes(state.source)
      ? { kind: state.source, remote: state.remote, path: state.path }
      : state.source === 'sshfs'
        ? { kind: 'sshfs', mountpoint: state.mountpoint, path: state.path }
        : { kind: 'nas', path: state.path };
    const items = paths.map(path => source.entries.find(entry => panelEntryPath(side, entry) === path))
      .filter(Boolean).map(entry => ({ name: entry.name, directory: !!entry.directory }));
    if (items.length !== paths.length) { toast('Výběr se změnil; obnovte panel.', true); return; }
    try {
      const job = await post('/api/rclone/copy', { source: descriptor(source), destination: descriptor(destination), items, confirm: phrase });
      $('#rclone-transfer-card').hidden = false;
      toast(`Rclone přenos spuštěn (úloha ${job.id}).`);
      pollRcloneJob(job.id, () => loadDualFiles());
    } catch (error) { toast(error.message, true); }
    return;
  }
  const confirmText = `COPY ${paths.length} ITEMS TO ${destinationLabel}`;
  if (prompt(`Kopírovat ${paths.length} vybraných položek z ${sourceLabel} do ${destinationLabel}? Při konfliktu názvů se přenos odmítne. Potvrďte přesně: ${confirmText}`) !== confirmText) return;
  const sourceIsAdb = source.source === 'adb';
  const archiveName = sourceIsAdb ? 'android-selection.zip' : 'selected-files.tar.gz';
  const archiveEndpoint = sourceIsAdb ? '/api/adb/archive-selection' : '/api/files/archive-selection';
  const archivePayload = sourceIsAdb ? { serial: source.serial, paths } : { paths };
  try {
    const archiveResponse = await fetch(archiveEndpoint, { method: 'POST', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(archivePayload) });
    if (!archiveResponse.ok) { let message = `HTTP ${archiveResponse.status}`; try { message = (await archiveResponse.json()).error || message; } catch (_) {} throw new Error(message); }
    const archive = await archiveResponse.blob();
    if (destination.source !== 'adb') {
      const query = new URLSearchParams({ path: destination.path, name: archiveName });
      const result = await api('/api/files/archive-upload?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: archive, timeoutMs: 0 });
      toast(`Přenos dokončen: ${result.extracted?.files || 0} souborů.`);
      await loadDualFiles();
    } else {
      const confirmArchive = `UPLOAD ARCHIVE ${archiveName} TO ${destination.path}`;
      const query = adbQuery({ serial: destination.serial, path: destination.path, name: archiveName, confirm: confirmArchive });
      const job = await api('/api/adb/archive-upload?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: archive, timeoutMs: 0 });
      toast(`Přenos do Androidu spuštěn (úloha ${job.id}).`);
      pollJob(job.id, 'Přenos do Androidu dokončen.', loadDualFiles);
    }
  } catch (error) { toast(error.message, true); }
}
async function pollRcloneJob(id, onComplete) {
  const card = $('#rclone-transfer-card'); const note = $('#rclone-transfer-note'); const progress = $('#rclone-transfer-progress');
  for (let attempt = 0; attempt < 3600; attempt++) {
    try {
      const job = await api(`/api/rclone/jobs/${encodeURIComponent(id)}`);
      const p = job.progress || {}; const bytes = Number(p.bytes || 0); const totalBytes = Number(p.totalBytes || 0);
      const byteText = totalBytes > 0 ? `${formatBytes(bytes)} / ${formatBytes(totalBytes)}` : `${formatBytes(bytes)} přeneseno`;
      note.textContent = `${job.completed || 0}/${job.total || 0} položek${job.current ? ` · ${job.current}` : ''} · ${byteText}${p.speed ? ` · ${formatBytes(p.speed)}/s` : ''}`;
      progress.value = job.total ? Math.round(100 * (job.completed || 0) / job.total) : 0;
      if (job.state === 'completed') { progress.value = 100; note.textContent += ' · hotovo'; toast('Rclone přenos dokončen.'); if (onComplete) await onComplete(); return; }
      if (job.state === 'failed') { note.textContent = job.error || 'Přenos selhal.'; toast(note.textContent, true); return; }
    } catch (error) { note.textContent = error.message; toast(error.message, true); return; }
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  note.textContent = 'Čekání na přenos překročilo limit zobrazení; úloha může dále běžet.';
}
async function downloadPanelSelection(side) {
  const state = dualFiles[side]; const selected = [...state.selected]; if (!selected.length) return;
  try {
    if ((state.source === 'nas' || state.source === 'sshfs') && selected.length === 1) {
      const entry = state.entries.find(item => panelEntryPath(side,item) === selected[0]);
      const link = node('a'); link.href = entry?.directory ? '/api/files/archive?path=' + encodeURIComponent(selected[0]) : '/api/files/download?path=' + encodeURIComponent(selected[0]); link.download = entry?.directory ? (entry.name + '.tar.gz') : entry.name; document.body.append(link); link.click(); link.remove(); return;
    }
    if (state.source === 'adb' && selected.length === 1) {
      const entry = state.entries.find(item => panelEntryPath(side,item) === selected[0]);
      if (entry && !entry.directory) { const link = node('a'); link.href = `/api/adb/download?${adbQuery({serial:state.serial,path:selected[0]})}`; link.download = entry.name; document.body.append(link); link.click(); link.remove(); return; }
    }
    if (state.source === 'nas' || state.source === 'sshfs') await downloadSelectionArchive('/api/files/archive-selection', { paths: selected }, 'selected-files.tar.gz');
    else if (state.source === 'adb') await downloadSelectionArchive('/api/adb/archive-selection', { serial: state.serial, paths: selected }, 'android-selection.zip');
    else toast('Rclone soubory stáhněte přenosem do panelu NAS.');
  } catch (error) { toast(error.message, true); }
}
async function deletePanelSelection(side) {
  const state = dualFiles[side]; const selected = [...state.selected]; if (!selected.length || state.source !== 'nas') return;
  const phrase = `DELETE SELECTED ${selected.length}`;
  if (prompt(`Vybrané soubory a složky budou před smazáním zazálohovány. Pro potvrzení zadejte: ${phrase}`) !== phrase) return;
  try {
    for (const path of selected) {
      const entry = state.entries.find(item => panelEntryPath(side,item) === path);
      const base = path.split('/').pop();
      const confirmText = entry?.directory ? `DELETE RECURSIVELY ${base}` : `DELETE ${base}`;
      await post('/api/files/delete', { path, confirm: confirmText });
    }
    toast(`${selected.length} položek smazáno a zazálohováno.`); await loadFiles();
  } catch (error) { toast(error.message, true); await loadFiles(); }
}

async function openEditor(path, service = null) {
  editorService = service;
  try {
    const data = await api('/api/files/read?path=' + encodeURIComponent(path));
    editorPath = path;
    $('#editor-title').textContent = path + (data.exists === false ? ' · nový soubor' : '');
    $('#editor-content').value = data.content;
    $('#editor-dialog').showModal();
  } catch (error) { toast(error.message, true); }
}
$('#editor-save').addEventListener('click', async () => {
  if (!editorPath) return;
  if (editorService) {
    const confirmService = `SAVE SERVICE ${editorService.name}`;
    if (prompt(`Skript služby se před uložením zazálohuje; zachová se jeho aktuální autostart stav. Pro potvrzení zadejte: ${confirmService}`) !== confirmService) return;
    try {
      const result = await post('/api/services/manage', { action: 'save', name: editorService.name, content: $('#editor-content').value, enabled: editorService.enabled, confirm: confirmService });
      $('#editor-dialog').close(); editorService = null; toast(result.note || 'Skript služby uložen a zazálohován.'); await loadServices();
    } catch (error) { toast(error.message, true); }
    return;
  }
  const base = editorPath.split('/').pop();
  const confirmText = `SAVE ${base}`;
  if (prompt(`Soubor se před uložením zazálohuje, pokud již existuje. Pro uložení zadejte: ${confirmText}`) !== confirmText) return;
  try {
    const result = await post('/api/files/save', { path: editorPath, content: $('#editor-content').value, confirm: confirmText });
    $('#editor-dialog').close();
    toast(result.created ? 'Profilový soubor vytvořen.' : 'Soubor uložen a původní verze zazálohována.');
    loadFiles();
    loadEnvProfiles();
    if (editorPath === $('#sshd-edit').dataset.path || editorPath === $('#ssh-client-edit').dataset.path) loadSSH();
  } catch (error) { toast(error.message, true); }
});
async function deleteFile(path, isDirectory = false) {
  const base = path.split('/').pop();
  const confirmText = isDirectory ? `DELETE RECURSIVELY ${base}` : `DELETE ${base}`;
  const explanation = isDirectory ? 'Složka bude zazálohována jako archiv a poté smazána včetně obsahu.' : 'Soubor bude nejprve zazálohován.';
  if (prompt(`${explanation} Pro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
  try {
    const result = await post('/api/files/delete', { path, confirm: confirmText });
    toast(isDirectory ? `Složka smazána; záloha: ${result.backup}` : 'Soubor smazán; záloha byla vytvořena.');
    loadFiles();
    loadEnvProfiles();
  } catch (error) { toast(error.message, true); }
}
async function renameFile(path) {
  const oldName = path.split('/').pop();
  const name = prompt(`Nový název pro ${path}:`, oldName);
  if (name === null || name === oldName) return;
  const confirmText = `RENAME ${path} -> ${name}`;
  if (prompt(`Pro přejmenování zadejte přesně: ${confirmText}`) !== confirmText) return;
  try {
    await post('/api/files/rename', { path, name, confirm: confirmText });
    toast('Přejmenováno.');
    loadFiles();
  } catch (error) { toast(error.message, true); }
}
async function changeMode(path, fallback) {
  const mode = prompt(`Nová práva pro ${path} (osmičkově, bez SUID/SGID):`, fallback);
  if (mode === null) return;
  const confirmText = `CHMOD ${path} ${mode}`;
  if (prompt(`Pro změnu práv zadejte přesně: ${confirmText}`) !== confirmText) return;
  try {
    await post('/api/files/chmod', { path, mode, confirm: confirmText });
    toast(`Práva nastavena na ${mode}.`);
    loadFiles();
  } catch (error) { toast(error.message, true); }
}
async function runScript(path) {
  const confirmText = `RUN ${path}`;
  if (prompt(`Skript se spustí jako uživatel WebUI. Pro spuštění zadejte přesně:\n${confirmText}`) !== confirmText) return;
  try {
    const job = await post('/api/files/run', { path, confirm: confirmText });
    toast(`Skript spuštěn (úloha ${job.id}).`);
    pollJob(job.id, `Skript dokončen: ${path}`, () => loadFiles());
  } catch (error) { toast(error.message, true); }
}
async function runAdbScript(path, serial) {
  const phrase = `RUN ANDROID SCRIPT ${serial}:${path}`;
  if (prompt(`Skript bude spuštěn na Android zařízení ${serial}. Zkontrolujte soubor a potvrďte přesně:\n${phrase}`) !== phrase) return;
  try {
    const job = await post('/api/adb/run-script', { serial, path, confirm: phrase });
    toast(`ADB skript spuštěn (úloha ${job.id}).`);
    pollJob(job.id, `ADB skript dokončen: ${path}`, loadDualFiles);
  } catch (error) { toast(error.message, true); }
}
function previewMedia(path, name, state = { source: 'nas' }) {
  const kind = mediaKind(name);
  const url = mediaPreviewUrl(state, path);
  const image = $('#media-image');
  const video = $('#media-video');
  $('#media-title').textContent = name;
  image.hidden = kind !== 'image';
  video.hidden = kind !== 'video';
  if (kind === 'image') image.src = url;
  else {
    video.src = url;
    video.load();
  }
  $('#media-dialog').showModal();
}
$('#media-dialog').addEventListener('close', () => {
  const video = $('#media-video');
  video.pause();
  video.removeAttribute('src');
  video.load();
  $('#media-image').removeAttribute('src');
});

async function loadSSH() {
  const box = $('#ssh-info');
  box.replaceChildren();
  try {
    const data = await api('/api/ssh');
    for (const [label, value] of [
      ['SSH klient', data.ssh_available ? 'nalezen' : 'nenalezen'],
      ['SSHD', data.sshd_available ? 'nalezen' : 'nenalezen'],
      ['SSHFS', data.sshfs_available ? 'nalezen' : 'nenalezen'],
      ['FUSE odpojovač', data.fusermount_available ? 'nalezen' : 'nenalezen'],
      ['Aktivní SSHFS mounty', (data.sshfs_mounts || []).length]
    ]) {
      const card = statCard(label, value, data.mode);
      card.classList.add('ssh-card');
      box.append(card);
    }
    $('#ssh-note').textContent = data.note || '';
    $('#ssh-note').className = 'notice notice-info';
    $('#sshd-config-path').textContent = data.config_path ? `Konfigurace: ${data.config_path}` : 'Konfigurace sshd nebyla nalezena.';
    $('#ssh-client-config-path').textContent = data.client_config_path ? `Konfigurace: ${data.client_config_path}` : 'SSH klientská konfigurace nebyla nalezena.';
    $('#sshd-edit').dataset.path = data.config_path || '';
    $('#ssh-client-edit').dataset.path = data.client_config_path || '';
    $('#sshd-edit').disabled = !!data.demo || !data.config_path;
    $('#ssh-client-edit').disabled = !!data.demo || !data.client_config_path;
    $('#sshd-validate').disabled = !!data.demo || !data.config_path || !data.sshd_available;
    $('#sshd-restart').disabled = !!data.demo || !data.sshd_service_available;
    $('#sshd-settings').replaceChildren();
    if (data.sshd_settings?.length) {
      for (const setting of data.sshd_settings) {
        const row = node('div');
        row.append(node('dt', setting.name), node('dd', setting.value));
        $('#sshd-settings').append(row);
      }
    } else {
      const row = node('div');
      row.append(node('dt', 'Nastavení'), node('dd', data.demo ? 'Demo režim nečte cílovou konfiguraci.' : 'Žádné vybrané direktivy nebyly nalezeny.'));
      $('#sshd-settings').append(row);
    }

    const mountsBox = $('#sshfs-mounts');
    mountsBox.replaceChildren();
    const mounts = data.sshfs_mounts || [];
    sshfsKnownMounts = mounts.filter(mount => mount.manageable);
    refreshFileSources();
    mountsBox.className = mounts.length ? '' : 'empty-state';
    if (!mounts.length) mountsBox.textContent = 'Žádné aktivní SSHFS mounty.';
    for (const mount of mounts) {
      const row = node('div', undefined, 'sshfs-row');
      const details = node('div', undefined, 'sshfs-details');
      details.append(node('div', mount.source || 'Vzdálený zdroj neznámý', 'service-title'));
      details.append(node('div', `Mountpoint: ${mount.mountpoint}`, 'service-meta'));
      row.append(details);
      if (mount.manageable && !data.demo && data.fusermount_available) {
        const actions = node('div', undefined, 'actions');
        const button = node('button', 'Odpojit', 'button button-danger');
        button.type = 'button';
        button.addEventListener('click', () => unmountSSHFS(mount));
        actions.append(button);
        row.append(actions);
      } else row.append(node('div', mount.manageable ? 'Odpojovač nedostupný' : 'Mimo spravovaný kořen', 'service-meta'));
      mountsBox.append(row);
    }
    const mountAllowed = !data.demo && data.sshfs_available && data.fusermount_available && !!data.client_config_path;
    $('#sshfs-mount-form').querySelectorAll('input, select, button').forEach(element => { element.disabled = !mountAllowed; });
  } catch (error) { $('#ssh-note').textContent = error.message; $('#ssh-note').className = 'notice notice-danger'; }
}

$('#sshd-edit').addEventListener('click', () => {
  const path = $('#sshd-edit').dataset.path;
  if (path) openEditor(path);
});
$('#ssh-client-edit').addEventListener('click', () => {
  const path = $('#ssh-client-edit').dataset.path;
  if (path) openEditor(path);
});
$('#sshd-validate').addEventListener('click', async () => {
  try {
    const result = await post('/api/ssh/validate', {});
    toast(result.message || 'Konfigurace sshd je platná.');
  } catch (error) { toast(error.message, true); }
});
$('#sshd-restart').addEventListener('click', () => serviceAction('sshd.sh', 'restart'));

$('#sshfs-mount-form').addEventListener('submit', async event => {
  event.preventDefault();
  const remote = $('#sshfs-remote').value.trim();
  const mountpoint = $('#sshfs-mountpoint').value.trim();
  const identityFile = $('#sshfs-identity').value.trim();
  const mountOptions = $('#sshfs-options').value.trim();
  const portInput = $('#sshfs-port').value.trim();
  const port = portInput ? String(parseInt(portInput, 10)) : 'default';
  const idmap = $('#sshfs-idmap').value;
  const reconnect = $('#sshfs-reconnect').checked;
  const compression = $('#sshfs-compression').checked;
  let confirmText = `MOUNT ${remote} -> ${mountpoint}`;
  confirmText += `\nPort ${port}\nIdmap ${idmap}\nReconnect ${reconnect ? 'yes' : 'no'}\nCompression ${compression ? 'yes' : 'no'}`;
  if (identityFile) confirmText += `\nIdentityFile ${identityFile}`;
  if (mountOptions) confirmText += `\nOptions ${mountOptions.split(',').map(item => item.trim()).join(',')}`;
  if (prompt(`Připojí SSHFS vzdálený zdroj do lokální prázdné složky. Pro potvrzení zadejte přesně:\n${confirmText}`) !== confirmText) return;
  try {
    const result = await post('/api/sshfs/mount', {
      remote, mountpoint, port: portInput || '',
      identity_file: identityFile, mount_options: mountOptions,
      idmap, reconnect, compression,
      confirm: confirmText
    });
    toast(`SSHFS úloha ${result.id} spuštěna.`);
    pollJob(result.id, 'SSHFS mount byl připojen.', loadSSH);
  } catch (error) { toast(error.message, true); }
});

async function unmountSSHFS(mount) {
  const confirmText = `UNMOUNT ${mount.mountpoint}`;
  if (prompt(`Mount bude odpojen ze systému. Pro potvrzení zadejte přesně:\n${confirmText}`) !== confirmText) return;
  try {
    const result = await post('/api/sshfs/unmount', { mountpoint: mount.mountpoint, confirm: confirmText });
    toast(`SSHFS úloha ${result.id} spuštěna.`);
    pollJob(result.id, 'SSHFS mount byl odpojen.', loadSSH);
  } catch (error) { toast(error.message, true); }
}
async function loadCron() {
  const box = $('#cron-info');
  box.replaceChildren();
  try {
    const data = await api('/api/cron');
    for (const [label, value] of [
      ['Crontab dostupný', data.available ? 'Ano' : 'Ne'],
      ['Počet aktivních úloh', String(data.entries)],
      ['Úlohy spravované WebUI', String(data.managed)]
    ]) {
      const card = node('article', undefined, 'card cron-card');
      card.append(node('div', label, 'label'), node('div', value, 'big-status'));
      box.append(card);
    }
    box.append(node('div', data.note, 'notice notice-info'));
  } catch (error) { box.append(node('div', error.message, 'notice notice-danger')); }
  await loadTweaks();
  await loadTweaksCron();
}
async function loadTweaksCron() {
  const note = $('#tweaks-cron-note');
  const textarea = $('#tweaks-cron-entries');
  note.className = 'notice notice-info';
  note.textContent = 'Načítám Tweaks crontab…';
  try {
    const data = await api('/api/tweaks/cron');
    note.className = data.available ? 'notice notice-info' : 'notice notice-warn';
    note.textContent = data.note || 'Stav Tweaks cron není dostupný.';
    $('#tweaks-cron-path').textContent = data.cron_path || data.config_path || 'Trvalá cesta nebyla ověřena.';
    textarea.value = data.entries || '';
    $('#tweaks-cron-enabled').checked = Boolean(data.enabled);
    $('#tweaks-cron-apply').disabled = !data.available;
    textarea.disabled = !data.available;
    $('#tweaks-cron-enabled').disabled = !data.available;
  } catch (error) {
    note.className = 'notice notice-danger';
    note.textContent = error.message;
    $('#tweaks-cron-apply').disabled = true;
    textarea.disabled = true;
    $('#tweaks-cron-enabled').disabled = true;
  }
}
$('#tweaks-cron-refresh').addEventListener('click', loadTweaksCron);
$('#tweaks-cron-apply').addEventListener('click', async () => {
  const confirmText = 'APPLY TWEAKS CRON';
  if (prompt(`Úlohy Tweaks cronu se spouštějí jako root. Změny budou uloženy, zálohovány a ihned předány Tweaks. Pro potvrzení zadejte: ${confirmText}`) !== confirmText) return;
  try {
    const job = await post('/api/tweaks/cron', { entries: $('#tweaks-cron-entries').value, enabled: $('#tweaks-cron-enabled').checked, confirm: confirmText });
    toast(`Tweaks cron se ukládá a aktivuje (úloha ${job.id}).`);
    pollJob(job.id, 'Tweaks cron uložen a aktivován.', loadTweaksCron);
  } catch (error) { toast(error.message, true); }
});
async function loadTweaks() {
  const network = $('#tweaks-network');
  const processes = $('#tweaks-processes');
  network.replaceChildren();
  processes.replaceChildren();
  try {
    const data = await api('/api/tweaks');
    network.append(node('div', data.note || 'Read-only snapshot.', 'muted'));
    if (!data.available) {
      processes.append(node('div', data.note || 'Host data is unavailable.', 'empty-state'));
      return;
    }
    const ips = node('div', undefined, 'tweaks-addresses');
    if (data.ips?.length) data.ips.forEach(ip => ips.append(node('code', ip)));
    else ips.append(node('span', 'Nenalezena žádná adresa.', 'muted'));
    network.append(ips, node('div', `Sockety: ${data.socket_count || 0}`, 'service-meta'));
    if (!data.sockets?.length) network.append(node('div', 'Žádné sockety nebyly načteny.', 'empty-state'));
    for (const socket of data.sockets || []) {
      const row = node('div', undefined, 'tweaks-row');
      row.append(node('strong', `${socket.protocol} ${socket.state}`, 'service-title'));
      row.append(node('code', `${socket.local} ← ${socket.remote}`));
      network.append(row);
    }
    processes.append(node('div', `Procesy: ${data.process_count || 0} · zobrazeno ${data.processes?.length || 0}`, 'service-meta'));
    if (!data.processes?.length) processes.append(node('div', 'Procesní tabulka /proc není dostupná.', 'empty-state'));
    for (const process of data.processes || []) {
      const row = node('div', undefined, 'tweaks-row');
      row.append(node('strong', `${process.name} · PID ${process.pid}`, 'service-title'));
      row.append(node('span', `UID ${process.uid || '?'} · ${process.state || '?'} · ${formatBytes((process.rss_kb || 0) * 1024)}`, 'service-meta'));
      processes.append(row);
    }
  } catch (error) {
    network.append(node('div', error.message, 'notice notice-danger'));
    processes.append(node('div', error.message, 'notice notice-danger'));
  }
}
async function power(action) {
  const confirmText = action === 'restart' ? 'REBOOT NSA320' : 'SHUTDOWN NSA320';
  const verb = action === 'restart' ? 'restart' : 'shutdown';
  if (prompt(`Pro potvrzení akce zadejte přesně:\n${confirmText}`) !== confirmText) return;
  try {
    const data = await post('/api/power', { action: verb, confirm: confirmText });
    toast(data.message || 'Příkaz odeslán.');
  } catch (error) { toast(error.message, true); }
}
$('#power-restart').addEventListener('click', () => power('restart'));
$('#power-shutdown').addEventListener('click', () => power('shutdown'));

$('#firmware-login-form').addEventListener('submit', event => {
  event.preventDefault();
  const username = $('#firmware-username').value;
  const password = $('#firmware-password').value;
  const url = new URL('http://192.168.1.20/r49435,/adv,/cgi-bin/weblogin.cgi');
  url.searchParams.set('username', username);
  url.searchParams.set('password', password);
  const link = node('a');
  link.href = url.toString();
  link.target = '_blank';
  link.rel = 'noopener noreferrer';
  document.body.append(link);
  link.click();
  link.remove();
  $('#firmware-password').value = '';
  toast('Přihlašovací požadavek byl otevřen ve firmwarovém UI.');
});

const terminalSessions = new Map();
let terminalId = '';
let terminalOffset = 0;
let terminalPollTimer = 0;
let terminalKind = 'local';
let terminalSerial = '';
let terminalBuffer = '';
let terminalContext = {};
const ansiColors = ['#1f252a','#c94d4d','#56ad72','#c6a549','#5795d0','#a66ac0','#53aaa8','#d8e0e4'];
function renderTerminalAnsi() {
  const output = $('#terminal-output'); output.replaceChildren();
  let fg = '', bg = '', bold = false, cursor = 0;
  const ansi = /\x1b\[([0-?]*)([ -/]*)([@-~])/g;
  const append = text => {
    if (!text) return;
    const span = document.createElement('span'); span.textContent = text;
    if (fg) span.style.color = fg;
    if (bg) span.style.backgroundColor = bg;
    if (bold) span.style.fontWeight = '700';
    output.append(span);
  };
  let match;
  while ((match = ansi.exec(terminalBuffer))) {
    append(terminalBuffer.slice(cursor, match.index)); cursor = ansi.lastIndex;
    if (match[3] !== 'm') continue;
    const codes = (match[1] || '0').split(';').map(value => Number(value || 0));
    for (const code of codes) {
      if (code === 0) { fg = ''; bg = ''; bold = false; }
      else if (code === 1) bold = true;
      else if (code === 22) bold = false;
      else if (code === 39) fg = '';
      else if (code === 49) bg = '';
      else if (code >= 30 && code <= 37) fg = ansiColors[code - 30];
      else if (code >= 90 && code <= 97) fg = ansiColors[code - 90].replace('#', '#');
      else if (code >= 40 && code <= 47) bg = ansiColors[code - 40];
      else if (code >= 100 && code <= 107) bg = ansiColors[code - 100];
    }
  }
  append(terminalBuffer.slice(cursor).replace(/\x1b\][^\x07]*(?:\x07|\x1b\\)/g, ''));
  output.scrollTop = output.scrollHeight;
}
function appendTerminal(text) {
  terminalBuffer += text;
  if (terminalBuffer.length > 400000) terminalBuffer = '[starší výstup terminálu byl zkrácen]\n' + terminalBuffer.slice(-350000);
  renderTerminalAnsi();
}
function terminalControls(active) {
  const session = terminalSessions.get(terminalId);
  $('#terminal-start').disabled = terminalSessions.size >= 6;
  $('#terminal-close').disabled = !session;
  $('#terminal-input').disabled = !active;
  $('#terminal-form button').disabled = !active;
  const supported = !!session && ['nas','adb','sshfs','sftp'].includes((session.context || {}).source);
  $('#terminal-open-files').disabled = !supported;
  $('#terminal-save-bookmark').disabled = !supported;
}
function terminalSessionTitle(session) {
  const context = session.context || {};
  if (session.kind === 'local') return 'NAS shell';
  if (session.kind === 'adb') return 'ADB · ' + (session.serial || 'zařízení');
  if (context.source === 'sftp') return 'SFTP · ' + (context.remote || 'remote');
  if (context.source === 'sshfs') return 'SSH · ' + (context.mountpoint || context.target || 'mount');
  return 'SSH · ' + (context.target || 'host');
}
function renderTerminalTabs() {
  const box = $('#terminal-tabs'); box.replaceChildren();
  for (const session of terminalSessions.values()) {
    const item = node('div', undefined, 'terminal-tab-item' + (session.id === terminalId ? ' is-active' : ''));
    const tab = node('button', terminalSessionTitle(session) + (session.running ? '' : ' · ukončeno'), 'terminal-tab');
    tab.type = 'button'; tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', session.id === terminalId ? 'true' : 'false');
    tab.addEventListener('click', () => selectTerminal(session.id));
    const close = node('button', '×', 'terminal-tab-close'); close.type = 'button'; close.setAttribute('aria-label', 'Zavřít ' + terminalSessionTitle(session));
    close.addEventListener('click', event => { event.stopPropagation(); closeTerminal(session.id); });
    item.append(tab, close); box.append(item);
  }
  terminalControls(!!terminalSessions.get(terminalId)?.running);
}
function saveActiveTerminal() {
  const session = terminalSessions.get(terminalId);
  if (!session) return;
  session.offset = terminalOffset; session.buffer = terminalBuffer; session.context = terminalContext;
}
function selectTerminal(id) {
  saveActiveTerminal(); clearTimeout(terminalPollTimer);
  const session = terminalSessions.get(id);
  if (!session) return;
  terminalId = id; terminalOffset = session.offset || 0; terminalBuffer = session.buffer || '';
  terminalKind = session.kind; terminalSerial = session.serial || ''; terminalContext = session.context || {};
  $('#terminal-title').textContent = terminalSessionTitle(session);
  renderTerminalAnsi(); renderTerminalTabs();
  $('#terminal-input').focus();
  if (session.running) pollTerminal();
}
async function refreshTerminalTargets() {
  const device = $('#terminal-device'); const selectedDevice = device.value;
  device.replaceChildren(new Option('Vyberte ADB zařízení', ''));
  for (const item of adbKnownDevices.filter(device => device.state === 'device')) device.add(new Option(item.serial, item.serial));
  if ([...device.options].some(option => option.value === selectedDevice)) device.value = selectedDevice;
  const remote = $('#terminal-ssh-remote'); const selectedRemote = remote.value;
  remote.replaceChildren(new Option('Ruční SSH host', ''));
  for (const item of rcloneKnownRemotes.filter(entry => entry.kind === 'sftp')) remote.add(new Option(item.name, item.name));
  if ([...remote.options].some(option => option.value === selectedRemote)) remote.value = selectedRemote;
  $('#terminal-device').hidden = $('#terminal-kind').value !== 'adb';
  $('#terminal-ssh-remote').hidden = $('#terminal-kind').value !== 'ssh';
  $('#terminal-ssh-target').hidden = $('#terminal-kind').value !== 'ssh' || !!remote.value;
}
async function startTerminal(kind = '', serial = '', cwd = '', options = {}) {
  kind = kind || $('#terminal-kind').value || 'local';
  const request = { kind };
  if (kind === 'local') { if (cwd) request.cwd = cwd; }
  else if (kind === 'adb') {
    request.serial = serial || $('#terminal-device').value;
    request.cwd = cwd || '/sdcard';
  } else if (kind === 'ssh') {
    request.remote = options.remote !== undefined ? options.remote : ($('#terminal-ssh-remote').value || '');
    request.target = options.target || $('#terminal-ssh-target').value.trim();
    request.cwd = cwd || '.';
    if (options.sourceContext?.source === 'sshfs') {
      request.panel_source = 'sshfs'; request.mountpoint = options.sourceContext.mountpoint;
      request.panel_path = options.sourceContext.path;
    }
  }
  try {
    const data = await post('/api/terminal/start', request);
    const session = { id: data.id, kind: data.kind || kind, serial: data.serial || request.serial || '',
      context: data.context || {}, offset: data.offset || 0, buffer: '', running: true };
    terminalSessions.set(session.id, session); selectTerminal(session.id); renderTerminalTabs();
  } catch (error) { toast(error.message, true); }
}
async function pollTerminal() {
  if (!terminalId) return;
  const pollingId = terminalId;
  try {
    const query = new URLSearchParams({ id: pollingId, offset: String(terminalOffset) });
    const data = await api(`/api/terminal/read?${query}`);
    if (terminalId !== pollingId) return;
    if (terminalOffset < data.base_offset) appendTerminal('\n[výstup začátku relace byl zkrácen]\n');
    if (data.data) appendTerminal(data.data);
    terminalOffset = data.offset;
    terminalContext = data.context || terminalContext;
    const current = terminalSessions.get(terminalId); if (current) { current.context = terminalContext; current.offset = terminalOffset; current.buffer = terminalBuffer; }
    $('#terminal-open-files').disabled = !['nas','adb','sshfs','sftp'].includes(terminalContext.source);
    $('#terminal-save-bookmark').disabled = !['nas','adb','sshfs','sftp'].includes(terminalContext.source);
    if (!data.running) {
      appendTerminal('\n[relace ukončena]\n');
      if (current) { current.running = false; current.buffer = terminalBuffer; }
      terminalControls(false); renderTerminalTabs();
      return;
    }
  } catch (error) {
    if (terminalId !== pollingId) return;
    appendTerminal(`\n[chyba terminálu: ${error.message}]\n`);
    const current = terminalSessions.get(terminalId); if (current) { current.running = false; current.buffer = terminalBuffer; }
    terminalControls(false); renderTerminalTabs();
    return;
  }
  terminalPollTimer = setTimeout(pollTerminal, document.hidden ? 1500 : 350);
}
async function closeTerminal(id = terminalId) {
  const wasActive = id === terminalId;
  if (wasActive) { saveActiveTerminal(); clearTimeout(terminalPollTimer); }
  terminalSessions.delete(id);
  try { await post('/api/terminal/close', { id }); }
  catch (error) { toast(error.message, true); }
  if (wasActive) {
    terminalId = '';
    const next = [...terminalSessions.values()].slice(-1)[0];
    if (next) selectTerminal(next.id);
    else { terminalOffset = 0; terminalBuffer = ''; terminalContext = {}; $('#terminal-title').textContent = 'Terminál'; $('#terminal-output').textContent = 'Terminál není spuštěn.'; terminalControls(false); }
  }
  renderTerminalTabs();
}
function splitSshfsSource(source) {
  if (typeof source !== 'string') return null;
  let divider = -1;
  if (source.startsWith('[')) { const close = source.indexOf(']'); if (close >= 0 && source[close + 1] === ':') divider = close + 1; }
  if (divider < 0) divider = source.indexOf(':');
  if (divider <= 0) return null;
  return { target: source.slice(0, divider), root: source.slice(divider + 1) || '/' };
}
function joinRemotePath(root, relative) {
  const parts = (String(root || '/') + '/' + String(relative || '')).split('/').filter(Boolean);
  if (parts.some(part => part === '.' || part === '..')) return '';
  return '/' + parts.join('/');
}
async function openTerminalHere(kind, identifier, path) {
  if (kind === 'local') return startTerminal('local', '', path);
  if (kind === 'adb') return startTerminal('adb', identifier, path);
  if (kind === 'sftp') return startTerminal('ssh', '', path, { remote: identifier });
  if (kind === 'sshfs') {
    const mount = sshfsKnownMounts.find(item => item.mountpoint === identifier);
    const split = mount && splitSshfsSource(mount.source);
    if (!mount || !split) return toast('SSHFS mount neobsahuje rozpoznatelný host:/cestu pro SSH terminál.', true);
    const relative = path === identifier ? '' : path.slice(identifier.length).replace(/^\//, '');
    const cwd = joinRemotePath(split.root, relative);
    if (!cwd) return toast('Vzdálená cesta není bezpečně normalizovaná.', true);
    return startTerminal('ssh', '', cwd, { remote: '', target: split.target,
      sourceContext: { source: 'sshfs', mountpoint: identifier, path } });
  }
}
async function openFilesFromTerminal() {
  const session = terminalSessions.get(terminalId); const context = session?.context || terminalContext;
  if (!context) return;
  const state = dualFiles.left;
  if (context.source === 'nas') { state.source = 'nas'; state.path = context.cwd || '/'; }
  else if (context.source === 'adb') { state.source = 'adb'; state.serial = context.serial || session.serial; state.path = context.cwd || '/sdcard'; }
  else if (context.source === 'sftp') { state.source = 'sftp'; state.remote = context.remote; state.path = context.cwd || '/'; }
  else if (context.source === 'sshfs') { state.source = 'sshfs'; state.mountpoint = context.mountpoint; state.path = context.path || context.mountpoint; }
  else return toast('Tento SSH host nemá připojený SFTP/SSHFS zdroj v souborovém panelu.', true);
  state.selected.clear(); refreshFileSources(); setView('files'); await loadDualPanel('left');
}
$('#terminal-start').addEventListener('click', () => startTerminal());
$('#terminal-close').addEventListener('click', closeTerminal);
$('#terminal-kind').addEventListener('change', refreshTerminalTargets);
$('#terminal-ssh-remote').addEventListener('change', refreshTerminalTargets);
$('#terminal-open-files').addEventListener('click', openFilesFromTerminal);
$('#terminal-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = $('#terminal-input');
  if (!terminalId || !input.value) return;
  const data = input.value + '\n';
  input.value = '';
  try { await post('/api/terminal/input', { id: terminalId, data }); }
  catch (error) { toast(error.message, true); }
});
const terminalKeys = {
  f1: '\x1bOP', f2: '\x1bOQ', f3: '\x1bOR', f4: '\x1bOS', f5: '\x1b[15~',
  f6: '\x1b[17~', f7: '\x1b[18~', f8: '\x1b[19~', f9: '\x1b[20~', f10: '\x1b[21~',
  up: '\x1b[A', down: '\x1b[B', right: '\x1b[C', left: '\x1b[D',
  home: '\x1b[H', end: '\x1b[F', enter: '\r', tab: '\t', esc: '\x1b'
};
const terminalModifiers = { ctrl: false, shift: false };
let terminalModifierInputStart = 0;
async function sendTerminalShortcut(data) {
  if (!terminalId) return toast('Nejprve spusťte terminál.', true);
  try { await post('/api/terminal/input', { id: terminalId, data }); }
  catch (error) { toast(error.message, true); }
}
$$('[data-terminal-key]').forEach(button => button.addEventListener('click', () => sendTerminalShortcut(terminalKeys[button.dataset.terminalKey])));
$$('[data-terminal-modifier]').forEach(button => button.addEventListener('click', () => {
  const key = button.dataset.terminalModifier; terminalModifiers[key] = !terminalModifiers[key];
  terminalModifierInputStart = $('#terminal-input').value.length;
  button.classList.toggle('is-active', terminalModifiers[key]); button.setAttribute('aria-pressed', String(terminalModifiers[key]));
  $('#terminal-input').focus();
}));
$('#terminal-input').addEventListener('keydown', event => {
  if (terminalModifiers.ctrl && event.key.length === 1) {
    event.preventDefault(); const code = event.key.toUpperCase().charCodeAt(0);
    if (code >= 64 && code <= 95) sendTerminalShortcut(String.fromCharCode(code - 64));
    terminalModifiers.ctrl = false; $('[data-terminal-modifier="ctrl"]').classList.remove('is-active');
    $('[data-terminal-modifier="ctrl"]').setAttribute('aria-pressed', 'false');
  } else if (terminalModifiers.shift && event.key.length === 1) {
    event.preventDefault(); const input = $('#terminal-input'); input.value += event.key.toUpperCase();
    terminalModifiers.shift = false; $('[data-terminal-modifier="shift"]').classList.remove('is-active');
    $('[data-terminal-modifier="shift"]').setAttribute('aria-pressed', 'false');
  } else if (terminalModifiers.shift && event.key === 'Enter') {
    event.preventDefault(); sendTerminalShortcut('\r'); terminalModifiers.shift = false;
    $('[data-terminal-modifier="shift"]').classList.remove('is-active');
    $('[data-terminal-modifier="shift"]').setAttribute('aria-pressed', 'false');
  }
});
$('#terminal-input').addEventListener('input', event => {
  const input = event.currentTarget; const added = input.value.slice(terminalModifierInputStart);
  if (!added) return;
  if (terminalModifiers.ctrl) {
    const char = added.slice(-1).toUpperCase().charCodeAt(0);
    input.value = input.value.slice(0, terminalModifierInputStart);
    if (char >= 64 && char <= 95) sendTerminalShortcut(String.fromCharCode(char - 64));
    terminalModifiers.ctrl = false; $('[data-terminal-modifier="ctrl"]').classList.remove('is-active');
    $('[data-terminal-modifier="ctrl"]').setAttribute('aria-pressed', 'false');
  } else if (terminalModifiers.shift) {
    input.value = input.value.slice(0, terminalModifierInputStart) + added.toUpperCase();
    terminalModifiers.shift = false; $('[data-terminal-modifier="shift"]').classList.remove('is-active');
    $('[data-terminal-modifier="shift"]').setAttribute('aria-pressed', 'false');
  }
});



let adbSelectedSerial = '';
let adbEditorTarget = null;
let adbAppCacheOnly = false;
let adbApps = [];
function adbQuery(params) { return new URLSearchParams(params).toString(); }
function adbSetControls(enabled) {
  $('#adb-connect-form').querySelectorAll('input,button').forEach(el => { el.disabled = !enabled; });
  $('#adb-server-restart').disabled = !enabled;
}
function selectAdbForPanel(side, serial) {
  dualFiles[side].source = 'adb'; dualFiles[side].serial = serial; dualFiles[side].path = '/sdcard';
  refreshFileSources(); loadDualPanel(side);
  setView('files');
}
async function loadAdb() {
  const note = $('#adb-note'); const box = $('#adb-devices');
  try {
    const data = await api('/api/adb');
    const enabled = data.available && !data.demo;
    adbSetControls(enabled); adbKnownDevices = data.devices || []; refreshFileSources(); refreshTerminalTargets();
    refreshAdbScreenDevices(enabled);
    note.className = data.error ? 'notice notice-warn' : 'notice notice-info';
    note.textContent = data.error || (enabled ? `ADB nalezen: ${data.binary}` : 'ADB není v demo režimu dostupný.');
    const appDevice = $('#adb-app-device'); const savedSerial = appDevice.value;
    appDevice.replaceChildren(new Option('Vyberte zařízení', ''));
    for (const device of adbKnownDevices.filter(item => item.state === 'device')) appDevice.add(new Option(device.serial, device.serial));
    if ([...appDevice.options].some(option => option.value === savedSerial)) appDevice.value = savedSerial;
    box.replaceChildren();
    if (!adbKnownDevices.length) box.append(node('div', 'Nejsou připojena žádná ADB zařízení.', 'empty-state'));
    if (adbSelectedSerial && !adbKnownDevices.some(device => device.serial === adbSelectedSerial && device.state === 'device')) adbSelectedSerial = '';
    for (const device of adbKnownDevices) {
      const row = node('div', undefined, `adb-device-row ${device.state === 'device' ? 'adb-online' : 'adb-offline'}`);
      const details = node('div', undefined, 'sshfs-details');
      details.append(node('div', `${device.serial} · ${device.state}`, 'service-title'));
      if (device.details) details.append(node('div', device.details, 'service-meta'));
      const actions = node('div', undefined, 'actions');
      const openWeb = node('button', 'Otevřít WebUI v zařízení', 'button button-primary'); openWeb.type = 'button'; openWeb.disabled = !enabled || device.state !== 'device';
      openWeb.addEventListener('click', async () => { try { const job = await post('/api/adb/open-webui', { serial: device.serial }); toast(`Otevírám FFP WebUI na ${device.serial}.`); pollJob(job.id, 'WebUI bylo otevřeno na zařízení.'); } catch (error) { toast(error.message, true); } });
      const panelA = node('button', 'Použít v panelu A', 'button'); panelA.type = 'button'; panelA.disabled = !enabled || device.state !== 'device'; panelA.addEventListener('click', () => selectAdbForPanel('left', device.serial));
      const panelB = node('button', 'Použít v panelu B', 'button'); panelB.type = 'button'; panelB.disabled = !enabled || device.state !== 'device'; panelB.addEventListener('click', () => selectAdbForPanel('right', device.serial));
      const appButton = node('button', 'Správa aplikací', 'button'); appButton.type = 'button'; appButton.disabled = !enabled || device.state !== 'device'; appButton.addEventListener('click', () => { appDevice.value = device.serial; loadAdbApps(); });
      const shellButton = node('button', 'ADB shell', 'button'); shellButton.type = 'button'; shellButton.disabled = !enabled || device.state !== 'device'; shellButton.addEventListener('click', () => { setView('terminal'); startTerminal('adb', device.serial); });
      const screenButton = node('button', 'Zrcadlit obrazovku', 'button'); screenButton.type = 'button'; screenButton.disabled = !enabled || device.state !== 'device'; screenButton.addEventListener('click', () => { $('#adb-screen-device').value = device.serial; startAdbScreen(); });
      const rebootMode = node('select', undefined, 'adb-reboot-mode');
      for (const [value, label] of [['system', 'Android / system'], ['recovery', 'Recovery'], ['bootloader', 'Bootloader'], ['fastboot', 'Fastboot / fastbootd']]) rebootMode.add(new Option(label, value));
      rebootMode.disabled = !enabled || device.state !== 'device';
      const rebootButton = node('button', 'Restartovat do režimu', 'button button-warning'); rebootButton.type = 'button'; rebootButton.disabled = !enabled || device.state !== 'device';
      rebootButton.addEventListener('click', async () => {
        const mode = rebootMode.value;
        const phrase = `REBOOT ${mode.toUpperCase()} ${device.serial}`;
        if (prompt(`Zařízení ${device.serial} se restartuje do režimu ${rebootMode.selectedOptions[0]?.textContent}. Pro potvrzení zadejte přesně: ${phrase}`) !== phrase) return;
        try { const job = await post('/api/adb/reboot', { serial: device.serial, mode, confirm: phrase }); toast(`Restart zařízení spuštěn (úloha ${job.id}).`); pollJob(job.id, 'ADB zařízení bylo restartováno.', loadAdb); }
        catch (error) { toast(error.message, true); }
      });
      const disconnect = node('button', 'Odpojit', 'button button-danger'); disconnect.type = 'button'; disconnect.disabled = !enabled || device.state !== 'device'; disconnect.addEventListener('click', () => disconnectAdb(device.serial));
      actions.append(openWeb, panelA, panelB, appButton, shellButton, screenButton, rebootMode, rebootButton, disconnect);
      row.append(details, actions); box.append(row);
    }
    if (adbSelectedSerial) adbSetControls(enabled);
  } catch (error) { note.className = 'notice notice-danger'; note.textContent = error.message; adbSetControls(false); refreshAdbScreenDevices(false); box.replaceChildren(node('div', 'Stav ADB se nepodařilo načíst.', 'empty-state')); }
}
async function disconnectAdb(serial) {
  try {
    await post('/api/adb/disconnect', { serial });
    if (adbSelectedSerial === serial) adbSelectedSerial = '';
    for (const side of ['left','right']) if (dualFiles[side].serial === serial) { dualFiles[side].source = 'nas'; dualFiles[side].serial = ''; dualFiles[side].path = '/'; }
    toast(`ADB odpojeno: ${serial}`); await loadAdb(); await loadDualFiles();
  } catch (error) { toast(error.message, true); }
}
async function loadAdbApps() {
  const serial = $('#adb-app-device').value; const box = $('#adb-app-list'); const note = $('#adb-apps-note');
  adbSelectedSerial = serial; box.replaceChildren();
  if (!serial) { note.className = 'notice notice-info'; note.textContent = 'Vyberte připojené zařízení.'; box.textContent = 'Načtěte seznam aplikací.'; return; }
  note.className = 'notice notice-info'; note.textContent = 'Načítám balíčky z Androidu…'; box.append(node('div', 'Načítám…', 'empty-state'));
  try {
    const data = await api('/api/adb/apps?' + adbQuery({ serial }));
    adbApps = data.apps || []; adbAppCacheOnly = Boolean(data.cache_only_supported);
    note.className = data.available ? 'notice notice-info' : 'notice notice-warn';
    note.textContent = `${data.note || ''} · ${adbApps.length} aplikací.`;
    renderAdbApps();
  } catch (error) { note.className = 'notice notice-danger'; note.textContent = error.message; box.replaceChildren(); }
}
function renderAdbApps() {
  const box = $('#adb-app-list'); box.replaceChildren();
  const query = $('#adb-app-search').value.trim().toLowerCase(); const filter = $('#adb-app-filter').value;
  const rows = adbApps.filter(app => (!query || app.package.toLowerCase().includes(query) || app.apk_path.toLowerCase().includes(query)) && (filter === 'all' || filter === app.type || filter === app.state));
  if (!rows.length) { box.append(node('div', adbApps.length ? 'Filtr nic nenašel.' : 'Seznam aplikací je prázdný.', 'empty-state')); return; }
  for (const app of rows) {
    const row = node('article', undefined, `adb-app-row adb-app-${app.type}`);
    const info = node('div', undefined, 'adb-app-info');
    info.append(node('strong', app.package, 'adb-app-package'));
    info.append(node('span', `${app.type === 'system' ? 'Systémová' : app.type === 'user' ? 'Uživatelská' : 'Neznámý typ'} · ${app.state === 'enabled' ? 'Povoleno' : app.state === 'disabled' ? 'Vypnuto' : 'Stav neznámý'}`, `badge ${app.state === 'enabled' ? 'badge-green' : app.state === 'disabled' ? 'badge-red' : 'badge-neutral'}`));
    if (app.apk_path) info.append(node('code', app.apk_path, 'adb-app-path'));
    const actions = node('div', undefined, 'actions');
    for (const [action,label,klass] of [['start','Spustit','button'],['stop','Zastavit','button button-quiet'],[app.state === 'disabled' ? 'unfreeze' : 'freeze',app.state === 'disabled' ? 'Povolit' : 'Vypnout','button button-quiet'],['clear-cache','Vymazat cache','button button-quiet'],['clear-data','Vymazat data','button button-warning'],['uninstall','Odinstalovat','button button-danger']]) {
      const button = node('button', label, klass); button.type = 'button'; if (action === 'clear-cache' && !adbAppCacheOnly) button.disabled = true;
      button.addEventListener('click', () => adbAppAction(app, action)); actions.append(button);
    }
    const apk = node('a', 'Stáhnout APK', 'button button-quiet'); apk.href = `/api/adb/apps/apk?${adbQuery({ serial: $('#adb-app-device').value, package: app.package })}`; apk.setAttribute('download', `${app.package}.apk`); actions.append(apk);
    row.append(info, actions); box.append(row);
  }
}
async function adbAppAction(app, action) {
  const serial = $('#adb-app-device').value; const labels = { start: 'START APP', stop: 'STOP APP', freeze: 'FREEZE APP', unfreeze: 'UNFREEZE APP', uninstall: 'UNINSTALL APP', 'clear-cache': 'CLEAR APP CACHE', 'clear-data': 'CLEAR APP DATA' };
  const confirmText = `${labels[action]} ${app.package}`;
  const explanation = action === 'clear-data' ? 'Tato akce odstraní data aplikace.' : action === 'uninstall' && app.type === 'system' ? 'Systémový balíček zůstane v obrazu ROM; odebere se pouze uživateli 0.' : 'Akce změní stav aplikace v Androidu.';
  if (prompt(`${explanation}\n\nPro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
  try { const job = await post('/api/adb/apps/action', { serial, package: app.package, action, confirm: confirmText }); toast(`ADB ${action} spuštěno (úloha ${job.id}).`); pollJob(job.id, `Akce dokončena: ${app.package}`, loadAdbApps); }
  catch (error) { toast(error.message, true); }
}
$('#adb-app-device').addEventListener('change', loadAdbApps);
$('#adb-apps-refresh').addEventListener('click', loadAdbApps);
$('#adb-app-search').addEventListener('input', renderAdbApps);
$('#adb-app-filter').addEventListener('change', renderAdbApps);
$('#adb-app-install-form').addEventListener('submit', async event => {
  event.preventDefault(); const serial = $('#adb-app-device').value; const file = $('#adb-app-apk').files[0];
  if (!serial || !file) return toast('Vyberte připojené zařízení a APK soubor.', true);
  const confirmText = `INSTALL APK ${file.name} ON ${serial}`;
  if (prompt(`Instalace APK ${file.name} do zařízení ${serial}. Pro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
  const query = adbQuery({ serial, filename: file.name, confirm: confirmText });
  try { const job = await api('/api/adb/apps/install?' + query, { method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file, timeoutMs: 0 }); event.currentTarget.reset(); toast(`Instalace spuštěna (úloha ${job.id}).`); pollJob(job.id, 'APK nainstalováno.', loadAdbApps); }
  catch (error) { toast(error.message, true); }
});
$('#adb-refresh').addEventListener('click', loadAdb);
$('#adb-server-restart').addEventListener('click', async () => {
  if (!confirm('Restartovat ADB server na NASu? Připojené relace se mohou na chvíli přerušit.')) return;
  try { const result = await post('/api/adb/server', { action: 'restart', confirm: 'RESTART ADB SERVER' }); toast(result.message || 'ADB server restartován.'); await loadAdb(); } catch (error) { toast(error.message, true); }
});
$('#adb-connect-form').addEventListener('submit', async event => {
  event.preventDefault(); const pairingCode = $('#adb-pair-code').value;
  try { await post('/api/adb/connect', { pair_endpoint: $('#adb-pair-endpoint').value.trim(), pairing_code: pairingCode, endpoint: $('#adb-connect-endpoint').value.trim() }); toast('ADB připojení dokončeno.'); await loadAdb(); }
  catch (error) { toast(error.message, true); } finally { $('#adb-pair-code').value = ''; }
});
async function openAdbEditor(path, serial) {
  try { const data = await api(`/api/adb/file?${adbQuery({ serial, path })}`); adbEditorTarget = { serial: data.serial, path: data.path }; $('#adb-editor-title').textContent = data.path; $('#adb-editor-content').value = data.content; $('#adb-editor-dialog').showModal(); }
  catch (error) { toast(error.message, true); }
}
$('#adb-editor-save').addEventListener('click', async () => {
  if (!adbEditorTarget) return;
  const confirmText = `SAVE ${adbEditorTarget.path}`;
  if (prompt(`Změní vzdálený soubor. Pro potvrzení zadejte přesně: ${confirmText}`) !== confirmText) return;
  try { await post('/api/adb/save', { ...adbEditorTarget, content: $('#adb-editor-content').value, confirm: confirmText }); $('#adb-editor-dialog').close(); toast('Soubor v Android zařízení uložen.'); await loadDualFiles(); }
  catch (error) { toast(error.message, true); }
});
$('#adb-editor-dialog').addEventListener('close', () => { adbEditorTarget = null; $('#adb-editor-content').value = ''; });

async function refreshView(name) {
  if (name === 'overview') return loadOverview();
  if (name === 'services') return loadServices();
  if (name === 'luanti') return loadLuanti();
  if (name === 'environment') return loadEnv();
  if (name === 'users') return loadUsers();
  if (name === 'packages') return Promise.all([loadPackages(), loadZypkg()]);
  if (name === 'files') {
    await Promise.all([loadSSH(), loadAdb(), loadRcloneRemotes()]);
    return loadFiles();
  }
  if (name === 'ssh') return loadSSH();
  if (name === 'cron') return loadCron();
  if (name === 'adb') return loadAdb();
}
async function initial() { await Promise.all([loadOverview(), checkBackendVersion()]); }
initial();

let adbScreenAvailable = false;
let adbScreenActive = false;
let adbScreenSerial = '';
let adbScreenTimer = null;
let adbScreenGeneration = 0;
let adbScreenRequestInFlight = false;
let adbScreenObjectUrl = '';
let adbScreenPointer = null;
const ADB_SCREEN_POLL_MS = 1000;
function updateAdbScreenControls() {
  const selected = $('#adb-screen-device').value;
  $('#adb-screen-device').disabled = !adbScreenAvailable || adbScreenActive;
  $('#adb-screen-start').disabled = !adbScreenAvailable || adbScreenActive || !selected;
  $('#adb-screen-stop').disabled = !adbScreenActive;
  $$('[data-adb-screen-key]').forEach(button => { button.disabled = !adbScreenActive; });
  $('#adb-screen-text').disabled = !adbScreenActive;
  $('#adb-screen-text-form button').disabled = !adbScreenActive;
}
function refreshAdbScreenDevices(enabled) {
  const select = $('#adb-screen-device');
  if (!select) return;
  const previous = select.value || adbScreenSerial;
  adbScreenAvailable = !!enabled;
  select.replaceChildren(new Option('Vyberte připojené zařízení', ''));
  const connected = adbKnownDevices.filter(device => device.state === 'device');
  for (const device of connected) select.add(new Option(device.serial, device.serial));
  if (connected.some(device => device.serial === previous)) select.value = previous;
  else if (adbScreenActive) {
    stopAdbScreen(true);
    $('#adb-screen-note').className = 'notice notice-warn';
    $('#adb-screen-note').textContent = 'Vybrané ADB zařízení již není připojeno.';
  }
  updateAdbScreenControls();
}
function stopAdbScreen(clearFrame = false) {
  const wasActive = adbScreenActive;
  adbScreenActive = false;
  adbScreenGeneration += 1;
  if (adbScreenTimer) clearTimeout(adbScreenTimer);
  adbScreenTimer = null;
  adbScreenPointer = null;
  updateAdbScreenControls();
  if (wasActive) {
    $('#adb-screen-note').className = 'notice notice-info';
    $('#adb-screen-note').textContent = 'Zrcadlení zastaveno. Poslední snímek zůstává zobrazený, dokud stránku neopustíte.';
  }
  if (clearFrame) {
    const image = $('#adb-screen-image');
    image.removeAttribute('src');
    image.hidden = true;
    $('#adb-screen-placeholder').hidden = false;
    $('#adb-screen-stage').hidden = true;
    if (adbScreenObjectUrl) URL.revokeObjectURL(adbScreenObjectUrl);
    adbScreenObjectUrl = '';
  }
}
function startAdbScreen() {
  const serial = $('#adb-screen-device').value;
  if (!serial || !adbScreenAvailable) return toast('Vyberte připojené ADB zařízení.', true);
  adbScreenSerial = serial;
  adbScreenActive = true;
  adbScreenStageStart();
}
function adbScreenStageStart() {
  const serial = adbScreenSerial;
  if (!serial || !adbScreenActive) return;
  if (adbScreenTimer) clearTimeout(adbScreenTimer);
  adbScreenGeneration += 1;
  const generation = adbScreenGeneration;
  $('#adb-screen-stage').hidden = false;
  $('#adb-screen-placeholder').hidden = false;
  $('#adb-screen-image').hidden = true;
  $('#adb-screen-note').className = 'notice notice-info';
  $('#adb-screen-note').textContent = `Připojuji se k ${serial}…`;
  updateAdbScreenControls();
  loadAdbScreenFrame(generation);
}
async function loadAdbScreenFrame(generation) {
  if (!adbScreenActive || generation !== adbScreenGeneration || currentView !== 'adb' || document.hidden || adbScreenRequestInFlight) return;
  adbScreenRequestInFlight = true;
  try {
    const response = await fetch(`/api/adb/screen?${adbQuery({ serial: adbScreenSerial, t: Date.now() })}`, { cache: 'no-store' });
    if (!response.ok) {
      let data = {};
      try { data = await response.json(); } catch (_) {}
      throw new Error(data.error || `HTTP ${response.status}`);
    }
    if (!(response.headers.get('content-type') || '').toLowerCase().startsWith('image/png')) throw new Error('Server nevrátil PNG snímek.');
    const blob = await response.blob();
    if (!blob.size || blob.size > 16 * 1024 * 1024) throw new Error('Snímek je prázdný nebo překračuje limit 16 MiB.');
    if (!adbScreenActive || generation !== adbScreenGeneration) return;
    const image = $('#adb-screen-image');
    const previousUrl = adbScreenObjectUrl;
    adbScreenObjectUrl = URL.createObjectURL(blob);
    image.onload = () => {
      $('#adb-screen-placeholder').hidden = true;
      $('#adb-screen-note').className = 'notice notice-info';
      $('#adb-screen-note').textContent = `Živě: ${adbScreenSerial} · ${image.naturalWidth} × ${image.naturalHeight} px · přibližně 1 snímek/s`;
      if (previousUrl) URL.revokeObjectURL(previousUrl);
    };
    image.onerror = () => {
      if (adbScreenObjectUrl) URL.revokeObjectURL(adbScreenObjectUrl);
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      adbScreenObjectUrl = '';
      if (adbScreenActive && generation === adbScreenGeneration) {
        stopAdbScreen(false);
        $('#adb-screen-note').className = 'notice notice-danger';
        $('#adb-screen-note').textContent = 'Prohlížeč nedokázal dekódovat PNG snímek.';
      }
    };
    image.src = adbScreenObjectUrl;
    image.hidden = false;
    $('#adb-screen-stage').hidden = false;
  } catch (error) {
    if (adbScreenActive && generation === adbScreenGeneration) {
      stopAdbScreen(false);
      $('#adb-screen-note').className = 'notice notice-danger';
      $('#adb-screen-note').textContent = `Zrcadlení selhalo: ${error.message}`;
    }
  } finally {
    adbScreenRequestInFlight = false;
    if (adbScreenActive && currentView === 'adb' && !document.hidden) {
      const nextGeneration = adbScreenGeneration;
      adbScreenTimer = setTimeout(() => loadAdbScreenFrame(nextGeneration), ADB_SCREEN_POLL_MS);
    }
  }
}
async function sendAdbScreenInput(payload) {
  if (!adbScreenActive) return;
  try {
    await post('/api/adb/screen/input', { serial: adbScreenSerial, ...payload });
    return true;
  } catch (error) {
    toast(error.message, true);
    return false;
  }
}
$('#adb-screen-start').addEventListener('click', startAdbScreen);
$('#adb-screen-stop').addEventListener('click', () => stopAdbScreen());
$('#adb-screen-device').addEventListener('change', () => {
  if (adbScreenActive) stopAdbScreen();
  adbScreenSerial = $('#adb-screen-device').value;
  updateAdbScreenControls();
});
$$('[data-adb-screen-key]').forEach(button => button.addEventListener('click', () => sendAdbScreenInput({ action: 'key', key: button.dataset.adbScreenKey })));
$('#adb-screen-text-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = $('#adb-screen-text');
  if (!input.value) return;
  if (await sendAdbScreenInput({ action: 'text', text: input.value })) input.value = '';
});
$('#adb-screen-image').addEventListener('pointerdown', event => {
  if (!adbScreenActive || !event.currentTarget.naturalWidth) return;
  event.preventDefault();
  adbScreenPointer = { id: event.pointerId, x: event.clientX, y: event.clientY, started: Date.now() };
  try { event.currentTarget.setPointerCapture(event.pointerId); } catch (_) {}
});
$('#adb-screen-image').addEventListener('pointerup', event => {
  const start = adbScreenPointer;
  adbScreenPointer = null;
  if (!start || start.id !== event.pointerId || !adbScreenActive) return;
  const image = event.currentTarget;
  const rect = image.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const point = (x, y) => ({
    x: Math.max(0, Math.min(image.naturalWidth - 1, Math.round((x - rect.left) * image.naturalWidth / rect.width))),
    y: Math.max(0, Math.min(image.naturalHeight - 1, Math.round((y - rect.top) * image.naturalHeight / rect.height)))
  });
  const from = point(start.x, start.y);
  const to = point(event.clientX, event.clientY);
  if (Math.hypot(event.clientX - start.x, event.clientY - start.y) < 8) {
    sendAdbScreenInput({ action: 'tap', x: to.x, y: to.y });
  } else {
    sendAdbScreenInput({ action: 'swipe', x1: from.x, y1: from.y, x2: to.x, y2: to.y, duration_ms: Math.max(80, Math.min(1000, Date.now() - start.started)) });
  }
});
$('#adb-screen-image').addEventListener('pointercancel', () => { adbScreenPointer = null; });
document.addEventListener('visibilitychange', () => {
  if (!document.hidden && adbScreenActive && currentView === 'adb') {
    if (adbScreenTimer) clearTimeout(adbScreenTimer);
    adbScreenTimer = null;
    loadAdbScreenFrame(adbScreenGeneration);
  }
});
window.addEventListener('pagehide', () => stopAdbScreen(true));
updateAdbScreenControls();
