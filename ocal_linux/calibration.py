"""
Gestion de la calibration constructeur du décentrage capteur.

Chaque unité OCAL est livrée avec une position de capteur légèrement différente
(indiquée par le fabricant, généralement liée au numéro de série). Ce module
permet de stocker cet offset (en pixels, à la résolution de référence du
fabricant) dans un fichier JSON, de le retrouver automatiquement à partir du
numéro de série de la caméra branchée, et de l'appliquer à l'affichage.

Format du fichier de calibration (calibrations.json à la racine du dépôt) :

{
  "<numero_de_serie>": {
    "center_x_px": 1933.92,
    "center_y_px": 1090.79,
    "ref_width": 3840,
    "ref_height": 2160,
    "note": "Valeurs fournies par le fabricant pour cette unité"
  }
}

IMPORTANT : center_x_px / center_y_px sont les coordonnées ABSOLUES du centre
optique réel dans l'image, à la résolution native ref_width x ref_height
utilisée par le fabricant pour la mesure — PAS un écart par rapport au centre.
C'est ce format que le fabricant fournit généralement (position mesurée du
capteur), pas directement un delta.

Le module calcule lui-même l'écart par rapport au centre géométrique
(dx = center_x_px - ref_width/2, dy = center_y_px - ref_height/2), puis le
remet à l'échelle si la caméra tourne dans une résolution différente de
ref_width x ref_height.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional, Tuple

DEFAULT_CALIB_PATH = Path(__file__).resolve().parent.parent / "calibrations.json"


def load_calibrations(path: Path = DEFAULT_CALIB_PATH) -> dict:
    """Charge le fichier de calibration. Renvoie {} si absent ou invalide."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[calibration] Impossible de lire {path} : {exc}")
        return {}


def save_calibrations(data: dict, path: Path = DEFAULT_CALIB_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


def set_calibration(
    serial: str,
    center_x_px: float,
    center_y_px: float,
    ref_width: int,
    ref_height: int,
    note: str = "",
    path: Path = DEFAULT_CALIB_PATH,
) -> None:
    """
    Ajoute ou met à jour l'entrée de calibration d'un numéro de série.

    center_x_px / center_y_px : coordonnées ABSOLUES du centre optique réel
    (telles que fournies par le fabricant), pas un écart par rapport au centre.
    """
    data = load_calibrations(path)
    data[serial] = {
        "center_x_px": center_x_px,
        "center_y_px": center_y_px,
        "ref_width": ref_width,
        "ref_height": ref_height,
        "note": note,
    }
    save_calibrations(data, path)


def get_offset_for_serial(
    serial: Optional[str],
    frame_width: int,
    frame_height: int,
    path: Path = DEFAULT_CALIB_PATH,
) -> Tuple[int, int]:
    """
    Renvoie l'écart (dx, dy) en pixels par rapport au centre géométrique,
    à la résolution courante de la caméra.

    Le fichier stocke la position ABSOLUE du centre optique (center_x_px,
    center_y_px) à la résolution de référence du fabricant (ref_width,
    ref_height) ; on calcule ici l'écart par rapport au centre géométrique
    de cette résolution de référence, puis on le remet à l'échelle pour la
    résolution courante. Renvoie (0, 0) si le numéro de série est inconnu.
    """
    if not serial:
        return 0, 0

    calibrations = load_calibrations(path)
    entry = calibrations.get(serial)
    if not entry:
        return 0, 0

    ref_w = entry.get("ref_width") or frame_width
    ref_h = entry.get("ref_height") or frame_height

    # Écart par rapport au centre géométrique, à la résolution de référence
    delta_x_ref = entry.get("center_x_px", ref_w / 2) - ref_w / 2
    delta_y_ref = entry.get("center_y_px", ref_h / 2) - ref_h / 2

    scale_x = frame_width / ref_w if ref_w else 1.0
    scale_y = frame_height / ref_h if ref_h else 1.0

    dx = round(delta_x_ref * scale_x)
    dy = round(delta_y_ref * scale_y)
    return dx, dy


def get_raw_entry_for_serial(serial: Optional[str], path: Path = DEFAULT_CALIB_PATH) -> Optional[dict]:
    """
    Renvoie l'entrée brute de calibration telle qu'enregistrée pour ce numéro de
    série (center_x_px, center_y_px, ref_width, ref_height, note), sans aucun
    calcul d'écart ni mise à l'échelle. None si absent ou serial vide.
    """
    if not serial:
        return None
    return load_calibrations(path).get(serial)


def detect_serial(device: str) -> Optional[str]:
    """
    Tente de récupérer un identifiant USB stable pour la caméra via udevadm,
    en interrogeant directement les propriétés udev du device (ID_SERIAL_SHORT /
    ID_SERIAL), plutôt qu'en remontant l'arbre des périphériques parents (qui peut
    remonter un champ 'serial' appartenant à un hub ou contrôleur USB parent, pas
    à la caméra elle-même).

    Renvoie None si udevadm est absent ou si aucun identifiant n'est exposé.
    Attention : certains contrôleurs UVC génériques bas coût renvoient la MÊME
    valeur (souvent une chaîne de version type "0001" ou "01.00.00") sur TOUS
    les exemplaires du même modèle — dans ce cas la valeur récupérée n'est pas
    un vrai numéro de série unique et ne peut pas servir à distinguer plusieurs
    unités. Vérifie avec --list en comparant deux caméras du même modèle si tu
    as un doute.
    """
    try:
        result = subprocess.run(
            ["udevadm", "info", "--query=property", "--name", device],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if result.returncode != 0:
        return None

    props = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    return props.get("ID_SERIAL_SHORT") or props.get("ID_SERIAL")


def _cli():
    import argparse

    parser = argparse.ArgumentParser(
        description="Gérer les calibrations de décentrage capteur par numéro de série."
    )
    parser.add_argument("--device", help="Périphérique caméra, ex. /dev/video49 (pour auto-détecter le numéro de série)")
    parser.add_argument("--serial", help="Numéro de série (remplace --device pour la détection)")
    parser.add_argument("--set", nargs=2, type=float, metavar=("CENTER_X", "CENTER_Y"),
                         help="Enregistre la position ABSOLUE (en pixels) du centre optique fournie par le "
                              "fabricant pour ce numéro de série — PAS un écart par rapport au centre")
    parser.add_argument("--ref-width", type=int, required=False,
                         help="Largeur de l'image à laquelle CENTER_X/CENTER_Y correspondent "
                              "(résolution native utilisée par le fabricant pour la mesure, ex: 3840)")
    parser.add_argument("--ref-height", type=int, required=False,
                         help="Hauteur de l'image à laquelle CENTER_X/CENTER_Y correspondent "
                              "(résolution native utilisée par le fabricant pour la mesure, ex: 2160)")
    parser.add_argument("--note", default="", help="Note libre (ex: source de la donnée constructeur)")
    parser.add_argument("--list", action="store_true", help="Liste les calibrations enregistrées")
    args = parser.parse_args()

    if args.list:
        data = load_calibrations()
        if not data:
            print("Aucune calibration enregistrée.")
        for serial, entry in data.items():
            rw, rh = entry.get("ref_width", 0), entry.get("ref_height", 0)
            cx, cy = entry.get("center_x_px", 0), entry.get("center_y_px", 0)
            dx = cx - rw / 2 if rw else 0
            dy = cy - rh / 2 if rh else 0
            print(f"{serial}: centre=({cx}, {cy}) @ {rw}x{rh}  ->  écart dx={dx:.2f} dy={dy:.2f}  "
                  f"{entry.get('note', '')}")
        return

    serial = args.serial
    if not serial and args.device:
        serial = detect_serial(args.device)
        if serial:
            print(f"Numéro de série détecté : {serial}")
        else:
            print("Numéro de série non détecté automatiquement — utilise --serial pour le fournir manuellement.")
            return

    if not serial:
        parser.error("Fournis --serial ou --device pour identifier la caméra.")

    if args.set:
        if not args.ref_width or not args.ref_height:
            parser.error(
                "--ref-width et --ref-height sont obligatoires avec --set : ce sont la largeur/hauteur "
                "de l'image à laquelle CENTER_X/CENTER_Y correspondent (résolution native utilisée par "
                "le fabricant pour la mesure, ex: --ref-width 3840 --ref-height 2160). "
                "Ne mets PAS la résolution à laquelle tu comptes utiliser la caméra si elle diffère."
            )
        center_x, center_y = args.set
        delta_x = center_x - args.ref_width / 2
        delta_y = center_y - args.ref_height / 2
        set_calibration(serial, center_x, center_y, args.ref_width, args.ref_height, args.note)
        print(f"Calibration enregistrée pour {serial} : centre=({center_x}, {center_y}) "
              f"à {args.ref_width}x{args.ref_height} -> écart réel dx={delta_x:.2f} dy={delta_y:.2f}")
    else:
        data = load_calibrations()
        entry = data.get(serial)
        if entry:
            print(f"{serial}: {entry}")
        else:
            print(f"Aucune calibration enregistrée pour {serial}. Utilise --set CENTER_X CENTER_Y "
                  f"--ref-width W --ref-height H pour en créer une.")


if __name__ == "__main__":
    _cli()
