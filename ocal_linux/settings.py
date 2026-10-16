"""
Sauvegarde / restauration des réglages d'affichage et de caméra.

Les réglages sont stockés dans un fichier JSON PERSONNEL, hors du dépôt :
    $XDG_CONFIG_HOME/ocal-linux/settings.json   (par défaut ~/.config/ocal-linux/settings.json)

Ils sont rangés par caméra (clé = numéro de série, ou "default" si inconnu) :

{
  "<numero_de_serie>": {
    "exposure": 166,
    "focus": 0,
    "brightness": 0,
    "contrast": 0,
    "circle_thickness": 3,
    "cross_thickness": 4,
    "radius_red": 0.15,       <- fraction du rayon max (min(largeur, hauteur) / 2)
    "radius_green": 0.30,
    "radius_blue": 0.45,
    "cross_arm": 0.15,
    "center_x": 0.5,          <- position x du centre (cercles ET croix), fraction de la largeur de l'image
    "center_y": 0.5           <- position y du centre, fraction de la hauteur de l'image
  }
}

Les rayons et la taille de la croix sont stockés en FRACTION du rayon max, et la position du
centre en fraction de la largeur/hauteur de l'image, pas en pixels, pour rester cohérents si la
résolution de capture change d'une session à l'autre. Le décalage constructeur (calibration) n'est
PAS inclus : il est recalculé à chaque lancement et s'ajoute à la position sauvegardée.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

DEFAULT_KEY = "default"


def default_settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "ocal-linux" / "settings.json"


def _key(serial: Optional[str]) -> str:
    return serial or DEFAULT_KEY


def load_settings(serial: Optional[str], path: Optional[Path] = None) -> dict:
    """Renvoie les réglages enregistrés pour cette caméra, ou {} si aucun/illisible."""
    path = path or default_settings_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[reglages] Impossible de lire {path} : {exc}")
        return {}
    entry = data.get(_key(serial), {})
    return entry if isinstance(entry, dict) else {}


def save_settings(serial: Optional[str], values: dict, path: Optional[Path] = None) -> Optional[Path]:
    """Enregistre les réglages de cette caméra sans toucher à ceux des autres. Renvoie le chemin, ou None si échec."""
    path = path or default_settings_path()
    data = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    data[_key(serial)] = values
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
    except OSError as exc:
        print(f"[reglages] Impossible d'écrire {path} : {exc}")
        return None
    return path


def clamp(value, low, high):
    """Borne une valeur lue dans le fichier (qui peut venir d'une autre résolution ou être corrompue)."""
    try:
        return max(low, min(high, int(round(value))))
    except (TypeError, ValueError):
        return low
