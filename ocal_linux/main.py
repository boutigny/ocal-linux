#!/usr/bin/env python3
"""
Prototype de collimateur électronique type OCAL pour Linux.

Fonctions :
  - Flux vidéo caméra UVC (V4L2)
  - Overlay de cercles concentriques ajustables (rouge / vert / bleu) + croix de
    collimation (taille/épaisseur réglables) au centre
  - Décalage automatique du centre optique selon la calibration constructeur
    (décentrage capteur propre à chaque numéro de série, voir calibration.py)
  - Contrôle exposition, focus, luminosité et contraste (via v4l2-ctl, plus fiable que cv2.set())
  - Fondu croisé (touche 'f') entre l'image courante et une image figée
  - Capture d'une image de référence (touche 's') pour comparaison
  - Option --flip-calib : inverse le sens du décalage constructeur (si la convention d'OCAL
    est l'inverse de celle supposée)
  - Sauvegarde des réglages par caméra (touche 'w', et automatiquement à la sortie avec 'q') ;
    ils sont rechargés au lancement suivant (voir settings.py)

Dépendances : opencv-python, v4l2-ctl (paquet v4l-utils)
Usage :
  python3 run.py /dev/video49
  python3 run.py /dev/video49 --serial ABC123
  python3 run.py /dev/video49 --offset 12 -5
"""

import argparse
import subprocess
import sys
import time

import cv2

from ocal_linux.calibration import detect_serial, get_offset_for_serial, get_raw_entry_for_serial
from ocal_linux.settings import clamp, load_settings, save_settings

WINDOW = "OCAL Linux"
CTRL_WINDOW = "Reglages"

# ---- Réglages par défaut (bornes issues de v4l2-ctl --list-ctrls) ----
EXPOSURE_MIN, EXPOSURE_MAX = 3, 2047
FOCUS_MIN, FOCUS_MAX = 0, 1023
BRIGHTNESS_MIN, BRIGHTNESS_MAX = -64, 64
CONTRAST_MIN, CONTRAST_MAX = 0, 95

# Largeur par défaut de la fenêtre d'image à l'ouverture (modifiable avec --window-width)
DEFAULT_WINDOW_WIDTH = 1600

# Plage du slider de réglage fin du centre : -FINE_RANGE..+FINE_RANGE pixels autour du curseur grossier
FINE_RANGE = 50


def parse_args():
    parser = argparse.ArgumentParser(description="Collimateur OCAL pour Linux")
    parser.add_argument("device", nargs="?", default="/dev/video0",
                         help="Périphérique caméra (ex: /dev/video49)")
    parser.add_argument("--serial", help="Force le numéro de série à utiliser pour la calibration")
    parser.add_argument("--offset", nargs=2, type=int, metavar=("DX", "DY"),
                         help="Force directement le décalage du centre optique en pixels "
                              "(ignore la calibration enregistrée)")
    parser.add_argument("--no-calib", action="store_true",
                         help="Désactive toute prise en compte du décentrage capteur")
    parser.add_argument("--flip-calib", nargs="?", const="xy", choices=["x", "y", "xy"],
                         help="Inverse le SENS du décalage constructeur, au cas où la convention de signe "
                              "d'OCAL serait l'inverse de celle supposée : '--flip-calib' ou '--flip-calib xy' "
                              "inverse les deux axes, 'x' ou 'y' un seul.")
    parser.add_argument("--width", type=int, help="Force la largeur de capture (ex: 3840 pour du 4K natif)")
    parser.add_argument("--height", type=int, help="Force la hauteur de capture (ex: 2160 pour du 4K natif)")
    parser.add_argument("--no-mjpg", action="store_true",
                         help="N'essaie pas de forcer le format MJPG (compressé). À utiliser seulement si "
                              "MJPG cause des problèmes d'image, ex: 'colorimétrie bizarre'")
    parser.add_argument("--display-scale", type=float, default=1.0,
                         help="Réduit uniquement l'image affichée à l'écran (ex: 0.5 pour moitié moins large/haut). "
                              "Le calcul de calibration reste fait à pleine résolution ; ça allège juste le rendu "
                              "de la fenêtre, souvent le vrai goulot d'étranglement en 4K.")
    parser.add_argument("--window-width", type=int, default=DEFAULT_WINDOW_WIDTH,
                         help=f"Largeur de la fenêtre d'image à l'ouverture, en pixels (défaut : {DEFAULT_WINDOW_WIDTH}) ; "
                              "la hauteur suit le rapport d'aspect de la caméra. La fenêtre reste redimensionnable à la souris.")
    parser.add_argument("--no-settings", action="store_true",
                         help="Ignore les réglages sauvegardés au démarrage (valeurs par défaut) ; "
                              "ils restent écrasables avec 'w' ou à la sortie")
    return parser.parse_args()


def v4l2_set(device: str, control: str, value: int):
    """Applique un contrôle V4L2 via v4l2-ctl (plus fiable que cv2.VideoCapture.set)."""
    try:
        subprocess.run(
            ["v4l2-ctl", "-d", device, "-c", f"{control}={value}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("v4l2-ctl introuvable : installe le paquet v4l-utils.")


def ensure_manual_modes(device: str):
    # auto_exposure : 1 = Manual Mode sur la plupart des caméras UVC (norme un peu tordue)
    v4l2_set(device, "auto_exposure", 1)
    v4l2_set(device, "focus_automatic_continuous", 0)


def nothing(_):
    pass


def apply_calib(center_x, center_y, calib_offset, width, height):
    """Centre RÉELLEMENT dessiné (en pixels) : position choisie + décalage constructeur, borné à l'image."""
    dx, dy = calib_offset
    cx = min(max(int(center_x) + dx, 0), width - 1)
    cy = min(max(int(center_y) + dy, 0), height - 1)
    return cx, cy


def flip_offset(calib_offset, flip):
    """Inverse le sens du décalage constructeur sur l'axe 'x', 'y' ou les deux ('xy'). flip=None : inchangé."""
    dx, dy = calib_offset
    if flip and "x" in flip:
        dx = -dx
    if flip and "y" in flip:
        dy = -dy
    return dx, dy


def draw_overlay(frame, center_x, center_y, r_red, r_green, r_blue, thickness,
                  cross_arm, cross_thickness, calib_offset):
    """
    center_x, center_y : position du centre choisie par l'utilisateur, EN PIXELS de l'image
                         (curseur grossier + curseur fin déjà additionnés par l'appelant)
    calib_offset : (dx, dy) en pixels, décalage constructeur à appliquer par-dessus
    cross_arm, cross_thickness : taille/épaisseur de la croix marquant le centre de collimation
    """
    h, w = frame.shape[:2]
    cx, cy = apply_calib(center_x, center_y, calib_offset, w, h)

    # Pas de .copy() ici : 'frame' est de toute façon écrasé à la prochaine itération
    # (ou déjà une nouvelle image issue de addWeighted en mode fondu), donc dessiner en
    # place évite une allocation + copie coûteuse à chaque image en haute résolution.
    cv2.circle(frame, (cx, cy), r_red, (0, 0, 255), thickness)
    cv2.circle(frame, (cx, cy), r_green, (0, 255, 0), thickness)
    cv2.circle(frame, (cx, cy), r_blue, (255, 0, 0), thickness)

    cv2.line(frame, (cx - cross_arm, cy), (cx + cross_arm, cy), (0, 255, 255), cross_thickness)
    cv2.line(frame, (cx, cy - cross_arm), (cx, cy + cross_arm), (0, 255, 255), cross_thickness)
    return frame


def resolve_calib_offset(args, device, frame_width, frame_height):
    """Détermine l'offset (dx, dy) à appliquer, selon la priorité :
       --offset > --serial > numéro de série auto-détecté > aucun décalage."""
    if args.no_calib:
        return (0, 0), None

    if args.offset:
        return tuple(args.offset), "manuel (--offset)"

    serial = args.serial or detect_serial(device)
    if not serial:
        print("[calibration] Numéro de série non fourni et non détecté automatiquement "
              "— aucun décalage constructeur appliqué. Utilise --serial ou --offset.")
        return (0, 0), None

    dx, dy = get_offset_for_serial(serial, frame_width, frame_height)
    if (dx, dy) == (0, 0):
        print(f"[calibration] Aucune calibration enregistrée pour le numéro de série {serial}. "
              f"Enregistre-la avec : python3 -m ocal_linux.calibration --serial {serial} "
              f"--set DX DY")
        return (0, 0), serial

    print(f"[calibration] Décalage appliqué pour {serial} : dx={dx} dy={dy}")
    return (dx, dy), serial


def main():
    args = parse_args()
    device = args.device

    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"Impossible d'ouvrir {device}")
        sys.exit(1)

    ensure_manual_modes(device)

    if not args.no_mjpg:
        # MJPG = compression matérielle côté caméra -> bien moins de données à faire transiter
        # sur l'USB que le YUYV brut, souvent indispensable pour tenir un framerate correct en
        # haute résolution (le YUYV en 4K peut saturer l'USB et faire chuter le débit à 1-2 im/s).
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

    if args.width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    if args.height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    # Réduit la mémoire tampon interne pour éviter d'accumuler du retard (latence) si le
    # traitement est plus lent que la capture ; pas supporté par tous les backends/drivers,
    # échoue silencieusement sinon.
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Une première lecture pour connaître la résolution réelle avant de résoudre la calibration
    ok, first_frame = cap.read()
    if not ok:
        print("Lecture caméra échouée dès la première image.")
        sys.exit(1)
    frame_h, frame_w = first_frame.shape[:2]
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc_str = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
    print(f"Résolution de capture effective : {frame_w}x{frame_h}  (format: {fourcc_str})")
    if args.width and frame_w != args.width:
        print(f"  ATTENTION : {args.width} demandé mais la caméra a renvoyé {frame_w} "
              f"(résolution non supportée par la caméra/le driver dans ce mode).")
    if fourcc_str.strip().upper() not in ("MJPG", "MJPEG") and not args.no_mjpg:
        print("  ATTENTION : la caméra n'a pas accepté MJPG malgré la demande — si c'est lent, "
              "vérifie 'v4l2-ctl --list-formats-ext' pour voir les formats réellement supportés "
              "à cette résolution.")

    calib_offset, serial = resolve_calib_offset(args, device, frame_w, frame_h)
    if args.flip_calib:
        calib_offset = flip_offset(calib_offset, args.flip_calib)
        print(f"[calibration] Sens du décalage constructeur INVERSÉ sur l'axe {args.flip_calib} "
              f"-> dx={calib_offset[0]} dy={calib_offset[1]}")

    # Le rayon max des cercles doit suivre la résolution réelle de capture : 400px fixe
    # n'a aucun sens en 4K (cercle minuscule) ni en 480p (cercle hors cadre).
    max_radius = min(frame_w, frame_h) // 2

    # Les réglages sont rangés par numéro de série ; avec --offset (identifiant fictif) ou
    # sans caméra identifiée, on utilise l'entrée "default".
    settings_serial = None if (args.offset or not serial) else serial
    saved = {} if args.no_settings else load_settings(settings_serial)
    if saved:
        print(f"[reglages] Réglages sauvegardés rechargés pour {settings_serial or 'default'}")

    def saved_ratio_px(name, default_ratio, minimum):
        """Rayon/taille sauvegardé en fraction du rayon max -> pixels à la résolution courante."""
        ratio = saved.get(name, default_ratio)
        try:
            ratio = float(ratio)
        except (TypeError, ValueError):
            ratio = default_ratio
        return clamp(max(minimum, ratio * max_radius), 0, max_radius)

    init_exposure = clamp(saved.get("exposure", 166), EXPOSURE_MIN, EXPOSURE_MAX)
    init_focus = clamp(saved.get("focus", 0), FOCUS_MIN, FOCUS_MAX)
    init_brightness = clamp(saved.get("brightness", 0), BRIGHTNESS_MIN, BRIGHTNESS_MAX)
    init_contrast = clamp(saved.get("contrast", 0), CONTRAST_MIN, CONTRAST_MAX)
    init_r_red = saved_ratio_px("radius_red", 0.15, 10)
    init_r_green = saved_ratio_px("radius_green", 0.30, 20)
    init_r_blue = saved_ratio_px("radius_blue", 0.45, 30)
    init_thickness = clamp(saved.get("circle_thickness", 3), 1, 10)
    init_cross_arm = saved_ratio_px("cross_arm", 0.15, 20)
    init_cross_thickness = clamp(saved.get("cross_thickness", 4), 1, 20)

    def saved_center_px(name, size):
        """Position du centre sauvegardée en fraction de l'image -> pixels ; milieu de l'image si absente/invalide."""
        try:
            return clamp(float(saved[name]) * size, 0, size)
        except (KeyError, TypeError, ValueError):
            return size // 2

    init_center_x = saved_center_px("center_x", frame_w)
    init_center_y = saved_center_px("center_y", frame_h)

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.namedWindow(CTRL_WINDOW, cv2.WINDOW_NORMAL)

    # Fenêtre d'image plus grande à l'ouverture, au rapport d'aspect de la caméra
    # (avec WINDOW_NORMAL elle reste redimensionnable à la souris ensuite).
    win_w = max(320, args.window_width)
    win_h = max(240, round(win_w * frame_h / frame_w))
    cv2.resizeWindow(WINDOW, win_w, win_h)

    # Sliders caméra
    cv2.createTrackbar("Exposition", CTRL_WINDOW, init_exposure, EXPOSURE_MAX, nothing)
    cv2.createTrackbar("Focus", CTRL_WINDOW, init_focus, FOCUS_MAX, nothing)
    # OpenCV ne gère pas les valeurs négatives dans un trackbar : on décale la plage
    # (-64..64 devient 0..128) et on soustrait BRIGHTNESS_MIN au moment de lire la valeur.
    cv2.createTrackbar("Luminosite", CTRL_WINDOW, init_brightness - BRIGHTNESS_MIN,
                       BRIGHTNESS_MAX - BRIGHTNESS_MIN, nothing)
    cv2.createTrackbar("Contraste", CTRL_WINDOW, init_contrast, CONTRAST_MAX, nothing)

    # Sliders overlay de collimation (position choisie par l'utilisateur,
    # le décalage constructeur calib_offset est appliqué en plus, pas à la place)
    # Position en PIXELS (1 cran = 1 px), plus un slider fin de +/-FINE_RANGE px pour les
    # derniers pixels ; les touches i/j/k/l déplacent aussi le centre pixel par pixel.
    cv2.createTrackbar("Centre X (px)", CTRL_WINDOW, init_center_x, frame_w, nothing)
    cv2.createTrackbar("Centre Y (px)", CTRL_WINDOW, init_center_y, frame_h, nothing)
    cv2.createTrackbar("Centre X fin (px)", CTRL_WINDOW, FINE_RANGE, 2 * FINE_RANGE, nothing)
    cv2.createTrackbar("Centre Y fin (px)", CTRL_WINDOW, FINE_RANGE, 2 * FINE_RANGE, nothing)
    cv2.createTrackbar("Rayon rouge", CTRL_WINDOW, init_r_red, max_radius, nothing)
    cv2.createTrackbar("Rayon vert", CTRL_WINDOW, init_r_green, max_radius, nothing)
    cv2.createTrackbar("Rayon bleu", CTRL_WINDOW, init_r_blue, max_radius, nothing)
    cv2.createTrackbar("Epaisseur", CTRL_WINDOW, init_thickness, 10, nothing)

    # Croix du centre de collimation (jaune) : taille et épaisseur réglables séparément
    # des cercles, avec des valeurs par défaut proportionnées à la résolution.
    cv2.createTrackbar("Taille croix collimation", CTRL_WINDOW, init_cross_arm, max_radius, nothing)
    cv2.createTrackbar("Epaisseur croix collimation", CTRL_WINDOW, init_cross_thickness, 20, nothing)

    def read_center():
        """Centre choisi (px) = curseur grossier + curseur fin (centré sur 0), borné à l'image.
        Il s'applique aux cercles ET à la croix ; le décalage constructeur s'y ajoute ensuite."""
        x = cv2.getTrackbarPos("Centre X (px)", CTRL_WINDOW) \
            + cv2.getTrackbarPos("Centre X fin (px)", CTRL_WINDOW) - FINE_RANGE
        y = cv2.getTrackbarPos("Centre Y (px)", CTRL_WINDOW) \
            + cv2.getTrackbarPos("Centre Y fin (px)", CTRL_WINDOW) - FINE_RANGE
        return min(max(x, 0), frame_w - 1), min(max(y, 0), frame_h - 1)

    def collect_settings():
        """Lit les sliders et renvoie le dict à sauvegarder (rayons/croix en fraction du rayon max,
        centre en fraction de la largeur/hauteur de l'image)."""
        mr = max(1, max_radius)
        center_px_x, center_px_y = read_center()
        return {
            "center_x": round(center_px_x / frame_w, 6),
            "center_y": round(center_px_y / frame_h, 6),
            "exposure": cv2.getTrackbarPos("Exposition", CTRL_WINDOW),
            "focus": cv2.getTrackbarPos("Focus", CTRL_WINDOW),
            "brightness": cv2.getTrackbarPos("Luminosite", CTRL_WINDOW) + BRIGHTNESS_MIN,
            "contrast": cv2.getTrackbarPos("Contraste", CTRL_WINDOW),
            "circle_thickness": max(1, cv2.getTrackbarPos("Epaisseur", CTRL_WINDOW)),
            "radius_red": round(cv2.getTrackbarPos("Rayon rouge", CTRL_WINDOW) / mr, 4),
            "radius_green": round(cv2.getTrackbarPos("Rayon vert", CTRL_WINDOW) / mr, 4),
            "radius_blue": round(cv2.getTrackbarPos("Rayon bleu", CTRL_WINDOW) / mr, 4),
            "cross_arm": round(cv2.getTrackbarPos("Taille croix collimation", CTRL_WINDOW) / mr, 4),
            "cross_thickness": max(1, cv2.getTrackbarPos("Epaisseur croix collimation", CTRL_WINDOW)),
        }

    def save_now():
        path = save_settings(settings_serial, collect_settings())
        if path:
            print(f"[reglages] Réglages sauvegardés dans {path}")
        return path

    frozen_frame = None
    crossfade = False
    fade_pos = 0  # 0..100

    print("Touches : s = figer une image de reference | f = activer/desactiver fondu | "
          "w = sauvegarder les reglages | i/k/j/l = deplacer le centre de 1 px | "
          "q = quitter (sauvegarde automatique)")
    if serial:
        print(f"Caméra identifiée : {serial}")

    raw_entry = get_raw_entry_for_serial(serial)
    if raw_entry:
        center_x = raw_entry.get("center_x_px")
        center_y = raw_entry.get("center_y_px")
        ref_w = raw_entry.get("ref_width")
        ref_h = raw_entry.get("ref_height")
        center_str = f"Centre constructeur: ({center_x}, {center_y}) @ {ref_w}x{ref_h}"
    else:
        center_str = "Centre constructeur: non enregistre"
    info_line = f"Camera: {serial or 'inconnue'}   {center_str}"
    if args.flip_calib:
        info_line += f"   [decalage inverse: {args.flip_calib}]"

    # Texte proportionnel à la résolution (sinon minuscule en 4K, comme la croix l'était avant)
    font_scale = max(0.5, min(frame_w, frame_h) / 1080 * 0.6)
    font_thickness = max(1, int(font_scale * 2))
    line_height = int(30 * font_scale)

    last_exp, last_focus = -1, -1
    last_brightness, last_contrast = -9999, -1
    frame = first_frame
    save_message_until = 0.0  # affiche brièvement "Réglages sauvegardés" après la touche 'w'

    while True:
        exp = cv2.getTrackbarPos("Exposition", CTRL_WINDOW)
        focus = cv2.getTrackbarPos("Focus", CTRL_WINDOW)
        brightness = cv2.getTrackbarPos("Luminosite", CTRL_WINDOW) + BRIGHTNESS_MIN
        contrast = cv2.getTrackbarPos("Contraste", CTRL_WINDOW)
        if exp != last_exp:
            v4l2_set(device, "exposure_time_absolute", exp)
            last_exp = exp
        if focus != last_focus:
            v4l2_set(device, "focus_absolute", focus)
            last_focus = focus
        if brightness != last_brightness:
            v4l2_set(device, "brightness", brightness)
            last_brightness = brightness
        if contrast != last_contrast:
            v4l2_set(device, "contrast", contrast)
            last_contrast = contrast

        cx, cy = read_center()
        r_red = cv2.getTrackbarPos("Rayon rouge", CTRL_WINDOW)
        r_green = cv2.getTrackbarPos("Rayon vert", CTRL_WINDOW)
        r_blue = cv2.getTrackbarPos("Rayon bleu", CTRL_WINDOW)
        thickness = max(1, cv2.getTrackbarPos("Epaisseur", CTRL_WINDOW))
        cross_arm = cv2.getTrackbarPos("Taille croix collimation", CTRL_WINDOW)
        cross_thickness = max(1, cv2.getTrackbarPos("Epaisseur croix collimation", CTRL_WINDOW))

        display = frame
        if crossfade and frozen_frame is not None:
            fh, fw = frame.shape[:2]
            frozen_resized = cv2.resize(frozen_frame, (fw, fh))
            alpha = fade_pos / 100.0
            display = cv2.addWeighted(frame, 1 - alpha, frozen_resized, alpha, 0)

        display = draw_overlay(display, cx, cy, r_red, r_green, r_blue, thickness,
                                cross_arm, cross_thickness, calib_offset)

        cv2.putText(display, info_line, (10, line_height),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 255), font_thickness)
        cv2.putText(display, f"Exp={exp} Focus={focus} Lum={brightness} Contr={contrast}", (10, line_height * 2),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 255), font_thickness)
        if time.time() < save_message_until:
            cv2.putText(display, "Reglages sauvegardes", (10, line_height * 3),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 255, 0), font_thickness)

        if args.display_scale != 1.0:
            display = cv2.resize(display, None, fx=args.display_scale, fy=args.display_scale,
                                  interpolation=cv2.INTER_AREA)

        cv2.imshow(WINDOW, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            frozen_frame = frame.copy()
            print("Image de référence figée.")
        elif key in (ord('i'), ord('k'), ord('j'), ord('l')):
            # Déplacement du centre d'1 pixel : i/k = haut/bas, j/l = gauche/droite
            name, limit, step = {
                ord('i'): ("Centre Y (px)", frame_h, -1),
                ord('k'): ("Centre Y (px)", frame_h, +1),
                ord('j'): ("Centre X (px)", frame_w, -1),
                ord('l'): ("Centre X (px)", frame_w, +1),
            }[key]
            cv2.setTrackbarPos(name, CTRL_WINDOW,
                               min(max(cv2.getTrackbarPos(name, CTRL_WINDOW) + step, 0), limit))
        elif key == ord('w'):
            if save_now():
                save_message_until = time.time() + 2.0
        elif key == ord('f'):
            crossfade = not crossfade
            print(f"Fondu croisé : {'ON' if crossfade else 'OFF'}")
        elif key == ord('+'):
            fade_pos = min(100, fade_pos + 5)
        elif key == ord('-'):
            fade_pos = max(0, fade_pos - 5)

        ok, frame = cap.read()
        if not ok:
            print("Lecture caméra échouée.")
            break

    # Sauvegarde automatique à la sortie (les fenêtres existent encore, donc les sliders sont lisibles)
    try:
        save_now()
    except cv2.error:
        pass  # fenêtre de réglages déjà fermée à la main : on garde le dernier fichier sauvegardé

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
