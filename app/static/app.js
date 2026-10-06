// AquaSentinelle CI : comportements d'interface, sans dépendance.
(function () {
  // Tiroir de navigation sur mobile
  var bouton = document.getElementById("ouvrir-menu"), lat = document.getElementById("laterale");
  if (bouton && lat) {
    bouton.addEventListener("click", function () {
      var ouvert = lat.classList.toggle("ouverte");
      bouton.setAttribute("aria-expanded", ouvert ? "true" : "false");
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { lat.classList.remove("ouverte"); bouton.setAttribute("aria-expanded", "false"); } });
  }
  // Retour visuel à l'envoi : le bouton cliqué indique « Envoi… » et l'envoi ne part qu'une fois
  document.querySelectorAll("form").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (f.dataset.envoye) { e.preventDefault(); return; }
      f.dataset.envoye = "1";
      var b = e.submitter || f.querySelector("button[type=submit], button:not([type])");
      if (b) {
        // désactivé APRÈS la constitution des données du formulaire : la valeur du bouton part bien
        setTimeout(function () { b.disabled = true; b.classList.add("envoi"); b.dataset.libelle = b.textContent; b.textContent = "Envoi…"; }, 0);
      }
    });
  });
  // Aperçu de la photo avant envoi (formulaire du relais)
  var photo = document.getElementById("photo"), apercu = document.getElementById("apercu");
  if (photo && apercu) {
    photo.addEventListener("change", function () {
      var f = photo.files && photo.files[0];
      if (f) { apercu.src = URL.createObjectURL(f); apercu.hidden = false; }
    });
  }
})();
