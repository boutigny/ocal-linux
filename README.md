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

## Usage de l'IA

Le développement des logiciels de ce projet s'est appuyé sur Claude Sonnet 5
