/*
medicion360.js — vista “Medición 360°”: mapa debajo + gráfico polar encima, guardado y listado.

Resumen:
- La página muestra un stack con un mapa Leaflet al fondo y un <canvas> encima donde se dibujan
  flechas (azimuts) coloreadas por potencia (dBm). Los datos llegan del backend vía
  /api/med360/live (polling cada ~1s).
- Controles: iniciar/detener la medición (POST /api/med360/start /stop), guardar el TXT actual
  (POST /api/med360/save) y generar una captura compuesta (mapa+gráfico) en PNG.
- El listado de mediciones 360° guardadas se carga desde /api/med360/list y permite descargar
  o eliminar un archivo.
- Dibujo en HiDPI: el canvas se escala en función de devicePixelRatio para verse nítido.
- Captura: usa leaflet-image para rasterizar el mapa a canvas y luego compone con el gráfico.
- Accesibilidad/UX: tooltips sobre el gráfico, tamaños responsivos (ResizeObserver), mensajes
  de estado y manejo robusto de errores (sin bloquear la UI).
*/
(() => {
  const $ = (q) => document.querySelector(q);

  // --- DOM ---
  const btnBack = $('#btnBack');
  const btnStart = $('#btnStart');
  const btnStop = $('#btnStop');
  const btnSave = $('#btnSave');
  const btnCapture = $('#btnCapture');
  const btnReloadList = $('#btnReloadList');
  const periodInput = $('#period');
  const statusEl = $('#liveStatus');

  const stack = $('#stack');
  const canvas = $('#polarCanvas');
  const tooltip = $('#tooltip');

  const list360 = $('#list360');
  const empty360 = $('#empty360');

  // --- Estado ---
  let liveTimer = null;// id del setInterval del polling en vivo
  let liveData = { lat: null, long: null, points: [] };
  let map, mapMarker, tileLayer;// id del setInterval del polling en vivo

  /** Formatea números con n decimales; si no es número, devuelve '—'. */
  function fmt(v, n = 2) { return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(n); }

  /** Devuelve un color HSL (verde→amarillo) según potencia relativa [pmin, pmax]. */
  function colorForPwr(pwr, pmin, pmax) {
    if (!isFinite(pwr) || !isFinite(pmin) || !isFinite(pmax)) return 'rgba(200,200,200,1)';
    const den = Math.max(1e-9, pmax - pmin);
    const t = Math.min(1, Math.max(0, (pwr - pmin) / den));
    const hue = t < 0.5 ? 120 - (t / 0.5) * 60 : 60 - ((t - 0.5) / 0.5) * 60;
    return `hsl(${hue}, 90%, 50%)`;
  }

  // --- Canvas helpers ---
  /**
  * Ajusta el canvas para pantallas HiDPI manteniendo tamaño CSS.
  * Devuelve el contexto y dimensiones lógicas (en CSS px).
  */
  function setupHiDPI(canvas) {
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || stack.clientWidth;
    const cssH = canvas.clientHeight || stack.clientHeight;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, cssW, cssH, dpr };
  }

  /**
   * Dibuja el gráfico polar: radios guía, ejes cardinales y flechas por punto (deg,pwr).
   * El color de cada flecha depende de la potencia relativa al rango [pmin, pmax].
   */
  function drawPolar(points, lat, lon) {
    const { ctx, cssW, cssH } = setupHiDPI(canvas);
    ctx.clearRect(0, 0, cssW, cssH);

    // Fondo transparente para ver el mapa debajo
    // (no pintar rectángulo de fondo)
    const cx = cssW / 2;
    const cy = cssH / 2;
    const R = Math.min(cssW, cssH) * 0.40;

    // guías (finas) para no tapar mapa
    ctx.strokeStyle = 'rgba(22,48,77,.7)';
    ctx.lineWidth = 1;
    [0.33, 0.66, 1.0].forEach(f => {
      ctx.beginPath();
      ctx.arc(cx, cy, R * f, 0, Math.PI * 2);
      ctx.stroke();
    });
    ctx.beginPath();
    ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy);
    ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R);
    ctx.stroke();

    // Cardinales
    ctx.fillStyle = '#cfe8ff';
    ctx.font = '12px system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif';
    ctx.fillText('N', cx - 4, cy - R - 6);
    ctx.fillText('S', cx - 4, cy + R + 14);
    ctx.fillText('O', cx - R - 12, cy + 4);
    ctx.fillText('E', cx + R + 6, cy + 4);

    // Rango de potencias (para colorear)
    const vals = points.map(p => p.pwr).filter(v => isFinite(v));
    const pmin = vals.length ? Math.min(...vals) : -100;
    const pmax = vals.length ? Math.max(...vals) : -30;

    const arrowLen = R * 0.92;
    const head = 8;
    const hitRadius = 10;
    hoverCache.length = 0;// reset hotspots para tooltip

    // Flechas por punto (una por azimut)
    points.forEach((p, idx) => {
      const deg = (p.deg % 360 + 360) % 360;
      const rad = (deg - 90) * Math.PI / 180;
      const x2 = cx + arrowLen * Math.cos(rad);
      const y2 = cy + arrowLen * Math.sin(rad);
      const col = colorForPwr(p.pwr, pmin, pmax);

      // vástago
      ctx.strokeStyle = col;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x2, y2);
      ctx.stroke();

      // punta
      const back = 12;
      const xr = x2 - back * Math.cos(rad);
      const yr = y2 - back * Math.sin(rad);
      const leftA = rad + Math.PI * 0.85;
      const rightA = rad - Math.PI * 0.85;

      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(xr + head * Math.cos(leftA), yr + head * Math.sin(leftA));
      ctx.lineTo(xr + head * Math.cos(rightA), yr + head * Math.sin(rightA));
      ctx.closePath();
      ctx.fill();
      // registro para hover/tooltip
      hoverCache.push({ x: x2, y: y2, idx, data: p, color: col, hit: hitRadius });
    });

    // pie info (ligero)
    ctx.fillStyle = '#cfe8ff';
    const footer = `Puntos: ${points.length} — Lat: ${fmt(lat, 6)}  Lon: ${fmt(lon, 6)}`;
    ctx.fillText(footer, 10, cssH - 10);
  }

  // --- Hover (tooltip sobre puntas de flecha) ---
  const hoverCache = [];
  canvas.addEventListener('mousemove', (ev) => {
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;

    let best = null, bestD = Infinity;
    for (const h of hoverCache) {
      const dx = x - h.x, dy = y - h.y;
      const d = Math.hypot(dx, dy);
      if (d < h.hit && d < bestD) { best = h; bestD = d; }
    }

    if (!best) { tooltip.hidden = true; return; }
    const d = best.data;
    tooltip.innerHTML = [
      `<b>Azimut:</b> ${fmt(d.deg, 1)}°`,
      `<b>Potencia:</b> ${fmt(d.pwr, 2)} dBm`,
      `<b>Lat:</b> ${fmt(liveData.lat, 6)}`,
      `<b>Lon:</b> ${fmt(liveData.long, 6)}`
    ].join('<br>');
    tooltip.style.left = `${x + 10}px`;
    tooltip.style.top = `${y - 10}px`;
    tooltip.hidden = false;
  });
  canvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });

  // --- Mapa Leaflet por debajo del canvas ---
  /**
   * Crea el mapa si no existe y sitúa/actualiza un marcador en (lat,lon).
   * No hace zoom si ya existe; sólo mueve el marcador.
   */
  function ensureMap(lat, lon) {
    if (!map) {
      map = L.map('map', { zoomControl: true });
      tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap'
      });
      tileLayer.addTo(map);

      // ajusta al tamaño del contenedor
      setTimeout(() => map.invalidateSize(), 50);
    }
    if (isFinite(lat) && isFinite(lon)) {
      if (!mapMarker) {
        mapMarker = L.marker([lat, lon]).addTo(map);
        map.setView([lat, lon], 16);
      } else {
        mapMarker.setLatLng([lat, lon]);
      }
    }
  }

  // Redibujo responsivo (canvas y mapa)
  const ro = new ResizeObserver(() => {
    if (map) map.invalidateSize();
    drawPolar(liveData.points || [], liveData.lat, liveData.long);
  });
  ro.observe(stack);

  // --- Live polling ---
  /** Consulta periódicamente /api/med360/live y actualiza mapa+gráfico+estado. */
  async function pollLive() {
    try {
      const r = await fetch('/api/med360/live?ts=' + Date.now(), { cache: 'no-store' });
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error('Respuesta live inválida');
      liveData = j;

      ensureMap(liveData.lat, liveData.long);
      drawPolar(liveData.points || [], liveData.lat, liveData.long);

      statusEl.textContent = `Muestras: ${liveData.n ?? (liveData.points?.length || 0)} — ` +
        `Lat: ${fmt(liveData.lat, 6)} Lon: ${fmt(liveData.long, 6)}`;
    } catch (e) {
      console.warn('live error:', e);
      statusEl.textContent = 'No hay live o falló la lectura.';
    }
  }
  function startPolling() { if (!liveTimer) { pollLive(); liveTimer = setInterval(pollLive, 1000); } }
  function stopPolling() { if (liveTimer) { clearInterval(liveTimer); liveTimer = null; } }

  // --- Acciones de la barra superior ---
  btnBack?.addEventListener('click', () => { location.href = '/pagina1.html'; });

  // Iniciar medición 360° (periodo en segundos)
  btnStart?.addEventListener('click', async () => {
    const per = Math.max(0.1, parseFloat(periodInput.value || '1') || 1);
    try {
      const r = await fetch('/api/med360/start', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ period: per })
      });
      const j = await r.json();
      if (!r.ok || !j.ok) return alert(j.error || 'No se pudo iniciar.');
      statusEl.textContent = `Medición iniciada (periodo ${per}s)…`;
      startPolling();
    } catch { alert('Empezando medicion'); }
  });

  // Detener medición 360°
  btnStop?.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/med360/stop', { method: 'POST' });
      const j = await r.json();
      if (!r.ok || !j.ok) return alert(j.error || 'No se pudo detener.');
      statusEl.textContent = 'Medición detenida.';
      stopPolling();
    } catch { alert('Error al detener.'); }
  });

  // Guardar TXT actual (primer línea equipo, luego lat/lon + pares az,dbm)
  btnSave?.addEventListener('click', async () => {
    try {
      const r = await fetch('/api/med360/save', { method: 'POST' });
      const j = await r.json();
      if (!r.ok || !j.ok) return alert(j.error || 'No se pudo guardar.');
      alert('Guardado en: ' + (j.file || '(desconocido)'));
      loadList();
      // Opcional: generar y descargar captura inmediatamente
      await doCaptureDownload();
    } catch { alert('Error al guardar.'); }
  });

  // --- Captura compuesta (mapa debajo + gráfico encima) ---
  /**
   * Genera un PNG uniendo el mapa (rasterizado con leaflet-image) y el canvas del gráfico.
   * Descarga automáticamente el archivo como 'medicion360_captura.png'.
   */
  async function doCaptureDownload() {
    try {
      // 1) Rasterizar el mapa Leaflet a un canvas
      const mapCanvas = await new Promise((resolve) => {
        try {
          window.leafletImage(map, (err, canvasOut) => resolve(err ? null : canvasOut));
        } catch { resolve(null); }
      });

      // 2) Clonar el canvas del gráfico a tamaño CSS (evitar escalas extrañas)
      const gW = canvas.clientWidth, gH = canvas.clientHeight;
      const graphCanvas = document.createElement('canvas');
      graphCanvas.width = gW; graphCanvas.height = gH;
      const gctx = graphCanvas.getContext('2d');
      gctx.drawImage(canvas, 0, 0, gW, gH);

      // 3) Componer mapa (arriba) + gráfico (abajo) en un canvas final
      const out = document.createElement('canvas');
      let finalW = gW, finalH = gH + (mapCanvas ? mapCanvas.height : 0);
      out.width = finalW; out.height = finalH;
      const octx = out.getContext('2d');
      octx.fillStyle = '#07101d'; octx.fillRect(0, 0, finalW, finalH);

      // Mapa debajo
      if (mapCanvas) {
        // Ajuste proporcional si el ancho del mapa no coincide con el del gráfico
        if (mapCanvas.width !== gW) {
          const ratio = mapCanvas.height / mapCanvas.width;
          const newH = Math.round(gW * ratio);
          octx.drawImage(mapCanvas, 0, 0, gW, newH);
          // gráfico encima
          octx.drawImage(graphCanvas, 0, newH);
        } else {
          octx.drawImage(mapCanvas, 0, 0);
          octx.drawImage(graphCanvas, 0, mapCanvas.height);
        }
      } else {
        // Sin mapa: sólo gráfico arriba, nota debajo
        octx.drawImage(graphCanvas, 0, 0);
        octx.fillStyle = '#9fb7d6';
        octx.font = '13px system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif';
        octx.fillText('(Mapa no disponible en la captura)', 10, gH + 20);
      }
      // 4) Descargar PNG
      const a = document.createElement('a');
      a.href = out.toDataURL('image/png');
      a.download = 'medicion360_captura.png';
      a.click();
    } catch {
      alert('No se pudo generar la captura.');
    }
  }
  btnCapture?.addEventListener('click', doCaptureDownload);

  // --- Lista de mediciones 360° guardadas ---
  /**
   * Carga la lista desde /api/med360/list y pinta tarjetas con acciones:
   * descargar, ver (vista detallada) y eliminar.
   */
  async function loadList() {
    try {
      const r = await fetch('/api/med360/list?ts=' + Date.now(), { cache: 'no-store' });
      const j = await r.json();
      if (!r.ok || !j.ok) throw new Error(j.error || 'error list');

      const items = Array.isArray(j.items) ? j.items : [];
      list360.innerHTML = ''; empty360.hidden = !!items.length;

      const frag = document.createDocumentFragment();
      items.forEach(it => {
        const name = it.name || '';
        const when = it.mtime ? new Date(it.mtime * 1000).toLocaleString() : '';
        const size = (it.size || it.size_bytes || 0);
        const human = (b => { const k = 1024, s = ['B', 'KB', 'MB', 'GB']; let i = 0, v = b; while (v >= k && i < s.length - 1) { v /= k; i++; } return v.toFixed(v < 10 && i > 0 ? 1 : 0) + ' ' + s[i]; })(size);

        const el = document.createElement('article');
        el.className = 'card';
        el.innerHTML = `
          <div class="card__top">
            <span class="badge">${it.equipo || '—'}</span>
            <time class="ts">${when}</time>
          </div>
          <h3 class="name" title="${name}">${name}</h3>
          <div class="meta"><span>Tamaño: <b>${human}</b></span></div>
          <div class="actions">
            <a class="btn" href="${it.url}" download>Descargar</a>
            <a class="btn btn-outline" href="/ver_medicion360.html?name=${encodeURIComponent(name)}">Ver</a>
            <button class="btn btn-danger" data-del="${name}">Eliminar</button>
          </div>
        `;
        frag.appendChild(el);
      });
      list360.appendChild(frag);
    } catch {
      list360.innerHTML = ''; empty360.hidden = false;
    }
  }
  // Eliminar un guardado desde la tarjeta (delegación de eventos)
  list360?.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('button');
    if (!btn) return;
    const del = btn.getAttribute('data-del');
    if (!del) return;
    if (!confirm(`¿Eliminar "${del}"?`)) return;
    try {
      const r = await fetch('/api/med360/delete', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: del })
      });
      const j = await r.json();
      if (!r.ok || !j.ok) return alert(j.error || 'No se pudo eliminar');
      loadList();
    } catch { alert('Error al eliminar'); }
  });

  btnReloadList?.addEventListener('click', loadList);

  // --- Arranque ---
  startPolling();
  loadList();
})();
