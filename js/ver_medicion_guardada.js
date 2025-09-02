// ver_medicion_guardada.js
// Gráfico como en tu versión "buena" + galería robusta (usa {i,file} o fallback por índices/extensiones)

document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(location.search);
  const name = params.get('name') || '';
  const encoded = encodeURIComponent(name);

  // Topbar / info
  const titleEl   = document.getElementById('title');
  const infoName  = document.getElementById('infoName');
  const btnBack   = document.getElementById('btnBack');
  const btnRebuild= document.getElementById('btnRebuild');

  // Acciones carpeta/CSV/ZIP (ZIP es opcional: sólo si existe el botón en tu HTML)
  const btnDownloadCSV = document.getElementById('btnDownloadCSV');
  const btnDownloadZIP = document.getElementById('btnDownloadZIP');
  const btnOpenFolder  = document.getElementById('btnOpenFolder');

  // Abrir interactivo (opcionales: sólo si están en el HTML)
  const btnOpenInteractive  = document.getElementById('btnOpenInteractive');
  const btnOpenInteractive2 = document.getElementById('btnOpenInteractive2');

  // PNG (4 paneles)
  const pngWrap = document.getElementById('pngWrap');
  const pngImg  = document.getElementById('pngImg');

  // Interactivo Plotly
  const htmlWrap = document.getElementById('htmlWrap');
  const htmlIfr  = document.getElementById('htmlIfr');

  // Galería
  const galeria   = document.getElementById('galeria');
  const msgImages = document.getElementById('msgImages');

  // Títulos y enlaces base
  if (titleEl)  titleEl.textContent = `Medición: ${name}`;
  if (infoName) infoName.textContent = name;
  if (btnDownloadCSV) btnDownloadCSV.href = `/guardado/${encoded}/data.txt`;
  if (btnDownloadZIP) btnDownloadZIP.href = `/api/guardado/zip?name=${encoded}`;
  if (btnOpenFolder)  btnOpenFolder.href  = `/guardado/${encoded}/`;

  const interactiveURL = `/guardado/${encoded}/analysis/muestreo_interactivo.html`;
  if (btnOpenInteractive)  btnOpenInteractive.href  = interactiveURL + `?ts=${Date.now()}`;
  if (btnOpenInteractive2) btnOpenInteractive2.href = interactiveURL + `?ts=${Date.now()}`;

  btnBack?.addEventListener('click', () => history.back());

  // ------------ Regenerar gráficos (flujo "bueno") ------------
  async function regen() {
    try {
      if (pngWrap) pngWrap.textContent = 'Generando…';
      if (htmlWrap) htmlWrap.textContent = 'Generando…';
      if (pngImg)  pngImg.style.display = 'none';
      if (htmlIfr) htmlIfr.hidden = true;

      const r = await fetch(`/api/guardado/build_graphs?name=${encoded}&ts=${Date.now()}`);
      const j = await r.json();

      if (!r.ok || !j.ok) {
        if (pngWrap)  pngWrap.textContent  = 'No se pudo generar el PNG.';
        if (htmlWrap) htmlWrap.textContent = 'No se pudo generar el interactivo.';
        console.error('build_graphs error:', j);
        return;
      }

      // PNG
      if (pngWrap) pngWrap.textContent = '';
      if (pngImg) {
        pngImg.src = `/guardado/${encoded}/analysis/analisis_potencia.png?ts=${Date.now()}`;
        pngImg.style.display = 'block';
      }

      // Iframe interactivo
      if (htmlWrap) htmlWrap.textContent = '';
      if (htmlIfr) {
        htmlIfr.src = interactiveURL + `?ts=${Date.now()}`;
        htmlIfr.hidden = false;
      }
    } catch (e) {
      console.error(e);
      if (pngWrap)  pngWrap.textContent  = 'No se pudo generar el PNG.';
      if (htmlWrap) htmlWrap.textContent = 'No se pudo generar el interactivo.';
    }
  }
  btnRebuild?.addEventListener('click', regen);

  // ------------ Galería (soporta {i,file} y fallback por índices/extensiones) ------------
  const EXT_TRY = ['.jpg','.JPG','.jpeg','.JPEG','.png','.PNG','.webp','.WEBP'];

  function rowByIdx(rows, i) {
    return rows.find(x => x.i === i) || {};
  }
  function messageImages(txt) {
    if (msgImages) {
      msgImages.textContent = txt;
    } else if (galeria) {
      galeria.innerHTML = `<p class="note">${txt}</p>`;
    }
  }

  function figFromFile(kind, i, file, rows) {
    const row = rowByIdx(rows, i);
    const lat = (row.lat != null && isFinite(row.lat))   ? (+row.lat).toFixed(6)   : '—';
    const lon = (row.long != null && isFinite(row.long)) ? (+row.long).toFixed(6)  : '—';
    const dbm = (row.dbm != null && isFinite(row.dbm))   ? (+row.dbm).toFixed(2)+' dBm' : '—';
    const azi = (row.acimut != null && isFinite(row.acimut)) ? (+row.acimut).toFixed(1)+'°' : 'no directivo';
    const fh  = [row.fecha || '-', row.hora || '-'].join(' ');
    const label = kind === 'frames' ? 'Frame' : 'Captura';
    const src   = `/guardado/${encoded}/${kind}/${encodeURIComponent(file)}`;

    const el = document.createElement('figure');
    el.className = 'imgcard';
    el.innerHTML = `
      <img src="${src}" alt="${label} ${i}" loading="lazy"
           style="width:100%;height:auto;display:block;border-radius:8px;">
      <figcaption style="margin-top:6px;color:#cfe8ff;font-size:13px;">
        <div><b>${label} ${i}</b> — muestra ${i}</div>
        <div>Fecha/Hora: ${fh}</div>
        <div>Lat: ${lat} &nbsp; Lon: ${lon}</div>
        <div>Potencia: ${dbm} &nbsp; Acimut: ${azi}</div>
      </figcaption>
    `;
    const img = el.querySelector('img');
    img.onerror = () => el.remove();
    return el;
  }

  function figFromIdx(kind, i, rows) {
    const row = rowByIdx(rows, i);
    const lat = (row.lat != null && isFinite(row.lat))   ? (+row.lat).toFixed(6)   : '—';
    const lon = (row.long != null && isFinite(row.long)) ? (+row.long).toFixed(6)  : '—';
    const dbm = (row.dbm != null && isFinite(row.dbm))   ? (+row.dbm).toFixed(2)+' dBm' : '—';
    const azi = (row.acimut != null && isFinite(row.acimut)) ? (+row.acimut).toFixed(1)+'°' : 'no directivo';
    const fh  = [row.fecha || '-', row.hora || '-'].join(' ');
    const label = kind === 'frames' ? 'Frame' : 'Captura';
    const stem  = (kind === 'frames') ? `frame_${i}` : `captura_${i}`;

    const el = document.createElement('figure');
    el.className = 'imgcard';
    el.innerHTML = `
      <img data-kind="${kind}" data-stem="${stem}" data-try="0"
           alt="${label} ${i}" loading="lazy"
           style="width:100%;height:auto;display:block;border-radius:8px;">
      <figcaption style="margin-top:6px;color:#cfe8ff;font-size:13px;">
        <div><b>${label} ${i}</b> — muestra ${i}</div>
        <div>Fecha/Hora: ${fh}</div>
        <div>Lat: ${lat} &nbsp; Lon: ${lon}</div>
        <div>Potencia: ${dbm} &nbsp; Acimut: ${azi}</div>
      </figcaption>
    `;
    const img = el.querySelector('img');
    img.onerror = () => tryNextExt(img, el);
    tryNextExt(img, el); // primer intento
    return el;
  }

  function tryNextExt(imgEl, figEl) {
    const t = parseInt(imgEl.dataset.try || '0', 10);
    if (t >= EXT_TRY.length) {
      figEl.remove();
      return;
    }
    const ext  = EXT_TRY[t];
    const kind = imgEl.dataset.kind;
    const stem = imgEl.dataset.stem;
    imgEl.dataset.try = String(t + 1);
    imgEl.src = `/guardado/${encoded}/${kind}/${stem}${ext}?ts=${Date.now()}`;
  }

  async function loadMeta() {
    if (!galeria) return;
    galeria.innerHTML = '<p class="note">Cargando imágenes…</p>';
    if (msgImages) msgImages.textContent = '';

    try {
      const r = await fetch(`/api/guardado/meta?name=${encoded}&ts=${Date.now()}`, { cache: 'no-store' });
      const j = await r.json();
      if (!r.ok || !j.ok) {
        messageImages(j?.error || 'No se pudieron cargar las imágenes.');
        return;
      }

      const rows = Array.isArray(j.rows) ? j.rows : [];
      const frames     = Array.isArray(j.frames) ? j.frames : null;         // [{i,file}]
      const capturas   = Array.isArray(j.capturas) ? j.capturas : null;     // [{i,file}]
      const frames_idx = Array.isArray(j.frames_idx) ? j.frames_idx : [];   // [i,...]
      const caps_idx   = Array.isArray(j.capturas_idx) ? j.capturas_idx : [];

      // Construcción
      const frag = document.createDocumentFragment();

      // Frames
      {
        const h = document.createElement('h3');
        h.textContent = 'Frames';
        h.style.color = '#e8f2ff';
        h.style.margin = '8px 0';
        frag.appendChild(h);

        const grid = document.createElement('div');
        grid.className = 'gallery';

        if (frames && frames.length) {
          frames.forEach(it => grid.appendChild(figFromFile('frames', it.i, it.file, rows)));
        } else if (frames_idx.length) {
          frames_idx.forEach(i => grid.appendChild(figFromIdx('frames', i, rows)));
        } else {
          grid.innerHTML = '<p class="note">No hay frames.</p>';
        }

        frag.appendChild(grid);
      }

      // Capturas
      {
        const h = document.createElement('h3');
        h.textContent = 'Capturas';
        h.style.color = '#e8f2ff';
        h.style.margin = '8px 0';
        frag.appendChild(h);

        const grid = document.createElement('div');
        grid.className = 'gallery';

        if (capturas && capturas.length) {
          capturas.forEach(it => grid.appendChild(figFromFile('capturas', it.i, it.file, rows)));
        } else if (caps_idx.length) {
          caps_idx.forEach(i => grid.appendChild(figFromIdx('capturas', i, rows)));
        } else {
          grid.innerHTML = '<p class="note">No hay capturas.</p>';
        }

        frag.appendChild(grid);
      }

      galeria.innerHTML = '';
      galeria.appendChild(frag);
    } catch (e) {
      console.error(e);
      messageImages('No se pudieron cargar las imágenes.');
    }
  }

  // Cargas iniciales
  regen();
  loadMeta();
});
