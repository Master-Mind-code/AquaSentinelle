// Choix d'une position : GPS du téléphone (« Ma position ») ou toucher la carte. Remplit lat / lon / precision.
// La géolocalisation du navigateur n'est disponible qu'en HTTPS (ou sur localhost) : sinon, la carte reste possible.
(function () {
  var conteneur = document.getElementById("choix-position");
  if (!conteneur || !window.L) return;
  var lat = document.getElementById("lat"), lon = document.getElementById("lon"), prec = document.getElementById("precision");
  var etat = document.getElementById("etat-position");
  var carte = L.map(conteneur).setView([5.36, -4.02], 11);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 19, attribution: "© OpenStreetMap"}).addTo(carte);
  var marqueur = null;
  function poser(la, lo, precision, source) {
    lat.value = la.toFixed(6); lon.value = lo.toFixed(6); prec.value = precision ? Math.round(precision) : "";
    if (marqueur) marqueur.setLatLng([la, lo]); else marqueur = L.marker([la, lo]).addTo(carte);
    carte.setView([la, lo], Math.max(carte.getZoom(), 16));
    etat.textContent = "Position enregistrée (" + source + (precision ? ", à " + Math.round(precision) + " m près" : "") + ").";
    etat.className = "ok-boite";
  }
  carte.on("click", function (e) { poser(e.latlng.lat, e.latlng.lng, null, "carte"); });
  var bouton = document.getElementById("ma-position");
  if (bouton) bouton.addEventListener("click", function () {
    if (!navigator.geolocation) { etat.textContent = "Votre téléphone ne donne pas sa position : touchez la carte."; return; }
    etat.textContent = "Recherche de votre position…"; etat.className = "info-boite";
    navigator.geolocation.getCurrentPosition(
      function (p) { poser(p.coords.latitude, p.coords.longitude, p.coords.accuracy, "GPS"); },
      function () { etat.textContent = "Position GPS indisponible (autorisation refusée ou connexion non sécurisée) : touchez la carte à l'endroit concerné."; etat.className = "alerte-boite"; },
      {enableHighAccuracy: true, timeout: 15000, maximumAge: 60000});
  });
})();
