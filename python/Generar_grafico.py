# -----------------------------------------------------------------------------
#   Función: Generar_grafico.py: Genera los gráficos que serviran para analizar los datos obtenidos en el muestreo
#  - analysis/analisis_potencia.png (4 paneles)
#  - analysis/muestreo_interactivo.html (Plotly con EXACTO layout y controles que en pagina1.html)
#  - analysis/top_summary.txt, top_details.html, top_photos.html
#  - Datos obtenidos: fecha,hora,dbm,acimut,lat,long
#  - Donde se guardan:guardado/save_X(...)/data.txt con filas: fecha,hora,lat,long,acimut,dbm
# -----------------------------------------------------------------------------


import os
import re
import sys
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # backend sin GUI para generar archivos en servidores o .exe
import matplotlib.pyplot as plt
from scipy.interpolate import griddata
from scipy.signal import find_peaks

# Ruta raíz del proyecto (carpeta padre de /python)
ROOT_DIR = Path(__file__).resolve().parent.parent

# ------------------ CLI ------------------
# Parser de argumentos para permitir:
#   --input       archivo de datos (Potencia.txt en vivo o data.txt de guardado)
#   --outdir      carpeta de salida para PNG/HTML/snippets
#   --framesdir   carpeta de frames opcional (si no, se infiere)
#   --capturasdir carpeta de capturas opcional (si no, se infiere)
#   --cmap        colormap Matplotlib (ej. inferno_r, RdYlGn_r, ...)
parser = argparse.ArgumentParser(description="Generar análisis desde Potencia.txt/data.txt.")
parser.add_argument("--input", default=str(ROOT_DIR / "txt" / "Potencia.txt"),
                    help="Ruta al archivo de datos (en vivo o guardado).")
parser.add_argument("--outdir", default=str(ROOT_DIR / "analysis"),
                    help="Directorio de salida para imágenes/HTML.")
parser.add_argument("--framesdir", default=None, help="Carpeta de frames (opcional).")
parser.add_argument("--capturasdir", default=None, help="Carpeta de capturas (opcional).")
parser.add_argument("--cmap", default=None, help="Colormap Matplotlib (inferno_r, RdYlGn_r, ...).")
# compat: `python generar_grafico.py inferno_r`
parser.add_argument("cmap_pos", nargs="?", default=None, help=argparse.SUPPRESS)
args = parser.parse_args()

# cmap (posicional > flag > por defecto)
cmap_name = (args.cmap_pos or args.cmap or "RdYlGn_r")
if cmap_name not in plt.colormaps():
    cmap_name = "RdYlGn_r"

IN_PATH  = Path(args.input).resolve()
OUT_DIR  = Path(args.outdir).resolve(); OUT_DIR.mkdir(parents=True, exist_ok=True)
PNG_PATH = OUT_DIR / "analisis_potencia.png"
HTML_INTERACTIVO = OUT_DIR / "muestreo_interactivo.html"
SNIPPET_SUMMARY  = OUT_DIR / "top_summary.txt"
SNIPPET_DETAILS  = OUT_DIR / "top_details.html"
SNIPPET_PHOTOS   = OUT_DIR / "top_photos.html"

# Detección de directorios frames/capturas si no se pasan por CLI:
#   - si el input está dentro de un guardado (save_*), se usan sus subcarpetas
#   - si no, se usan las carpetas globales del proyecto
if args.framesdir:
    FRAMES_DIR = Path(args.framesdir).resolve()
else:
    FRAMES_DIR = (IN_PATH.parent / "frames") if IN_PATH.parent.name.startswith("save_") else (ROOT_DIR / "frames")
if args.capturasdir:
    CAPTURAS_DIR = Path(args.capturasdir).resolve()
else:
    CAPTURAS_DIR = (IN_PATH.parent / "capturas") if IN_PATH.parent.name.startswith("save_") else (ROOT_DIR / "capturas")

# ------------------ Utils ------------------

######################################
# funcion _is_date_prefix: comprueba si una cadena empieza con un prefijo de fecha AAAA-MM-DD para distinguir líneas de encabezado o de equipo
######################################
def _is_date_prefix(s: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", str(s or "").strip()))

######################################
# funcion _fmt_num: intenta formatear un valor como número con formato dado devolviendo '—' si no es finito o no convertible
######################################
def _fmt_num(v, fmt="{:.6f}"):
    try:
        v = float(v)
        if not np.isfinite(v): return "—"
        return fmt.format(v)
    except Exception:
        return "—"

######################################
# funcion _public_url: convierte una ruta absoluta a ruta pública relativa al ROOT_DIR para ser servida vía Flask devolviendo None si no se puede relativizar
######################################
def _public_url(p: Path) -> str | None:
    try:
        rel = p.resolve().relative_to(ROOT_DIR)
        return "/" + str(rel).replace("\\", "/")
    except Exception:
        return None

# ------------------ Lectura robusta ------------------

######################################
# funcion leer_datos: carga Potencia.txt o data.txt y normaliza columnas a fecha hora dbm acimut lat long aceptar tanto formato “en vivo” como “guardado” saltando encabezados o la línea de equipo si existe
######################################
def leer_datos(path: Path) -> pd.DataFrame:
    
    #Devuelve columnas normalizadas: fecha,hora,dbm,acimut,lat,long
    #  - En vivo:  fecha,hora,dbm,acimut,lat,long
    #  - Guardado: fecha,hora,lat,long,acimut,dbm
    #Salta 1ª línea si no es fecha (nombre de equipo) y cabecera "fecha,..." si aparece.
    
    if not path.exists():
        print(f"[generar_grafico] AVISO: no existe {path}", flush=True)
        return pd.DataFrame(columns=["fecha","hora","dbm","acimut","lat","long"])

    # Lee texto completo, ignora líneas vacías, y limpia espacios
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        raw = path.read_text(errors="ignore").splitlines()
    raw = [ln.strip() for ln in raw if ln.strip()]
    
    # Si la primera línea no empieza con fecha, suele ser el nombre del equipo -> descártala
    if raw and not _is_date_prefix(raw[0].split(",")[0]):  # línea equipo
        raw = raw[1:]
         # Si hay cabecera "fecha,...", descártala
    if raw and re.match(r"^\s*fecha\s*,", raw[0], re.IGNORECASE):  # cabecera
        raw = raw[1:]
    if not raw:
        return pd.DataFrame(columns=["fecha","hora","dbm","acimut","lat","long"])
   
    # Carga CSV robusto con separadores comunes
    from io import StringIO
    sio = StringIO("\n".join(raw))
    try:
        df = pd.read_csv(sio, header=None, engine="python", sep=r"[,\t;]+")
    except Exception:
        sio.seek(0)
        df = pd.read_csv(sio, header=None)

    # Asegura 6 columnas y normaliza nombres temporales
    if df.shape[1] < 6:
        for _ in range(6 - df.shape[1]):
            df[df.shape[1]] = np.nan
    df = df.iloc[:, :6].copy()
    df.columns = ["c0","c1","c2","c3","c4","c5"]
  
    # Detecta si c2 es dbm (en vivo) o lat (guardado) viendo el porcentaje de valores dentro de rango típico dBm
    c2 = pd.to_numeric(df["c2"], errors="coerce")  # vivo: dbm ; guardado: lat

    def frac_dbm(s: pd.Series) -> float:
        arr = s.to_numpy(dtype=float)
        mask = np.isfinite(arr)
        if not mask.any(): return 0.0
        rng = (arr[mask] >= -200) & (arr[mask] <= -5)
        return float(rng.mean())

    if frac_dbm(c2) >= 0.5:
        # EN VIVO: columnas ya vienen como dbm en c2
        out = pd.DataFrame({
            "fecha": df["c0"].astype(str),
            "hora":  df["c1"].astype(str),
            "dbm":   pd.to_numeric(df["c2"], errors="coerce"),
            "acimut":pd.to_numeric(df["c3"], errors="coerce"),
            "lat":   pd.to_numeric(df["c4"], errors="coerce"),
            "long":  pd.to_numeric(df["c5"], errors="coerce"),
        })
    else:
        # GUARDADO: data.txt trae lat/long en c2/c3 y dbm en c5
        out = pd.DataFrame({
            "fecha": df["c0"].astype(str),
            "hora":  df["c1"].astype(str),
            "dbm":   pd.to_numeric(df["c5"], errors="coerce"),
            "acimut":pd.to_numeric(df["c4"], errors="coerce"),
            "lat":   pd.to_numeric(df["c2"], errors="coerce"),
            "long":  pd.to_numeric(df["c3"], errors="coerce"),
        })

    # Descarta filas sin dbm y reinicia índices
    out = out.dropna(subset=["dbm"]).reset_index(drop=True)
    return out

# ------------------ Cargar datos ------------------
datos = leer_datos(IN_PATH)
x = datos["long"].to_numpy() if "long" in datos else np.array([])
y = datos["lat"].to_numpy()  if "lat"  in datos else np.array([])
z = datos["dbm"].to_numpy()  if "dbm"  in datos else np.array([])
az = datos["acimut"].to_numpy() if "acimut" in datos else np.array([])

# Índice del punto con máxima potencia (para snippets)
idx_max = int(np.nanargmax(z)) if len(z) else None

# ------------------ Snippets top ------------------

######################################
# funcion escribir_snippets: genera los ficheros resumen del punto máximo incluyendo resumen texto detalles HTML y las fotos asociadas si existen en frames y capturas
######################################
def escribir_snippets():
    if idx_max is None or not (len(x) and len(y) and len(z)):
        # No hay datos: escribe placeholders vacíos
        SNIPPET_SUMMARY.write_text("Sin datos disponibles.\n", encoding="utf-8")
        SNIPPET_DETAILS.write_text("", encoding="utf-8")
        SNIPPET_PHOTOS.write_text("<em>Sin imágenes disponibles.</em>", encoding="utf-8")
        return

    # Extrae valores del punto máximo (seguro y con NaN-check)
    lat_val = y[idx_max] if np.isfinite(y[idx_max]) else None
    lon_val = x[idx_max] if np.isfinite(x[idx_max]) else None
    pot_val = z[idx_max] if np.isfinite(z[idx_max]) else None
    azi_val = az[idx_max] if len(az) and np.isfinite(az[idx_max]) else None

    fecha = str(datos.loc[idx_max, "fecha"])
    hora  = str(datos.loc[idx_max, "hora"])

    # Resumen simple (línea única)
    SNIPPET_SUMMARY.write_text(
        f"Muestra #{idx_max} — {_fmt_num(pot_val, '{:.1f}')} dBm ({fecha} {hora}) — "
        f"Lat {_fmt_num(lat_val)}, Lon {_fmt_num(lon_val)}\n", encoding="utf-8"
    )

    # Detalles formateados en HTML (tags visuales)
    details_html = f"""
<div class="tag">Muestra #{idx_max}</div>
<div class="tag">Potencia: <strong>{_fmt_num(pot_val, '{:.1f}')} dBm</strong></div>
<div class="tag">Lat: <strong>{_fmt_num(lat_val)}</strong></div>
<div class="tag">Lon: <strong>{_fmt_num(lon_val)}</strong></div>
<div class="tag">Azimut: <strong>{'—' if azi_val is None else f'{azi_val:.1f}°'}</strong></div>
<div class="tag">Fecha/Hora: <strong>{fecha} {hora}</strong></div>
""".strip()
    SNIPPET_DETAILS.write_text(details_html, encoding="utf-8")

    # Búsqueda de imágenes asociadas (frame_{idx}.* y captura_{idx}.*)
    def buscar_img(dir_path: Path, stem: str):
        for ext in (".jpg",".jpeg",".png",".webp",".JPG",".JPEG",".PNG",".WEBP"):
            p = (dir_path / f"{stem}{ext}").resolve()
            if p.exists():
                return _public_url(p), p
        return None, None

    figs = []
    u, p = buscar_img(FRAMES_DIR, f"frame_{idx_max}")
    if p: figs.append(f'<figure><img src="{u or ""}" alt="Frame {idx_max}"><figcaption>Frame del punto</figcaption></figure>')
    u, p = buscar_img(CAPTURAS_DIR, f"captura_{idx_max}")
    if p: figs.append(f'<figure><img src="{u or ""}" alt="Captura {idx_max}"><figcaption>Captura del punto</figcaption></figure>')
    SNIPPET_PHOTOS.write_text(("".join(figs) if figs else "<em>Sin imágenes disponibles.</em>"), encoding="utf-8")

# Genera los snippets inmediatamente
escribir_snippets()

# ------------------ Interpolación para mapas estáticos ------------------
# Malla de interpolación (si hay pocos puntos cae a mallas 2x2 para evitar errores)
if len(x) >= 2 and len(y) >= 2:
    gx = np.linspace(np.nanmin(x), np.nanmax(x), 100)
    gy = np.linspace(np.nanmin(y), np.nanmax(y), 100)
else:
    gx = np.linspace(np.nanmin(x) if len(x) else 0, np.nanmax(x) if len(x) else 1, 2)
    gy = np.linspace(np.nanmin(y) if len(y) else 0, np.nanmax(y) if len(y) else 1, 2)

grid_x, grid_y = np.meshgrid(gx, gy)
# Interpolación robusta: intenta cubic -> linear -> nearest
try:
    grid_z = griddata((x, y), z, (grid_x, grid_y), method='cubic')
    if np.all(np.isnan(grid_z)):
        raise ValueError("grid_z NaN con cubic")
except Exception:
    try:
        grid_z = griddata((x, y), z, (grid_x, grid_y), method='linear')
    except Exception:
        grid_z = griddata((x, y), z, (grid_x, grid_y), method='nearest')

# ------------------ PNG 4 paneles ------------------

######################################
# funcion generar_png: crea un PNG con cuatro paneles superficie 3D mapa de calor dispersión por puntos y detección de picos temporales guardándolo en analysis/analisis_potencia.png
######################################
def generar_png():
    if not len(z):
        # Si no hay datos, borra el PNG previo (si existe) y sale
        try:
            if PNG_PATH.exists(): PNG_PATH.unlink()
        except Exception: pass
        return

    fig = plt.figure(figsize=(10, 10))
    fig.suptitle("Análisis de Potencia", fontsize=16)

    # 1) Superficie 3D
    ax3d = fig.add_subplot(221, projection='3d')
    surf = ax3d.plot_surface(grid_x, grid_y, grid_z, cmap=cmap_name, edgecolor='none')
    ax3d.set_title("Distribución Potencia")
    ax3d.set_xlabel("Longitud"); ax3d.set_ylabel("Latitud")
    ax3d.set_xticklabels([]); ax3d.set_yticklabels([]); ax3d.set_zticklabels([])
    fig.colorbar(surf, ax=ax3d, label="Potencia (dBm)")

    # 2) Mapa de calor
    ax2 = fig.add_subplot(222)
    im = ax2.imshow(
        grid_z,
        extent=(np.nanmin(gx), np.nanmax(gx), np.nanmin(gy), np.nanmax(gy)),
        origin='lower',
        cmap=cmap_name
    )
    ax2.set_title("Mapa de Calor (dBm)")
    ax2.set_xlabel("Longitud"); ax2.set_ylabel("Latitud")
    ax2.set_xticklabels([]); ax2.set_yticklabels([])
    fig.colorbar(im, ax=ax2, label="Potencia (dBm)")

    # 3) Puntos (SIN líneas de acimut)
    ax3 = fig.add_subplot(223)
    sc = ax3.scatter(x, y, c=z, cmap=cmap_name, alpha=0.85)
    ax3.set_title("Puntos (dBm)")
    ax3.set_xlabel("Longitud"); ax3.set_ylabel("Latitud")
    ax3.set_xticklabels([]); ax3.set_yticklabels([])
    fig.colorbar(sc, ax=ax3)

    # 4) Picos
    ax4 = fig.add_subplot(224)
    vals = z
    finite = np.isfinite(vals)
    thr = np.percentile(vals[finite], 90) if finite.any() else np.nan
    peaks, _ = (find_peaks(vals, height=thr, distance=3)
                if len(vals) and not np.isnan(thr) else (np.array([], dtype=int), {}))
    ax4.plot(range(len(vals)), vals, label="Potencia")
    if len(peaks):
        ax4.scatter(peaks, vals[peaks], color="red", label="Pico/s", zorder=5)
    if not np.isnan(thr):
        ax4.axhline(thr, color="orange", linestyle="--", label=f"Umbral {thr:.1f} dBm")
    ax4.set_title("Picos en el tiempo")
    ax4.set_xlabel("Orden nº Muestras")
    ax4.legend(fontsize=8)
    ax4.grid(True, alpha=0.3, linestyle="--", linewidth=0.5)

    plt.tight_layout(rect=[0, 0.03, 1, 0.97])
    plt.savefig(PNG_PATH, dpi=300)
    plt.close(fig)
    print(f"[generar_grafico] PNG guardado en {PNG_PATH}", flush=True)

# ------------------ Plotly (EXACTO al de pagina1.html) ------------------

######################################
# funcion _plotly_layout_pagina1: devuelve el layout unificado para plotly igual al usado en pagina1 evitando solapes con título leyenda botones y slider ajustando márgenes y standoff
######################################
def _plotly_layout_pagina1():
    
    #Layout unificado:
    #  - leyenda horizontal arriba, correctamente dentro del lienzo
    #  - márgenes generosos para no solapar ni con botones ni con slider
    #  - títulos de ejes con standoff para separarlos del slider
    
    return dict(
        title="Recorrido de muestreo interactivo",
        xaxis_title="Longitud", yaxis_title="Latitud",
        xaxis=dict(scaleanchor="y", scaleratio=1, showgrid=True, title_standoff=24),
        yaxis=dict(showgrid=True, title_standoff=24),
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.12,   # más arriba que antes para evitar choques con título
            xanchor="left",   x=0.0     # <-- (antes x=4 causaba solapes raros)
        ),
        margin=dict(l=50, r=30, t=170, b=170)  # margen superior e inferior más amplios
    )

######################################
# funcion generar_plotly: crea el HTML interactivo con plotly mostrando ruta puntos coloreados por dBm marcador del máximo y animación con slider y controles guardándolo en analysis/muestreo_interactivo.html
######################################
def generar_plotly():
    try:
        import plotly.express as px
        import plotly.graph_objects as go
        from plotly.offline import plot as plot_offline
    except Exception:
        # Si no está Plotly, se omite el interactivo (no rompe el resto)
        print("[generar_grafico] AVISO: Plotly no está instalado. Interactivo no generado.", file=sys.stderr)
        try:
            if HTML_INTERACTIVO.exists(): HTML_INTERACTIVO.unlink()
        except Exception: pass
        return

    # Índice de muestra para hover y animación
    df = datos.copy().reset_index(drop=True)
    if df.empty:
        HTML_INTERACTIVO.write_text("<html><body><em>Sin datos.</em></body></html>", encoding="utf-8")
        print(f"[generar_grafico] Interactivo vacío en {HTML_INTERACTIVO}", flush=True)
        return

    # Índice de muestra para hover y animación
    df["muestra"] = np.arange(len(df))
    
    # etiqueta acimut legible
    def _fmt_az(v):
        try:
            f = float(v)
            if np.isfinite(f): return f"{f:.1f}°"
        except Exception:
            pass
        return "no directivo"
    df["az_label"] = df["acimut"].map(_fmt_az)

    # Ruta semitransparente (contexto) y puntos coloreados por potencia
    ruta = go.Scatter(
        x=df["long"], y=df["lat"], mode="markers",
        marker=dict(size=6),
        name="Ruta completa",
        hoverinfo="skip",
        opacity=0.25
    )
    puntos = go.Scatter(
        x=df["long"], y=df["lat"], mode="markers",
        marker=dict(size=8, color=df["dbm"], colorscale="RdYlGn_r",
                    colorbar=dict(title="Potencia (dBm)")),
        name="Puntos (potencia)",
        hovertemplate=(
            "<b>Muestra %{customdata[0]}</b><br>"
            "Fecha: %{customdata[2]}<br>"
            "Hora: %{customdata[3]}<br>"
            "Lat: %{y:.6f}<br>Lon: %{x:.6f}<br>"
            "Pot: %{customdata[1]:.1f} dBm<br>"
            "%{customdata[4]}<extra></extra>"
        ),
        customdata=np.stack([df["muestra"], df["dbm"], df["fecha"], df["hora"], df["az_label"]], axis=1)
    )

    data_traces = [ruta, puntos]

    # Punto máximo resaltado
    try:
        i_max = int(np.nanargmax(df["dbm"].to_numpy()))
    except Exception:
        i_max = None
    if i_max is not None:
        data_traces.append(
            go.Scatter(
                x=[df.loc[i_max, "long"]], y=[df.loc[i_max, "lat"]],
                mode="markers+text",
                marker=dict(size=18, color="red", line=dict(width=2, color="black"), symbol="star"),
                text=["MAX"], textposition="top center",
                name="Punto máximo",
                hovertemplate=(
                    "<b>Punto máximo</b><br>"
                    "Muestra %{customdata[0]}<br>"
                    "Fecha: %{customdata[2]}<br>"
                    "Hora: %{customdata[3]}<br>"
                    "Lat: %{y:.6f}<br>Lon: %{x:.6f}<br>"
                    "Pot: %{customdata[1]:.1f} dBm<br>"
                    "%{customdata[4]}<extra></extra>"
                ),
                customdata=np.array([[
                    df.loc[i_max, "muestra"], df.loc[i_max, "dbm"],
                    df.loc[i_max, "fecha"],   df.loc[i_max, "hora"],
                    df.loc[i_max, "az_label"]
                ]], dtype=object)
            )
        )

    # Construye figura con layout unificado
    fig = go.Figure(data=data_traces)
    fig.update_layout(**_plotly_layout_pagina1())

    # Frames de animación: un marcador grande que “recorre” las muestras
    frames = []
    p_min, p_max = df["dbm"].min(), df["dbm"].max()
    den = max(1e-9, (p_max - p_min))
    for i in range(len(df)):
        frac = (df.loc[i, "dbm"] - p_min) / den
        color_i = px.colors.sample_colorscale("RdYlGn_r", frac)[0]
        frames.append(go.Frame(
            name=str(i),
            data=[go.Scatter(
                x=[df.loc[i, "long"]], y=[df.loc[i, "lat"]],
                mode="markers",
                marker=dict(size=14, color=color_i, line=dict(width=1)),
                customdata=np.array([[
                    df.loc[i, "muestra"], df.loc[i, "dbm"],
                    df.loc[i, "fecha"],   df.loc[i, "hora"],
                    df.loc[i, "az_label"]
                ]], dtype=object),
                hovertemplate=(
                    "<b>Muestra %{customdata[0]}</b><br>"
                    "Fecha: %{customdata[2]}<br>"
                    "Hora: %{customdata[3]}<br>"
                    "Lat: %{y:.6f}<br>Lon: %{x:.6f}<br>"
                    "Pot: %{customdata[1]:.1f} dBm<br>"
                    "%{customdata[4]}<extra></extra>"
                ),
                name="Muestra actual"
            )],
            traces=[len(data_traces)]  # se añadirá el trace al final
        ))
    fig.add_trace(go.Scatter(x=[], y=[], mode="markers", marker=dict(size=14), name="Muestra actual"))

    # Slider + botones (posicionados para no tapar títulos/ejes)
    frame_names = [str(i) for i in range(len(df))]
    SPEED_MS = 1000
    TRANS_MS = int(SPEED_MS * 0.25)
    fig.frames = frames

    steps = [
        dict(
            method="animate",
            args=[[str(i)], {
                "mode": "immediate",
                "frame": {"duration": SPEED_MS, "redraw": True},
                "transition": {"duration": TRANS_MS}
            }],
            label=str(i)
        ) for i in range(len(df))
    ]
    # Slider y botones con más separación para NO tapar títulos/ejes
    fig.update_layout(
        sliders=[dict(
            steps=steps, active=0,
            x=0.0, xanchor="left",
            y=-0.12, yanchor="top",          # <-- más abajo que antes
            currentvalue={"prefix": "Muestra: ", "visible": True},
            pad={"t": 0, "b": 0},
            transition={"duration": 0}
        )],
        updatemenus=[dict(
            type="buttons", direction="right",
            x=0.0, y=1.42, xanchor="left", yanchor="bottom",  # <-- un pelín más arriba
            pad={"r": 10, "t": 6}, showactive=False,
            buttons=[
                dict(label="▶️ Reproducir", method="animate",
                     args=[None, {"fromcurrent": True, "mode": "immediate",
                                  "frame": {"duration": SPEED_MS, "redraw": True},
                                  "transition": {"duration": TRANS_MS}}]),
                dict(label="⏸ Pausa", method="animate",
                     args=[[None], {"mode": "immediate",
                                    "frame": {"duration": 0, "redraw": False},
                                    "transition": {"duration": 0}}]),
                dict(label="⏮ Inicio", method="animate",
                     args=[[frame_names[0]] if frame_names else [None],
                          {"mode": "immediate",
                           "frame": {"duration": 0, "redraw": True},
                           "transition": {"duration": 0}}]),
                dict(label="▶️ Reproducir desde inicio", method="animate",
                     args=[frame_names if frame_names else [None],
                           {"mode": "immediate",
                            "frame": {"duration": SPEED_MS, "redraw": True},
                            "transition": {"duration": TRANS_MS}}]),
                dict(label="⏭ Fin", method="animate",
                     args=[[frame_names[-1]] if frame_names else [None],
                           {"mode": "immediate",
                            "frame": {"duration": 0, "redraw": True},
                            "transition": {"duration": 0}}]),
            ]
        )]
    )

    # Misma config que en pagina1: sin logo, con barra de modo
    config = dict(displaylogo=False, displayModeBar=True)

    # Exporta a HTML estático con Plotly offline
    from plotly.offline import plot as plot_offline
    plot_offline(fig, filename=str(HTML_INTERACTIVO), include_plotlyjs=True, auto_open=False, config=config)
    print(f"[generar_grafico] Interactivo guardado en {HTML_INTERACTIVO}", flush=True)

# ------------------ Run ------------------
try:
    generar_png()
    generar_plotly()
    print("[generar_grafico] OK fin generar_grafico", flush=True)
except Exception as e:
    print("generar_grafico.py falló", file=sys.stderr)
    print(e, file=sys.stderr)
