// SORTIE GUI core: API helper, tabs, campaign list, career wizard, settings.
const SORTIE = { cid: localStorage.getItem('sortie.cid') || null, pages: {}, overview: null, tab: 'home' };

SORTIE.api = async function (method, url, body) {
  const res = await fetch(url, {
    method, headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) throw new Error((data && data.detail) || res.statusText);
  return data;
};
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
SORTIE.esc = esc;
SORTIE.pct = (x) => Math.round((x || 0) * 100) + '%';
SORTIE.meter = (x) => `<div class="meter ${x < 0.3 ? 'low' : x < 0.6 ? 'mid' : ''}"><div style="width:${Math.max(0, Math.min(100, x * 100))}%"></div></div>`;
SORTIE.side = (s) => `<span class="${s}">${s === 'blue' ? 'BLUE' : 'RED'}</span>`;

SORTIE.notice = function (text, kind) {
  const n = $('#notice');
  if (!text) { n.hidden = true; return; }
  n.hidden = false; n.className = kind || ''; n.textContent = text;
};

SORTIE.show = async function (tab) {
  SORTIE.tab = tab;
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  document.querySelectorAll('main > section').forEach((s) => { s.hidden = s.id !== 'tab-' + tab; });
  try { if (SORTIE.pages[tab]) await SORTIE.pages[tab](); } catch (e) { SORTIE.notice(e.message, 'err'); }
};

SORTIE.checkStale = async function () {
  try {
    const s = await SORTIE.api('GET', '/api/status');
    if (s.restart_needed) SORTIE.notice('SORTIE has been updated on disk. Close the SORTIE window and start it again so the new version is used.', 'err');
  } catch (e) { /* server not reachable: the page itself will say so */ }
};

SORTIE.refreshBar = async function () {
  const bar = $('#campaign-bar'), gen = $('#btn-generate');
  document.querySelectorAll('#tabs button[data-needs]').forEach((b) => { b.disabled = !SORTIE.cid; });
  if (!SORTIE.cid) { bar.innerHTML = '<span>No campaign selected</span>'; gen.hidden = true; SORTIE.overview = null; return; }
  try {
    const o = SORTIE.overview = await SORTIE.api('GET', `/api/campaigns/${SORTIE.cid}/overview`);
    const p = o.pilot || {}, sq = o.squadron || {};
    bar.innerHTML = `<span><b>${esc(o.meta.name)}</b></span><span>Cycle <b>${o.meta.turn}</b> &middot; ${esc(o.meta.date.replace('T', ' ').slice(0, 16))}</span>` +
      `<span>${esc(p.rank || '')} <b>${esc(p.callsign || '')}</b> (${esc(p.status || '')})</span>` +
      `<span>${esc(sq.name || '-')} &middot; <b>${esc(sq.aircraft || '-')}</b></span>` +
      `<span>War: <b>${o.meta.status === 'active' ? (o.meta.war_score > 0 ? '+' : '') + o.meta.war_score : o.meta.status.toUpperCase()}</b></span>`;
    gen.hidden = o.meta.status !== 'active';
  } catch (e) {
    SORTIE.cid = null; localStorage.removeItem('sortie.cid'); bar.textContent = 'No campaign selected'; gen.hidden = true;
  }
};

SORTIE.select = async function (cid) {
  SORTIE.cid = cid;
  if (cid) localStorage.setItem('sortie.cid', cid); else localStorage.removeItem('sortie.cid');
  await SORTIE.refreshBar();
};

// ---- Campaigns + wizard ------------------------------------------------------------------
SORTIE.pages.home = async function () {
  const [list, theaters, status] = await Promise.all([
    SORTIE.api('GET', '/api/campaigns'), SORTIE.api('GET', '/api/theaters'), SORTIE.api('GET', '/api/status')]);
  SORTIE.theaters = theaters;
  const rows = list.map((c) => `<tr class="${c.id === SORTIE.cid ? 'me' : ''}"><td>${esc(c.name)}<div class="dim path">id ${esc(c.id)}</div></td>
    <td class="dim">${new Date(c.updated * 1000).toLocaleString()}</td>
    <td><button onclick="SORTIE.select('${c.id}').then(()=>SORTIE.show('ato'))">Open</button>
        <button class="danger" onclick="SORTIE.removeCampaign('${c.id}')">Delete</button></td></tr>`).join('');
  $('#tab-home').innerHTML = `
    <div class="cols2">
      <div class="panel"><h2>Your campaigns</h2>
        ${list.length ? `<table><tr><th>Campaign</th><th>Last played</th><th></th></tr>${rows}</table>` : '<p class="dim">No campaigns yet. Start a career on the right.</p>'}
        <h3>Environment</h3>
        <table>
          <tr><td>Saved Games</td><td class="path">${esc(status.saved_games || 'not found')}</td></tr>
          <tr><td>DCS install</td><td class="path">${esc(status.dcs_install || 'not found - loadouts will be empty')}</td></tr>
          <tr><td>Missions written to</td><td class="path">${esc(status.output_dir)}</td></tr>
          <tr><td>RAM / profile</td><td>${status.ram_gb} GB &rarr; ${esc(status.profile)}</td></tr>
          <tr><td>MOOSE</td><td class="${status.moose ? 'ok' : 'warn'}">${status.moose ? 'found' : 'missing (run tools\\fetch_moose.py)'}</td></tr>
        </table></div>
      <div class="panel"><h2>New career</h2><div id="wizard"></div></div>
    </div>`;
  SORTIE.wizard(status);
};

SORTIE.removeCampaign = async function (cid) {
  if (!confirm('Delete this campaign permanently?')) return;
  await SORTIE.api('DELETE', '/api/campaigns/' + cid);
  if (cid === SORTIE.cid) await SORTIE.select(null);
  SORTIE.show('home');
};

SORTIE.wizard = function (status) {
  const w = $('#wizard'), T = SORTIE.theaters;
  const st = SORTIE.wz = SORTIE.wz || { theater: T[0] && T[0].id, side: 'blue', squadron: null, callsign: 'Rookie', difficulty: 'normal', profile: 'auto' };
  const t = T.find((x) => x.id === st.theater) || T[0];
  if (!t) { w.innerHTML = '<p class="warn">No theater templates found in data/theaters.</p>'; return; }
  const side = t.sides[st.side];
  const playable = side.squadrons.filter((s) => s.playable);
  if (!playable.find((s) => s.id === st.squadron)) st.squadron = playable[0] ? playable[0].id : null;
  const sq = side.squadrons.find((s) => s.id === st.squadron);
  w.innerHTML = `
    <label>Theater</label><select id="wz-theater">${T.map((x) => `<option value="${x.id}" ${x.id === t.id ? 'selected' : ''}>${esc(x.name)} (${x.year})</option>`).join('')}</select>
    <p class="dim">${esc(t.description)}</p>
    ${t.terrain_fallback ? '<p class="warn">This terrain is not available in pydcs; a stand-in map is used (see docs/DECISIONS.md).</p>' : ''}
    ${!t.terrain_supported ? '<p class="red">Terrain not supported: missions cannot be generated.</p>' : ''}
    <label>Side</label><select id="wz-side">${['blue', 'red'].map((s) => `<option value="${s}" ${s === st.side ? 'selected' : ''}>${esc(t.sides[s].name)}</option>`).join('')}</select>
    <label>Squadron and aircraft (only modules you own, flyable and in era)</label>
    <select id="wz-squadron">${playable.map((s) => `<option value="${s.id}" ${s.id === st.squadron ? 'selected' : ''}>${esc(s.name)} - ${esc(s.aircraft)} (${s.airframes} aircraft)</option>`).join('')}</select>
    ${playable.length ? '' : '<p class="warn">No squadron on this side flies a module you own. Check Settings &rarr; Owned modules.</p>'}
    ${sq ? `<p class="dim">Roles: ${sq.tasks.map((x) => `<span class="tag">${x}</span>`).join('')}<br>You will not choose your missions: the ATO tasks this squadron each cycle.</p>` : ''}
    <label>Callsign</label><input type="text" id="wz-callsign" value="${esc(st.callsign)}" maxlength="24">
    <div class="row"><div style="flex:1"><label>Difficulty</label><select id="wz-difficulty">${status.difficulties.map((x) => `<option ${x === st.difficulty ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
    <div style="flex:1"><label>Performance profile</label><select id="wz-profile">${['auto', 'light', 'standard', 'heavy'].map((x) => `<option value="${x}" ${x === st.profile ? 'selected' : ''}>${x === 'auto' ? 'auto (' + status.profile_auto + ', ' + status.ram_gb + ' GB RAM)' : x}</option>`).join('')}</select></div></div>
    <p><button class="primary" id="wz-go" ${sq && t.terrain_supported ? '' : 'disabled'}>Start career</button></p>`;
  const bind = (id, key, redraw) => { $(id).onchange = (e) => { st[key] = e.target.value; if (redraw) SORTIE.wizard(status); }; };
  bind('#wz-theater', 'theater', true); bind('#wz-side', 'side', true); bind('#wz-squadron', 'squadron', true);
  bind('#wz-callsign', 'callsign'); bind('#wz-difficulty', 'difficulty'); bind('#wz-profile', 'profile');
  $('#wz-go').onclick = async () => {
    try {
      const r = await SORTIE.api('POST', '/api/campaigns', {
        theater_id: t.id, side: st.side, squadron_id: st.squadron, aircraft: sq.aircraft,
        callsign: $('#wz-callsign').value || 'Rookie', difficulty: st.difficulty, profile: st.profile,
        seed: Math.floor(Math.random() * 1e6) });
      await SORTIE.select(r.id); SORTIE.notice('Career started. Your first tasking is on the ATO page.', 'good');
      SORTIE.show('ato');
    } catch (e) { SORTIE.notice(e.message, 'err'); }
  };
};

// ---- Settings --------------------------------------------------------------------------------
SORTIE.pages.settings = async function () {
  const [s, status, mods] = await Promise.all([
    SORTIE.api('GET', '/api/settings'), SORTIE.api('GET', '/api/status'), SORTIE.api('GET', '/api/modules')]);
  const prof = status.profiles;
  $('#tab-settings').innerHTML = `
    <div class="cols2"><div>
      <div class="panel"><h2>Paths</h2>
        <label>DCS Saved Games folder (blank = auto-detect)</label><input type="text" id="st-sg" value="${esc(s.saved_games || '')}" placeholder="${esc(status.saved_games || 'not found')}">
        <label>DCS install folder (blank = auto-detect)</label><input type="text" id="st-inst" value="${esc(s.dcs_install || '')}" placeholder="${esc(status.dcs_install || 'not found')}">
        <label>Mission output folder (blank = &lt;Saved Games&gt;\\Missions\\SORTIE)</label><input type="text" id="st-out" value="${esc(s.output_dir || '')}" placeholder="${esc(status.output_dir)}">
        <p class="dim">Detected: Saved Games <span class="path">${esc(status.saved_games || '-')}</span><br>Install <span class="path">${esc(status.dcs_install || '-')}</span><br>Event file <span class="path">${esc(status.events_file)}</span></p></div>
      <div class="panel"><h2>Performance</h2>
        <p>Installed RAM: <b>${status.ram_gb} GB</b> &rarr; automatic profile <b>${esc(status.profile_auto)}</b></p>
        <label>Profile</label><select id="st-profile">${['auto', 'light', 'standard', 'heavy'].map((x) => `<option ${x === s.profile ? 'selected' : ''}>${x}</option>`).join('')}</select>
        <table style="margin-top:8px"><tr><th>Profile</th><th>AI aircraft</th><th>Ground groups</th><th>Naval</th><th>Bubble km</th><th>Spawn/despawn km</th></tr>
        ${Object.keys(prof).map((k) => `<tr class="${k === status.profile ? 'me' : ''}"><td>${k}</td><td>${prof[k].max_air}</td><td>${prof[k].max_ground_groups}</td><td>${prof[k].max_naval_groups}</td><td>${prof[k].bubble_km}</td><td>${prof[k].spawn_km} / ${prof[k].despawn_km}</td></tr>`).join('')}</table>
        <p class="dim">Numbers are starting guesses; tune them in config/defaults.yaml.</p>
        <label>Units shown in briefings, kneeboards and this GUI</label>
        <select id="st-units">${['imperial', 'metric'].map((x) => `<option ${x === s.units ? 'selected' : ''}>${x}</option>`).join('')}</select></div>
      <div class="panel"><h2>Co-op / multiplayer</h2>
        <label>Seats in your own flight (1 = single player, 2-4 = friends fly as your wingmen)</label><input type="number" id="st-coop" min="1" max="4" value="${s.coop_slots}">
        <label>Extra pilots flying their own aircraft in other flights of the mission (0-12)</label><input type="number" id="st-extra" min="0" max="12" value="${s.coop_extra_slots}">
        <p class="dim">Each extra pilot gets a wingman seat in another friendly flight that departs during the mission, in an aircraft from the list below. The ATO still decides what those flights do. A seat nobody takes simply does not spawn and costs the campaign nothing.</p>
        <label><input type="checkbox" id="st-coopall" ${s.coop_modules === null ? 'checked' : ''}> Extra pilots may fly any flyable aircraft (untick to choose)</label>
        <div class="checks" id="st-coopmods" style="margin-top:6px;${s.coop_modules === null ? 'display:none' : ''}">${mods.map((m) => `<label><input type="checkbox" class="st-cmod" value="${esc(m.id)}" ${(s.coop_modules || []).includes(m.id) ? 'checked' : ''}> ${esc(m.id)}</label>`).join('')}</div>
        <h3>Dedicated server</h3>
        <label><input type="checkbox" id="st-srvon" ${s.save_to_server ? 'checked' : ''}> Also save each mission into the server's Missions\\SORTIE folder</label>
        <label>Server Saved Games folder</label><input type="text" id="st-srv" value="${esc(s.server_saved_games || '')}" placeholder="${esc((status.server_candidates || [])[0] || 'e.g. C:\\Users\\you\\Saved Games\\DCS.server1')}">
        ${(status.server_candidates || []).length ? '<p class="dim">Found: ' + status.server_candidates.map((c) => `<a href="#" class="st-srvpick">${esc(c)}</a>`).join(', ') + '</p>' : ''}
        <p class="dim">Events are read from whichever of these the mission writes to:<br>${(status.event_files || []).map((f) => `<span class="path">${esc(f)}</span>`).join('<br>')}</p></div>
      <div class="panel"><h2>ATC / GCI / voice (optional, default off)</h2>
        <label><input type="checkbox" id="st-atc" ${s.atc_enabled ? 'checked' : ''}> Enable ATC/GCI layer (needs MOOSE in the mission)</label>
        <label>Voice engine (via MOOSE MSRS + SimpleRadio Standalone; text messages are always shown)</label>
        <select id="st-voice">${status.voices.map((x) => `<option ${x === s.voice ? 'selected' : ''}>${x}</option>`).join('')}</select>
        <label>SRS install folder</label><input type="text" id="st-srs" value="${esc(s.srs_path)}">
        <label>SRS port</label><input type="number" id="st-srsport" value="${s.srs_port}">
        <label>Piper voice model (.onnx path or name)</label><input type="text" id="st-piper" value="${esc(s.piper_voice)}">
        <label>Google credentials JSON path</label><input type="text" id="st-google" value="${esc(s.google_credentials)}"></div>
    </div><div class="panel"><h2>Owned modules</h2>
      <p class="dim">Tick the aircraft you own. Careers, transfers and reassignments only ever use ticked modules.</p>
      <div class="row"><button id="st-all">All</button><button id="st-none">None</button></div>
      <div class="checks" style="margin-top:8px">${mods.map((m) => `<label><input type="checkbox" class="st-mod" value="${esc(m.id)}" ${m.owned ? 'checked' : ''}> ${esc(m.id)} <span class="dim">${m.year}</span></label>`).join('')}</div>
    </div></div>
    <p><button class="primary" id="st-save">Save settings</button></p>`;
  const boxes = () => Array.from(document.querySelectorAll('.st-mod'));
  $('#st-coopall').onchange = (e) => { $('#st-coopmods').style.display = e.target.checked ? 'none' : ''; };
  document.querySelectorAll('.st-srvpick').forEach((a) => { a.onclick = (e) => { e.preventDefault(); $('#st-srv').value = a.textContent; $('#st-srvon').checked = true; }; });
  $('#st-all').onclick = () => boxes().forEach((b) => { b.checked = true; });
  $('#st-none').onclick = () => boxes().forEach((b) => { b.checked = false; });
  $('#st-save').onclick = async () => {
    try {
      await SORTIE.api('PUT', '/api/settings', {
        saved_games: $('#st-sg').value.trim(), dcs_install: $('#st-inst').value.trim(), output_dir: $('#st-out').value.trim(),
        profile: $('#st-profile').value, coop_slots: parseInt($('#st-coop').value, 10) || 1,
        coop_extra_slots: parseInt($('#st-extra').value, 10) || 0, units: $('#st-units').value,
        coop_modules: $('#st-coopall').checked ? null : Array.from(document.querySelectorAll('.st-cmod')).filter((b) => b.checked).map((b) => b.value),
        save_to_server: $('#st-srvon').checked, server_saved_games: $('#st-srv').value.trim(),
        atc_enabled: $('#st-atc').checked, voice: $('#st-voice').value, srs_path: $('#st-srs').value,
        srs_port: parseInt($('#st-srsport').value, 10) || 5002, piper_voice: $('#st-piper').value,
        google_credentials: $('#st-google').value, owned_modules: boxes().filter((b) => b.checked).map((b) => b.value) });
      SORTIE.notice('Settings saved.', 'good'); SORTIE.pages.settings();
    } catch (e) { SORTIE.notice(e.message, 'err'); }
  };
};

SORTIE.start = async function () {
  document.querySelectorAll('#tabs button').forEach((b) => { b.onclick = () => { SORTIE.notice(''); SORTIE.show(b.dataset.tab); }; });
  $('#btn-generate').onclick = () => SORTIE.generate();
  await SORTIE.refreshBar();
  await SORTIE.show(SORTIE.cid ? 'ato' : 'home');
  SORTIE.checkStale();
};
