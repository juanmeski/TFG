# -----------------------------------------------------------------------------
#   Función: server.py: Servidor Flask de toda la aplicación.
#   Sirve ficheros estáticos (HTML/CSS/JS/medios),
#   lanza y detiene los procesos de adquisición (PR100 o simulador) con streaming de logs,
#   gestiona guardados de mediciones en carpetas, genera gráficos y mapas, expone APIs
#   para Medición 360°, comprime guardados a ZIP y ofrece utilidades como cambiar la
#   frecuencia del PR100. Las rutas están organizadas por bloques: estáticos, proceso
#   principal, utilidades de lectura y guardado, APIs de 360°, y compresión de resultados.
# -----------------------------------------------------------------------------
from flask import Flask, request, jsonify, send_from_directory, Response, send_file
import os
import sys
import signal
import subprocess
from datetime import datetime
import re
import shutil
from glob import glob
import io
import zipfile
from pathlib import Path

import pandas as pd
import numpy as np
from pandas.errors import EmptyDataError, ParserError

# ====== CONFIG ======
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

HTML_DIR     = os.path.join(ROOT_DIR, "html")
CSS_DIR      = os.path.join(ROOT_DIR, "css")
JS_DIR       = os.path.join(ROOT_DIR, "js")
VIDEO_DIR    = os.path.join(ROOT_DIR, "video")
IMAGES_DIR   = os.path.join(ROOT_DIR, "images")
JSON_DIR     = os.path.join(ROOT_DIR, "json")
ANIMATED_DIR = os.path.join(ROOT_DIR, "animated")
MAP_DIR      = os.path.join(ROOT_DIR, "map")
FRAMES_DIR   = os.path.join(ROOT_DIR, "frames")
CAPT_DIR     = os.path.join(ROOT_DIR, "capturas")
TXT_DIR      = os.path.join(ROOT_DIR, "txt")
PY_DIR       = os.path.join(ROOT_DIR, "python")
ANALYSIS_DIR = os.path.join(ROOT_DIR, "analysis")
GUARDADO_DIR = os.path.join(ROOT_DIR, "guardado")

# 360°
GUARDADO360_DIR = os.path.join(ROOT_DIR, "guardado360")
os.makedirs(GUARDADO360_DIR, exist_ok=True)

os.makedirs(ANALYSIS_DIR, exist_ok=True)
os.makedirs(GUARDADO_DIR, exist_ok=True)

EQUIPO_ACTUAL = os.environ.get("EQUIPO_ACTUAL", "PR100")

app = Flask(__name__, template_folder='html')

# ======================================================================
#                          RUTAS ESTÁTICAS
# ======================================================================

######################################
# funcion home: sirve la página principal index.html desde la carpeta html
######################################
@app.route('/')
def home():
    return send_from_directory(HTML_DIR, 'index.html')

######################################
# funcion mostrar_pagina: sirve páginas numeradas /paginaN.html desde la carpeta html
######################################
@app.route('/pagina<int:num>.html')
def mostrar_pagina(num):
    return send_from_directory(HTML_DIR, f'pagina{num}.html')

######################################
# funcion view_guardados: sirve la vista de mediciones guardadas guardados.html
######################################
@app.route('/guardados')
def view_guardados():
    return send_from_directory(HTML_DIR, "guardados.html")

######################################
# funcion view_ver_medicion_guardada: sirve la vista de detalle de una medición guardada
######################################
@app.route('/ver_medicion_guardada.html')
def view_ver_medicion_guardada():
    return send_from_directory(HTML_DIR, "ver_medicion_guardada.html")

######################################
# funcion medicion360_view: sirve la interfaz de Medición 360°
######################################
@app.route('/medicion360')
def medicion360_view():
    return send_from_directory(HTML_DIR, "medicion360.html")

######################################
# funcion ver_medicion360_view: sirve la vista para ver una medición 360° guardada
######################################
@app.route('/ver_medicion360.html')
def ver_medicion360_view():
    return send_from_directory(HTML_DIR, "ver_medicion360.html")

######################################
# funcion serve_css: sirve archivos CSS estáticos
######################################
@app.route('/css/<path:filename>')
def serve_css(filename): return send_from_directory(CSS_DIR, filename)

######################################
# funcion serve_js: sirve archivos JavaScript estáticos
######################################
@app.route('/js/<path:filename>')
def serve_js(filename): return send_from_directory(JS_DIR, filename)

######################################
# funcion serve_video: sirve archivos de vídeo estáticos
######################################
@app.route('/video/<path:filename>')
def serve_video(filename): return send_from_directory(VIDEO_DIR, filename)

######################################
# funcion serve_images: sirve imágenes estáticas
######################################
@app.route('/images/<path:filename>')
def serve_images(filename): return send_from_directory(IMAGES_DIR, filename)

######################################
# funcion serve_json: sirve archivos JSON estáticos
######################################
@app.route('/json/<path:filename>')
def serve_json(filename): return send_from_directory(JSON_DIR, filename)

######################################
# funcion serve_animated: sirve recursos animados estáticos
######################################
@app.route('/animated/<path:filename>')
def serve_animated(filename): return send_from_directory(ANIMATED_DIR, filename)

######################################
# funcion serve_map: sirve mapas HTML generados por folium
######################################
@app.route('/map/<path:filename>')
def serve_map(filename): return send_from_directory(MAP_DIR, filename)

######################################
# funcion serve_frames: sirve imágenes de frames generadas por el sistema
######################################
@app.route('/frames/<path:filename>')
def serve_frames(filename): return send_from_directory(FRAMES_DIR, filename)

######################################
# funcion serve_capturas_lc: sirve capturas en minúsculas /capturas/...
######################################
@app.route('/capturas/<path:filename>')
def serve_capturas_lc(filename): return send_from_directory(CAPT_DIR, filename)

######################################
# funcion serve_capturas_uc: alias para servir /Capturas/... por compatibilidad
######################################
@app.route('/Capturas/<path:filename>')
def serve_capturas_uc(filename): return send_from_directory(CAPT_DIR, filename)

######################################
# funcion serve_txt: sirve ficheros de texto (datos en vivo y otros)
######################################
@app.route('/txt/<path:filename>')
def serve_txt(filename): return send_from_directory(TXT_DIR, filename)

######################################
# funcion serve_python: sirve ficheros del directorio python (solo lectura)
######################################
@app.route('/python/<path:filename>')
def serve_python(filename): return send_from_directory(PY_DIR, filename)

######################################
# funcion serve_analysis: sirve salidas de análisis (png/html) forzando no cache
######################################
@app.route('/analysis/<path:filename>')
def serve_analysis(filename):
    resp = send_from_directory(ANALYSIS_DIR, filename)
    resp.headers['Cache-Control'] = 'no-store, max-age=0'
    return resp

######################################
# funcion serve_guardado: sirve cualquier archivo dentro de /guardado con rutas anidadas
######################################
@app.route('/guardado/<path:filename>')
def serve_guardado(filename):
    return send_from_directory(GUARDADO_DIR, filename)

######################################
# funcion serve_guardado360: sirve ficheros dentro de /guardado360
######################################
@app.route('/guardado360/<path:filename>')
def serve_guardado360(filename):
    return send_from_directory(GUARDADO360_DIR, filename)

# ======================================================================
#                      PROCESO MEDICIÓN (stream)
# ======================================================================
current_process = None

######################################
# funcion _stop_current_process_if_any: intenta detener con elegancia el subproceso en ejecución y lo fuerza si es necesario, limpiando el puntero global
######################################
def _stop_current_process_if_any(timeout=8):
    #Detiene el subproceso si existe.
    global current_process
    if current_process is not None and current_process.poll() is None:
        if hasattr(signal, "CTRL_BREAK_EVENT"):
            try: current_process.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception: pass
        try:
            current_process.wait(timeout=timeout)
        except Exception:
            current_process.terminate()
    current_process = None

######################################
# funcion _remove_file: elimina un fichero si existe, ignorando errores
######################################
def _remove_file(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

######################################
# funcion _remove_potencia_to_end_loop: borra txt/Potencia.txt para provocar salida limpia en los loops de adquisición
######################################
def _remove_potencia_to_end_loop():
    _remove_file(os.path.join(TXT_DIR, "Potencia.txt"))

######################################
# funcion ejecutar_script: lanza python/Main.py con SAMPLE_PERIOD opcional y devuelve la salida en streaming por HTTP
######################################
@app.route('/ejecutar-script', methods=['POST'])
def ejecutar_script():
   
    #Lanza python/Main.py y devuelve salida en streaming.
    #Lee sample_seconds del body para ajustar SAMPLE_PERIOD (simulador/PR100 lo usan).
    
    global current_process
    if current_process is not None and current_process.poll() is None:
        return jsonify({"message": "El script ya está en ejecución."}), 400

    try:
        data = request.get_json(silent=True) or {}
        secs = data.get("sample_seconds")

        env = os.environ.copy()
        if secs is not None:
            try:
                v = float(secs)
                if v > 0: env["SAMPLE_PERIOD"] = str(v)
            except Exception:
                pass

        creationflags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        current_process = subprocess.Popen(
            [sys.executable, os.path.join(PY_DIR, 'Main.py')],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=1, text=True, creationflags=creationflags, env=env
        )

        def generate():
            for line in iter(current_process.stdout.readline, ''):
                yield line
        return Response(generate(), content_type='text/plain')

    except Exception as e:
        return jsonify({"message": f"Error al ejecutar el script: {str(e)}"}), 500

######################################
# funcion detener_script: detiene el subproceso de adquisición si está en marcha
######################################
@app.route('/detener-script', methods=['POST'])
def detener_script():
    try:
        _stop_current_process_if_any()
        return jsonify({"message": "Script detenido correctamente!"})
    except Exception as e:
        return jsonify({"message": f"Error al detener el script: {str(e)}"}), 500

# ======================================================================
#                           LECTURA ROBUSTA
# ======================================================================
SEP_FLEX = r"[,\t;]\s*|(?:\s{2,})|(?:(?<=\d)\s+(?=\d))"

######################################
# funcion leer_potencia: lectura flexible del formato antiguo de Potencia.txt devolviendo columnas normalizadas fecha,hora,potencia
######################################
def leer_potencia(path):
    #Compat: lectura flexible del viejo Potencia.txt (3 columnas).
    if not os.path.exists(path):
        return pd.DataFrame(columns=["fecha","hora","potencia"])
    try:
        df = pd.read_csv(path, header=None, engine="python", sep=SEP_FLEX)
    except (EmptyDataError, ParserError):
        return pd.DataFrame(columns=["fecha","hora","potencia"])
    except Exception:
        try:
            df = pd.read_csv(path, header=None)
        except (EmptyDataError, ParserError):
            return pd.DataFrame(columns=["fecha","hora","potencia"])

    if df.shape[1] >= 3:
        df = df.iloc[:, :3].copy()
        df.columns = ["fecha", "hora", "potencia"]
    elif df.shape[1] == 1:
        df.columns = ["potencia"]
        df["fecha"] = ""; df["hora"] = ""
        df = df[["fecha","hora","potencia"]]
    elif df.shape[1] == 2:
        df.columns = ["fecha","potencia"]
        df["hora"] = ""
        df = df[["fecha","hora","potencia"]]
    else:
        return pd.DataFrame(columns=["fecha","hora","potencia"])

    df["potencia"] = pd.to_numeric(df["potencia"], errors="coerce")
    return df.dropna(subset=["potencia"]).reset_index(drop=True)

# ======================================================================
#              FORMATO NUEVO DE GUARDADO EN CARPETA
# ======================================================================
SAFE_SAVE_DIR_RE = re.compile(r"^save_\d+(?:\(.+\))?$", re.IGNORECASE)

######################################
# funcion _safe_guardado_folder: valida nombres de carpeta de guardado tipo save_N(YYYY-MM-DD_HH-MM-SS)
######################################
def _safe_guardado_folder(name: str) -> bool:
    return bool(name and SAFE_SAVE_DIR_RE.match(name) and "/" not in name and "\\" not in name)

######################################
# funcion _next_save_dir: calcula el siguiente nombre de carpeta save_N(timestamp) en /guardado
######################################
def _next_save_dir(base_dir: str, ts_str: str) -> str:
    try:
        existentes = os.listdir(base_dir)
    except FileNotFoundError:
        os.makedirs(base_dir, exist_ok=True)
        existentes = []
    ns = []
    pat = re.compile(r"^save_(\d+)")
    for n in existentes:
        m = pat.match(n)
        if m:
            try: ns.append(int(m.group(1)))
            except: pass
    N = max(ns)+1 if ns else 1
    return os.path.join(base_dir, f"save_{N}({ts_str})")

######################################
# funcion _leer_potencia_robusto_txt: parsea data.txt o Potencia.txt con ruido y devuelve dataframe normalizado fecha,hora,dbm,acimut,lat,long
######################################
def _leer_potencia_robusto_txt(path_txt: str) -> pd.DataFrame:
    
    #Lee data.txt (fecha,hora,dbm,acimut,lat,long) o Potencia.txt con ruido/encabezados.
    
    if not os.path.exists(path_txt):
        return pd.DataFrame(columns=["fecha","hora","dbm","acimut","lat","long"])
    raw = open(path_txt, "r", encoding="utf-8", errors="ignore").read()
    raw = raw.replace(";", ",").replace("\t", ",")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        return pd.DataFrame(columns=["fecha","hora","dbm","acimut","lat","long"])
    # buscar primera línea con >=5 comas
    start = None
    for i, ln in enumerate(lines):
        if ln.count(",") >= 5:
            start = i; break
    if start is None:
        return pd.DataFrame(columns=["fecha","hora","dbm","acimut","lat","long"])
    useful = "\n".join(lines[start:])
    from io import StringIO
    buf = StringIO(useful)
    try:
        df = pd.read_csv(buf, header=None, names=["fecha","hora","dbm","acimut","lat","long"],
                         engine="python", sep=",", on_bad_lines="skip")
    except Exception:
        buf.seek(0)
        df = pd.read_csv(buf, header=None, names=["fecha","hora","dbm","acimut","lat","long"],
                         engine="python", sep=r"[,\s]+", on_bad_lines="skip")

    df["dbm"]  = pd.to_numeric(df["dbm"],  errors="coerce")
    def _az(v):
        try: return float(v)
        except: return np.nan
    df["acimut"] = df["acimut"].apply(_az)
    df["lat"]  = pd.to_numeric(df["lat"],  errors="coerce")
    df["long"] = pd.to_numeric(df["long"], errors="coerce")
    df = df.dropna(subset=["dbm"]).reset_index(drop=True)
    return df

######################################
# funcion _copiar_carpeta_si_existe: copia archivos coincidentes con patrón desde una carpeta origen a destino preservando nombres
######################################
def _copiar_carpeta_si_existe(src_dir: str, dst_dir: str, patron: str):
    os.makedirs(dst_dir, exist_ok=True)
    patrones = [patron,
                patron.replace("*.jpg", "*.jpeg"),
                patron.replace("*.jpg", "*.png"),
                patron.replace("*.jpg", "*.webp")]
    vistos = set()
    for pat in patrones:
        for src in glob(os.path.join(src_dir, pat)):
            base = os.path.basename(src)
            if base in vistos:
                continue
            vistos.add(base)
            try:
                shutil.copy2(src, os.path.join(dst_dir, base))
            except Exception:
                pass

# ======================================================================
#                    DETENER + GUARDAR (NUEVO FORMATO)
# ======================================================================

######################################
# funcion detener_y_guardar: detiene adquisición, empaqueta datos en guardado/save_N(...)/ con data.txt, equipo.txt y copia imágenes
######################################
@app.route('/detener-guardar', methods=['POST'])
def detener_y_guardar():
    """
    Guarda:
      guardado/save_N(...)/data.txt + equipo.txt + frames/ + capturas/
    """
    try:
        pot_path  = os.path.join(TXT_DIR, "Potencia.txt")
        df = _leer_potencia_robusto_txt(pot_path)

        # aunque no haya datos, hace la carpeta, pero devolvemos ok=False
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        save_dir = _next_save_dir(GUARDADO_DIR, ts)
        os.makedirs(save_dir, exist_ok=True)

        if df.empty:
            _remove_potencia_to_end_loop()
            _stop_current_process_if_any(timeout=6)
            return jsonify({"ok": False, "msg": "No hay datos suficientes para guardar.", "name": os.path.basename(save_dir)})

        # equipo + CSV
        open(os.path.join(save_dir, "equipo.txt"), "w", encoding="utf-8").write(EQUIPO_ACTUAL + "\n")
        with open(os.path.join(save_dir, "data.txt"), "w", encoding="utf-8", newline="") as f:
            f.write("fecha,hora,dbm,acimut,lat,long\n")
            df.to_csv(f, index=False, header=False)

        # copiar imágenes actuales
        _copiar_carpeta_si_existe(FRAMES_DIR,   os.path.join(save_dir, "frames"),   "frame_*.jpg")
        _copiar_carpeta_si_existe(CAPT_DIR,     os.path.join(save_dir, "capturas"), "captura_*.jpg")

        # limpiar y parar
        _remove_potencia_to_end_loop()
        _stop_current_process_if_any(timeout=6)

        return jsonify({
            "ok": True,
            "dir": f"/guardado/{os.path.basename(save_dir)}",
            "name": os.path.basename(save_dir),
            "rows": int(len(df)),
            "equipo": EQUIPO_ACTUAL
        })
    except Exception as e:
        _remove_potencia_to_end_loop()
        _stop_current_process_if_any(timeout=6)
        return jsonify({"ok": False, "error": str(e)}), 500

######################################
# funcion detener_borrar: detiene adquisición y borra Potencia.txt sin guardar
######################################
@app.route('/detener-borrar', methods=['POST'])
def detener_borrar():
    try:
        _remove_potencia_to_end_loop()
        _stop_current_process_if_any(timeout=6)
        return jsonify({"ok": True, "msg": "Medición detenida. Se ha eliminado Potencia.txt."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

######################################
# funcion fin_y_guardados: detiene todo y devuelve un redirect lógico a /guardados en la UI
######################################
@app.route('/fin-y-guardados', methods=['POST'])
def fin_y_guardados():
    try:
        _remove_potencia_to_end_loop()
        _stop_current_process_if_any(timeout=6)
        return jsonify({"ok": True, "goto": "/guardados"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ======================================================================
#                   LISTAR / BORRAR GUARDADOS (carpetas)
# ======================================================================

######################################
# funcion _list_guardados_items: compone el listado de carpetas de guardados con metadatos tamaño, fecha y nº de filas
######################################
def _list_guardados_items():
    os.makedirs(GUARDADO_DIR, exist_ok=True)
    items = []
    for name in os.listdir(GUARDADO_DIR):
        if not _safe_guardado_folder(name):
            continue
        full = os.path.join(GUARDADO_DIR, name)
        if not os.path.isdir(full):
            continue
        equipo = "—"
        rows = 0
        size_bytes = 0
        try:
            eq_path = os.path.join(full, "equipo.txt")
            if os.path.isfile(eq_path):
                with open(eq_path, "r", encoding="utf-8", errors="ignore") as f:
                    equipo = (f.readline() or "").strip() or "—"

            data_path = os.path.join(full, "data.txt")
            if os.path.isfile(data_path):
                with open(data_path, "r", encoding="utf-8", errors="ignore") as f:
                    _ = f.readline()  # cabecera
                    rows = sum(1 for ln in f if ln.strip())
                size_bytes += os.path.getsize(data_path)

            for sub in ("frames", "capturas", "analysis"):
                subdir = os.path.join(full, sub)
                if os.path.isdir(subdir):
                    for fn in os.listdir(subdir):
                        p = os.path.join(subdir, fn)
                        if os.path.isfile(p):
                            size_bytes += os.path.getsize(p)
        except Exception:
            pass

        try:
            st = os.stat(full)
            items.append({
                "name": name,
                "url": f"/guardado/{name}/data.txt",
                "size_bytes": size_bytes,
                "mtime": st.st_mtime,
                "equipo": equipo,
                "rows": rows
            })
        except Exception:
            continue

    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


######################################
# funcion api_guardados_list: API que devuelve el listado de guardados ordenados por fecha
######################################
@app.route('/api/guardados/list', methods=['GET'])
def api_guardados_list():
    try:
        return jsonify({"ok": True, "items": _list_guardados_items()})
    except Exception as e:
        return jsonify({"ok": False, "items": [], "error": str(e)}), 500

######################################
# funcion api_guardados_alias: alias de /api/guardados/list para compatibilidad
######################################
@app.route('/api/guardados', methods=['GET'])
def api_guardados_alias():
    try:
        return jsonify({"ok": True, "items": _list_guardados_items()})
    except Exception as e:
        return jsonify({"ok": False, "items": [], "error": str(e)}), 500

######################################
# funcion api_guardados_delete: elimina una carpeta de guardado validando el nombre
######################################
@app.route('/api/guardados/delete', methods=['POST'])
def api_guardados_delete():
    try:
        data = request.get_json(force=True) or {}
        name = str(data.get('name', '')).strip()
        if not _safe_guardado_folder(name):
            return jsonify({"ok": False, "error": "Nombre inválido"}), 400
        path_abs = os.path.join(GUARDADO_DIR, name)
        if not os.path.isdir(path_abs):
            return jsonify({"ok": False, "error": "Guardado no encontrado"}), 404
        shutil.rmtree(path_abs, ignore_errors=True)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ======================================================================
#                 META DE UN GUARDADO + GENERAR GRÁFICOS
# ======================================================================

######################################
# funcion api_guardado_meta: devuelve metadatos y listas de frames/capturas de un guardado concreto
######################################
@app.route('/api/guardado/meta', methods=['GET'])
def api_guardado_meta():
    
    #Devuelve:
    # - rows: [{i, fecha, hora, dbm, acimut, lat, long}]
    # - frames: [{i, file}], capturas: [{i, file}]
   
    name = request.args.get("name", "").strip()
    if not _safe_guardado_folder(name):
        return jsonify({"ok": False, "error": "Nombre inválido."}), 400

    base = os.path.join(GUARDADO_DIR, name)
    data_path = os.path.join(base, "data.txt")

    if not os.path.exists(base):
        return jsonify({"ok": False, "error": "Guardado no existe."}), 404
    if not os.path.exists(data_path):
        # compat: intenta encontrar otro txt con datos
        cand = None
        for fn in os.listdir(base):
            if fn.lower().endswith(".txt") and fn.lower() not in ("equipo.txt",):
                cand = os.path.join(base, fn); break
        data_path = cand or data_path

    rows = []
    try:
        df = _leer_potencia_robusto_txt(data_path)
        for i, r in df.iterrows():
            rows.append({
                "i": int(i),
                "fecha": str(r.get("fecha", "")),
                "hora":  str(r.get("hora", "")),
                "dbm":   (None if pd.isna(r.get("dbm")) else float(r.get("dbm"))),
                "acimut": (None if pd.isna(r.get("acimut")) else float(r.get("acimut"))),
                "lat":   (None if pd.isna(r.get("lat")) else float(r.get("lat"))),
                "long":  (None if pd.isna(r.get("long")) else float(r.get("long")))
            })
    except Exception as e:
        return jsonify({"ok": False, "error": f"Error leyendo data.txt: {e}"}), 500

    def archivos_con_idx(d, prefix):
        out = []
        if os.path.isdir(d):
            for fn in os.listdir(d):
                m = re.match(rf"^{re.escape(prefix)}_(\d+)\.(jpe?g|png|webp)$", fn, re.IGNORECASE)
                if m:
                    try:
                        out.append({"i": int(m.group(1)), "file": fn})
                    except:
                        pass
        out.sort(key=lambda o: o["i"])
        return out

    frames   = archivos_con_idx(os.path.join(base, "frames"),   "frame")
    capturas = archivos_con_idx(os.path.join(base, "capturas"), "captura")

    return jsonify({
        "ok": True,
        "name": name,
        "rows": rows,
        "frames": frames,
        "capturas": capturas
    })

######################################
# funcion api_guardado_build_graphs: ejecuta generar_grafico.py para un guardado concreto y escribe salidas en /analysis
######################################
@app.route('/api/guardado/build_graphs', methods=['GET'])
def api_guardado_build_graphs():
    
    #Genera:
    #  guardado/<name>/analysis/analisis_potencia.png
    #  guardado/<name>/analysis/muestreo_interactivo.html
    
    name = request.args.get("name", "").strip()
    cmap = request.args.get("cmap", "RdYlGn_r")
    if not _safe_guardado_folder(name):
        return jsonify({"ok": False, "error": "Nombre inválido."}), 400

    base = os.path.join(GUARDADO_DIR, name)
    data_path = os.path.join(base, "data.txt")
    out_dir   = os.path.join(base, "analysis")
    frames_d  = os.path.join(base, "frames")
    caps_d    = os.path.join(base, "capturas")
    os.makedirs(out_dir, exist_ok=True)

    if not os.path.exists(data_path):
        return jsonify({"ok": False, "error": "data.txt no encontrado en el guardado."}), 404

    try:
        cmd = [
            sys.executable,
            os.path.join(PY_DIR, "generar_grafico.py"),
            "--input", data_path,
            "--outdir", out_dir,
            "--framesdir", frames_d,
            "--capturasdir", caps_d,
            "--cmap", cmap,
            
            
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return jsonify({"ok": False, "error": "generar_grafico.py falló", "stderr": res.stderr, "stdout": res.stdout}), 500
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ======================================================================
#                          MAPAS / GRÁFICOS (global)
# ======================================================================

######################################
# funcion generar_mapa: endpoint que ejecuta python/map.py para actualizar mapas globales
######################################
@app.route('/generar-mapa', methods=['POST'])
def generar_mapa():
    result = subprocess.run([sys.executable, os.path.join(PY_DIR, "map.py")])
    if result.returncode == 0:
        return jsonify({"status": "Mapa actualizado"})
    return jsonify({"status": "error"}), 500

######################################
# funcion actualizar_grafico: ejecuta generar_grafico.py sobre el Potencia.txt en vivo y guarda salidas en /analysis
######################################
@app.route('/actualizar_grafico')
def actualizar_grafico():
    cmap = request.args.get("cmap", "RdYlGn_r")
    cmd = [
        sys.executable, os.path.join(PY_DIR, "generar_grafico.py"),
        "--cmap", cmap,
        "--input", os.path.join(TXT_DIR, "Potencia.txt"),
        "--outdir", ANALYSIS_DIR,
        "--framesdir", FRAMES_DIR,
        "--capturasdir", CAPT_DIR
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        return jsonify(status="ok")
    else:
        return jsonify(status="error", detail="No se pudo generar el gráfico", stderr=result.stderr), 500

######################################
# funcion obtener_grafico: sirve la imagen PNG del análisis global forzando no cache
######################################
@app.route('/grafico')
def obtener_grafico():
    grafico_path = os.path.join(ANALYSIS_DIR, "analisis_potencia.png")
    if os.path.exists(grafico_path):
        resp = send_file(grafico_path, mimetype="image/png")
        resp.headers['Cache-Control'] = 'no-store, max-age=0'
        return resp
    return "Imagen no encontrada", 404

# ======================================================================
#                           FRECUENCIA (PR100)
# ======================================================================
try:
    from python.Cambiar_freq import enviar_comando_frecuencia
except Exception:
    enviar_comando_frecuencia = None

######################################
# funcion cambiar_frecuencia: endpoint para enviar FREQ al PR100 con validación y eco opcional
######################################
@app.route('/cambiar_frecuencia', methods=['POST'])
def cambiar_frecuencia():
    if not enviar_comando_frecuencia:
        return jsonify({"ok": False, "mensaje": "Función no disponible en el servidor."}), 500
    try:
        data = request.get_json(force=True)
        freq = str(data.get("frecuencia", "")).strip().replace(",", ".")
        if not re.fullmatch(r"\d+(\.\d+)?", freq or ""):
            return jsonify({"ok": False, "mensaje": "Frecuencia inválida."}), 400
        echo = enviar_comando_frecuencia(freq)  # ahora es SINCRÓNICA
        return jsonify({"ok": True, "mensaje": f"Frecuencia cambiada a {freq} MHz", "echo": echo})
    except Exception as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 500


# ======================================================================
#                                 360°
# ======================================================================
current_process_360 = None

######################################
# funcion _stop_current_process_360: detiene el subproceso de medición 360° con timeout y limpieza
######################################
def _stop_current_process_360(timeout=6):
    global current_process_360
    if current_process_360 is not None and current_process_360.poll() is None:
        if hasattr(signal, "CTRL_BREAK_EVENT"):
            try: current_process_360.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception: pass
        try:
            current_process_360.wait(timeout=timeout)
        except Exception:
            current_process_360.terminate()
    current_process_360 = None

######################################
# funcion _med360_path: devuelve la ruta absoluta del fichero txt de medición 360
######################################
def _med360_path():
    return os.path.join(TXT_DIR, "medicion360.txt")

######################################
# funcion api_med360_start: inicia el subproceso de medición 360 con periodo configurable vía JSON
######################################
@app.route('/api/med360/start', methods=['POST'])
def api_med360_start():
    global current_process_360
    if current_process_360 is not None and current_process_360.poll() is None:
        return jsonify({"ok": False, "error": "Ya hay una medición 360 en curso."}), 400
    try:
        data = request.get_json(force=True) or {}
        period = float(data.get("period", 1.0))
    except Exception:
        return jsonify({"ok": False, "error": "Parámetros inválidos."}), 400

    env = os.environ.copy()
    env["SAMPLE_PERIOD"] = str(period if period > 0 else 1.0)

    creationflags = 0
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    script_name = "medicion360.py"  # o "medicion360.py"
    current_process_360 = subprocess.Popen(
        [sys.executable, os.path.join(PY_DIR, script_name)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        bufsize=1, text=True, creationflags=creationflags, env=env
    )
    return jsonify({"ok": True})

######################################
# funcion api_med360_stop: detiene la medición 360°, borra el fichero temporal y para el proceso
######################################
@app.route('/api/med360/stop', methods=['POST'])
def api_med360_stop():
    try:
        try:
            os.remove(_med360_path())
        except Exception:
            pass
        _stop_current_process_360(timeout=6)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

######################################
# funcion api_med360_live: lee en tiempo real el fichero medicion360.txt y devuelve lat,long y lista de puntos {deg,pwr}
######################################
@app.route('/api/med360/live', methods=['GET'])
def api_med360_live():
    path = _med360_path()
    if not os.path.exists(path):
        return jsonify({"ok": True, "lat": None, "long": None, "points": []})

    lat = None; lon = None; points = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            # 1) primera línea: lat,long
            first = f.readline()
            if first:
                nums = re.findall(r'[-+]?\d+(?:\.\d+)?', first)
                if len(nums) >= 2:
                    lat = float(nums[0]); lon = float(nums[1])

            # 2) resto: acimut,potencia
            for line in f:
                nums = re.findall(r'[-+]?\d+(?:\.\d+)?', line)
                if len(nums) >= 2:
                    deg = float(nums[0]) % 360.0
                    pwr = float(nums[1])
                    points.append({"deg": deg, "pwr": pwr})
    except Exception:
        pass

    return jsonify({"ok": True, "lat": lat, "long": lon, "points": points, "n": len(points)})

######################################
# funcion next_save360_name: genera nombre incremental para el archivo de guardado 360° tipo save360_N(timestamp).txt
######################################
def next_save360_name(base_dir, ts_str):
    try:
        existentes = os.listdir(base_dir)
    except FileNotFoundError:
        os.makedirs(base_dir, exist_ok=True)
        existentes = []
    nums = []
    pat = re.compile(r"^save360_(\d+)\(")
    for nombre in existentes:
        m = pat.match(nombre)
        if m:
            try: nums.append(int(m.group(1)))
            except ValueError: pass
    n = (max(nums) + 1) if nums else 1
    return os.path.join(base_dir, f"save360_{n}({ts_str}).txt")

######################################
# funcion api_med360_save: guarda el archivo actual de medición 360 en la carpeta guardado360 con prefijo y equipo
######################################
@app.route('/api/med360/save', methods=['POST'])
def api_med360_save():
    path = _med360_path()
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "No hay medición 360 activa."}), 400

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo leer medicion360.txt: {e}"}), 500

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    outpath = next_save360_name(GUARDADO360_DIR, ts)

    try:
        with open(outpath, "w", encoding="utf-8", newline="") as f:
            f.write(f"{EQUIPO_ACTUAL}\n")
            for ln in content.splitlines():
                f.write(ln.rstrip() + "\n")
    except Exception as e:
        return jsonify({"ok": False, "error": f"No se pudo guardar: {e}"}), 500

    return jsonify({"ok": True, "file": f"/guardado360/{os.path.basename(outpath)}"})

######################################
# funcion api_med360_list: lista ficheros de guardado360 con tamaño, fecha y equipo
######################################
@app.route('/api/med360/list', methods=['GET'])
def api_med360_list():
    items = []
    try:
        os.makedirs(GUARDADO360_DIR, exist_ok=True)
        for fname in os.listdir(GUARDADO360_DIR):
            if not re.match(r"^save360_\d+(?:\(.+\))?\.txt$", fname, re.IGNORECASE):
                continue
            full = os.path.join(GUARDADO360_DIR, fname)
            if not os.path.isfile(full): 
                continue
            try:
                size = os.path.getsize(full)
                mtime = os.path.getmtime(full)
                with open(full, "r", encoding="utf-8", errors="ignore") as f:
                    equipo = (f.readline() or "").strip() or "—"
                items.append({
                    "name": fname,
                    "url": f"/guardado360/{fname}",
                    "size": size,
                    "mtime": mtime,
                    "equipo": equipo
                })
            except Exception:
                pass
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return jsonify({"ok": True, "items": items})
    except Exception as e:
        return jsonify({"ok": False, "items": [], "error": str(e)}), 500

######################################
# funcion api_med360_delete: elimina un archivo de guardado360 validando el nombre para seguridad
######################################
@app.route('/api/med360/delete', methods=['POST'])
def api_med360_delete():
    try:
        data = request.get_json(force=True)
        name = str(data.get("name", ""))
    except Exception:
        return jsonify({"ok": False, "error": "Petición inválida."}), 400

    if "/" in name or "\\" in name or not name.lower().endswith(".txt") or name.startswith("."):
        return jsonify({"ok": False, "error": "Nombre inválido."}), 400

    full = os.path.join(GUARDADO360_DIR, name)
    if not os.path.exists(full):
        return jsonify({"ok": False, "error": "Archivo no encontrado."}), 404
    try:
        os.remove(full)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ===== ZIP COMPLETO DEL GUARDADO =====
######################################
# funcion api_guardado_zip: crea y devuelve un ZIP en memoria con el contenido íntegro de un guardado validado
######################################
@app.route("/api/guardado/zip")
def api_guardado_zip():
    name = request.args.get("name", "")
    if not _safe_guardado_folder(name):
        return jsonify(ok=False, error="Parámetro 'name' inválido"), 400

    base = (Path(GUARDADO_DIR) / name).resolve()
    guardado_root = Path(GUARDADO_DIR).resolve()

    # Seguridad: validar que está dentro de /guardado
    try:
        base.relative_to(guardado_root)
    except Exception:
        return jsonify(ok=False, error="Ruta inválida"), 400

    if not base.exists() or not base.is_dir():
        return jsonify(ok=False, error="No existe la medición"), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base):
            for fn in files:
                fp = Path(root) / fn
                arc = Path(name) / fp.relative_to(base)  # dentro del zip: <name>/...
                zf.write(fp, arcname=str(arc))
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"{name}.zip",
    )

# ======================================================================
#                                    MAIN
# ======================================================================

######################################
# funcion main_app_run: punto de entrada en desarrollo, arranca Flask en 0.0.0.0:5000 con debug habilitado
######################################
if __name__ == '__main__':
    # Desarrollo. Para producción usa un WSGI real.
    app.run(host='0.0.0.0', port=5000, debug=True)
