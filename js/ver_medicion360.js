/*
ver_medicion360.js — visor de mediciones 360° guardadas

Este script carga y muestra una medición 360° previamente guardada. Lee el archivo
TXT indicado por el parámetro de URL `name` (servido desde /guardado360/<name>),
cuyo formato es: primera línea el equipo; segunda línea lat,long; y a partir de la
tercera, pares “acimut, potencia”. Con esos datos:
- Coloca un mapa Leaflet (OSM) como fondo y, superpuesto, dibuja en un <canvas> un
  diagrama polar con flechas coloreadas según la potencia relativa.
- Muestra metadatos (equipo, lat, lon, nº de puntos) y tooltips en hover con valores
  exactos (acimut, potencia, lat, lon).
- Escala correctamente en pantallas HiDPI y se re-renderiza al redimensionar.
- Permite descargar una captura PNG combinada (mapa + gráfico) usando leaflet-image;
  si el mapa no puede renderizarse a canvas, genera igualmente la imagen indicando
  que el mapa no está disponible.
*/
(() => {
  const $ = (q) => document.querySelector(q);
  const params = new URLSearchParams(location.search);
  const name = params.get('name') || '';

  const hName = $('#hName');
  const hEquipo = $('#hEquipo');
  const hLat = $('#hLat');
  const hLon = $('#hLon');
  const hN = $('#hN');
  const btnTxt = $('#btnTxt');
  const btnDownloadPng = $('#btnDownloadPng');

  const stack = $('#stack');
  const canvas = $('#polarCanvas');
  const tooltip = $('#tooltip');

  let map, mapMarker;

  const data = { lat: null, long: null, points: [], equipo: '—' };
  /*fmt(v, n): Formatea números para mostrarlos (o '—' si no hay valor).*/
  function fmt(v, n = 2) { return (v == null || isNaN(v)) ? '—' : Number(v).toFixed(n); }

  /*colorForPwr(pwr, pmin, pmax): Asigna un color HSL en función de la potencia relativa.*/
  function colorForPwr(pwr, pmin, pmax) {
    if (!isFinite(pwr) || !isFinite(pmin) || !isFinite(pmax)) return 'rgba(200,200,200,1)';
    const den = Math.max(1e-9, pmax - pmin);
    const t = Math.min(1, Math.max(0, (pwr - pmin) / den));
    const hue = t < 0.5 ? 120 - (t / 0.5) * 60 : 60 - ((t - 0.5) / 0.5) * 60;
    return `hsl(${hue}, 90%, 50%)`;
  }

  /*loadFile(): Descarga y parsea el TXT guardado, rellena estructura 'data' y pinta.*/
  async function loadFile() {
    hName.textContent = name || '(sin nombre)';
    btnTxt.href = `/guardado360/${encodeURIComponent(name)}`;

    try {
      const r = await fetch(`/guardado360/${encodeURIComponent(name)}?ts=${Date.now()}`, { cache: 'no-store' });
      const txt = await r.text();

      const lines = txt.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
      if (!lines.length) throw new Error('vacío');

      // 1ª línea: equipo
      data.equipo = lines[0] || '—';

      // 2ª línea: lat,long
      if (lines.length >= 2) {
        const m = lines[1].match(/[-+]?\d+(?:\.\d+)?/g) || [];
        if (m.length >= 2) {
          data.lat = parseFloat(m[0]);
          data.long = parseFloat(m[1]);
        }
      }
      // resto: deg,pwr
      data.points = [];
      for (let i = 2; i < lines.length; i++) {
        const m = lines[i].match(/[-+]?\d+(?:\.\d+)?/g) || [];
        if (m.length >= 2) {
          const deg = (parseFloat(m[0]) % 360 + 360) % 360;
          const pwr = parseFloat(m[1]);
          if (isFinite(deg) && isFinite(pwr)) data.points.push({ deg, pwr });
        }
      }

      hEquipo.textContent = data.equipo;
      hLat.textContent = fmt(data.lat, 6);
      hLon.textContent = fmt(data.long, 6);
      hN.textContent = String(data.points.length);

      ensureMap();
      draw();
    } catch (e) {
      hEquipo.textContent = '—';
    }
  }
  /*ensureMap(): Inicializa/actualiza el mapa y su marcador.*/
  function ensureMap() {
    if (!map) {
      map = L.map('map', { zoomControl: true });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap'
      }).addTo(map);
      setTimeout(() => map.invalidateSize(), 0);
    }
    if (isFinite(data.lat) && isFinite(data.long)) {
      if (!mapMarker) {
        mapMarker = L.marker([data.lat, data.long]).addTo(map);
        map.setView([data.lat, data.long], 16);
      } else {
        mapMarker.setLatLng([data.lat, data.long]);
        map.panTo([data.lat, data.long]);
      }
    } else {
      map.setView([20, 0], 2);
    }
  }

  /*setupHiDPI(canvas): Ajusta el canvas a la densidad de píxeles del dispositivo (HiDPI).*/
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

  const hoverCache = [];
  /*draw(): Dibuja las guías y flechas del diagrama polar en el canvas y precalcula zonas de hover.*/
  function draw() {
    const { ctx, cssW, cssH } = setupHiDPI(canvas);
    ctx.clearRect(0, 0, cssW, cssH);

    const cx = cssW / 2;
    const cy = cssH / 2;
    const R = Math.min(cssW, cssH) * 0.40;

    ctx.strokeStyle = 'rgba(22,48,77,.7)';
    ctx.lineWidth = 1;
    [0.33, 0.66, 1.0].forEach(f => { ctx.beginPath(); ctx.arc(cx, cy, R * f, 0, Math.PI * 2); ctx.stroke(); });
    ctx.beginPath(); ctx.moveTo(cx - R, cy); ctx.lineTo(cx + R, cy); ctx.moveTo(cx, cy - R); ctx.lineTo(cx, cy + R); ctx.stroke();
    ctx.fillStyle = '#cfe8ff';
    ctx.font = '12px system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif';
    ctx.fillText('N', cx - 4, cy - R - 6); ctx.fillText('S', cx - 4, cy + R + 14);
    ctx.fillText('O', cx - R - 12, cy + 4); ctx.fillText('E', cx + R + 6, cy + 4);

    const vals = data.points.map(p => p.pwr).filter(v => isFinite(v));
    const pmin = vals.length ? Math.min(...vals) : -100;
    const pmax = vals.length ? Math.max(...vals) : -30;

    hoverCache.length = 0;
    const arrowLen = R * 0.92, head = 8, hitRadius = 10;

    data.points.forEach((p, idx) => {
      const rad = (p.deg - 90) * Math.PI / 180;
      const x2 = cx + arrowLen * Math.cos(rad);
      const y2 = cy + arrowLen * Math.sin(rad);
      const col = colorForPwr(p.pwr, pmin, pmax);

      ctx.strokeStyle = col; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x2, y2); ctx.stroke();

      const back = 12;
      const xr = x2 - back * Math.cos(rad);
      const yr = y2 - back * Math.sin(rad);
      const leftA = rad + Math.PI * 0.85, rightA = rad - Math.PI * 0.85;
      ctx.fillStyle = col;
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(xr + head * Math.cos(leftA), yr + head * Math.sin(leftA));
      ctx.lineTo(xr + head * Math.cos(rightA), yr + head * Math.sin(rightA));
      ctx.closePath(); ctx.fill();

      hoverCache.push({ x: x2, y: y2, idx, data: p, hit: hitRadius });
    });

    ctx.fillStyle = '#cfe8ff';
    ctx.fillText(`Puntos: ${data.points.length} — Lat: ${fmt(data.lat, 6)}  Lon: ${fmt(data.long, 6)}`, 10, cssH - 10);
  }
  /*(eventos) mousemove/mouseleave: Gestionan tooltips.*/
  canvas.addEventListener('mousemove', (ev) => {
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
    let best = null, dmin = Infinity;
    for (const h of hoverCache) {
      const d = Math.hypot(x - h.x, y - h.y);
      if (d < h.hit && d < dmin) { best = h; dmin = d; }
    }
    if (!best) { tooltip.hidden = true; return; }
    tooltip.innerHTML = [
      `<b>Azimut:</b> ${fmt(best.data.deg, 1)}°`,
      `<b>Potencia:</b> ${fmt(best.data.pwr, 2)} dBm`,
      `<b>Lat:</b> ${fmt(data.lat, 6)}`,
      `<b>Lon:</b> ${fmt(data.long, 6)}`
    ].join('<br>');
    tooltip.style.left = `${x + 10}px`;
    tooltip.style.top = `${y - 10}px`;
    tooltip.hidden = false;
  });
  canvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });

  const ro = new ResizeObserver(() => {
    if (map) map.invalidateSize();
    draw();
  });
  ro.observe(stack);
  /*(evento) btnDownloadPng: Genera la captura combinada mapa+gráfico.*/
  btnDownloadPng?.addEventListener('click', async () => {
    try {
      const mapCanvas = await new Promise((resolve) => {
        try {
          window.leafletImage(map, (err, canvasOut) => resolve(err ? null : canvasOut));
        } catch { resolve(null); }
      });
      // gráfico a tamaño CSS
      const gW = canvas.clientWidth, gH = canvas.clientHeight;
      const graphCanvas = document.createElement('canvas');
      graphCanvas.width = gW; graphCanvas.height = gH;
      const gctx = graphCanvas.getContext('2d');
      gctx.drawImage(canvas, 0, 0, gW, gH);

      const out = document.createElement('canvas');
      out.width = gW; out.height = gH;
      const octx = out.getContext('2d');

      if (mapCanvas) {
        // mapa al fondo, ajustado al tamaño del gráfico
        octx.drawImage(mapCanvas, 0, 0, gW, gH);
        // gráfico encima
        octx.drawImage(graphCanvas, 0, 0);
      } else {
        octx.fillStyle = '#07101d'; octx.fillRect(0, 0, gW, gH);
        octx.drawImage(graphCanvas, 0, 0);
        octx.fillStyle = '#9fb7d6';
        octx.font = '13px system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif';
        octx.fillText('(Mapa no disponible en la captura)', 10, gH - 12);
      }

      const a = document.createElement('a');
      a.href = out.toDataURL('image/png');
      a.download = `${name || 'medicion360'}.png`;
      a.click();
    } catch {
      alert('No se pudo generar la captura.');
    }
  });

  // go!
  loadFile();
})();
