#!/usr/bin/env python3
"""
Prototype de collimateur électronique type OCAL pour Linux.

Fonctions :
  - Flux vidéo caméra UVC (V4L2)
  - Overlay de cercles concentriques ajustables (rouge / vert / bleu) + croix
  - Contrôle exposition et focus (via v4l2-ctl, plus fiable que cv2.set())
  - Fondu croisé (touche 'f') entre l'image courante et une image figée
  - Capture d'une image de référence (touche 's') pour comparaison

Dépendances : opencv-python, v4l2-ctl (paquet v4l-utils)
Usage : python3 ocal_linux.py /dev/video49
"""

import sys
import subprocess
import cv2
import numpy as np

DEVICE = sys.argv[1] if len(sys.argv) > 1 else "/dev/video0"

WINDOW = "OCAL Linux"
CTRL_WINDOW = "Reglages"

# ---- Réglages par défaut (bornes issues de v4l2-ctl --list-ctrls) ----
EXPOSURE_MIN, EXPOSURE_MAX = 3, 2047
FOCUS_MIN, FOCUS_MAX = 0, 1023


def v4l2_set(control: str, value: int):
    """Applique un contrôle V4L2 via v4l2-ctl (plus fiable que cv2.VideoCapture.set)."""
    try:
        subprocess.run(
            ["v4l2-ctl", "-d", DEVICE, "-c", f"{control}={value}"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        print("v4l2-ctl introuvable : installe le paquet v4l-utils.")


def ensure_manual_modes():
    # auto_exposure : 1 = Manual Mode sur la plupart des caméras UVC (norme un peu tordue)
    v4l2_set("auto_exposure", 1)
    v4l2_set("focus_automatic_continuous", 0)


def nothing(_):
    pass


def draw_overlay(frame, cx, cy, r_red, r_green, r_blue, thickness):
    h, w = frame.shape[:2]
    cx = int(cx * w / 1000)
    cy = int(cy * h / 1000)
    overlay = frame.copy()
    cv2.circle(overlay, (cx, cy), r_red, (0, 0, 255), thickness)
    cv2.circle(overlay, (cx, cy), r_green, (0, 255, 0), thickness)
    cv2.circle(overlay, (cx, cy), r_blue, (255, 0, 0), thickness)
    cv2.line(overlay, (cx - 30, cy), (cx + 30, cy), (0, 255, 255), 1)
    cv2.line(overlay, (cx, cy - 30), (cx, cy + 30), (0, 255, 255), 1)
    return overlay


def main():
    cap = cv2.VideoCapture(DEVICE, cv2.CAP_V4L2)
    if not cap.isOpened():
        print(f"Impossible d'ouvrir {DEVICE}")
        sys.exit(1)

    ensure_manual_modes()

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.namedWindow(CTRL_WINDOW, cv2.WINDOW_NORMAL)

    # Sliders caméra
    cv2.createTrackbar("Exposition", CTRL_WINDOW, 166, EXPOSURE_MAX, nothing)
    cv2.createTrackbar("Focus", CTRL_WINDOW, 0, FOCUS_MAX, nothing)

    # Sliders overlay de collimation
    cv2.createTrackbar("Centre X (o/oo)", CTRL_WINDOW, 500, 1000, nothing)
    cv2.createTrackbar("Centre Y (o/oo)", CTRL_WINDOW, 500, 1000, nothing)
    cv2.createTrackbar("Rayon rouge", CTRL_WINDOW, 60, 400, nothing)
    cv2.createTrackbar("Rayon vert", CTRL_WINDOW, 120, 400, nothing)
    cv2.createTrackbar("Rayon bleu", CTRL_WINDOW, 180, 400, nothing)
    cv2.createTrackbar("Epaisseur", CTRL_WINDOW, 1, 5, nothing)

    frozen_frame = None
    crossfade = False
    fade_pos = 0  # 0..100

    print("Touches : s = figer une image de reference | f = activer/desactiver fondu | q = quitter")

    last_exp, last_focus = -1, -1

    while True:
        ok, frame = cap.read()
        if not ok:
            print("Lecture caméra échouée.")
            break

        exp = cv2.getTrackbarPos("Exposition", CTRL_WINDOW)
        focus = cv2.getTrackbarPos("Focus", CTRL_WINDOW)
        if exp != last_exp:
            v4l2_set("exposure_time_absolute", exp)
            last_exp = exp
        if focus != last_focus:
            v4l2_set("focus_absolute", focus)
            last_focus = focus

        cx = cv2.getTrackbarPos("Centre X (o/oo)", CTRL_WINDOW)
        cy = cv2.getTrackbarPos("Centre Y (o/oo)", CTRL_WINDOW)
        r_red = cv2.getTrackbarPos("Rayon rouge", CTRL_WINDOW)
        r_green = cv2.getTrackbarPos("Rayon vert", CTRL_WINDOW)
        r_blue = cv2.getTrackbarPos("Rayon bleu", CTRL_WINDOW)
        thickness = max(1, cv2.getTrackbarPos("Epaisseur", CTRL_WINDOW))

        display = frame
        if crossfade and frozen_frame is not None:
            fh, fw = frame.shape[:2]
            frozen_resized = cv2.resize(frozen_frame, (fw, fh))
            alpha = fade_pos / 100.0
            display = cv2.addWeighted(frame, 1 - alpha, frozen_resized, alpha, 0)

        display = draw_overlay(display, cx, cy, r_red, r_green, r_blue, thickness)

        cv2.putText(display, f"Exp={exp} Focus={focus}", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        cv2.imshow(WINDOW, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            frozen_frame = frame.copy()
            print("Image de référence figée.")
        elif key == ord('f'):
            crossfade = not crossfade
            print(f"Fondu croisé : {'ON' if crossfade else 'OFF'}")
        elif key == ord('+'):
            fade_pos = min(100, fade_pos + 5)
        elif key == ord('-'):
            fade_pos = max(0, fade_pos - 5)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
