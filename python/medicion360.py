# -----------------------------------------------------------------------------
#   Función: medicion360.py: Realiza una medicion en 360 grados en una ubicación estática.
#   Abre una conexión SCPI con el PR100 por TCP y toma medidas reales.
#   Crea/trunca txt/medicion360.txt.
#   Escribe la primera línea con "lat,long" cuando el GPS del PR100 tenga fix (si no, deja la línea vacía).
#   En cada periodo de muestreo, consulta brújula (azimut) y nivel (dBµV), convierte a dBm y añade líneas "az,dbm".
#   Si falta cualquier dato (GPS/azimut/potencia), NO escribe nada (no inventa).
#   Termina de forma limpia si borras el archivo txt/medicion360.txt o recibes una señal (Ctrl+C, etc.).
# -----------------------------------------------------------------------------


import os, json, re, math, signal, asyncio
from pathlib import Path
from datetime import datetime

# ================== Rutas ==================
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
TXT_DIR      = ROOT_DIR / "txt"
JSON_MENU    = ROOT_DIR / "json" / "menu.json"
TXT_DIR.mkdir(parents=True, exist_ok=True)
OUT_PATH = TXT_DIR / "medicion360.txt"

# ================== Config ==================
HOST = os.environ.get("PR100_HOST", "172.17.75.1")
try:
    PORT = int(os.environ.get("PR100_PORT", "5555"))
except Exception:
    PORT = 5555

try:
    PERIODO_S = float(os.environ.get("SAMPLE_PERIOD", "1.0"))
    if PERIODO_S <= 0: PERIODO_S = 1.0
except Exception:
    PERIODO_S = 1.0

READ_TIMEOUT_S = float(os.environ.get("SCPI_READ_TIMEOUT", "3.0"))
GPS_WAIT_S     = float(os.environ.get("GPS_WAIT_S", "8.0"))  # espera inicial para tener lat/lon

######################################
# funcion log: imprime mensajes prefijados con [MED360] y flush inmediato para facilitar la trazabilidad en tiempo real
######################################
def log(msg: str):
    print(f"[MED360] {msg}", flush=True)

######################################
# funcion dbuv_to_dbm: convierte niveles de dBµV a dBm aplicando la relación estándar dBm = dBµV - 107
######################################
def dbuv_to_dbm(dbuv: float) -> float:
    return dbuv - 107.0

######################################
# funcion extraer_primer_float: busca y devuelve el primer número de punto flotante que aparezca en una cadena; si no hay, retorna None
######################################
def extraer_primer_float(s: str):
    if not s: return None
    m = re.search(r'(-?\d+(?:\.\d+)?)', s)
    return float(m.group(1)) if m else None

######################################
# funcion parse_gps_data: parsea la respuesta SCPI SYST:GPS:DATA? del PR100 (formato grados-minutos-segundos con hemisferios) y devuelve latitud y longitud en grados decimales
######################################
def parse_gps_data(s: str):
    
    #PR100 SYST:GPS:DATA? ejemplo:
    #GPS,1,1239090583,220,4,N,48,7,40.33,E,11,36,47.42,2009,4,7,7,49,42,0.00,18.89,0.0,554
    #(lat, lon) grados decimales
    
    if not s:
        return None, None
    try:
        parts = [p.strip() for p in s.split(",")]
        i_ns = next((i for i,p in enumerate(parts) if p in ("N","S")), None)
        if i_ns is None or i_ns + 3 >= len(parts): return None, None
        hemi_ns = parts[i_ns]
        lat_d = float(parts[i_ns+1]); lat_m = float(parts[i_ns+2]); lat_s = float(parts[i_ns+3])

        i_ew = next((i for i,p in enumerate(parts[i_ns+4:], start=i_ns+4) if p in ("E","W")), None)
        if i_ew is None or i_ew + 3 >= len(parts): return None, None
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
# funcion obtener_comandos_pr100: lee json/menu.json y extrae los comandos SCPI del PR100 (medida, gps, brújula) con valores por defecto si faltan
######################################
def obtener_comandos_pr100():
    #Lee json/menu.json y devuelve dict de comandos relevantes por índice.
    cmds = []
    try:
        data = json.loads(JSON_MENU.read_text(encoding='utf-8'))
        for equipo in data.get("Menu", []):
            if equipo.get("name") == "PR100":
                cmds = [str(c) for c in equipo.get("commands", [])]
                break
    except Exception as e:
        log(f"AVISO leyendo {JSON_MENU}: {e}")
    # índices que esperas: 2 medida, 3 gps, 4 brújula 
    cmd_measure = cmds[2].strip() if len(cmds) > 2 and cmds[2].strip() else 'SENSe:DATA? "VOLT:AC"'
    cmd_gps     = cmds[3].strip() if len(cmds) > 3 and cmds[3].strip() else "SYST:GPS:DATA?"
    cmd_compass = cmds[4].strip() if len(cmds) > 4 and cmds[4].strip() else "SYST:COMPass:DATA?"
    return cmd_measure, cmd_gps, cmd_compass

# ================== SCPI helpers (async) ==================
######################################
# funcion scpi_write: envía un comando SCPI terminado en nueva línea por el writer asíncrono y vacía el buffer
######################################
async def scpi_write(writer, cmd: str):
    writer.write((cmd.rstrip("\n") + "\n").encode("ascii", errors="ignore"))
    await writer.drain()

######################################
# funcion scpi_query_line: envía un comando SCPI y espera una línea de respuesta con timeout configurable, devolviendo la cadena decodificada
######################################
async def scpi_query_line(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                          cmd: str, timeout: float = READ_TIMEOUT_S) -> str:
    await scpi_write(writer, cmd)
    line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    return line.decode(errors="replace").strip()

# ================== Señales ==================
stop_ev = asyncio.Event()

######################################
# funcion _handle_sig: manejador de señales que marca el evento de parada para terminar el bucle principal de adquisición de manera ordenada
######################################
def _handle_sig(*_): stop_ev.set()
signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, _handle_sig)

# ================== Main ==================
######################################
# funcion main: coordina la conexión SCPI al PR100, espera fix de GPS para la cabecera del archivo, realiza lecturas periódicas de potencia y azimut, escribe líneas válidas y finaliza limpiamente al recibir señal o al borrarse el archivo de salida
######################################
async def main():
    log(f"Periodo: {PERIODO_S}s — HOST:{HOST} PORT:{PORT}")

    # Truncar archivo 360
    OUT_PATH.write_text("", encoding="utf-8")
    log(f"Truncado {OUT_PATH}")

    # Cargar comandos
    cmd_measure, cmd_gps, cmd_compass = obtener_comandos_pr100()
    log(f"Comandos -> medida: [{cmd_measure}] gps: [{cmd_gps}] brújula: [{cmd_compass}]")

    # Conexión SCPI TCP (ASCII)
    reader, writer = await asyncio.open_connection(HOST, PORT)
    try:
        await scpi_write(writer, "*CLS")
        await scpi_write(writer, "FORMat:DATA ASCii")
    except Exception as e:
        log(f"AVISO init SCPI: {e}")

    # Esperar un rato para tener lat/lon antes de ninguna muestra
    start_wait = asyncio.get_event_loop().time()
    lat0 = lon0 = None
    while not stop_ev.is_set():
        # Si el usuario borra el archivo -> salir
        if not OUT_PATH.exists():
            log("medicion360.txt borrado externamente. Saliendo…")
            break

        # Intentar GPS
        try:
            gps_resp = await scpi_query_line(reader, writer, cmd_gps, READ_TIMEOUT_S)
        except Exception as e:
            gps_resp = ""
            log(f"GPS fallo: {e}")
        lat, lon = parse_gps_data(gps_resp)
        if lat is not None and lon is not None:
            lat0, lon0 = lat, lon
            break

        # Si se excede tiempo de espera, seguimos sin coordenadas (no inventar)
        if asyncio.get_event_loop().time() - start_wait >= GPS_WAIT_S:
            break
        await asyncio.sleep(0.5)

    # Escribir primera línea: lat,long (si las tenemos); si no, línea vacía
    try:
        with OUT_PATH.open("a", encoding="utf-8", newline="") as f:
            if lat0 is not None and lon0 is not None:
                f.write(f"{lat0:.6f},{lon0:.6f}\n")
                log(f"GPS inicial: {lat0:.6f},{lon0:.6f}")
            else:
                f.write("\n")  # 1ª línea vacía -> server pondrá lat/long = None
                log("GPS inicial no disponible (1ª línea vacía).")
    except Exception as e:
        log(f"ERROR escribiendo cabecera GPS: {e}")

    # Bucle de adquisición 360°
    try:
        while not stop_ev.is_set():
            if not OUT_PATH.exists():
                log("medicion360.txt borrado externamente. Saliendo…")
                break

            # 1) Medida (dBµV -> dBm)
            try:
                resp = await scpi_query_line(reader, writer, cmd_measure, READ_TIMEOUT_S)
            except Exception as e:
                resp = ""
                log(f"Medida fallo: {e}")
            dbuv = extraer_primer_float(resp)
            dbm  = dbuv_to_dbm(dbuv) if dbuv is not None else None

            # 2) Brújula (azimut)
            try:
                comp_resp = await scpi_query_line(reader, writer, cmd_compass, READ_TIMEOUT_S)
            except Exception as e:
                comp_resp = ""
                log(f"Brújula fallo: {e}")
            az = extraer_primer_float(comp_resp)  # puede ser None

            # 3) Si tenemos az y dbm, escribir línea "az,dbm"
            if az is not None and dbm is not None and math.isfinite(az) and math.isfinite(dbm):
                try:
                    with OUT_PATH.open("a", encoding="utf-8", newline="") as f:
                        f.write(f"{az:.1f},{dbm:.2f}\n")
                except Exception as e:
                    log(f"ERROR escribiendo muestra: {e}")
            else:
                # No inventar: no escribimos
                pass

            await asyncio.sleep(PERIODO_S)
    except Exception as e:
        log(f"ERROR loop 360: {e}")
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        log("Conexión cerrada. Fin 360.")
    return 0

######################################
# funcion main_guard: punto de entrada para ejecutar la medición 360 desde línea de comandos y cerrar limpiamente ante Ctrl+C
######################################
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
