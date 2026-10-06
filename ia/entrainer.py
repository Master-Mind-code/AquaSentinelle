"""Entraîne le classificateur de caniveaux (S25) : MobileNetV3-Small pré-entraîné, apprentissage par transfert.

    pip install -r ia/requirements-ia.txt
    python ia/entrainer.py --donnees dataset [--epoques 15] [--sortie models]

Découpage stratifié 70 / 15 / 15 (graine fixe) : le jeu de TEST n'est jamais vu pendant l'entraînement
ni pour choisir le meilleur modèle. Sorties dans --sortie :
  caniveaux.onnx, caniveaux.labels.json (lus par l'application), rapport_ia.json (précision par classe, matrice).
Le prétraitement d'évaluation (256 puis recadrage central 224) est identique à app/services/ia.py.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import train_test_split
from torch import nn
from torch.utils.data import DataLoader, Subset
from torchvision import datasets, models, transforms

MOY, ECART = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
MIN_PAR_CLASSE = 30


def transfos():
    entrainement = transforms.Compose([
        transforms.RandomResizedCrop(224, scale=(0.7, 1.0)), transforms.RandomHorizontalFlip(),
        transforms.ColorJitter(0.3, 0.3, 0.2), transforms.ToTensor(), transforms.Normalize(MOY, ECART)])
    evaluation = transforms.Compose([
        transforms.Resize(256), transforms.CenterCrop(224), transforms.ToTensor(), transforms.Normalize(MOY, ECART)])
    return entrainement, evaluation


def evaluer(modele, chargeur) -> tuple[list[int], list[int]]:
    modele.eval()
    vrais, predits = [], []
    with torch.no_grad():
        for x, y in chargeur:
            predits += modele(x).argmax(1).tolist()
            vrais += y.tolist()
    return vrais, predits


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--donnees", default="dataset")
    p.add_argument("--sortie", default="models")
    p.add_argument("--epoques", type=int, default=15)
    p.add_argument("--graine", type=int, default=42)
    p.add_argument("--sans-preentrainement", action="store_true", help="pour un essai hors ligne")
    a = p.parse_args()
    random.seed(a.graine); np.random.seed(a.graine); torch.manual_seed(a.graine)

    t_ent, t_eval = transfos()
    base_ent = datasets.ImageFolder(a.donnees, transform=t_ent)
    base_eval = datasets.ImageFolder(a.donnees, transform=t_eval)
    classes, cibles = base_ent.classes, np.array(base_ent.targets)
    effectifs = {c: int((cibles == i).sum()) for i, c in enumerate(classes)}
    print(f"Classes : {effectifs}")
    if min(effectifs.values()) < MIN_PAR_CLASSE:
        print(f"ATTENTION : moins de {MIN_PAR_CLASSE} photos dans une classe, les résultats seront peu fiables.")

    idx = np.arange(len(cibles))
    i_ent, i_reste = train_test_split(idx, test_size=0.3, stratify=cibles, random_state=a.graine)
    i_val, i_test = train_test_split(i_reste, test_size=0.5, stratify=cibles[i_reste], random_state=a.graine)
    ch = lambda base, i, melange: DataLoader(Subset(base, i), batch_size=32, shuffle=melange, num_workers=0)
    ent, val, test = ch(base_ent, i_ent, True), ch(base_eval, i_val, False), ch(base_eval, i_test, False)
    print(f"Découpage : {len(i_ent)} entraînement, {len(i_val)} validation, {len(i_test)} test")

    poids = None if a.sans_preentrainement else models.MobileNet_V3_Small_Weights.IMAGENET1K_V1
    modele = models.mobilenet_v3_small(weights=poids)
    modele.classifier[3] = nn.Linear(modele.classifier[3].in_features, len(classes))
    opt = torch.optim.AdamW([{"params": modele.features.parameters(), "lr": 1e-4},
                             {"params": modele.classifier.parameters(), "lr": 1e-3}], weight_decay=1e-4)
    # pondération des classes : un jeu déséquilibré (peu de « bouché ») ne doit pas écraser la classe rare
    pond = torch.tensor([len(cibles) / (len(classes) * max(1, effectifs[c])) for c in classes], dtype=torch.float32)
    perte = nn.CrossEntropyLoss(weight=pond)

    meilleur, etat = -1.0, None
    for ep in range(1, a.epoques + 1):
        modele.train()
        t0, total = time.time(), 0.0
        for x, y in ent:
            opt.zero_grad()
            l = perte(modele(x), y)
            l.backward()
            opt.step()
            total += l.item() * len(y)
        v, pr = evaluer(modele, val)
        acc = float(np.mean(np.array(v) == np.array(pr))) if v else 0.0
        print(f"époque {ep:2d} · perte {total / max(1, len(i_ent)):.3f} · exactitude validation {acc:.2%} · {time.time() - t0:.0f} s")
        if acc > meilleur:
            meilleur, etat = acc, {k: t.clone() for k, t in modele.state_dict().items()}
    modele.load_state_dict(etat)

    v, pr = evaluer(modele, test)
    rapport = classification_report(v, pr, labels=list(range(len(classes))), target_names=classes,
                                    output_dict=True, zero_division=0)
    matrice = confusion_matrix(v, pr, labels=list(range(len(classes)))).tolist()
    print("\nJeu de TEST (jamais vu) :")
    print(classification_report(v, pr, labels=list(range(len(classes))), target_names=classes, zero_division=0))
    print("Matrice de confusion (lignes : vrai, colonnes : prédit) :", classes)
    for c, ligne in zip(classes, matrice):
        print(f"  {c:8s} {ligne}")

    sortie = Path(a.sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    modele.eval()
    torch.onnx.export(modele, torch.zeros(1, 3, 224, 224), str(sortie / "caniveaux.onnx"), input_names=["image"],
                      output_names=["logits"], opset_version=17, dynamo=False)
    (sortie / "caniveaux.labels.json").write_text(json.dumps(classes), encoding="utf-8")
    (sortie / "rapport_ia.json").write_text(json.dumps({
        "classes": classes, "effectifs": effectifs, "decoupage": [len(i_ent), len(i_val), len(i_test)],
        "exactitude_validation": meilleur, "rapport_test": rapport, "matrice_test": matrice,
        "date": time.strftime("%Y-%m-%d %H:%M"), "preentrainement": not a.sans_preentrainement,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nModèle exporté : {sortie / 'caniveaux.onnx'} (redémarrer l'application pour le charger)")


if __name__ == "__main__":
    main()
