# OCAL Linux

Client Linux (non officiel) pour caméra de collimation électronique type **OCAL** (Newton / RC / SCT).

Le logiciel officiel OCAL n'existe que pour Windows et Android. La caméra OCAL est une caméra UVC (USB Video Class) standard, ce qui la rend nativement compatible avec Linux (Video4Linux2). Ce projet réimplémente les fonctions essentielles du logiciel officiel :

- Affichage du flux vidéo en direct
- Cercles concentriques ajustables (rouge / vert / bleu) + croix centrale, pour aligner les miroirs
- Réglage de l'exposition et du focus via les contrôles caméra V4L2
- Image de référence figée + fondu croisé pour comparer deux états de collimation

## Statut

Prototype fonctionnel. Non affilié à OCAL / ocalworld.com.

Testé avec un capteur exposant les contrôles suivants (`v4l2-ctl --list-ctrls`) :

```
auto_exposure            (menu) : Manual Mode disponible
exposure_time_absolute   (int)  : 3 – 2047
focus_absolute           (int)  : 0 – 1023
focus_automatic_continuous (bool)
```

Si ta caméra OCAL expose des plages différentes, adapte les constantes `EXPOSURE_MIN/MAX` et `FOCUS_MIN/MAX` dans `src/ocal_linux/main.py`.

## Prérequis

- Linux avec support Video4Linux2 (quasiment toutes les distributions récentes)
- Python 3.9+
- Le paquet système `v4l-utils` (fournit `v4l2-ctl`)

```bash
sudo apt install v4l-utils      # Debian / Ubuntu
sudo dnf install v4l-utils      # Fedora
sudo pacman -S v4l-utils        # Arch
```

## Installation

```bash
git clone https://github.com/<ton-compte>/ocal-linux.git
cd ocal-linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Identifier le bon périphérique vidéo

Branche la caméra OCAL puis :

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/videoX --list-ctrls
```

Le node à utiliser est celui qui affiche les contrôles caméra (`exposure_time_absolute`, `focus_absolute`, etc.) — certaines caméras exposent aussi un second node `/dev/videoX+1` sans contrôles (metadata), à ignorer.

## Utilisation

```bash
python3 run.py /dev/videoX
```

Raccourcis clavier :

| Touche | Action |
|---|---|
| `s` | Fige l'image courante comme référence |
| `f` | Active/désactive le fondu croisé avec la référence |
| `+` / `-` | Ajuste l'intensité du fondu |
| `q` | Quitte |

Les sliders de la fenêtre "Reglages" contrôlent en direct l'exposition, le focus, la position du centre et les rayons des trois cercles.

## Roadmap

- [ ] Sauvegarde/chargement d'un profil par caméra (numéro de série → position du capteur), comme le logiciel officiel
- [ ] Détection auto des ronds/miroir par traitement d'image (Hough circles) pour proposer un centrage automatique
- [ ] Interface graphique plus complète (PyQt) avec presets Newton / RC / SCT
- [ ] Empaquetage (`pipx` / AppImage) pour installation simplifiée

## Contribuer

Les PR sont bienvenues, notamment pour :
- Tester sur d'autres modèles de caméra OCAL et remonter les plages de contrôles V4L2
- Améliorer l'ergonomie de l'overlay

## Licence

MIT — voir [LICENSE](LICENSE).

## Avertissement

Ce projet n'est pas affilié à OCAL / ocalworld.com. Il s'agit d'une réimplémentation indépendante basée sur le fait que le matériel OCAL utilise le standard UVC/V4L2.
