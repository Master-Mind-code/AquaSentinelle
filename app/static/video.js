// AquaSentinelle CI : lecteur de la vidéo animée du guide (/guide). Scènes HTML minutées, sous-titres, voix du téléphone.
(function () {
  var video = document.getElementById("video");
  if (!video) return;
  var scenes = Array.prototype.slice.call(video.querySelectorAll(".scene"));
  var durees = scenes.map(function (s) { return parseFloat(s.dataset.duree) * 1000; });
  var total = durees.reduce(function (a, b) { return a + b; }, 0);
  var lancer = document.getElementById("video-lancer"), lecture = document.getElementById("video-lecture"),
      son = document.getElementById("video-son"), barre = document.querySelector("#video-barre span"),
      temps = document.getElementById("video-temps"), sousTitres = document.getElementById("video-sous-titres"),
      chapitres = document.getElementById("video-chapitres");

  var courant = 0, ecoule = 0, enLecture = false, dernier = 0, parleEnCours = false;
  var synthese = window.speechSynthesis, voix = null, voixActive = !!synthese;

  function choisirVoix() {
    if (!synthese) return;
    var v = synthese.getVoices().filter(function (x) { return /^fr/i.test(x.lang); });
    voix = v.filter(function (x) { return /fr[-_]FR/i.test(x.lang); })[0] || v[0] || null;
  }
  if (synthese) { choisirVoix(); synthese.addEventListener && synthese.addEventListener("voiceschanged", choisirVoix); }

  function mmss(ms) { var s = Math.round(ms / 1000); return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2); }
  function icone(bouton, nom) { var u = bouton.querySelector("use"); if (u) u.setAttribute("href", "/static/icones.svg#" + nom); }

  scenes.forEach(function (s, i) {
    var li = document.createElement("li"), b = document.createElement("button");
    b.type = "button"; b.className = "leger";
    b.innerHTML = "<span>" + (i + 1) + "</span>" + s.dataset.titre;
    b.addEventListener("click", function () { aller(i); jouer(); video.scrollIntoView({ block: "start" }); });
    li.appendChild(b); chapitres.appendChild(li);
  });

  function parler(texte) {
    if (!synthese || !voixActive) return;
    synthese.cancel();
    var u = new SpeechSynthesisUtterance(texte);
    u.lang = "fr-FR"; if (voix) u.voice = voix; u.rate = 0.95;
    parleEnCours = true;
    u.onend = u.onerror = function () { parleEnCours = false; };
    synthese.speak(u);
  }
  function taire() { parleEnCours = false; if (synthese) synthese.cancel(); }

  function aller(i) {
    courant = Math.max(0, Math.min(scenes.length - 1, i)); ecoule = 0;
    scenes.forEach(function (s, j) {
      s.classList.remove("active");
      s.hidden = j !== courant;
    });
    void scenes[courant].offsetWidth;            // relance les animations CSS de la scène
    scenes[courant].classList.add("active");
    sousTitres.textContent = scenes[courant].dataset.texte;
    chapitres.querySelectorAll("button").forEach(function (b, j) {
      if (j === courant) b.setAttribute("aria-current", "step"); else b.removeAttribute("aria-current");
    });
    if (enLecture) parler(scenes[courant].dataset.texte);
    afficherTemps();
  }
  function afficherTemps() {
    var avant = durees.slice(0, courant).reduce(function (a, b) { return a + b; }, 0) + Math.min(ecoule, durees[courant]);
    barre.style.width = (100 * avant / total) + "%";
    temps.textContent = mmss(avant) + " / " + mmss(total);
  }
  function boucle(t) {
    if (!enLecture) return;
    ecoule += t - dernier; dernier = t;
    // la scène suivante attend aussi la fin de la phrase : une voix lente ne se fait pas couper
    if (ecoule >= durees[courant] && !parleEnCours) {
      if (courant === scenes.length - 1) { fin(); return; }
      aller(courant + 1);
    }
    afficherTemps();
    requestAnimationFrame(boucle);
  }
  function jouer() {
    if (enLecture) return;
    enLecture = true; lancer.hidden = true; video.classList.add("en-lecture");
    icone(lecture, "pause"); lecture.setAttribute("aria-label", "Pause");
    ecoule = 0; aller(courant);                    // reprise au début de la scène, avec sa phrase
    dernier = performance.now(); requestAnimationFrame(boucle);
  }
  function pause() {
    enLecture = false; taire(); video.classList.remove("en-lecture");
    icone(lecture, "play"); lecture.setAttribute("aria-label", "Lecture");
  }
  function fin() {
    pause(); courant = 0; ecoule = 0;
    lancer.hidden = false; lancer.querySelector("span").textContent = "Revoir la vidéo";
    barre.style.width = "100%"; temps.textContent = mmss(total) + " / " + mmss(total);
  }

  lancer.addEventListener("click", jouer);
  lecture.addEventListener("click", function () { enLecture ? pause() : jouer(); });
  if (!synthese) { son.hidden = true; }
  son.addEventListener("click", function () {
    voixActive = !voixActive;
    son.setAttribute("aria-pressed", voixActive ? "true" : "false");
    son.setAttribute("aria-label", voixActive ? "Couper la voix" : "Activer la voix");
    icone(son, voixActive ? "volume-2" : "volume-x");
    if (!voixActive) taire(); else if (enLecture) parler(scenes[courant].dataset.texte);
  });
  document.addEventListener("visibilitychange", function () { if (document.hidden && enLecture) pause(); });

  aller(0);
})();
