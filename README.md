# Practica_Final_TFG_Juan_Mesquida_
Página web Búsqueda interferencias (JPIT)
pyinstaller --noconfirm --windowed --onefile `
  --name BuscadorInterferencias `
  --add-data "html;html" `
  --add-data "css;css" `
  --add-data "js;js" `
  --add-data "video;video" `
  --add-data "images;images" `
  --add-data "json;json" `
  --add-data "animated;animated" `
  --add-data "map;map" `
  --add-data "frames;frames" `
  --add-data "Capturas;Capturas" `
  --add-data "txt;txt" `
  --add-data "analysis;analysis" `
  --add-data "python;python" `
  app_desktop.py

