const app = document.querySelector('#app');
const keyInput = document.querySelector('#api-key');
keyInput.value = sessionStorage.getItem('gateway-api-key') || '';
keyInput.addEventListener('change', () => sessionStorage.setItem('gateway-api-key', keyInput.value));

async function api(path, options = {}) {
  const response = await fetch(`/v1${path}`, { ...options, headers: { Authorization: `Bearer ${keyInput.value}`, 'Content-Type': 'application/json', ...(options.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error?.message || `Request failed (${response.status})`);
  return response.json();
}
const escape = (value) => String(value ?? '').replace(/[&<>"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[char]);
function error(error) { app.innerHTML = `<p class="error">${escape(error.message)}. Enter an API key with the required scope.</p>`; }

async function overview() {
  const [health, adapters] = await Promise.all([api('/health'), api('/adapters')]);
  app.innerHTML = `<div class="header"><h1>Overview</h1></div><div class="grid"><section class="card"><h2>Gateway</h2><p class="ok">${escape(health.status || 'healthy')}</p></section><section class="card"><h2>Adapters</h2><p>${adapters.adapters.length} configured</p></section></div>`;
}
async function connections() {
  const data = await api('/adapter-instances');
  app.innerHTML = `<div class="header"><h1>Connections</h1><button id="add">Add connection</button></div><table><thead><tr><th>ID</th><th>Type</th><th>Source</th><th>State</th><th></th></tr></thead><tbody>${data.instances.map(item => `<tr><td>${escape(item.id)}</td><td>${escape(item.type)}</td><td>${escape(item.source)}</td><td>${escape(item.state || (item.enabled ? 'configured' : 'disabled'))}</td><td><button data-lifecycle="start" data-id="${escape(item.id)}">Start</button> <button data-lifecycle="stop" data-id="${escape(item.id)}">Stop</button> <button data-lifecycle="restart" data-id="${escape(item.id)}">Restart</button> <button data-auth="${escape(item.id)}">Authentication</button> ${item.source === 'managed' ? `<button data-delete="${escape(item.id)}">Delete</button>` : 'Read-only'}</td></tr>`).join('')}</tbody></table>`;
  document.querySelector('#add').onclick = addConnection;
  document.querySelectorAll('[data-lifecycle]').forEach(button => button.onclick = async () => { await api(`/adapters/${button.dataset.id}/${button.dataset.lifecycle}`, { method: 'POST' }); connections(); });
  document.querySelectorAll('[data-auth]').forEach(button => button.onclick = () => showAuth(button.dataset.auth));
  document.querySelectorAll('[data-delete]').forEach(button => button.onclick = async () => { await api(`/adapter-instances/${button.dataset.delete}`, { method: 'DELETE' }); connections(); });
}
async function showAuth(adapterId) {
  const dialog = document.createElement('dialog');
  dialog.innerHTML = `<form method="dialog"><h2>Authentication: ${escape(adapterId)}</h2><p id="auth-status">Loading…</p><div id="auth-challenge"></div><menu><button id="auth-cancel" type="button">Cancel authentication</button><button id="auth-start" type="button">Start authentication</button><button>Close</button></menu></form>`;
  document.body.append(dialog); dialog.showModal();
  const render = info => { dialog.querySelector('#auth-status').textContent = info.status + (info.reason ? `: ${info.reason}` : ''); const challenge = info.challenge; dialog.querySelector('#auth-challenge').innerHTML = challenge ? `${challenge.qr_uri ? `<img alt="Authentication QR code" src="${escape(challenge.qr_uri)}">` : ''}<p>${escape(challenge.instructions || '')}</p><code>${escape(challenge.verification_code || '')}</code>` : ''; };
  const refresh = async () => render(await api(`/adapters/${adapterId}/auth`));
  dialog.querySelector('#auth-start').onclick = async () => { render(await api(`/adapters/${adapterId}/auth/start`, { method: 'POST' })); };
  dialog.querySelector('#auth-cancel').onclick = async () => { render(await api(`/adapters/${adapterId}/auth/cancel`, { method: 'POST' })); };
  dialog.addEventListener('close', () => dialog.remove()); await refresh();
}
async function addConnection() {
  const catalog = await api('/adapter-types');
  const choices = catalog.adapter_types.map(item => `<option value="${escape(item.type)}">${escape(item.name)}</option>`).join('');
  app.insertAdjacentHTML('beforeend', `<dialog open><form method="dialog"><h2>Add connection</h2><label>ID <input name="id" required pattern="[A-Za-z0-9_-]+"></label><label>Type <select name="type">${choices}</select></label><label>Configuration (JSON) <textarea name="config" rows="8">{}</textarea></label><p class="error" id="form-error"></p><menu><button value="cancel">Cancel</button><button value="save">Save</button></menu></form></dialog>`);
  const dialog = document.querySelector('dialog'); dialog.querySelector('form').addEventListener('submit', async event => { if (event.submitter.value !== 'save') return; event.preventDefault(); const form = new FormData(event.currentTarget); try { await api('/adapter-instances', { method: 'POST', body: JSON.stringify({ id: form.get('id'), type: form.get('type'), enabled: true, config: JSON.parse(form.get('config')) }) }); dialog.close(); dialog.remove(); connections(); } catch (err) { dialog.querySelector('#form-error').textContent = err.message; } });
}
async function agents() {
  const data = await api('/agents');
  app.innerHTML = `<div class="header"><h1>Agents</h1><button id="enroll">Create enrollment</button></div><table><thead><tr><th>Name</th><th>Status</th><th>Scopes</th><th></th></tr></thead><tbody>${data.agents.map(agent => `<tr><td>${escape(agent.display_name)}</td><td>${escape(agent.status)}</td><td>${escape(agent.scopes.join(', '))}</td><td><button data-revoke="${escape(agent.id)}">Revoke</button></td></tr>`).join('')}</tbody></table>`;
  document.querySelector('#enroll').onclick = async () => { const result = await api('/agent-enrollments', { method: 'POST', body: JSON.stringify({ name_hint: 'External Agent', scopes: ['events:read', 'commands:send'] }) }); const dialog = document.createElement('dialog'); dialog.innerHTML = `<form method="dialog"><h2>Agent setup package</h2><p>Save this one-time token in the Agent environment; do not put it in a cloud-model prompt.</p><label>Enrollment token <textarea readonly rows="2">${escape(result.token)}</textarea></label><label>Environment command <textarea readonly rows="3">export GATEWAY_URL=${location.origin}\nexport GATEWAY_ENROLLMENT_TOKEN=${escape(result.token)}</textarea></label><label>Bootstrap prompt <textarea readonly rows="6">Register yourself with the current AstrBot-Gateway. Gateway URL is in GATEWAY_URL and the one-time token is in GATEWAY_ENROLLMENT_TOKEN. Read /.well-known/astrbot-gateway, register, configure Bridge/MCP, run doctor, then report heartbeat. Do not modify Gateway source code.</textarea></label><menu><button>Done</button></menu></form>`; document.body.append(dialog); dialog.showModal(); dialog.addEventListener('close', () => dialog.remove()); };
  document.querySelectorAll('[data-revoke]').forEach(button => button.onclick = async () => { await api(`/agents/${button.dataset.revoke}/revoke`, { method: 'POST' }); agents(); });
}
async function endpoints() { const data = await api('/discovery'); app.innerHTML = `<h1>Endpoints</h1><pre>${escape(JSON.stringify(data.endpoints, null, 2))}</pre>`; }
async function system() { const data = await api('/health'); app.innerHTML = `<h1>System</h1><pre>${escape(JSON.stringify(data, null, 2))}</pre>`; }
const pages = { '/overview': overview, '/connections': connections, '/agents': agents, '/endpoints': endpoints, '/system': system };
async function route() { try { await (pages[location.hash.slice(1)] || overview)(); } catch (err) { error(err); } }
addEventListener('hashchange', route); route();
