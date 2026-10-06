"""Cycle de vie d'une alerte : décision, attente de validation, escalade, diffusion, journal (S11-S17).

États : en_attente -> escaladee -> envoyee | rejetee | annulee (si le niveau redescend avant validation).
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.db import journaliser
from app.securite import dechiffrer
from app.settings import reglages
from src import anti_abus
from src.alertes import decider
from src.canaux import canal
from src.messages import message


def niveau_annonce(cx: Connection, zone_id: str) -> str | None:
    r = cx.execute(text("SELECT niveau FROM etat_zone WHERE zone_id = :z"), {"z": zone_id}).first()
    return r.niveau if r else None


def _fixer_etat(cx: Connection, zone_id: str, niveau: str) -> None:
    cx.execute(text("""
        INSERT INTO etat_zone (zone_id, niveau) VALUES (:z, :n)
        ON CONFLICT (zone_id) DO UPDATE SET niveau = EXCLUDED.niveau, maj_le = now()
    """), {"z": zone_id, "n": niveau})


def _zone(cx: Connection, zone_id: str):
    return cx.execute(text("SELECT id, nom, langue, telegram_chat FROM zone WHERE id = :z"), {"z": zone_id}).one()


def _creer(cx: Connection, zone_id: str, score_id: int | None, niveau: str, statut: str, crue: bool = False) -> int:
    z = _zone(cx, zone_id)
    return cx.execute(text("""
        INSERT INTO alerte (zone_id, score_id, niveau, texte, statut)
        VALUES (:z, :s, :n, :t, :st) RETURNING id
    """), {"z": zone_id, "s": score_id, "n": niveau, "t": message(niveau, z.nom, z.langue, crue, f"{reglages().base_url}/prevention"), "st": statut}).scalar_one()


def traiter_score(cx: Connection, sc: dict) -> dict:
    """Applique les règles r1 à un score qui vient d'être calculé. Renvoie ce qui a été fait."""
    zone_id, niveau = sc["zone_id"], sc.get("niveau")
    if niveau is None:  # aucune donnée de pluie (panne de collecte) : on ne décide rien, surtout pas d'annuler un rouge
        return {"action": "rien", "raison": "aucune donnée de pluie"}
    attente = cx.execute(text(
        "SELECT id FROM alerte WHERE zone_id = :z AND statut IN ('en_attente','escaladee')"), {"z": zone_id}).first()
    if attente:
        if niveau == "rouge":
            return {"action": "deja_en_attente", "alerte_id": attente.id}
        cx.execute(text("UPDATE alerte SET statut = 'annulee' WHERE id = :i"), {"i": attente.id})
        journaliser(cx, "alerte", f"{zone_id} : rouge en attente annulé, niveau redescendu à {niveau}")

    d = decider(niveau, niveau_annonce(cx, zone_id))
    crue = (sc.get("entrees") or {}).get("lecture_retenue") == "debit"
    if d.action == "envoyer":
        aid = _creer(cx, zone_id, sc.get("id"), niveau, "envoyee", crue)
        _fixer_etat(cx, zone_id, niveau)
        bilan = diffuser(cx, aid)
        journaliser(cx, "alerte", f"{zone_id} : {d.raison}, alerte {aid} envoyée ({bilan})")
        return {"action": "envoyee", "alerte_id": aid, "raison": d.raison, "diffusion": bilan}
    if d.action == "attendre_validation":
        aid = _creer(cx, zone_id, sc.get("id"), niveau, "en_attente", crue)
        notifier_operateurs(cx, f"VALIDATION REQUISE : alerte rouge {zone_id} "
                                f"({sc.get('pluie_24h_mm', 0):.0f} mm). {reglages().base_url}/operateur/alertes")
        journaliser(cx, "alerte", f"{zone_id} : rouge en attente de validation (alerte {aid})")
        return {"action": "en_attente", "alerte_id": aid, "raison": d.raison}
    if niveau_annonce(cx, zone_id) != niveau:
        _fixer_etat(cx, zone_id, niveau)
    return {"action": "rien", "raison": d.raison}


def valider(cx: Connection, alerte_id: int, operateur: str) -> dict:
    a = cx.execute(text("SELECT id, zone_id, niveau, statut FROM alerte WHERE id = :i FOR UPDATE"), {"i": alerte_id}).one()
    if a.statut not in ("en_attente", "escaladee"):
        raise ValueError(f"alerte {alerte_id} déjà traitée ({a.statut})")
    cx.execute(text("UPDATE alerte SET validee_par = :o, validee_le = now(), statut = 'envoyee' WHERE id = :i"),
               {"o": operateur, "i": alerte_id})
    _fixer_etat(cx, a.zone_id, a.niveau)
    bilan = diffuser(cx, alerte_id)
    journaliser(cx, "alerte", f"alerte {alerte_id} validée par {operateur} ({bilan})")
    return bilan


def rejeter(cx: Connection, alerte_id: int, operateur: str) -> None:
    n = cx.execute(text("""
        UPDATE alerte SET statut = 'rejetee', validee_par = :o, validee_le = now()
        WHERE id = :i AND statut IN ('en_attente','escaladee')
    """), {"o": operateur, "i": alerte_id}).rowcount
    if not n:
        raise ValueError(f"alerte {alerte_id} déjà traitée")
    journaliser(cx, "alerte", f"alerte {alerte_id} rejetée par {operateur}")


def escalader(cx: Connection) -> int:
    """Rouges en attente depuis plus de ESCALADE_MINUTES : on relance les administrateurs (S12)."""
    lignes = cx.execute(text("""
        UPDATE alerte SET statut = 'escaladee', escaladee_le = now()
        WHERE statut = 'en_attente' AND cree_le < now() - make_interval(mins => :m)
        RETURNING id, zone_id
    """), {"m": reglages().escalade_minutes}).all()
    for l in lignes:
        notifier_operateurs(cx, f"ESCALADE : alerte rouge {l.zone_id} non validée depuis "
                                f"{reglages().escalade_minutes} min. {reglages().base_url}/operateur/alertes",
                            admins_seulement=True)
        journaliser(cx, "escalade", f"alerte {l.id} ({l.zone_id}) escaladée")
    return len(lignes)


def notifier_operateurs(cx: Connection, texte: str, admins_seulement: bool = False) -> None:
    filtre = "AND role = 'admin'" if admins_seulement else ""
    ops = cx.execute(text(f"SELECT identifiant, telegram_chat FROM operateur WHERE actif {filtre}")).all()
    canal("console").envoyer("operateurs", texte)
    for o in ops:
        if o.telegram_chat and reglages().telegram_token:
            try:
                canal("telegram").envoyer(o.telegram_chat, texte)
            except Exception as e:
                journaliser(cx, "erreur", f"notification {o.identifiant} : {e}")


def _verdict_anti_abus(cx: Connection, abonne_id: int, texte: str, niveau: str) -> str:
    r = cx.execute(text("""
        SELECT
          count(*) FILTER (WHERE a.texte = :t AND e.le > now() - make_interval(hours => :h)) AS meme,
          count(*) FILTER (WHERE e.le >= date_trunc('day', now())) AS jour
        FROM envoi e JOIN alerte a ON a.id = e.alerte_id
        WHERE e.abonne_id = :ab AND e.statut = 'ok'
    """), {"t": texte, "h": reglages().anti_doublon_heures, "ab": abonne_id}).one()
    return anti_abus.verdict(niveau, r.meme > 0, r.jour, reglages().plafond_envois_jour)


def diffuser(cx: Connection, alerte_id: int) -> dict:
    a = cx.execute(text("""
        SELECT a.id, a.zone_id, a.niveau, a.texte, s.calcule_le
        FROM alerte a LEFT JOIN score_risque s ON s.id = a.score_id WHERE a.id = :i
    """), {"i": alerte_id}).one()
    z = _zone(cx, a.zone_id)
    abonnes = cx.execute(text(
        "SELECT id, canal, contact_chiffre FROM abonne WHERE zone_id = :z AND actif"), {"z": a.zone_id}).all()
    canaux, bilan = {}, {"ok": 0, "echec": 0, "bloque_doublon": 0, "bloque_plafond": 0}

    def _envoyer(nom_canal: str, dest: str) -> tuple[str, str]:
        try:
            if nom_canal not in canaux:
                canaux[nom_canal] = canal(nom_canal)
            return ("ok", "") if canaux[nom_canal].envoyer(dest, a.texte) else ("echec", "refus du fournisseur")
        except Exception as e:
            return "echec", str(e)[:300]

    for ab in abonnes:
        statut = _verdict_anti_abus(cx, ab.id, a.texte, a.niveau)
        detail = ""
        if statut == "ok":
            statut, detail = _envoyer(ab.canal, dechiffrer(ab.contact_chiffre))
        cx.execute(text("INSERT INTO envoi (alerte_id, abonne_id, canal, statut, detail) VALUES (:a, :b, :c, :s, :d)"),
                   {"a": alerte_id, "b": ab.id, "c": ab.canal, "s": statut, "d": detail})
        bilan[statut] += 1
    # canal public de la zone (un message, tous les membres le voient)
    if z.telegram_chat:
        statut, detail = _envoyer("telegram", z.telegram_chat)
        cx.execute(text("INSERT INTO envoi (alerte_id, canal, statut, detail) VALUES (:a, 'telegram_canal', :s, :d)"),
                   {"a": alerte_id, "s": statut, "d": detail})
        bilan[statut] += 1
    # toujours une trace console (démonstration, et preuve en cas de panne des canaux)
    canal("console").envoyer(a.zone_id, a.texte)

    cx.execute(text("""
        UPDATE alerte SET envoyee_le = clock_timestamp(), nb_destinataires = :n,
          latence_ms = CASE WHEN CAST(:t AS timestamptz) IS NULL THEN NULL
                            ELSE (extract(epoch FROM clock_timestamp() - CAST(:t AS timestamptz)) * 1000)::int END
        WHERE id = :i
    """), {"n": bilan["ok"], "t": a.calcule_le, "i": alerte_id})
    return bilan
