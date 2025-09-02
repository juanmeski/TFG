/*
index.js — portada: carga el menú de equipos y rellena la galería.

Este script obtiene /json/menu.json, solicita (opcionalmente) la geolocalización del usuario
—que hoy no se utiliza para nada crítico— y pinta en index.html hasta MAX_MENU tarjetas con
nombre, imagen y enlace a /pagina{N}.html. Si la geolocalización falla o el usuario la deniega,
la carga del contenido no se detiene. El bloque comentado del inicio es legado y no se usa.
*/
// Estado global sencillo para el JSON del menú
var menus;


//Número máximo de museos en el grid container
const MAX_MENU = 6;

// Opciones de geolocalización (opcionales: si falla, seguimos igual)
var options = {
  enableHighAccuracy: true,
  timeout: 5000,
  maximumAge: 0
};

// ------------------------------------------------------------
// Carga del JSON de menú (XHR clásico por compatibilidad)
// ------------------------------------------------------------
const xhttp = new XMLHttpRequest();
xhttp.open('GET', '/json/menu.json', true)
xhttp.send();
xhttp.onreadystatechange = function () {
  // Espera a que termine y sea OK
  if (this.readyState == 4 && this.status == 200) {

    menus = JSON.parse(this.responseText);
    navigator.geolocation.getCurrentPosition(success, error, options);
    addPageContent();
  }
}
// ------------------------------------------------------------
// Rellena la portada con los elementos del menú
// ------------------------------------------------------------
function addPageContent() {

  for (let i = 0; i < MAX_MENU; i++) {
    document.getElementById("titulo_galeria_index" + i.toString()).innerHTML = menus.Menu[i].name;
    document.getElementById("foto_galeria_index" + i.toString()).src = menus.Menu[i].image;
    document.getElementById("titulo_galeria_index" + i.toString()).href = "/pagina" + (i + 1) + ".html";
  }

}
// ------------------------------------------------------------
// Callbacks de geolocalización (hoy solo informativos)
// ------------------------------------------------------------
/**
 * Éxito en geolocalización: guardamos coords para usos futuros
 * y repintamos (por si en el futuro condiciona el contenido).
 */

function success(pos) {
  var crd = pos.coords;
  userLat = crd.latitude;
  userLng = crd.longitude;
  locationError = false;
  //Añadimos el contenido de la página
  addPageContent();
}

function error(err) {
  console.warn('ERROR(' + err.code + '): ' + err.message);
};




