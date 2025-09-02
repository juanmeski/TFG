# -----------------------------------------------------------------------------
#   Función: Main.py:
#   Este módulo actúa como orquestador para iniciar la medición del sistema desde Python.
#   Actualmente lanza el proceso del equipo de medida (PR100 o su stub de pruebas) en una sesión de proceso separada,
#   delegando la recolección de muestras a ese script. Originalmente contemplaba integrar una cámara y un GPS alternativo
#   para sincronizar capturas e información de ubicación, pero esas piezas (Camara/Camara_alternativo y Gps_alternativo)
#   no se usan finalmente y permanecen comentadas para referencia futura.
# -----------------------------------------------------------------------------

import time
import threading
from multiprocessing import Manager, Process
import subprocess
import os
import signal

import sys

# ######################################
# # funcion signal_handler: manejador de señal para terminar ordenadamente la medición imprimiendo un aviso antes de salir
# ######################################
#def signal_handler(sig, frame):
  #  print('Proceso medición detenido')
   # sys.exit(0)

# ######################################
# # funcion wait_for_camera: bloquea la ejecución hasta que la cámara haya hecho la primera foto para evitar errores por arranque lento
# ######################################
# wait_for_camera(flag_camera):
#    print("Esperando a que la cámara tome la primera foto para evitar errores...")
   # while flag_camera.value == 0:
   #     time.sleep(1)
   # print("La cámara ha tomado la primera foto. Continuando...")

# ######################################
# # funcion run_camera: lanza el script de la cámara en un proceso independiente o la variante alternativa si aplica
# ######################################
#def run_camera(flag_camera):
   # subprocess.Popen(['python', 'Camara.py', str(flag_camera.value)])
#from Camara_alternativo import run_camera
  #  run_camera(flag_camera)
    
# ######################################
# # funcion run_gps: arranca el proceso del GPS alternativo que publica la posición de manera asíncrona
# ######################################
#def run_gps():
    
#    subprocess.Popen(['python', 'python/Gps_alternativo.py'])
    
######################################
# funcion run_equipo: inicia el script del equipo de medición en un nuevo grupo de procesos para poder detenerlo de forma limpia desde fuera
######################################
def run_equipo():
   
   subprocess.Popen(
   ['python', 'python/Pr100.py'],
  #   ['python', 'python/pruebasinpr100.py'],# stub de pruebas sin PR100
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP  # clave en Windows para enviar señales a todo el grupo
    )
    
# ######################################
# # funcion run_map: refresca periódicamente la generación del mapa en un bucle simple ejecutando el script correspondiente
# ######################################
#def run_map():
    #while True:
     #   print("Actualizando el mapa...")
    #    subprocess.Popen(['python', 'Map.py'])  # Ejecutar el script del mapa
   #     time.sleep(5)  # Esperar x segundos antes de actualizar el mapa


######################################
# funcion main: punto de entrada que prepara el entorno y lanza en paralelo el proceso de medición delegando el bucle de adquisición al script del equipo
######################################
def main():
    print("Iniciando el proceso principal...",flush=True)
    
   # Si en el futuro reactivas cámara/GPS:
    # manager = Manager()
    # flag_camera = manager.Value("i", 0)  # 0 hasta tener primera foto
    # camera_process = Process(target=run_camera, args=(flag_camera,))
    # camera_process.start()
    # wait_for_camera(flag_camera)

    # Ejecutar  scripts: GPS y medición(pe. Pr100.py)

    medicion_process = Process(target=run_equipo)
    medicion_process.start()

    
if __name__ == "__main__":
    main()
