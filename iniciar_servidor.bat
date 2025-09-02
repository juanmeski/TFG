@echo off
REM Ir a la carpeta del script (raíz del proyecto)
cd /d "%~dp0"

REM (Opcional) Modo producción
set FLASK_ENV=production

REM Lanzar el servidor en una ventana aparte MINIMIZADA
REM Cambia "py" por "py -3.13" o "python" si lo necesitas
start "Buscador Interferencias (server)" /min py server.py

REM Esperar a que el puerto 5000 responda (máx ~10s)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$t=Get-Date; while((Get-Date)-$t -lt (New-TimeSpan -Seconds 10)){" ^
  " if (Test-NetConnection -ComputerName 'localhost' -Port 5000 -InformationLevel Quiet){exit 0};" ^
  " Start-Sleep -Milliseconds 250 }; exit 1"

REM Abra o no con éxito, intenta abrir el navegador
start "" http://localhost:5000
