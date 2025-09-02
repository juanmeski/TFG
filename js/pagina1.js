/*
pagina1.js — (medición estándar)

- Controla el flujo de una sesión de muestreo: iniciar (stream de logs), detener+guardar,
  detener+borrar, y navegar a “Guardados”.
- Refresca los mapas (puntos y calor) generados en el servidor y permite mostrar/ocultar
  sus bloques.
- Cambia la frecuencia del equipo activo validando el formato (MHz con punto decimal).
- Lanza la generación del análisis (PNG + Plotly interactivo) con la paleta seleccionada,
  y pinta los “snippets” del punto máximo (resumen, detalles, fotos).
- Aplica recargas “sin caché” para evitar imágenes/iframes obsoletos y hace un
  auto-refresh ligero de los snippets cada 5 s.

*/

// --------------------- Utilidades ---------------------
/** Lee texto de una URL añadiendo ?ts=... para saltarse caché. */
async function fetchTextNoCache(url) {
  const ts = Date.now();
  const r = await fetch(`${url}?ts=${ts}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status} en ${url}`);
  return r.text();
}

/** Fuerza recarga de una <img> agregando un timestamp. */
function forceReloadImg(id, url) {
  const el = document.getElementById(id);
  if (el) el.src = `${url}?ts=${Date.now()}`;
}

/** Fuerza recarga de un <iframe> agregando un timestamp. */
function forceReloadIframe(id, url) {
  const el = document.getElementById(id);
  if (el) el.src = `${url}?ts=${Date.now()}`;
}

// --------------------- Pintar Top Snippets ---------------------
async function pintarTopSnippets() {
  const dato1 = document.getElementById("dato1");
  const det = document.getElementById("top_details");
  const gal = document.getElementById("fotos_top");

  try {
    const [summary, details, photos] = await Promise.all([
      fetchTextNoCache("/analysis/top_summary.txt"),
      fetchTextNoCache("/analysis/top_details.html"),
      fetchTextNoCache("/analysis/top_photos.html"),
    ]);

    if (dato1) dato1.textContent = (summary || "").trim();
    if (det) det.innerHTML = details || "";
    if (gal) gal.innerHTML = photos || "";

    console.log("[Top] Pintado OK:",
      {
        summaryLen: (summary || "").length,
        detailsLen: (details || "").length,
        photosLen: (photos || "").length
      });
  } catch (e) {
    console.error("[Top] Error pintando snippets:", e);
    if (dato1) dato1.textContent = "No se pudo cargar el punto máximo.";
  }
}

// --------------------- Empezar medición ---------------------
document.getElementById('ejecutar')?.addEventListener('click', async function () {
  const log = document.getElementById("logArea");
  if (log) log.value = "";

  // Pregunta periodo de muestreo (segundos)
  const val = prompt("Segundos por muestra (ej. 5):", "5");
  if (val === null) return;
  const secs = parseFloat(val);
  if (!(secs > 0)) {
    alert("Introduce un número válido (> 0) para los segundos por muestra");
    return;
  }

  // Lanza el proceso principal (python/Main.py) y muestra su stdout en tiempo rea
  const resp = await fetch('/ejecutar-script', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sample_seconds: secs })
  });

  if (!resp.ok || !resp.body) {
    let msg = "No se pudo iniciar la medición";
    try { const j = await resp.json(); if (j.message) msg = j.message; } catch { }
    alert(msg);
    return;
  }

  // Lectura del stream línea a línea
  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (log) {
      log.value += decoder.decode(value);
      log.scrollTop = log.scrollHeight;
    }
  }
});



// --------------------- Detener y GUARDAR ---------------------
document.getElementById('detenerGuardar')?.addEventListener('click', async () => {
  const r = await fetch('/detener-guardar', { method: 'POST' });
  const j = await r.json().catch(() => ({ ok: false }));
  if (j.ok) {
    alert(`Guardado en ${j.file}\nEquipo: ${j.equipo}\nFilas: ${j.rows}`);
  } else {
    alert(j.msg || j.error || 'No se pudo guardar (tal vez no había datos).');
  }
  location.reload();
});

// --------------------- Detener y BORRAR (sin guardar) ---------------------
document.getElementById('detenerBorrar')?.addEventListener('click', async () => {
  const r = await fetch('/detener-borrar', { method: 'POST' });
  const j = await r.json().catch(() => ({ ok: false }));
  if (j.ok) {
    alert('Medición detenida y datos borrados.');
  } else {
    alert(j.error || 'Error al borrar/detener.');
  }
  location.reload();
});


// --------------------- Actualizar mapas (puntos y calor) ---------------------
document.addEventListener("DOMContentLoaded", function () {
  document.getElementById("actualizarMapa")?.addEventListener("click", function () {
    fetch("/generar-mapa", { method: "POST" })
      .then(r => r.json())
      .then(() => {
        forceReloadIframe("mapaFrame", "/map/mapa_puntos.html");
        forceReloadIframe("mapaFrame1", "/map/mapa_calor.html");
      })
      .catch(e => console.error("Error al actualizar el mapa:", e));
  });
});

// --------------------- Mostrar/ocultar mapas ---------------------
document.getElementById('toggleButton')?.addEventListener('click', function () {
  const bloque = document.getElementById('bloque3');
  const button = document.getElementById('toggleButton');
  if (!bloque || !button) return;

  const visible = getComputedStyle(bloque).display !== 'none';
  bloque.style.display = visible ? 'none' : 'block';
  button.textContent = visible ? 'Mostrar mapa de puntos muestreo ➡' : '⬅ Cerrar mapa';
  button.style.fontWeight = 'bold';
});

document.getElementById('toggleButton1')?.addEventListener('click', function () {
  const bloque = document.getElementById('bloque4');
  const button = document.getElementById('toggleButton1');
  if (!bloque || !button) return;

  const visible = getComputedStyle(bloque).display !== 'none';
  bloque.style.display = visible ? 'none' : 'block';
  button.textContent = visible ? 'Mostrar mapa de calor muestreo ➡' : '⬅ Cerrar mapa';
  button.style.fontWeight = 'bold';
});

// --------------------- Cambiar frecuencia ---------------------
document.getElementById('cambiarFrecuenciaBtn')?.addEventListener('click', async () => {
  const elIn = document.getElementById('inputVariable');
  const elOut = document.getElementById('valor_var1');
  if (!elIn) return;

  // Permite decimales con punto (concorde con la validación del backend)
  let frecuencia = (elIn.value || "").trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(frecuencia)) {
    alert('Introduce un número válido en MHz (ej.: 433.92)');
    return;
  }

  try {
    const r = await fetch('/cambiar_frecuencia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ frecuencia })
    });
    const j = await r.json();
    if (j.ok) {
      if (elOut) elOut.textContent = j.mensaje + (j.echo ? ` (eco: ${j.echo})` : "");
    } else {
      alert(j.mensaje || 'No se pudo cambiar la frecuencia');
    }
  } catch (e) {
    alert('Error de red al cambiar la frecuencia');
  }
});


// --------------------- Actualizar análisis (PNG + Interactivo + Top) ---------------------
document.getElementById('actualizarGrafico')?.addEventListener('click', async () => {
  const select = document.getElementById('selectCmap');
  const cmap = select ? select.value : 'RdYlGn_r';

  console.log("[Analisis] solicitando /actualizar_grafico con cmap:", cmap);
  const res = await fetch(`/actualizar_grafico?cmap=${encodeURIComponent(cmap)}`, { cache: "no-store" });
  let j = {};
  try { j = await res.json(); } catch { }
  if (!res.ok || j.status !== 'ok') {
    console.error('[Analisis] No se pudo regenerar el gráfico', j);
    alert('No se pudo regenerar el gráfico');
    return;
  }
  // Recarga de la imagen PNG y del HTML interactivo
  forceReloadImg("grafico", "/grafico");
  forceReloadIframe("iframeInteractivo", "/analysis/muestreo_interactivo.html");
  // “Snippets” del punto máximo (resumen/detalles/fotos)
  await pintarTopSnippets();
});

// --------------------- Carga inicial ---------------------
document.addEventListener("DOMContentLoaded", () => {
  pintarTopSnippets();// pinta al entrar en la página
});

// Ver mediciones guardadas: parar medición y navegar
document.getElementById('MedicionesGuardadas')?.addEventListener('click', async () => {
  try {
    // Parar medición actual y asegurar salida del bucle (borra Potencia.txt)
    await fetch('/fin-y-guardados', { method: 'POST' });
  } catch (e) {
    console.warn('fin-y-guardados fallo (ignorable):', e);
  }
  // Ir a la página de guardados
  window.location.href = '/guardados';
});

// --------------------- Enlace rápido a Medición 360° ---------------------
document.getElementById('medicion360Btn')?.addEventListener('click', async () => {

  try { await fetch('/detener-borrar', { method: 'POST' }); } catch (e) { }
  // Navega a la página de medición 360
  window.location.href = '/medicion360';
});

// refresco periódico de los snippets superiores (resumen/detalles/fotos)
setInterval(() => {
  try { pintarTopSnippets(); } catch (e) { console.warn('topSnippets:', e); }
}, 5000);