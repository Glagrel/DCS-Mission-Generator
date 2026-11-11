// SORTIE GUI pages: map, squadrons, pilot, logistics.
(function () {
  const esc = SORTIE.esc, api = SORTIE.api, $ = (s) => document.querySelector(s);
  const COL = { blue: '#4c9be8', red: '#e0564f' };
  const base = () => `/api/campaigns/${SORTIE.cid}`;

  // ---- Map ---------------------------------------------------------------------------------
  SORTIE.pages.map = async function () {
    const d = await api('GET', base() + '/map');
    if (typeof L === 'undefined') {
      $('#map').innerHTML = '<p style="padding:16px" class="warn">Leaflet could not be loaded (no internet?). ' +
        'The map needs https://unpkg.com/leaflet once; all other pages work offline.</p>';
      return;
    }
    if (!SORTIE.map) {
      SORTIE.map = L.map('map', { preferCanvas: true });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 12, attribution: '&copy; OpenStreetMap' }).addTo(SORTIE.map);
      SORTIE.layers = L.layerGroup().addTo(SORTIE.map);
    }
    const g = SORTIE.layers; g.clearLayers();
    const pts = [];
    const dot = (lat, lon, color, r, html, fill) => { pts.push([lat, lon]); return L.circleMarker([lat, lon], { radius: r, color, weight: 2, fillColor: fill || color, fillOpacity: 0.85 }).bindPopup(html).addTo(g); };
    d.routes.forEach((r) => L.polyline(r.line, { color: COL[r.coalition], weight: r.kind === 'rail' ? 3 : 2, opacity: 0.35 + 0.4 * (1 - r.interdiction), dashArray: r.kind === 'sea' ? '2 8' : r.kind === 'rail' ? '10 6' : null })
      .bindPopup(`Supply route (${r.kind})<br>capacity ${r.capacity} t/cycle<br>interdiction ${SORTIE.pct(r.interdiction)}`).addTo(g));
    d.sams.forEach((s) => {
      if (s.health < 0.1) return;
      if (s.role !== 'ewr') L.circle([s.lat, s.lon], { radius: s.range_km * 1000, color: COL[s.coalition], weight: 1, fillOpacity: 0.06, dashArray: s.role === 'aaa' ? '3 5' : null }).addTo(g);
      else L.circle([s.lat, s.lon], { radius: s.range_km * 1000, color: COL[s.coalition], weight: 1, fill: false, opacity: 0.25, dashArray: '2 10' }).addTo(g);
      dot(s.lat, s.lon, COL[s.coalition], 4, `<b>${esc(s.name)}</b><br>${esc(s.type)} (${s.role})<br>range ${s.range_km} km<br>health ${SORTIE.pct(s.health)}`, '#111');
    });
    d.fronts.forEach((f) => {
      L.polyline(f.axis, { color: '#888', weight: 1, dashArray: '4 6', opacity: 0.5 }).addTo(g);
      L.polyline(f.line, { color: '#f2e04a', weight: 5 }).bindPopup(`<b>${esc(f.name)}</b><br>position ${SORTIE.pct(f.position)} toward red rear<br>pressure ${f.pressure}`).addTo(g);
    });
    d.nodes.forEach((n) => dot(n.lat, n.lon, COL[n.coalition], 6, `<b>${esc(n.name)}</b><br>${n.kind}<br>health ${SORTIE.pct(n.health)}<br>stock ${n.stock} t` + (n.output ? `<br>output ${n.output} t/cycle` : ''), n.health < 0.3 ? '#333' : '#d9b44a'));
    d.ground.forEach((u) => { pts.push([u.lat, u.lon]); L.marker([u.lat, u.lon], { icon: L.divIcon({ className: '', html: `<div style="width:14px;height:10px;border:2px solid ${COL[u.coalition]};background:#111"></div>` }) }).bindPopup(`<b>${esc(u.name)}</b><br>strength ${SORTIE.pct(u.strength)}<br>supply ${SORTIE.pct(u.supply)}`).addTo(g); });
    d.naval.forEach((n) => { if (n.health > 0.05) dot(n.lat, n.lon, COL[n.coalition], 7, `<b>${esc(n.name)}</b><br>${n.role}<br>${n.units.length} ships, health ${SORTIE.pct(n.health)}`, '#1d3557'); });
    d.airbases.forEach((b) => dot(b.lat, b.lon, COL[b.coalition], 8, `<b>${esc(b.name)}</b> (${b.kind})<br>runway ${SORTIE.pct(b.runway)}<br>fuel ${b.fuel} t, munitions ${SORTIE.pct(b.munitions)}<br>${b.squadrons.map(esc).join('<br>')}`));
    d.packages.forEach((p) => L.marker([p.lat, p.lon], { icon: L.divIcon({ className: '', html: `<div style="color:${p.player ? '#f2e04a' : '#9fc6f0'};font-size:11px;font-weight:700;text-shadow:0 0 3px #000;white-space:nowrap">${p.player ? '&#9733; ' : ''}${esc(p.mission)}</div>` }) }).bindPopup(`Package ${esc(p.id)}: ${esc(p.mission)} on ${esc(p.name)}`).addTo(g));
    if (d.player_route.length) {
      L.polyline(d.player_route.map((w) => [w.lat, w.lon]), { color: '#f2e04a', weight: 3, dashArray: '8 6' }).addTo(g);
      d.player_route.forEach((w, i) => L.circleMarker([w.lat, w.lon], { radius: 3, color: '#f2e04a' }).bindTooltip(i + ' ' + w.name).addTo(g));
    }
    const be = d.bullseye[d.side];
    if (be) L.circleMarker([be.lat, be.lon], { radius: 9, color: '#fff', weight: 1, fill: false }).bindTooltip('Bullseye').addTo(g);
    if (pts.length && SORTIE.mapTurn !== SORTIE.cid + ':' + d.turn) { SORTIE.map.fitBounds(pts, { padding: [20, 20] }); SORTIE.mapTurn = SORTIE.cid + ':' + d.turn; }
    setTimeout(() => SORTIE.map.invalidateSize(), 50);
    $('#map-legend').innerHTML = `<span><i style="background:${COL.blue}"></i>blue</span><span><i style="background:${COL.red}"></i>red</span>
      <span><i style="background:#f2e04a"></i>front line / your route</span><span><i style="background:#d9b44a"></i>supply node</span>
      <span>rings = SAM/AAA range, dotted = EWR, squares = ground formations, lines = supply routes (faded when interdicted)</span>`;
  };

  // ---- Squadrons -------------------------------------------------------------------------------
  SORTIE.pages.roster = async function () {
    const r = await api('GET', base() + '/roster');
    const state = (s) => `<span class="${s.state === 'ready' ? 'ok' : s.state === 'limited' ? 'warn' : 'red'}">${s.state}${s.reason ? ' - ' + esc(s.reason) : ''}</span>`;
    $('#tab-roster').innerHTML = `<div class="panel"><h2>Squadron roster</h2><table>
      <tr><th>Squadron</th><th>Aircraft</th><th>Base</th><th>Airframes</th><th>Pilots</th><th>Ready now</th><th>Status</th><th>Roles</th><th>Kills / losses</th><th>Sorties</th></tr>
      ${r.map((s) => `<tr class="${s.is_player ? 'me' : ''}"><td>${esc(s.name)}${s.is_player ? ' <span class="tag me">YOU</span>' : ''}</td>
        <td>${esc(s.aircraft)}${s.owned && s.flyable ? ' <span class="tag">owned</span>' : ''}</td><td>${esc(s.airbase)}</td>
        <td>${s.airframes}/${s.airframes_max} ${SORTIE.meter(s.airframes / Math.max(1, s.airframes_max))}</td>
        <td>${s.pilots}/${s.pilots_max}</td><td>${s.ready}</td><td>${state(s)}</td>
        <td>${s.tasks.map((t) => `<span class="tag">${t}</span>`).join('')}</td><td>${s.kills} / ${s.losses}</td><td>${s.sorties_flown}</td></tr>`).join('')}
    </table><p class="dim">Replacement airframes and pilots arrive each cycle from production, prioritised to the most depleted squadrons. Squadrons without airframes, pilots, fuel, munitions or a usable runway are grounded.</p></div>`;
  };

  // ---- Pilot career ---------------------------------------------------------------------------
  SORTIE.pages.career = async function () {
    const p = await api('GET', base() + '/career');
    if (!p) { $('#tab-career').innerHTML = '<p>No pilot.</p>'; return; }
    const k = p.kills;
    const hist = p.history.map((h) => h.mission === 'TRANSFER'
      ? `<tr><td>${h.turn}</td><td colspan="6"><b>Transferred</b> ${esc(h.transfer.from || '')} &rarr; ${esc(h.transfer.to)} (${esc(h.transfer.aircraft)}): ${esc(h.transfer.reason)}</td></tr>`
      : `<tr><td>${h.turn}</td><td>${esc(h.mission)}</td><td>${esc(h.aircraft || '')}</td><td>${SORTIE.pct(h.success)}</td>
         <td>${h.kills_air || 0} / ${h.kills_ground || 0} / ${h.kills_naval || 0}</td><td>${((h.flight_time_s || 0) / 3600).toFixed(1)} h</td>
         <td>${esc(h.status)}${h.promoted ? ' &middot; promoted to ' + esc(h.promoted) : ''}${(h.awards || []).length ? ' &middot; ' + h.awards.map(esc).join(', ') : ''}</td></tr>`).join('');
    $('#tab-career').innerHTML = `<div class="cols2"><div class="panel"><h2>${esc(p.rank)} "${esc(p.callsign)}"</h2>
      <table><tr><td>Status</td><td class="${p.status === 'active' ? 'ok' : 'red'}"><b>${esc(p.status.toUpperCase())}</b></td></tr>
      <tr><td>Squadron</td><td>${esc(p.squadron_name)}</td></tr><tr><td>Current aircraft</td><td>${esc(p.aircraft)}</td></tr>
      <tr><td>Qualifications</td><td>${p.qualifications.map((q) => `<span class="tag">${esc(q)}</span>`).join('')}</td></tr>
      <tr><td>Flying hours</td><td>${p.hours.toFixed(1)}</td></tr><tr><td>Sorties / landings</td><td>${p.sorties} / ${p.landings}</td></tr>
      <tr><td>Kills</td><td>air ${k.air} &middot; ground ${k.ground} &middot; naval ${k.naval} &middot; structures ${k.structure}</td></tr>
      <tr><td>Ejections</td><td>${p.ejections}</td></tr><tr><td>Career points</td><td>${p.points}</td></tr></table></div>
      <div class="panel"><h2>Awards</h2>${p.awards.length ? p.awards.map((a) => `<div>&#127894; ${esc(a)}</div>`).join('') : '<p class="dim">None yet.</p>'}</div></div>
      <div class="panel"><h2>Mission history</h2>${hist ? `<table><tr><th>Cycle</th><th>Mission</th><th>Aircraft</th><th>Success</th><th>Kills A/G/N</th><th>Time</th><th>Outcome</th></tr>${hist}</table>` : '<p class="dim">No sorties flown yet.</p>'}</div>`;
  };

  // ---- Logistics -------------------------------------------------------------------------------
  SORTIE.pages.logistics = async function () {
    const d = await api('GET', base() + '/logistics');
    const fuel = (b) => { const f = b.fuel.jet + b.fuel.avgas; return `${f.toFixed(0)} t ${SORTIE.meter(f / Math.max(1, b.fuel_cap))}`; };
    $('#tab-logistics').innerHTML = `
      <div class="panel"><h2>Airbases</h2><table><tr><th>Base</th><th>Side</th><th>Fuel</th><th>Munitions</th><th>Weapon types tracked</th><th>Aircraft</th><th>Runway</th><th>Fed by</th></tr>
      ${d.bases.map((b) => `<tr><td>${esc(b.name)}${b.hit ? ' <span class="tag red">hit last cycle</span>' : ''}</td><td>${SORTIE.side(b.coalition)}</td><td>${fuel(b)}</td>
        <td>${SORTIE.pct(b.munition_level)} ${SORTIE.meter(b.munition_level)}</td>
        <td title="${esc(b.weapons.map((w) => w.item + ': ' + w.count).join('\n'))}">${b.weapons_tracked || '<span class="dim">generic stock</span>'}</td>
        <td>${b.aircraft}</td><td>${SORTIE.pct(b.runway)}</td><td>${esc(b.supply_node || (b.kind === 'carrier' ? 'replenishment at sea' : '-'))}</td></tr>`).join('')}</table>
      <p class="dim">Per-weapon counts appear once a mission has been flown from a base (read back from the DCS warehouse). Hover a number to see them.</p></div>
      <div class="cols2"><div class="panel"><h2>Supply nodes</h2><p>Production network health: ${SORTIE.side('blue')} ${SORTIE.pct(d.network.blue)} &middot; ${SORTIE.side('red')} ${SORTIE.pct(d.network.red)}</p>
      <table><tr><th>Node</th><th>Kind</th><th>Side</th><th>Health</th><th>Stock</th><th>Output</th><th>Received</th></tr>
      ${d.nodes.map((n) => `<tr><td>${esc(n.name)}</td><td>${n.kind}</td><td>${SORTIE.side(n.coalition)}</td><td>${SORTIE.pct(n.health)} ${SORTIE.meter(n.health)}</td><td>${n.stock.toFixed(0)} t</td><td>${n.output || '-'}</td><td>${n.received_last_turn.toFixed(0)} t</td></tr>`).join('')}</table></div>
      <div class="panel"><h2>Supply routes</h2><table><tr><th>Route</th><th>Side</th><th>Kind</th><th>Capacity</th><th>Interdiction</th></tr>
      ${d.routes.map((r) => `<tr><td>${esc(r.src_name)} &rarr; ${esc(r.dst_name)}</td><td>${SORTIE.side(r.coalition)}</td><td>${r.kind}</td><td>${r.capacity} t</td><td class="${r.interdiction > 0.3 ? 'red' : ''}">${SORTIE.pct(r.interdiction)}</td></tr>`).join('')}</table></div></div>`;
  };
})();
