# -----------------------------------------------------------------------------
#   Función: Pr100.py: Adquisición con PR100 (SCPI TCP 5555) leyendo comandos desde json/menu.json:
#   Al arrancar:
#     Trunca txt/Potencia.txt
#     Borra capturas/ y frames/
#   Cada muestra:
#     Escribe: fecha,hora,dbm,acimut,lat,long
#     Captura PR100 → /capturas/captura_{idx}.jpg (PNG→JPG) o tarjeta (fallback)
#     Crea frame → /frames/frame_{idx}.jpg (tarjeta estilo simulador)
#     Periodo ajustable por UDP (127.0.0.1:9999).


import os, json, re, math, signal, asyncio, socket, time
from io import BytesIO
from pathlib import Path
from datetime import datetime

# --- Visual (tarjetas) ---
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from PIL import Image  # para convertir PNG->JPG (capturas)
except Exception:
    Image = None

# ================== Rutas ==================
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
TXT_DIR      = ROOT_DIR / "txt"
CAPTURAS_DIR = ROOT_DIR / "capturas"
FRAMES_DIR   = ROOT_DIR / "frames"
JSON_MENU    = ROOT_DIR / "json" / "menu.json"

TXT_DIR.mkdir(parents=True, exist_ok=True)
CAPTURAS_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

OUT_PATH = TXT_DIR / "Potencia.txt"

# ================== Config ==================
HOST = os.environ.get("PR100_HOST", "172.17.75.1")   #IP del Pr100
try:
    PORT = int(os.environ.get("PR100_PORT", "5555"))  # SCPI TCP del PR100
except Exception:
    PORT = 5555

try:
    PERIODO_S = float(os.environ.get("SAMPLE_PERIOD", "5"))
    if PERIODO_S <= 0:
        PERIODO_S = 5.0
except Exception:
    PERIODO_S = 5.0

READ_TIMEOUT_S = float(os.environ.get("SCPI_READ_TIMEOUT", "3.0"))
CAPTURE_CMD_INDEX = os.environ.get("CAPTURE_CMD_INDEX")  # índice del JSON para la captura

# ================== Utils ==================
######################################
# funcion log: escribe mensajes de traza prefijados con [PR100] y flush inmediato para depuración en tiempo real
######################################
def log(msg: str):
    print(f"[PR100] {msg}", flush=True)

######################################
# funcion dbuv_to_dbm: convierte dBµV a dBm asumiendo 50 Ω mediante la relación aproximada dBm = dBµV - 107
######################################
def dbuv_to_dbm(dbuv: float) -> float:
    #Conversión aproximada de dBµV a dBm (50 Ω).
    return dbuv - 107.0

######################################
# funcion extraer_primer_float: obtiene el primer número de punto flotante dentro de un string y devuelve None si no hay
######################################
def extraer_primer_float(s: str):
    #Extrae el primer float en un string. Devuelve None si no hay.
    if not s:
        return None
    m = re.search(r'(-?\d+(?:\.\d+)?)', s)
    return float(m.group(1)) if m else None

######################################
# funcion parse_gps_data: interpreta la respuesta SYST:GPS:DATA? del PR100 (DMS con hemisferios) y devuelve latitud y longitud en grados decimales o (None,None)
######################################
def parse_gps_data(s: str):
    
    #Parse para SYST:GPS:DATA? del PR100 (ejemplo):
    #GPS,1,1239090583,220,4,N,48,7,40.33,E,11,36,47.42,2009,4,7,7,49,42,0.00,18.89,0.0,554
    #-> (lat, lon) grados decimales o (None, None).
    
    if not s:
        return None, None
    try:
        parts = [p.strip() for p in s.split(",")]
        i_ns = next((i for i,p in enumerate(parts) if p in ("N","S")), None)
        if i_ns is None or i_ns + 3 >= len(parts):
            return None, None
        hemi_ns = parts[i_ns]
        lat_d = float(parts[i_ns+1]); lat_m = float(parts[i_ns+2]); lat_s = float(parts[i_ns+3])

        i_ew = next((i for i,p in enumerate(parts[i_ns+4:], start=i_ns+4) if p in ("E","W")), None)
        if i_ew is None or i_ew + 3 >= len(parts):
            return None, None
        hemi_ew = parts[i_ew]
        lon_d = float(parts[i_ew+1]); lon_m = float(parts[i_ew+2]); lon_s = float(parts[i_ew+3])

        lat = lat_d + lat_m/60.0 + lat_s/3600.0
        lon = lon_d + lon_m/60.0 + lon_s/3600.0
        if hemi_ns == "S": lat = -lat
        if hemi_ew == "W": lon = -lon
        return lat, lon
    except Exception:
        return None, None

######################################
# funcion obtener_comandos_por_equipo: abre json/menu.json y devuelve la lista de comandos SCPI asociados al equipo indicado por posición
######################################
def obtener_comandos_por_equipo(nombre_equipo: str):

    try:
        data = json.loads(JSON_MENU.read_text(encoding='utf-8'))
        for equipo in data.get("Menu", []):
            if equipo.get("name") == nombre_equipo:
                return [str(c) for c in equipo.get("commands", [])]
    except Exception as e:
        log(f"AVISO: no se pudo leer {JSON_MENU}: {e}")
    return []

######################################
# funcion get_cmd: recupera un comando por índice de la lista o devuelve un valor por defecto si no existe o está vacío
######################################
def get_cmd(cmds, index, default=None):
    
    try:
        if index is not None and index < len(cmds):
            c = cmds[index].strip()
            return c if c else default
    except Exception:
        pass
    return default

######################################
# funcion find_capture_cmd: determina el comando SCPI para capturar la pantalla priorizando un índice explícito, una coincidencia heurística de FETCH y por último un valor por defecto
######################################
def find_capture_cmd(cmds, default="DISPlay:WINDow:FETch?"):
    
    #Determina el comando de captura:
    #  1) Si CAPTURE_CMD_INDEX está definido y válido → ese.
    #  2) Si hay un comando que contenga 'DISPlay:WINDow:FETch?' → ese.
    #  3) Si no, default.
    
    # 1) índice explícito
    if CAPTURE_CMD_INDEX is not None:
        try:
            i = int(CAPTURE_CMD_INDEX)
            c = get_cmd(cmds, i, None)
            if c: return c
        except Exception:
            pass
    # 2) búsqueda heurística
    for c in cmds:
        cc = str(c).strip().upper()
        if "DISPLAY:WINDOW:FETCH?" in cc.replace(" ", ""):
            return str(c).strip()
    # 3) por defecto
    return default

######################################
# funcion save_card_img: genera una imagen tipo “tarjeta” (fallback) con título, fecha, lat/lon, acimut y potencia y la graba como JPEG
######################################
def save_card_img(title, when_iso, lat, lon, az, dbm, out_path):
    #Genera tarjeta JPG (estilo simulador / fallback).
    fig = plt.figure(figsize=(6,6), dpi=140)
    ax = fig.add_subplot(111)
    fig.patch.set_facecolor("#0b1220")
    ax.set_facecolor("#0b1220")
    ax.axis('off')

    ax.text(0.5, 0.88, title, ha='center', va='center',
            fontsize=18, color="#7dd3fc", fontweight='bold', transform=ax.transAxes)
    ax.text(0.5, 0.80, when_iso, ha='center', va='center',
            fontsize=10, color="#a8c7ff", transform=ax.transAxes)

    lines = [
        f"Lat:     {(f'{lat:.6f}' if lat is not None else '—')}",
        f"Lon:     {(f'{lon:.6f}' if lon is not None else '—')}",
        f"Acimut:  {(f'{az:.1f}°' if (az is not None and math.isfinite(az)) else 'no directivo')}",
        f"Potencia:{(f'{dbm:.2f} dBm' if dbm is not None and math.isfinite(dbm) else '—')}",
    ]
    ax.text(0.5, 0.60, "\n".join(lines), ha='center', va='center',
            fontsize=16, color="#e5eefc", transform=ax.transAxes)

    ang = math.radians(((az if (az is not None and math.isfinite(az)) else 0.0) - 90.0))
    circ = plt.Circle((0.5, 0.30), 0.18, fill=False, color="#38bdf8", lw=2, transform=ax.transAxes)
    ax.add_patch(circ)
    x2 = 0.5 + 0.17*math.cos(ang)
    y2 = 0.30 + 0.17*math.sin(ang)
    ax.plot([0.5, x2], [0.30, y2], '-', lw=3, color="#7dd3fc", transform=ax.transAxes)
    ax.text(0.5, 0.12, "N", ha='center', va='center', color="#9bdcff", transform=ax.transAxes)

    try:
        plt.savefig(
            out_path,
            bbox_inches='tight',
            facecolor=fig.get_facecolor(),
            format='jpeg',
            pil_kwargs={"quality": 92, "optimize": True, "progressive": True}
        )
    except TypeError:
        plt.savefig(out_path, bbox_inches='tight', facecolor=fig.get_facecolor(), format='jpeg')
    finally:
        plt.close(fig)
    return out_path

# ================== SCPI helpers ==================
######################################
# funcion scpi_write: envía un comando SCPI (ASCII con salto de línea) por el writer asíncrono y fuerza el vaciado del buffer
######################################
async def scpi_write(writer, cmd: str):
    writer.write((cmd.rstrip("\n") + "\n").encode("ascii"))
    await writer.drain()

######################################
# funcion scpi_query_line: envía un comando SCPI y lee una línea de respuesta con timeout devolviendo la cadena decodificada
######################################
async def scpi_query_line(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                          cmd: str, timeout: float = READ_TIMEOUT_S) -> str:
    await scpi_write(writer, cmd)
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    return line.decode(errors="replace").strip()

######################################
# funcion _scpi_recv_block: lee una respuesta SCPI en formato block data (#<n><len><bytes>) devolviendo los bytes recibidos o lanza error si el formato es incorrecto
######################################
def _scpi_recv_block(sock_file):
    #Lee block data SCPI: #<n><len><bytes> y devuelve bytes.
    first = sock_file.read(1)
    if first != b'#':
        rest = first + sock_file.readline()
        raise RuntimeError(f"Respuesta no es block data: {rest.decode(errors='replace').strip()}")
    ndigits = int(sock_file.read(1))
    blen = int(sock_file.read(ndigits))
    data = b''
    while len(data) < blen:
        chunk = sock_file.read(blen - len(data))
        if not chunk:
            raise RuntimeError("Conexión cerrada durante lectura de captura")
        data += chunk
    return data

######################################
# funcion _fetch_png_via_scpi: realiza una captura de pantalla del PR100 ejecutando el comando de captura y devolviendo los bytes PNG recibidos por socket
######################################
def _fetch_png_via_scpi(host: str, port: int, capture_cmd: str, timeout: float = 8.0) -> bytes:
    #Hace *solo* la captura binaria con el comando de captura (por defecto DISPlay:WINDow:FETch?) usando socket crudo.
    with socket.create_connection((host, port), timeout=timeout) as s:
        f = s.makefile("rwb", buffering=0)
        f.write(b"*CLS\n")
        cmd = (capture_cmd.strip() + "\n").encode("ascii", errors="ignore")
        f.write(cmd)
        return _scpi_recv_block(f)

######################################
# funcion _guardar_jpg_desde_png_bytes: convierte bytes PNG a JPEG usando Pillow y guarda el archivo de salida en la ruta indicada
######################################
def _guardar_jpg_desde_png_bytes(png_bytes: bytes, out_path: Path):
    if Image is None:
        raise RuntimeError("Pillow no disponible para convertir PNG->JPG")
    im = Image.open(BytesIO(png_bytes)).convert("RGB")
    im.save(out_path, "JPEG", quality=92, optimize=True, progressive=True)
    return out_path

######################################
# funcion guardar_captura_real_o_fallback: intenta guardar una captura real del PR100 y si falla genera una tarjeta fallback conservando metadatos
######################################
async def guardar_captura_real_o_fallback(idx, lat, lon, az, dbm, when_iso, capture_cmd: str):
    #Intenta captura real del PR100; si falla, crea tarjeta.
    out = CAPTURAS_DIR / f"captura_{idx}.jpg"
    try:
        png = await asyncio.to_thread(_fetch_png_via_scpi, HOST, PORT, capture_cmd)
        try:
            return _guardar_jpg_desde_png_bytes(png, out)
        except Exception as e_img:
            log(f"AVISO: no se pudo convertir PNG->JPG ({e_img}). Creo tarjeta.")
            return save_card_img("Medición PR100", when_iso, lat, lon, az, dbm, out)
    except Exception as e:
        log(f"AVISO: captura real fallida, creo tarjeta manual: {e}")
        return save_card_img("Medición PR100", when_iso, lat, lon, az, dbm, out)

######################################
# funcion save_frame_img: genera siempre un frame ilustrativo estilo simulador con los datos de la muestra y lo guarda como JPEG
######################################
def save_frame_img(when_iso, lat, lon, az, dbm, idx):
    #Genera SIEMPRE un frame estilo simulador (no usamos cámara).
    out = FRAMES_DIR / f"frame_{idx}.jpg"
    return save_card_img("Frame PR100", when_iso, lat, lon, az, dbm, out)

# ================== UDP para cambiar periodo ==================
######################################
# clase PeriodProtocol: receptor UDP que parsea un float en segundos y actualiza de forma segura el periodo de muestreo en caliente
######################################
class PeriodProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        global PERIODO_S
        try:
            v = float(data.decode('utf-8').strip())
            if v > 0:
                PERIODO_S = v
                log(f"Periodo actualizado a {PERIODO_S} s (UDP)")
        except Exception as e:
            log(f"Datagrama UDP inválido: {e}")

# ================== Señales ==================
stop_ev = asyncio.Event()

######################################
# funcion _handle_sig: manejador de señales para terminar ordenadamente el bucle principal al recibir SIGINT/SIGTERM/SIGBREAK
######################################
def _handle_sig(*_): stop_ev.set()
signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, _handle_sig)

# ================== Main ==================
######################################
# funcion main: inicializa estado y recursos, limpia datos previos, configura UDP, se conecta al PR100, adquiere datos por periodo, guarda CSV y capturas/frames y cierra todo limpiamente al finalizar
######################################
async def main():
    global PERIODO_S
    log(f"Periodo inicial: {PERIODO_S} s")

    # Truncar SIEMPRE (nueva medición)
    OUT_PATH.write_text("", encoding="utf-8")
    log(f"Truncado {OUT_PATH}")

    # Limpiar capturas y frames antiguas
    removed_c = 0
    for p in CAPTURAS_DIR.glob("captura_*.*"):
        try:
            p.unlink(); removed_c += 1
        except Exception:
            pass
    removed_f = 0
    for p in FRAMES_DIR.glob("frame_*.*"):
        try:
            p.unlink(); removed_f += 1
        except Exception:
            pass
    log(f"Capturas antiguas eliminadas ({removed_c}). Frames eliminados ({removed_f}). Empezando en 0.")

    # UDP (si el puerto ya está en uso, continuar sin UDP)
    transport = None
    try:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: PeriodProtocol(), local_addr=("127.0.0.1", 9999)
        )
        log("UDP en 127.0.0.1:9999 listo.")
    except Exception as e:
        log(f"AVISO: no se pudo abrir UDP 9999 (sigo sin él): {e}")

    # Leer comandos PR100 desde JSON
    cmds = obtener_comandos_por_equipo("PR100")
    cmd_idn     = get_cmd(cmds, 0, None)
    cmd_measure = get_cmd(cmds, 2, 'SENSe:DATA? "VOLT:AC"')
    cmd_gps     = get_cmd(cmds, 3, "SYST:GPS:DATA?")
    cmd_compass = get_cmd(cmds, 4, "SYST:COMPass:DATA?")
    cmd_freq    = get_cmd(cmds, 5, None)
    cmd_capture = find_capture_cmd(cmds, default="DISPlay:WINDow:FETch?")

    # Conexión TCP "simple" (sin telnet) para comandos ASCII
    reader, writer = await asyncio.open_connection(HOST, PORT)
    log(f"Conectado a {HOST}:{PORT}")

    # Limpia y fuerza ASCII para lecturas de nivel
    try:
        await scpi_write(writer, "*CLS")
        await scpi_write(writer, "FORMat:DATA ASCii")
    except Exception as e:
        log(f"AVISO inicial (*CLS/FORMat) falló: {e}")

    # Set de frecuencia (opcional) y *IDN? (opcional)
    try:
        if cmd_freq:
            await scpi_write(writer, cmd_freq)
            log(f"FREQ set con: {cmd_freq}")
    except Exception as e:
        log(f"AVISO al configurar FREQ: {e}")

    try:
        if cmd_idn:
            idn = await scpi_query_line(reader, writer, cmd_idn, READ_TIMEOUT_S)
            log(f"*IDN?: {idn}")
    except Exception as e:
        log(f"AVISO leyendo *IDN?: {e}")

    idx = 0
    try:
        while not stop_ev.is_set():
            if not OUT_PATH.exists():
                log("Potencia.txt eliminado externamente. Saliendo…")
                break

            ahora = datetime.now()
            fecha = ahora.strftime("%Y-%m-%d")
            hora  = ahora.strftime("%H:%M:%S")
            when_iso = ahora.isoformat(timespec="seconds")

            # 1) Medida principal (dBµV ASCII -> dBm)
            try:
                resp = await scpi_query_line(reader, writer, cmd_measure, READ_TIMEOUT_S)
            except Exception as e:
                resp = ""
                log(f"AVISO lectura medida falló: {e}")
            dbuv = extraer_primer_float(resp)
            dbm  = dbuv_to_dbm(dbuv) if dbuv is not None else float("nan")

            # 2) GPS
            try:
                gps_resp = await scpi_query_line(reader, writer, cmd_gps, READ_TIMEOUT_S)
            except Exception as e:
                gps_resp = ""
                log(f"AVISO lectura GPS falló: {e}")
            lat, lon = parse_gps_data(gps_resp)

            # 3) Brújula
            try:
                comp_resp = await scpi_query_line(reader, writer, cmd_compass, READ_TIMEOUT_S)
            except Exception as e:
                comp_resp = ""
                log(f"AVISO lectura brújula falló: {e}")
            az = extraer_primer_float(comp_resp)

            # 4) Escribir línea CSV
            az_txt  = f"{az:.1f}" if (az is not None and math.isfinite(az)) else "no directivo"
            lat_txt = f"{lat:.6f}" if (lat is not None and math.isfinite(lat)) else ""
            lon_txt = f"{lon:.6f}" if (lon is not None and math.isfinite(lon)) else ""
            line = f"{fecha},{hora},{dbm},{az_txt},{lat_txt},{lon_txt}\n"
            try:
                with OUT_PATH.open("a", encoding="utf-8") as f:
                    f.write(line)
            except Exception as e:
                log(f"ERROR escribiendo {OUT_PATH}: {e}")

            # 5) Captura por muestra (real con fallback)
            _ = await guardar_captura_real_o_fallback(idx, lat, lon, az, dbm, when_iso, cmd_capture)

            # 6) Frame por muestra (siempre, estilo simulador)
            _ = save_frame_img(when_iso, lat, lon, az, dbm, idx)

            idx += 1
            await asyncio.sleep(PERIODO_S)

    except Exception as e:
        log(f"ERROR en loop principal: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        if transport is not None:
            transport.close()
        log("Conexión cerrada. Fin.")
    return 0

######################################
# funcion main_guard: punto de entrada para ejecutar el lazo de adquisición y terminar de forma limpia ante KeyboardInterrupt
######################################
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
