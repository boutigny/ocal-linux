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

## Calibration du décentrage capteur (par numéro de série)

Chaque unité OCAL a un capteur légèrement décentré par rapport au boîtier,
et le fabricant fournit une correction propre à chaque numéro de série.
Ce projet stocke cette correction dans `calibrations.json` (non versionné,
voir `calibrations.example.json` pour le format) et l'applique automatiquement
par-dessus la position choisie avec les sliders.

**Important : le fabricant fournit une position ABSOLUE, pas un écart.**
Les valeurs données par OCAL (ex: `1933.92 1090.79`) sont les coordonnées du
centre optique réel dans l'image, à la résolution native de la caméra —
**pas** un décalage à ajouter tel quel. Utiliser ces valeurs comme décalage
brut envoie les cercles complètement hors de l'image ; l'outil calcule
lui-même l'écart réel par rapport au centre géométrique.

**Enregistrer la calibration de ta caméra :**

```bash
# Laisse l'outil détecter le numéro de série automatiquement via USB
python3 -m ocal_linux.calibration --device /dev/video49 --set CENTER_X CENTER_Y --ref-width W --ref-height H

# Ou fournis le numéro de série toi-même s'il n'est pas détecté automatiquement
python3 -m ocal_linux.calibration --serial <numero_de_serie> --set CENTER_X CENTER_Y --ref-width W --ref-height H
```

- `CENTER_X CENTER_Y` : la position absolue fournie par le fabricant (ex: `1933.92 1090.79`)
- `--ref-width` / `--ref-height` : la résolution **native** de la caméra à laquelle cette position a été mesurée (ex: `3840 2160` pour un capteur 4K) — à vérifier avec `v4l2-ctl -d /dev/videoX --list-formats-ext` (résolution la plus élevée listée). **Ne mets pas** la résolution à laquelle tu comptes utiliser la caméra si elle diffère.

Exemple concret :
```bash
python3 -m ocal_linux.calibration --serial ABC123 --set 1933.92 1090.79 --ref-width 3840 --ref-height 2160
# -> écart réel calculé : dx=13.92 dy=10.79 (légèrement décentré, comme attendu)
```

Le programme calcule l'écart par rapport au centre géométrique de cette
résolution de référence, puis le remet à l'échelle automatiquement si tu
utilises une résolution caméra différente.

**Vérifier les calibrations enregistrées :**

```bash
python3 -m ocal_linux.calibration --list
```

**Au lancement**, `run.py` applique automatiquement la calibration correspondant
au numéro de série détecté. Tu peux aussi la forcer manuellement :

```bash
python3 run.py /dev/video49 --serial <numero_de_serie>   # force la calibration à charger
python3 run.py /dev/video49 --offset 12 -5                # force un décalage direct, ignore le fichier
python3 run.py /dev/video49 --no-calib                    # désactive toute correction
```

Si le numéro de série n'est pas détecté automatiquement (caméra sans numéro de
série exposé sur le bus USB) ou n'a pas encore de calibration enregistrée, le
programme le signale et continue sans décalage.

### Vérifier le sens de la calibration

Le manuel d'OCAL ne précise pas la convention (origine, sens des axes) des valeurs de calibration. Le programme suppose que ce sont les coordonnées de l'axe mécanique dans l'image (origine en haut à gauche, x vers la droite, y vers le bas). Pour vérifier, compare avec le logiciel officiel, même caméra et même résolution, en lançant d'abord `python3 run.py /dev/videoX --no-calib` pour avoir la référence sans décalage.

Si le centre des cercles tombe du côté *opposé* à celui du logiciel officiel, inverse le sens du décalage :

```bash
python3 run.py /dev/videoX --flip-calib        # inverse x et y
python3 run.py /dev/videoX --flip-calib x      # inverse seulement l'axe x (ou y)
```

## Utilisation

```bash
python3 run.py /dev/videoX
```

La fenêtre d'image s'ouvre à 1600 px de large (hauteur selon le rapport d'aspect de la caméra) et reste redimensionnable à la souris. Pour une autre taille d'ouverture : `python3 run.py /dev/videoX --window-width 2000`.

Raccourcis clavier :

| Touche | Action |
|---|---|
| `s` | Fige l'image courante comme référence |
| `f` | Active/désactive le fondu croisé avec la référence |
| `+` / `-` | Ajuste l'intensité du fondu |
| `i` / `k` | Déplace le centre des cercles de 1 px vers le haut / le bas |
| `j` / `l` | Déplace le centre des cercles de 1 px vers la gauche / la droite |
| `w` | Sauvegarde les réglages courants |
| `q` | Quitte (sauvegarde automatiquement les réglages) |

Les sliders de la fenêtre "Reglages" contrôlent en direct l'exposition, le focus, la luminosité, le contraste, la position du centre (en pixels, avec un slider grossier et un slider fin de ±50 px par axe), les rayons et l'épaisseur des trois cercles, ainsi que la taille et l'épaisseur de la croix de collimation.

## Sauvegarde des réglages

Les réglages sont sauvegardés par caméra (clé = numéro de série) dans un fichier personnel, **hors du dépôt** :

```
~/.config/ocal-linux/settings.json      (ou $XDG_CONFIG_HOME/ocal-linux/settings.json)
```

Sont sauvegardés : exposition, focus, luminosité, contraste, épaisseur des cercles, rayons des trois cercles, taille et épaisseur de la croix de collimation, et la **position x, y du centre** (commune aux cercles et à la croix, sliders grossiers + fins additionnés). Le décalage constructeur (calibration) n'est pas inclus : il est recalculé à chaque lancement et s'ajoute à la position sauvegardée.

- Touche `w` : sauvegarde immédiate (un message « Reglages sauvegardes » s'affiche brièvement)
- Touche `q` : sauvegarde automatique à la sortie
- Au lancement suivant, les réglages de la caméra détectée sont rechargés automatiquement
- `python3 run.py /dev/videoX --no-settings` : démarre avec les valeurs par défaut sans lire le fichier

Les rayons des cercles, la taille de la croix et la position du centre sont stockés en proportion de la résolution de capture, ils restent donc cohérents si tu changes de résolution (`--width` / `--height`).

## Roadmap

- [x] Sauvegarde/chargement d'un profil par caméra (numéro de série → position du capteur), comme le logiciel officiel
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
