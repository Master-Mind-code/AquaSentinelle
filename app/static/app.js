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

  var reduit = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;

  var racine = document.documentElement;

  // Thème clair / sombre : le choix est mémorisé ; sans choix, on suit le réglage du système (voir le script du <head>)
  var bascules = document.querySelectorAll("[data-theme-bascule]");
  var majBascules = function () {
    var sombre = racine.getAttribute("data-theme") === "dark";
    bascules.forEach(function (b) {
      b.setAttribute("aria-pressed", sombre ? "true" : "false");
      if (b.classList.contains("theme-bouton")) b.setAttribute("aria-label", sombre ? "Passer en mode clair" : "Passer en mode sombre");
      var libelle = b.querySelector("[data-theme-libelle]");
      if (libelle) libelle.textContent = sombre ? "Mode clair" : "Mode sombre";
    });
    var couleur = document.querySelector('meta[name="theme-color"]');
    if (couleur) couleur.setAttribute("content", sombre ? "#070B14" : "#0B1120");
  };
  bascules.forEach(function (b) {
    b.addEventListener("click", function () {
      var suivant = racine.getAttribute("data-theme") === "dark" ? "light" : "dark";
      var appliquer = function () { racine.setAttribute("data-theme", suivant); majBascules(); };
      try { localStorage.setItem("aqua-theme", suivant); } catch (err) {}
      // Fondu enchaîné entre les deux thèmes quand le navigateur sait le faire
      if (document.startViewTransition && !reduit) document.startViewTransition(appliquer); else appliquer();
    });
  });
  majBascules();
  if (window.matchMedia) {
    var systeme = matchMedia("(prefers-color-scheme: dark)");
    var suivreSysteme = function (e) {
      var choisi = null;
      try { choisi = localStorage.getItem("aqua-theme"); } catch (err) {}
      if (!choisi) { racine.setAttribute("data-theme", e.matches ? "dark" : "light"); majBascules(); }
    };
    if (systeme.addEventListener) systeme.addEventListener("change", suivreSysteme);
  }

  // En-tête : quand le haut de page sort de l'écran, la barre devient un îlot de verre flottant
  var entete = document.getElementById("entete"), repere = document.getElementById("haut-de-page");
  if (entete && repere && "IntersectionObserver" in window) {
    new IntersectionObserver(function (entrees) {
      entete.classList.toggle("defile", !entrees[0].isIntersecting);
    }).observe(repere);
  }

  // Menu sur téléphone : plein écran en verre, liens qui montent un à un ; Échap ou un lien le referment
  var menu = document.getElementById("menu-public"), menuMobile = document.getElementById("menu-mobile");
  if (menu && menuMobile) {
    racine.classList.add("menu-js");
    var ouvrirMenu = function (ouvert) {
      menu.setAttribute("aria-expanded", ouvert ? "true" : "false");
      menu.setAttribute("aria-label", ouvert ? "Fermer le menu" : "Ouvrir le menu");
      menuMobile.classList.toggle("ouvert", ouvert);
      racine.classList.toggle("menu-ouvert", ouvert);
      if (ouvert) { var premier = menuMobile.querySelector("a"); if (premier) setTimeout(function () { premier.focus(); }, 120); }
    };
    menu.addEventListener("click", function () { ouvrirMenu(menu.getAttribute("aria-expanded") !== "true"); });
    menuMobile.querySelectorAll("a").forEach(function (a) { a.addEventListener("click", function () { ouvrirMenu(false); }); });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menuMobile.classList.contains("ouvert")) { ouvrirMenu(false); menu.focus(); }
    });
  }

  // Accueil : la ville choisie colore toute la page. Sans script, le formulaire recharge la page avec ?ville=.
  var donnees = document.getElementById("etats-villes"), choix = document.getElementById("ville");
  if (donnees && choix) {
    var etats = JSON.parse(donnees.textContent), cle = "aqua-ville";
    var titre = document.getElementById("titre-situation"), l1 = titre.querySelector("[data-l1]"),
        l2 = titre.querySelector("[data-l2]"), phrase = document.querySelector("[data-phrase]"),
        zoneSms = document.getElementById("sms-zone"), voir = document.querySelector(".bouton-voir");
    if (voir) voir.hidden = true;

    var appliquer = function (id, memoriser) {
      var e = etats[id] || etats[""];
      document.body.setAttribute("data-champ", e.champ);
      l1.textContent = e.l1; l2.textContent = e.l2; phrase.textContent = e.phrase;
      titre.classList.toggle("long", !!e.long);
      // sur la carte de la goutte : anneau autour de la ville choisie (le repère d'Abidjan regroupe ses communes)
      document.querySelectorAll(".repere").forEach(function (r) {
        r.classList.toggle("choisie", !!id && (r.dataset.ville === id || (r.dataset.communes || "").split(" ").indexOf(id) >= 0));
      });
      if (id && zoneSms) { zoneSms.value = id; zoneSms.dispatchEvent(new Event("change")); }
      if (memoriser) {
        try { if (id) localStorage.setItem(cle, id); else localStorage.removeItem(cle); } catch (err) {}
        history.replaceState(null, "", id ? "/?ville=" + encodeURIComponent(id) : "/");
      }
    };
    choix.addEventListener("change", function () { appliquer(choix.value, true); });

    // Une ville de la liste : on la choisit et on remonte voir sa couleur
    document.querySelectorAll("[data-ville]").forEach(function (lien) {
      lien.addEventListener("click", function (ev) {
        ev.preventDefault();
        choix.value = lien.dataset.ville;
        appliquer(lien.dataset.ville, true);
        document.getElementById("situation").scrollIntoView({ behavior: reduit ? "auto" : "smooth" });
      });
    });

    // Ville mémorisée lors d'une visite précédente (sauf si l'adresse en désigne une)
    if (!/[?&]ville=/.test(location.search)) {
      var memoire = null;
      try { memoire = localStorage.getItem(cle); } catch (err) {}
      if (memoire && etats[memoire]) { choix.value = memoire; appliquer(memoire, false); }
    }
  }

  // Formulaires en étapes : chaque étape est cochée dès que ce qu'elle demande est rempli (data-fait).
  // La position GPS arrive après coup (position.js remplit #lat sans événement) : on revérifie régulièrement.
  document.querySelectorAll("form[data-progression]").forEach(function (form) {
    var liste = form.parentElement.querySelector(".progression");
    if (!liste) return;
    var etapes = form.querySelectorAll("[data-etape]");
    var rempli = function (el) {
      if (el.type === "file") return el.files && el.files.length > 0;
      if (el.type === "checkbox" || el.type === "radio") return el.checked;
      return !!(el.value || "").trim();
    };
    var mettreAJour = function () {
      var courante = null;
      etapes.forEach(function (etape) {
        var fait = Array.prototype.some.call(form.querySelectorAll(etape.dataset.fait), rempli);
        var li = liste.querySelector('[data-pour="' + etape.dataset.etape + '"]');
        if (!li) return;
        li.classList.toggle("fait", fait);
        li.removeAttribute("aria-current");
        if (!fait && !courante) courante = li;
      });
      if (courante) courante.setAttribute("aria-current", "step");
    };
    ["input", "change", "click"].forEach(function (t) { form.addEventListener(t, function () { requestAnimationFrame(mettreAJour); }); });
    setInterval(mettreAJour, 1500);
    mettreAJour();
  });

  // Alertes SMS (page dédiée et accueil) : l'aperçu du téléphone reprend le vrai modèle de message, pour la commune choisie
  var sms = document.querySelector("[data-sms]"), communeSms = document.querySelector("#form-abonnement #zone, #sms-zone");
  if (sms && communeSms) {
    var majSms = function (animer) {
      var option = communeSms.options[communeSms.selectedIndex];
      if (!option) return;
      var modele = option.dataset.type === "fluviale" ? sms.dataset.crue : sms.dataset.pluie;
      sms.textContent = modele.replace("{zone}", option.text);
      if (animer) { var bulle = sms.parentElement; bulle.classList.remove("nouveau"); void bulle.offsetWidth; bulle.classList.add("nouveau"); }
    };
    communeSms.addEventListener("change", function () { majSms(true); });
    majSms(false);
  }

  // Pluviomètre : le dessin se remplit avec la hauteur saisie (graduation jusqu'à 100 mm)
  var champMm = document.querySelector("[data-jauge]"), jauge = document.querySelector(".jauge");
  if (champMm && jauge) {
    var valeur = jauge.querySelector("[data-jauge-valeur]"), note = jauge.querySelector("[data-jauge-note]");
    var enregistre = parseFloat(valeur.textContent) || 0;   // relevé qui vient d'être envoyé, le cas échéant
    var majJauge = function () {
      var saisi = String(champMm.value).replace(",", ".");
      var mm = Math.max(0, saisi === "" ? enregistre : parseFloat(saisi) || 0);
      jauge.style.setProperty("--niveau", Math.min(mm, 100) / 100);
      valeur.textContent = Math.round(mm);
      note.textContent = mm > 100 ? "Au-delà de la graduation : vérifiez avant d'envoyer."
                       : mm >= 50 ? "Forte pluie : ce relevé sera vérifié avant d'entrer dans le calcul." : "";
    };
    champMm.addEventListener("input", majJauge);
    majJauge();
  }

  // Entrées au défilement sur toutes les pages : les blocs marqués à la main, plus les blocs de contenu de chaque page
  // (portail et espace opérateur). Le contenu n'est masqué que si ce script tourne.
  if (!reduit && "IntersectionObserver" in window) {
    var auto = document.querySelectorAll([
      "main.public > :not(.tete):not(.champ):not(.moment):not(.formulaire-etapes):not(.lecture):not(.geste):not(script):not(svg):not([data-revele]):not(.revele)",
      ".formulaire-etapes > .progression", ".formulaire [data-etape]", ".formulaire .envoi-form",
      ".principal main > :not(script):not(.indicateurs):not(.grille):not(.deux-colonnes):not(.tete):not(.champ)",
      ".indicateurs > *", ".grille > *", ".deux-colonnes > *", ".pied-colonnes > *", ".mot-blocs"
    ].join(","));
    auto.forEach(function (el) {
      if (el.closest(".tete, [data-revele]") && !el.matches(".pied-colonnes > *")) return;
      el.classList.add("revele");
      // léger décalage entre voisins d'une même grille
      var rang = Array.prototype.indexOf.call(el.parentElement.children, el);
      if (el.parentElement.matches(".indicateurs, .grille, .deux-colonnes, .pied-colonnes")) el.style.setProperty("--i", Math.min(rang, 6));
    });
    document.querySelectorAll(".mot-blocs .bloc").forEach(function (b, j) { b.style.setProperty("--j", j); });
  }
  var cibles = document.querySelectorAll("[data-revele], .revele");
  if (cibles.length && "IntersectionObserver" in window && !reduit) {
    document.documentElement.classList.add("revele-actif");
    var observateur = new IntersectionObserver(function (entrees) {
      entrees.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("vu"); observateur.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -6% 0px" });
    cibles.forEach(function (c) { observateur.observe(c); });
    window.addEventListener("beforeprint", function () { cibles.forEach(function (c) { c.classList.add("vu"); }); });
  }
})();
