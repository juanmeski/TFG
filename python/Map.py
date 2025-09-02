# -----------------------------------------------------------------------------
#   Función: Map.py: Genera los mapas de puntos y de calor según las coordenadas que obtengamos del muestreo
# -----------------------------------------------------------------------------

import folium
import pandas as pd
import os
from folium.plugins import HeatMap
from branca.colormap import LinearColormap
import numpy as np
from pathlib import Path

# Muestra imagen en el popup si existe frames/frame_{i}.jpg
mostrar_foto = False

######################################
# funcion leer_datos: carga un fichero de medidas (fecha,hora,dbm,acimut,lat,long), tolera que haya una primera línea con el nombre del equipo y/o una cabecera, normaliza tipos numéricos y descarta filas sin lat/lon o dbm para devolver un DataFrame listo para mapear
######################################
def leer_datos(path: str = "txt/Potencia.txt") -> pd.DataFrame:
    
    #fecha,hora,dbm,acimut,lat,long
    #Soporta que el archivo tenga 2 primeras líneas (equipo + cabecera).
    
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=["fecha","hora","dbm","acimut","lat","long"])
    
    # Lectura flexible (coma, tabulador, punto y coma, o espacios raros)
    try:
        # Fallback muy permisivo
        df = pd.read_csv(p, header=None, engine='python',
                         sep=r"[,\t;]\s*|(?:\s{2,})|(?:(?<=\d)\s+(?=\d))")
    except Exception:
        df = pd.read_csv(p, header=None)
        
    # Si la primera línea no parece una fecha (p.ej. "PR100"), asume:
    #   línea 0: equipo
    #   línea 1: cabecera
    # y empieza en la línea 2
    if len(df) >= 2 and isinstance(df.iloc[0,0], str) and not str(df.iloc[0,0]).startswith("20"):
        df = df.iloc[2:].reset_index(drop=True)
        
    # Asegura 6 columnas, con nombres estándar
    n = df.shape[1]
    cols = ["fecha","hora","dbm","acimut","lat","long"]
    if n >= 6:
        df = df.iloc[:, :6].copy(); df.columns = cols
    else:
        for _ in range(6-n): df[n] = np.nan; n += 1
        df.columns = cols

    # Parseos robustos
    def _az(v):
        try: return float(v)
        except: return np.nan
    df["dbm"] = pd.to_numeric(df["dbm"], errors="coerce")
    df["acimut"] = df["acimut"].apply(_az)
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["long"] = pd.to_numeric(df["long"], errors="coerce")
    
    # Mantiene solo filas con potencia y coordenadas válidas
    df = df.dropna(subset=["dbm","lat","long"]).reset_index(drop=True)
    return df

######################################
# funcion generar_mapa: crea dos mapas Folium centrados en la zona de muestreo (puntos y calor), pinta círculos codificados por color según dBm, añade leyenda y guarda los HTML en map/mapa_puntos.html y map/mapa_calor.html
######################################
def generar_mapa():
    datos = leer_datos("txt/Potencia.txt")
    os.makedirs('map', exist_ok=True)

    # Caso sin datos: mapas básicos centrados por defecto
    if datos.empty:
        folium.Map(location=[39.5, 2.5], zoom_start=12).save('map/mapa_puntos.html')
        folium.Map(location=[39.5, 2.5], zoom_start=12).save('map/mapa_calor.html')
        print("[AVISO] Sin datos. Mapas vacíos generados.")
        return

    # Envolvente y centro para encuadre
    lat_min, lat_max = float(datos['lat'].min()), float(datos['lat'].max())
    lon_min, lon_max = float(datos['long'].min()), float(datos['long'].max())
    
    # Evita bounds degenerados si solo hay un punto
    if lat_min == lat_max: lat_min -= 0.0005; lat_max += 0.0005
    if lon_min == lon_max: lon_min -= 0.0005; lon_max += 0.0005
    bounds = [[lat_min, lon_min], [lat_max, lon_max]]
    center_lat = (lat_min + lat_max) / 2.0
    center_lon = (lon_min + lon_max) / 2.0

    # Mapas base
    mapa_puntos = folium.Map(location=[center_lat, center_lon], zoom_start=16)
    mapa_calor  = folium.Map(location=[center_lat, center_lon], zoom_start=16)

    # Rango de potencia y colormap coherente en ambos mapas
    max_pot = float(datos['dbm'].max())
    min_pot = float(datos['dbm'].min())
    colors_v2r = ['green', 'yellow', 'red']
    colormap = LinearColormap(colors=colors_v2r, vmin=min_pot, vmax=max_pot)
    colormap.caption = "Potencia (dBm) — bajo → verde, alto → rojo"
    colormap.add_to(mapa_puntos)
    colormap2 = LinearColormap(colors=colors_v2r, vmin=min_pot, vmax=max_pot)
    colormap2.caption = "Potencia (dBm) — bajo → verde, alto → rojo"
    colormap2.add_to(mapa_calor)

    # Capas: puntos con popup + heatmap (intensidad normalizada)
    heat_data = []
    for i, row in datos.iterrows():
        popup_text = (
            f"Lat: {row['lat']:.6f}<br>"
            f"Lon: {row['long']:.6f}<br>"
            f"Potencia: {row['dbm']:.1f} dBm<br>"
            f"Acimut: {('—' if np.isnan(row['acimut']) else f'{row['acimut']:.1f}°')}"
        )
        iframe = folium.IFrame(html=popup_text, width=220, height=110)
        popup = folium.Popup(iframe, max_width=240)
        color = colormap(row['dbm'])
        folium.CircleMarker(
            location=[row['lat'], row['long']],
            radius=6, color='black', weight=2,
            fill_color=color, fill=True, fill_opacity=0.7,
            popup=popup
        ).add_to(mapa_puntos)

        # Intensidad del HeatMap: 0..1 respecto al rango actual
        intensity = (row['dbm'] - min_pot) / (max_pot - min_pot) if max_pot != min_pot else 0.5
        heat_data.append([row['lat'], row['long'], float(intensity)])

    HeatMap(
        heat_data, min_opacity=0.2, radius=15, blur=25,
        gradient={0.0: 'green', 0.5: 'yellow', 1.0: 'red'}
    ).add_to(mapa_calor)

    # Encaja ambos mapas a los límites de los datos
    try: mapa_puntos.fit_bounds(bounds)
    except Exception: pass
    try: mapa_calor.fit_bounds(bounds)
    except Exception: pass

    # Salida
    mapa_puntos.save('map/mapa_puntos.html')
    mapa_calor.save('map/mapa_calor.html')
    print("Mapas generados en map/mapa_puntos.html y map/mapa_calor.html")

######################################
# funcion main_guard: punto de entrada del script para generar los mapas directamente al ejecutarlo desde línea de comandos
######################################
if __name__ == "__main__":
    generar_mapa()
