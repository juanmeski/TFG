# -----------------------------------------------------------------------------
#   Función: Pr100.py: Simulador sin PR100: leyendo comandos desde json/menu.json:
#   txt/Potencia.txt al arrancar (nueva medición).
#   capturas/ y frames/ y empieza desde 0.
#   Cada muestra escribe: fecha,hora,dbm,acimut,lat,long
#   Guarda captura JPG y frame JPG por muestra en /capturas/captura_{idx}.jpg y /frames/frame_{idx}.jpg
#   Permite cambiar periodo por UDP (127.0.0.1:9999). Si el puerto está ocupado, sigue sin UDP.
# -----------------------------------------------------------------------------

import asyncio
import os
import math
import random
from datetime import datetime
from pathlib import Path
import signal

# ================== CONFIG ==================
BASE_DIR = Path(__file__).resolve().parent          # .../python
ROOT_DIR = BASE_DIR.parent                          # raíz del proyecto
TXT_DIR = ROOT_DIR / "txt"
CAPTURAS_DIR = ROOT_DIR / "capturas"
FRAMES_DIR = ROOT_DIR / "frames"
TXT_DIR.mkdir(parents=True, exist_ok=True)
CAPTURAS_DIR.mkdir(parents=True, exist_ok=True)
FRAMES_DIR.mkdir(parents=True, exist_ok=True)

OUT_PATH = TXT_DIR / "Potencia.txt"

# Periodo (s)
try:
    PERIODO_S = float(os.environ.get("SAMPLE_PERIOD", "5"))
    if PERIODO_S <= 0:
        PERIODO_S = 5.0
except Exception:
    PERIODO_S = 5.0

# Sim potencia
BASE_DBM       = float(os.environ.get("SIM_BASE_DBM", "-70"))
NOISE_STD_DB   = float(os.environ.get("SIM_NOISE_STD_DB", "3"))
SINE_AMP_DB    = float(os.environ.get("SIM_SINE_AMP_DB", "8"))
SINE_PERIOD_S  = float(os.environ.get("SIM_SINE_PERIOD_S", "120"))
DRIFT_DBPM     = float(os.environ.get("SIM_DRIFT_DBPM", "0.0"))
SPIKE_PROB     = float(os.environ.get("SIM_SPIKE_PROB", "0.03"))
SPIKE_DBM      = float(os.environ.get("SIM_SPIKE_DBM", "-35"))
CLAMP_MIN      = float(os.environ.get("SIM_CLAMP_MIN_DBM", "-120"))
CLAMP_MAX      = float(os.environ.get("SIM_CLAMP_MAX_DBM", "-10"))

# Sim geografía (centro Mallorca por defecto)
CENTER_LAT = float(os.environ.get("SIM_CENTER_LAT", "39.5696"))
CENTER_LON = float(os.environ.get("SIM_CENTER_LON", "2.6502"))
STEP_METERS = float(os.environ.get("SIM_STEP_METERS", "2.0"))

CAPTURE_EXT = "jpg"

######################################
# funcion meters_to_deg_latlon: convierte un desplazamiento en metros a incrementos de latitud/longitud en grados corrigiendo por la latitud
######################################
def meters_to_deg_latlon(d_m, lat_deg):
    dlat = d_m / 111_320.0
    dlon = d_m / (111_320.0 * max(1e-6, math.cos(math.radians(lat_deg))))
    return dlat, dlon

######################################
# funcion next_capture_path: devuelve la ruta de archivo para la captura JPG del índice dado dentro de /capturas
######################################
def next_capture_path(idx):
    return CAPTURAS_DIR / f"captura_{idx}.{CAPTURE_EXT}"

######################################
# funcion next_frame_path: devuelve la ruta de archivo para el frame JPG del índice dado dentro de /frames
######################################
def next_frame_path(idx):
    return FRAMES_DIR / f"frame_{idx}.{CAPTURE_EXT}"


######################################
# funcion save_card_img: genera y guarda una imagen de tarjeta (JPG) con los metadatos de la muestra simulada y una rosa con el acimut
######################################
def save_card_img(title, when_iso, lat, lon, az, dbm, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

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
        f"Lat:     {lat:.6f}",
        f"Lon:     {lon:.6f}",
        f"Acimut:  {(f'{az:.1f}°' if az is not None else 'no directivo')}",
        f"Potencia:{dbm:.2f} dBm"
    ]
    ax.text(0.5, 0.60, "\n".join(lines), ha='center', va='center',
            fontsize=16, color="#e5eefc", transform=ax.transAxes)

    ang = math.radians(((az or 0.0) - 90.0))
    circ = plt.Circle((0.5, 0.30), 0.18, fill=False, color="#38bdf8", lw=2, transform=ax.transAxes)
    ax.add_patch(circ)
    x2 = 0.5 + 0.17*math.cos(ang)
    y2 = 0.30 + 0.17*math.sin(ang)
    ax.plot([0.5, x2], [0.30, y2], '-', lw=3, color="#7dd3fc", transform=ax.transAxes)
    ax.text(0.5, 0.12, "N", ha='center', va='center', color="#9bdcff", transform=ax.transAxes)

    try:
        plt.savefig(out_path, bbox_inches='tight', facecolor=fig.get_facecolor(),
                    format='jpeg', pil_kwargs={"quality": 92, "optimize": True, "progressive": True})
    except TypeError:
        plt.savefig(out_path, bbox_inches='tight', facecolor=fig.get_facecolor(), format='jpeg')
    finally:
        plt.close(fig)
    return out_path

######################################
# clase PeriodProtocol: receptor UDP que lee un número en segundos y actualiza en caliente el periodo de muestreo del simulador
######################################
class PeriodProtocol(asyncio.DatagramProtocol):
    def datagram_received(self, data, addr):
        global PERIODO_S
        try:
            v = float(data.decode('utf-8').strip())
            if v > 0:
                PERIODO_S = v
                print(f"[INFO] Periodo actualizado a {PERIODO_S} s (UDP)", flush=True)
        except Exception as e:
            print(f"[AVISO] UDP inválido: {e}", flush=True)

######################################
# clase SimState: mantiene el estado de la simulación (tiempo inicial, posición y acimut) con utilidades para el tiempo transcurrido
######################################
class SimState:
    def __init__(self):
        self.start = datetime.now()
        self.lat = CENTER_LAT
        self.lon = CENTER_LON
        self.az  = 0.0

    ######################################
    # funcion elapsed_seconds: devuelve segundos transcurridos desde el inicio de la simulación para modular la potencia
    ######################################
    def elapsed_seconds(self):
        return (datetime.now() - self.start).total_seconds()

######################################
# funcion next_dbm: genera el siguiente valor de potencia dBm combinando base, seno, deriva lenta, ruido y eventos de pico, con límites de seguridad
######################################
def next_dbm(state: SimState) -> float:
    t = state.elapsed_seconds()
    sine = SINE_AMP_DB * math.sin(2 * math.pi * (t / SINE_PERIOD_S)) if SINE_PERIOD_S > 0 else 0.0
    drift = DRIFT_DBPM * (t / 60.0)
    noise = random.gauss(0.0, NOISE_STD_DB)
    val = BASE_DBM + sine + drift + noise
    if random.random() < SPIKE_PROB:
        val = SPIKE_DBM + random.gauss(0.0, 1.0)
    val = max(CLAMP_MIN, min(CLAMP_MAX, val))
    return float(f"{val:.2f}")

######################################
# funcion next_geo: actualiza posición y acimut simulando un pequeño desplazamiento aleatorio y un avance de orientación en grados
######################################
def next_geo(state: SimState):
    step = random.uniform(0, STEP_METERS)
    bearing = random.uniform(0, 2*math.pi)
    dlat, dlon = meters_to_deg_latlon(step, state.lat)
    state.lat += dlat * math.sin(bearing)
    state.lon += dlon * math.cos(bearing)
    state.az = (state.az + random.uniform(2.0, 12.0)) % 360.0
    return state.lat, state.lon, state.az

stop_ev = asyncio.Event()

######################################
# funcion _handle_sig: marca el evento de parada para finalizar el bucle principal al recibir señales SIGINT/SIGTERM/SIGBREAK
######################################
def _handle_sig(*_): stop_ev.set()
signal.signal(signal.SIGINT, _handle_sig)
signal.signal(signal.SIGTERM, _handle_sig)
if hasattr(signal, 'SIGBREAK'):
    signal.signal(signal.SIGBREAK, _handle_sig)

######################################
# funcion main: orquesta la simulación; prepara carpetas y archivos, limpia recursos previos, configura UDP opcional, genera muestras periódicas, guarda CSV y tarjetas, y cierra ordenadamente
######################################
async def main():
    global PERIODO_S
    print(f"[INFO] Periodo inicial: {PERIODO_S} s", flush=True)

    # Truncar SIEMPRE Potencia.txt
    OUT_PATH.write_text("", encoding="utf-8")
    print(f"[INFO] Truncado {OUT_PATH}", flush=True)

    # Limpiar capturas y frames
    removed_c = 0
    for p in CAPTURAS_DIR.glob("captura_*.*"):
        try: p.unlink(); removed_c += 1
        except Exception: pass
    removed_f = 0
    for p in FRAMES_DIR.glob("frame_*.*"):
        try: p.unlink(); removed_f += 1
        except Exception: pass
    print(f"[INFO] Capturas antiguas eliminadas ({removed_c}). Frames eliminados ({removed_f}). Empezando en 0.", flush=True)

    # UDP (robusto)
    loop = asyncio.get_running_loop()
    transport = None
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: PeriodProtocol(), local_addr=("127.0.0.1", 9999)
        )
        print("[INFO] UDP en 127.0.0.1:9999 listo.", flush=True)
    except OSError as e:
        print(f"[AVISO] UDP 9999 ocupado: {e}. Continuo sin control por UDP.", flush=True)

    state = SimState()
    idx = 0

    try:
        while not stop_ev.is_set():
            ahora = datetime.now()
            fecha = ahora.strftime("%Y-%m-%d")
            hora  = ahora.strftime("%H:%M:%S")

            dbm = next_dbm(state)
            lat, lon, az = next_geo(state)

            # línea CSV: fecha,hora,dbm,acimut,lat,long
            line = f"{fecha},{hora},{dbm},{az:.1f},{lat:.6f},{lon:.6f}\n"
            if not OUT_PATH.exists():
                print("[INFO] Potencia.txt eliminado externamente. Saliendo…", flush=True)
                break
            with OUT_PATH.open("a", encoding="utf-8") as f:
                f.write(line)

            # capturas + frames
            save_card_img("Medición simulada", ahora.isoformat(timespec="seconds"), lat, lon, az, dbm, next_capture_path(idx))
            save_card_img("Frame simulado",    ahora.isoformat(timespec="seconds"), lat, lon, az, dbm, next_frame_path(idx))

            idx += 1
            await asyncio.sleep(PERIODO_S)
    finally:
        if transport is not None:
            transport.close()
        print("[INFO] Simulador finalizado.", flush=True)

######################################
# funcion main_guard: punto de entrada que ejecuta el bucle de simulación y maneja KeyboardInterrupt para una salida limpia
######################################
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
