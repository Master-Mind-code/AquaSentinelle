// AquaSentinelle CI : guide de première visite (Gouti) et bouton d'aide du portail public. Sans dépendance.
(function () {
  var guide = document.getElementById("guide");
  if (!guide || typeof guide.showModal !== "function") return;   // navigateur trop ancien : la page reste utilisable
  var etapes = guide.querySelectorAll(".guide-etape"), n = etapes.length, courant = 0;
  var points = guide.querySelector(".guide-points"), compte = guide.querySelector(".guide-compte");
  var bPrec = guide.querySelector('[data-guide="precedent"]'), bSuiv = guide.querySelector('[data-guide="suivant"]'),
      bFin = guide.querySelector('[data-guide="fin"]');
  var cle = "aqua-guide-vu-" + guide.dataset.jeu;

  // stockage facultatif : en navigation privée ou bloqué, le guide se montre simplement à chaque visite
  function lire() { try { return localStorage.getItem(cle); } catch (e) { return null; } }
  function noter() { try { localStorage.setItem(cle, "1"); } catch (e) {} }

  for (var i = 0; i < n; i++) points.appendChild(document.createElement("span"));

  function montrer(k) {
    courant = Math.max(0, Math.min(n - 1, k));
    etapes.forEach(function (e, j) { e.hidden = j !== courant; });
    points.querySelectorAll("span").forEach(function (p, j) { p.className = j === courant ? "actif" : ""; });
    compte.textContent = "Étape " + (courant + 1) + " sur " + n;
    guide.setAttribute("aria-labelledby", "guide-titre-" + (courant + 1));
    bPrec.style.visibility = courant === 0 ? "hidden" : "visible";
    bSuiv.hidden = courant === n - 1;
    bFin.hidden = courant !== n - 1;
    (courant === n - 1 ? bFin : bSuiv).focus();
  }
  function ouvrir() { fermerBulle(); montrer(0); if (!guide.open) guide.showModal(); }

  bPrec.addEventListener("click", function () { montrer(courant - 1); });
  bSuiv.addEventListener("click", function () { montrer(courant + 1); });
  bFin.addEventListener("click", function () { guide.close(); });
  guide.addEventListener("close", noter);          // fermé, passé ou terminé : on ne le réimpose pas
  guide.addEventListener("click", function (e) { if (e.target === guide) guide.close(); });   // clic hors de la boîte
  guide.addEventListener("keydown", function (e) {
    if (e.key === "ArrowRight") montrer(courant + 1);
    if (e.key === "ArrowLeft") montrer(courant - 1);
  });

  // Bouton d'aide flottant : conseil propre à la page, puis guide ou vidéo
  var bouton = document.getElementById("gouti-bouton"), bulle = document.getElementById("gouti-bulle");
  function fermerBulle() { if (bulle) { bulle.hidden = true; bouton.setAttribute("aria-expanded", "false"); } }
  if (bouton && bulle) {
    bouton.addEventListener("click", function () {
      bulle.hidden = !bulle.hidden;
      bouton.setAttribute("aria-expanded", bulle.hidden ? "false" : "true");
    });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") fermerBulle(); });
  }
  document.querySelectorAll('[data-guide="ouvrir"]').forEach(function (b) { b.addEventListener("click", ouvrir); });

  // Première visite : le guide s'ouvre seul, sauf sur la page d'urgence
  var demande = /[?&]guide=1\b/.test(location.search);
  if (demande || (guide.dataset.auto === "oui" && !lire() && !/[?&]guide=0\b/.test(location.search))) {
    setTimeout(ouvrir, 500);
  }
})();
