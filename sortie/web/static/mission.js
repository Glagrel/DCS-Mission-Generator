// SORTIE GUI: ATO & briefing, mission generation, live feed, debrief.
(function () {
  const esc = SORTIE.esc, api = SORTIE.api, $ = (s) => document.querySelector(s);
  const base = () => `/api/campaigns/${SORTIE.cid}`;
  const hms = (s) => { s = Math.max(0, Math.round(s || 0)); return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor(s % 3600 / 60)).padStart(2, '0')}`; };
  const freq = (f) => (f ? f.toFixed(3) + ' AM' : '-');

  function briefingHtml(b) {
    if (!b.assigned) return `<div class="panel"><h2>No sortie this cycle</h2><p class="warn">${esc(b.reason)}</p>
      <p><button id="btn-skip">Stand down and advance the war one cycle</button></p></div>`;
    const f = b.flight, th = b.threats;
    return `<div class="panel"><h2>Your tasking: ${esc(b.mission)} &mdash; ${esc(b.target.name)}</h2>
      <p><b>Why you:</b> ${esc(b.reason)}</p><p><b>Objective:</b> ${esc(b.objective)}</p>
      <table>
        <tr><td>Flight</td><td><b>${esc(f.callsign)}</b> &middot; ${f.count} &times; ${esc(f.aircraft)} &middot; ${esc(f.squadron)} from ${esc(f.base)}</td></tr>
        <tr><td>Package</td><td>${esc(b.package.id)} (${esc(b.package.mission)})</td></tr>
        <tr><td>Time on target</td><td><b>${esc(b.tot)}</b>${b.target.bullseye ? ' &middot; target bullseye ' + esc(b.target.bullseye) : ''}</td></tr>
        <tr><td>Radio</td><td>${freq(f.freq)}</td></tr>
        <tr><td>Loadout</td><td>${f.stores.length ? f.stores.map(esc).join(', ') : '<span class="dim">' + (f.loadout ? esc(f.loadout) : 'no stock loadout known - arm on the ramp') + '</span>'}</td></tr>
        <tr><td>Escort</td><td>${b.escort.length ? b.escort.map(esc).join(', ') : 'none'}</td></tr>
        <tr><td>SEAD support</td><td>${b.sead.length ? b.sead.map(esc).join(', ') : 'none'}</td></tr>
        <tr><td>Tanker</td><td>${b.tankers.length ? b.tankers.map((t) => `${esc(t.callsign)} ${esc(t.aircraft)} ${freq(t.freq)} TACAN ${esc(t.tacan || '-')}`).join('<br>') : 'none'}</td></tr>
        <tr><td>AWACS / GCI</td><td>${b.awacs.length ? b.awacs.map((a) => `${esc(a.callsign)} ${esc(a.aircraft)} ${freq(a.freq)}`).join('<br>') : (b.gci ? 'GCI ' + freq(b.gci.freq) : 'none')}</td></tr>
        <tr><td>Home base stocks</td><td>munitions ${SORTIE.pct(b.base_status.munitions)}, runway ${SORTIE.pct(b.base_status.runway)}, fuel ${(b.base_status.fuel_jet_t + b.base_status.fuel_avgas_t).toFixed(0)} t</td></tr>
      </table>
      <h3>Package</h3><table><tr><th>Callsign</th><th>Aircraft</th><th>Task</th><th>Squadron</th><th>Freq</th></tr>
      ${b.package.flights.map((r) => `<tr class="${r.player ? 'me' : ''}"><td>${esc(r.callsign)}</td><td>${r.count} &times; ${esc(r.aircraft)}</td><td>${r.task}</td><td>${esc(r.squadron)}</td><td>${freq(r.freq)}</td></tr>`).join('')}</table>
      <h3>Route</h3><table><tr><th>#</th><th>Waypoint</th><th>Time</th><th>Altitude</th><th>Speed</th><th>Position</th></tr>
      ${b.waypoints.map((w, i) => `<tr><td>${i}</td><td>${esc(w.name)}</td><td>${esc(w.time)}</td><td>${w.alt_m.toFixed(0)} m</td><td>${w.speed_kmh.toFixed(0)} km/h</td><td class="dim">${w.lat.toFixed(3)}, ${w.lon.toFixed(3)}</td></tr>`).join('')}</table>
      <h3>Threats</h3>
      ${th.sams.length ? `<table><tr><th>System</th><th>Site</th><th>Range</th><th>From route</th></tr>${th.sams.slice(0, 10).map((s) => `<tr><td>${esc(s.type)}</td><td>${esc(s.name)}</td><td>${s.range_km} km</td><td class="${s.inside ? 'red' : ''}">${s.dist_km} km${s.inside ? ' - route inside ring' : ''}</td></tr>`).join('')}</table>` : '<p class="dim">No known air defences near the route.</p>'}
      ${th.air.length ? '<p><b>Expected air opposition:</b> ' + th.air.slice(0, 6).map((a) => `${a.count} &times; ${esc(a.aircraft)} (${a.task}) near ${esc(a.near)}`).join('; ') + '</p>' : '<p class="dim">No enemy fighters expected near the route.</p>'}
      <p class="row"><button class="primary" id="btn-gen2">Generate Next Mission</button><button id="btn-skip">Skip this sortie (resolve abstractly)</button></p>
      <div id="gen-result"></div></div>`;
  }

  SORTIE.pages.ato = async function () {
    const [b, ato] = await Promise.all([api('GET', base() + '/briefing'), api('GET', base() + '/ato')]);
    await SORTIE.refreshBar();
    $('#tab-ato').innerHTML = `<div class="cols2"><div>${briefingHtml(b)}</div>
      <div class="panel"><h2>Air Tasking Order &mdash; cycle ${ato.turn}</h2>
      <p class="dim">You do not pick missions. The ATO is built from the state of the war; priority and reason are shown for every package.</p>
      <table><tr><th>Pkg</th><th>Mission</th><th>Target</th><th>TOT</th><th>Prio</th><th>Flights</th></tr>
      ${ato.packages.map((p) => `<tr class="${p.player ? 'me' : ''}" title="${esc(p.reason)}"><td>${esc(p.id)}</td><td>${p.mission}</td><td>${esc(p.target)}<div class="dim">${esc(p.reason)}</div></td><td>+${hms(p.tot_s)}</td><td>${p.score.toFixed(0)}</td>
        <td>${p.flights.map((f) => `<span class="tag ${f.player ? 'me' : ''}">${f.count}&times;${esc(f.aircraft)} ${f.task}</span>`).join('')}</td></tr>`).join('')}</table></div></div>`;
    const g = $('#btn-gen2'); if (g) g.onclick = () => SORTIE.generate();
    const s = $('#btn-skip'); if (s) s.onclick = () => SORTIE.skip();
    if (SORTIE.lastBuild && SORTIE.lastBuild.cid === SORTIE.cid && SORTIE.lastBuild.turn === ato.turn) showBuild(SORTIE.lastBuild.res);
  };

  function showBuild(r) {
    const box = $('#gen-result'); if (!box) return;
    box.innerHTML = `<h3>Mission generated</h3><p class="ok"><b>${esc(r.filename)}</b></p><p class="path">${esc(r.path)}</p>
      <p>${r.stats.aircraft} aircraft in ${r.stats.flights} flights, ${r.stats.ground_groups} ground groups, ${r.stats.static_groups} structures, ${r.stats.naval_groups} naval groups &middot; profile ${esc(r.stats.profile)} &middot; ${r.stats.coop_slots > 1 ? r.stats.coop_slots + ' client slots (co-op)' : 'single player'} &middot; ${r.stats.size_kb} kB</p>
      ${r.warnings.length ? '<p class="warn">' + r.warnings.map(esc).join('<br>') + '</p>' : ''}
      <p class="dim">In DCS: Mission &rarr; My Missions &rarr; SORTIE, fly it, then come back to Live Mission / Debrief.</p>`;
  }

  SORTIE.generate = async function () {
    if (!SORTIE.cid) return;
    SORTIE.notice('Generating mission...');
    try {
      const r = await api('POST', base() + '/mission');
      SORTIE.lastBuild = { cid: SORTIE.cid, turn: r.briefing.turn, res: r };
      SORTIE.notice('Mission written to ' + r.path, 'good');
      await SORTIE.show('ato');
    } catch (e) { SORTIE.notice('Mission generation FAILED: ' + e.message, 'err'); }
  };

  SORTIE.skip = async function () {
    if (!confirm('Stand down this cycle? The whole ATO is resolved without you and the war advances.')) return;
    try { SORTIE.debriefData = await api('POST', base() + '/skip'); await SORTIE.refreshBar(); SORTIE.show('debrief'); }
    catch (e) { SORTIE.notice(e.message, 'err'); }
  };

  // ---- Live mission feed ------------------------------------------------------------------------
  SORTIE.pages.live = async function () {
    $('#tab-live').innerHTML = `<div class="cols2"><div class="panel"><h2>Live mission feed</h2>
      <p class="dim" id="live-status">Waiting for events...</p><div class="feed" id="live-feed"></div></div>
      <div class="panel"><h2>Situation</h2><div id="live-snap" class="dim">No snapshot yet.</div>
      <h3>After landing</h3><p>When you are back (or have left the aircraft), end the mission in DCS and press:</p>
      <p><button class="primary" id="btn-debrief">End sortie &amp; debrief</button></p></div></div>`;
    $('#btn-debrief').onclick = () => SORTIE.runDebrief();
    SORTIE.liveLines = [];
    if (SORTIE.liveTimer) clearInterval(SORTIE.liveTimer);
    const poll = async () => {
      if (SORTIE.tab !== 'live') { clearInterval(SORTIE.liveTimer); SORTIE.liveTimer = null; return; }
      try {
        const d = await api('GET', base() + '/live');
        $('#live-status').innerHTML = (d.exists ? `<span class="ok">Event file found</span>` : `<span class="warn">No event file yet</span>`) +
          ` &middot; ${d.count} events for this sortie${d.malformed ? ' &middot; ' + d.malformed + ' malformed lines skipped' : ''}<br><span class="path">${esc(d.file)}</span>`;
        d.events.forEach((e) => SORTIE.liveLines.push(e));
        const feed = $('#live-feed');
        feed.innerHTML = SORTIE.liveLines.slice(-300).reverse().map((e) => `<div class="${e.side || ''}">${esc(e.clock)} ${e.player ? '&#9733; ' : ''}${esc(e.text)}</div>`).join('') || '<div class="dim">Nothing yet. Start the mission in DCS.</div>';
        if (d.snapshot) {
          const c = d.snapshot.counts || {};
          const row = (s) => c[s] ? `<tr><td>${SORTIE.side(s)}</td><td>${c[s].air || 0}</td><td>${c[s].helo || 0}</td><td>${c[s].ground || 0}</td><td>${c[s].ship || 0}</td></tr>` : '';
          $('#live-snap').innerHTML = `<table><tr><th>Side</th><th>Aircraft</th><th>Helos</th><th>Ground units</th><th>Ships</th></tr>${row('blue')}${row('red')}</table>` +
            (d.snapshot.players || []).map((p) => `<p>&#9733; ${esc(p.p || 'player')} in ${esc(p.ty || '')} ${p.air ? 'airborne' : 'on the ground'}</p>`).join('');
        }
      } catch (e) { $('#live-status').textContent = e.message; }
    };
    await poll();
    SORTIE.liveTimer = setInterval(poll, 2000);
  };

  SORTIE.runDebrief = async function () {
    try { SORTIE.debriefData = await api('POST', base() + '/debrief'); await SORTIE.refreshBar(); SORTIE.notice(''); SORTIE.show('debrief'); }
    catch (e) { SORTIE.notice(e.message, 'err'); }
  };

  // ---- Debrief ----------------------------------------------------------------------------------
  SORTIE.pages.debrief = async function () {
    const d = SORTIE.debriefData && SORTIE.debriefData.turn ? SORTIE.debriefData : await api('GET', base() + '/debrief');
    SORTIE.debriefData = null;
    if (!d || !d.turn) { $('#tab-debrief').innerHTML = '<div class="panel"><h2>Debrief</h2><p class="dim">No sortie has been debriefed yet. Fly the generated mission, then use Live Mission &rarr; End sortie &amp; debrief.</p></div>'; return; }
    const p = d.player || {}, w = d.war || {}, air = w.air || {}, pilot = d.pilot || {};
    const outcome = d.state === 'skipped' ? '<span class="dim">Stood down</span>' : d.mission_success ? '<span class="ok">MISSION SUCCESS</span>' : '<span class="red">MISSION FAILED</span>';
    const flights = Object.entries(d.flights || {}).map(([id, f]) => `<tr><td>${esc(id)}</td><td>${f.lost}</td><td>${f.pilots_lost}</td><td>${f.kills_air}</td><td>${f.kills_ground + f.kills_structure}</td><td>${f.kills_naval}</td><td>${SORTIE.pct(f.success)}</td></tr>`).join('');
    const fronts = Object.entries((w.ground || {}).fronts || {}).map(([id, f]) => `<div>${esc(id)}: ${SORTIE.pct(f.from)} &rarr; ${SORTIE.pct(f.to)} (${f.to > f.from ? 'blue advance' : f.to < f.from ? 'red advance' : 'static'})</div>`).join('');
    const repl = Object.entries((w.replacements || {}).airframes || {}).map(([k, v]) => `${esc(k)} +${v}`).join(', ');
    $('#tab-debrief').innerHTML = `<div class="cols2"><div>
      <div class="panel"><h2>Debrief &mdash; cycle ${d.turn}</h2><p class="big">${outcome}</p>
        ${d.task ? `<p>${esc(d.task)} on ${esc(d.target || '')}</p>` : ''}
        ${d.state !== 'skipped' ? `<table>
          <tr><td>Flight time</td><td>${((d.flight_time_s || 0) / 3600).toFixed(2)} h</td></tr>
          <tr><td>Your kills</td><td>air ${p.kills_air || 0} &middot; ground ${p.kills_ground || 0} &middot; naval ${p.kills_naval || 0} &middot; structures ${p.kills_structure || 0}</td></tr>
          <tr><td>Aircraft</td><td>${p.landed ? '<span class="ok">landed' + (p.landed_at ? ' at ' + esc(p.landed_at) : '') + '</span>' : p.ejected ? '<span class="red">lost - ejected</span>' : p.crashed ? '<span class="red">lost - crashed</span>' : p.took_off ? '<span class="warn">did not land</span>' : '<span class="dim">never took off</span>'}</td></tr>
          <tr><td>Pilot status</td><td>${esc((p.career_status || pilot.status || '').toUpperCase())}</td></tr>
          ${p.career_promoted ? `<tr><td>Promotion</td><td class="ok">Promoted to ${esc(p.career_promoted)}</td></tr>` : ''}
          ${(p.career_awards || []).length ? `<tr><td>Awards</td><td class="ok">${p.career_awards.map(esc).join(', ')}</td></tr>` : ''}
          <tr><td>Aircraft lost in your mission</td><td>${SORTIE.side('blue')} ${(d.summary.aircraft_lost || {}).blue || 0} &middot; ${SORTIE.side('red')} ${(d.summary.aircraft_lost || {}).red || 0}</td></tr></table>` : ''}
        ${d.transfer ? `<p class="warn"><b>New orders:</b> transferred to ${esc(d.transfer.to)} (${esc(d.transfer.aircraft)}). ${esc(d.transfer.reason)}</p>` : ''}
        <p>Next: cycle ${d.next.turn}, ${esc(d.next.date.replace('T', ' ').slice(0, 16))}${d.next.status !== 'active' ? ' &mdash; <b>CAMPAIGN ' + d.next.status.toUpperCase() + '</b>' : ''}
        <button onclick="SORTIE.show('ato')">See next assignment</button></p></div>
      ${flights ? `<div class="panel"><h2>Flights simulated in DCS</h2><table><tr><th>Flight</th><th>Lost</th><th>Pilots lost</th><th>Air kills</th><th>Ground</th><th>Naval</th><th>Success</th></tr>${flights}</table></div>` : ''}
      <div class="panel"><h2>Campaign consequences</h2>
        ${(d.summary.consequences || []).length ? d.summary.consequences.map((c) => `<div>&bull; ${esc(c)}</div>`).join('') : '<p class="dim">No lasting damage from your mission.</p>'}
        <h3>Rest of the war this cycle</h3>
        <table><tr><th>Side</th><th>Sorties</th><th>Aircraft lost</th><th>Air kills</th><th>Ground/structure kills</th></tr>
        ${['blue', 'red'].map((s) => air[s] ? `<tr><td>${SORTIE.side(s)}</td><td>${air[s].sorties}</td><td>${air[s].lost}</td><td>${air[s].kills_air}</td><td>${air[s].kills_ground + air[s].kills_structure}</td></tr>` : '').join('')}</table>
        <h3>Front lines</h3>${fronts || '<p class="dim">-</p>'}
        ${((w.ground || {}).captured || []).length ? '<p class="warn">Captured: ' + w.ground.captured.map(esc).join(', ') + '</p>' : ''}
        <h3>Replacements</h3><p>${repl || '<span class="dim">none</span>'}</p>
        ${(d.summary.warehouse_notes || []).length ? '<h3>Warehouse readback</h3>' + d.summary.warehouse_notes.map((n) => `<div>${esc(n)}</div>`).join('') : ''}</div></div>
      <div class="panel"><h2>Mission timeline</h2><div class="feed">${(d.timeline || []).map((e) => `<div class="${e.side || ''}">${esc(e.clock)} ${e.player ? '&#9733; ' : ''}${esc(e.text)}</div>`).join('') || '<div class="dim">No events.</div>'}</div></div></div>`;
  };
})();
