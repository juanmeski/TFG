# -----------------------------------------------------------------------------
#   Función: Cambiar_freq.py: Cambio de frecuencia del PR100 vía SCPI TCP (socket)
# - Usa HOST/PORT desde variables de entorno (mismo puerto que pr100.py).
# - Envía:   FREQ <MHz>MHz
# - Verifica: FREQ?  (si responde, devuelve eco; si no, "OK")
# - Valida formato "número con punto" en MHz (p.ej. "433.92").
# -----------------------------------------------------------------------------

import os, re, socket

HOST = os.environ.get("PR100_HOST", "172.17.75.1")
PORT = int(os.environ.get("PR100_PORT", "5555"))  # mismo puerto que pr100.py

######################################
# funcion _write_line: escribe una línea SCPI en el socket asegurando salto de línea y codificación ASCII ignorando caracteres no imprimibles
######################################
def _write_line(f, s: str):
    # Asegura un único '\n' al final y codifica en ASCII de forma segura.
    f.write((s.rstrip("\n") + "\n").encode("ascii", errors="ignore"))

######################################
# funcion enviar_comando_frecuencia: valida la cadena de frecuencia en MHz, construye y envía FREQ <MHz>MHz por SCPI TCP al PR100, solicita eco con FREQ? y devuelve la respuesta o "OK" si no hay eco
######################################
def enviar_comando_frecuencia(freq_mhz: str) -> str:
    
    #Cambia la frecuencia central del PR100.
    #- freq_mhz: string numérica en MHz, admite decimales con punto (ej. "433.92")
    #Devuelve el eco de 'FREQ?' si es posible, si no "OK".
    #Lanza ValueError si freq es inválida.
    
    # Normaliza separador decimal y valida que sea numérico (entero o decimal).
    freq = str(freq_mhz or "").strip().replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d+)?", freq):
        raise ValueError("Frecuencia inválida; usa formato numérico en MHz (ej. 433.92)")

    # Prepara comandos SCPI:
    # - Fijar frecuencia (MHz)
    # - Preguntar eco de frecuencia
    cmd_set  = f"FREQ {freq}MHz"
    cmd_echo = "FREQ?"

    # Conexión SCPI directa (socket crudo) al PR100:
    # Usamos makefile para leer/escribir tipo archivo (más simple que usar s.send/recv).
    # Timeout corto para no bloquear la UI si el equipo no responde.
    with socket.create_connection((HOST, PORT), timeout=5.0) as s:
        f = s.makefile("rwb", buffering=0)
        
        # Limpia estado y envía set + echo
        _write_line(f, "*CLS")
        _write_line(f, cmd_set)
        _write_line(f, cmd_echo)
        
        # Algunas implementaciones devuelven "4.339200e+08" o "433.92 MHz".
        # Si no hay respuesta en la primera línea, devolvemos "OK" igualmente.
        resp = f.readline().decode(errors="ignore").strip()
        return resp or "OK"
