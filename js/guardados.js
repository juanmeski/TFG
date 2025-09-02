/*
guardados.js — listado y acciones de “Mediciones guardadas”

Este script controla la vista /guardados.html. Hace 3 cosas principales:
1) Carga desde el backend la lista de carpetas guardadas (JSON de /api/guardados/list o /api/guardados)
   y las pinta en una cuadricula de tarjetas con: nombre, equipo, tamaño, nº de filas y fecha.
2) Ofrece utilidades por cada tarjeta: Ver (navega a /ver_medicion_guardada.html?name=…),
   Descargar (el TXT), Previsualizar (abre modal con las primeras ~120 líneas) y Eliminar.
3) Añade búsqueda por texto (filtra por nombre/equipo) y controles de navegación (Atrás, Ir a medir, Recargar).

Notas:
- No modifica ni reordena datos en el servidor; solo consume endpoints:
  * GET  /api/guardados/list  (o fallback GET /api/guardados)
  * POST /api/guardados/delete { name }
- La previsualización usa un modal simple y solo lee el comienzo del archivo (para no cargar ficheros enormes).
- Toda la apariencia depende de guardados.css y la estructura HTML existente.
*/

document.addEventListener('DOMContentLoaded', () => {
  // --- Referencias a elementos de la UI ---
  const grid = document.getElementById('grid');
  const empty = document.getElementById('emptyState');
  const q = document.getElementById('q');
  const clearQ = document.getElementById('clearQ');
  const btnReload = document.getElementById('btnReload');
  const btnBack = document.getElementById('btnBack');
  const goMeasure = document.getElementById('goMeasure');
  const goMeasure2 = document.getElementById('goMeasure2');

  // Modal de previsualización (abre un TXT y muestra primeras líneas)
  const modal = document.getElementById('modal');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');
  const modalDownload = document.getElementById('modalDownload');
  const modalClose = document.getElementById('modalClose');
  const modalClose2 = document.getElementById('modalClose2');

  // Estado en memoria: lista completa y vista filtrada
  let items = [];
  let view = [];

  // ----------------------------------------
  // Utilidad: formatear tamaño en bytes
  // ----------------------------------------
  function fmtSize(bytes) {
    if (bytes == null) return '—';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    let i = 0; let v = bytes;
    while (v >= k && i < sizes.length - 1) { v /= k; i++; }
    return v.toFixed(v < 10 && i > 0 ? 1 : 0) + ' ' + sizes[i];
  }

  // ----------------------------------------
  // Render: pinta las tarjetas en el grid
  // ----------------------------------------
  function render() {
    if (!grid || !empty) return;
    grid.innerHTML = '';
    empty.hidden = true;

    if (!view.length) {
      // Estado vacío (no hay guardados o el filtro no devuelve resultados)
      empty.hidden = false;
      return;
    }

    const frag = document.createDocumentFragment();
    view.forEach(item => {
      const card = document.createElement('article');
      card.className = 'card';
      const when = item.mtime ? new Date(item.mtime * 1000).toLocaleString() : '';
      const rows = (item.rows != null ? item.rows : '—');
      const sizeVal = item.size_bytes != null ? item.size_bytes : item.size;

      // Link “Ver” lleva a la página con detalle y gráficos del guardado seleccionado
      const verHref = `/ver_medicion_guardada.html?name=${encodeURIComponent(item.name)}`;

      card.innerHTML = `
        <div class="card__top">
          <span class="badge">${(item.equipo || '—')}</span>
          <time class="ts">${when}</time>
        </div>
        <h3 class="name" title="${item.name}">${item.name}</h3>
        <div class="meta">
          <span>Filas: <b>${rows}</b></span>
          <span>Tamaño: <b>${fmtSize(sizeVal)}</b></span>
        </div>
        <div class="actions">
          <a class="btn btn-accent" href="${verHref}">Ver</a>
          <a class="btn" href="${item.url}" download>Descargar</a>
          <button class="btn btn-outline" data-preview="${item.url}" data-name="${item.name}">Previsualizar</button>
          <button class="btn btn-danger" data-del="${item.name}">Eliminar</button>
        </div>
      `;
      frag.appendChild(card);
    });
    grid.appendChild(frag);
  }

  // ----------------------------------------
  // Filtro de búsqueda (por nombre/equipo)
  // ----------------------------------------
  function applyFilter() {
    const term = (q?.value || '').toLowerCase().trim();
    if (!term) { view = items.slice(); render(); return; }
    view = items.filter(it =>
      (it.name || '').toLowerCase().includes(term) ||
      (it.equipo || '').toLowerCase().includes(term)
    );
    render();
  }

  // ----------------------------------------
  // Carga de la lista desde el backend
  // Intenta /api/guardados/list, si falla usa /api/guardados (alias)
  // ----------------------------------------
  async function loadList() {
    try {
      let r = await fetch('/api/guardados/list?ts=' + Date.now(), { cache: 'no-store' });
      let j = await r.json();
      const arr = Array.isArray(j.items) ? j.items
        : Array.isArray(j.archivos) ? j.archivos
          : [];
      items = arr;
      view = items.slice();
      render();
    } catch (e) {
      // Fallback a endpoint alias
      try {
        let r2 = await fetch('/api/guardados?ts=' + Date.now(), { cache: 'no-store' });
        let j2 = await r2.json();
        const arr2 = Array.isArray(j2.items) ? j2.items
          : Array.isArray(j2.archivos) ? j2.archivos
            : [];
        items = arr2;
        view = items.slice();
        render();
      } catch (err) {
        console.error('No se pudo cargar la lista:', err);
        items = []; view = [];
        render();
      }
    }
  }

  // ----------------------------------------
  // Modal: abrir/cerrar previsualización TXT
  // ----------------------------------------
  async function openPreview(url, name) {
    modalTitle.textContent = name || 'Previsualización';
    modalBody.textContent = 'Cargando…';
    modalDownload.href = url || '#';
    modal.hidden = false;
    try {
      // Añadimos ts para evitar caché del navegador
      const r = await fetch(url + '?ts=' + Date.now(), { cache: 'no-store' });
      const txt = await r.text();
      // Sólo mostramos las primeras ~120 líneas
      const lines = txt.split(/\r?\n/).slice(0, 120).join('\n');
      modalBody.textContent = lines || '(vacío)';
    } catch (e) {
      modalBody.textContent = 'No se pudo cargar el archivo.';
    }
  }
  function closePreview() { modal.hidden = true; }

  // ----------------------------------------
  // Eventos de la barra superior / navegación
  // ----------------------------------------
  btnReload?.addEventListener('click', loadList);
  btnBack?.addEventListener('click', () => { location.href = '/pagina1.html'; });
  goMeasure?.addEventListener('click', () => { location.href = '/pagina1.html'; });
  goMeasure2?.addEventListener('click', () => { location.href = '/pagina1.html'; });

  // Buscador + limpiar
  q?.addEventListener('input', applyFilter);
  clearQ?.addEventListener('click', () => { q.value = ''; applyFilter(); });

  // Modal (cerrar por botones o al pulsar el fondo)
  modalClose?.addEventListener('click', closePreview);
  modalClose2?.addEventListener('click', closePreview);
  modal.addEventListener('click', (e) => {
    if (e.target.classList.contains('modal__backdrop')) closePreview();
  });

  // ----------------------------------------
  // Delegación de eventos en la grid de tarjetas
  //  - Previsualizar: abre modal con primeras líneas del TXT
  //  - Eliminar: confirma y llama al endpoint de borrado
  // ----------------------------------------
  grid.addEventListener('click', async (e) => {
    const btn = e.target.closest('button, a');
    if (!btn) return;

    // Previsualizar TXT (modal)
    const prevUrl = btn.getAttribute('data-preview');
    if (prevUrl) {
      const name = btn.getAttribute('data-name') || 'Archivo';
      e.preventDefault();
      openPreview(prevUrl, name);
      return;
    }

    // Eliminar guardado (POST /api/guardados/delete)
    const delName = btn.getAttribute('data-del');
    if (delName) {
      e.preventDefault();
      if (!confirm(`¿Eliminar "${delName}"?`)) return;
      try {
        const r = await fetch('/api/guardados/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: delName })
        });
        const j = await r.json();
        if (!r.ok || !j.ok) {
          alert(j.error || 'No se pudo eliminar.');
          return;
        }
        // Actualizamos la lista en memoria y re-renderizamos (mantiene el filtro activo)
        items = items.filter(it => it.name !== delName);
        applyFilter();
      } catch (err) {
        alert('Error al eliminar.');
      }
      return;
    }
  });

  // Carga inicial
  loadList();
});
