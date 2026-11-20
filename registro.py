"""
Registro continuo de la deteccion (se activa junto con el analisis en vivo, tecla ESPACIO).
Escribe dos CSV por sesion en la carpeta logs/:
  frames_<sesion>.csv : una fila por frame analizado (si se vio el marco, cuantas piezas, altura, nadir)
  piezas_<sesion>.csv : una fila por pieza vista en un frame con marco (casilla, simbolo, posicion, rasgos)
No necesita saber cuantas piezas hay: registra lo que aparezca. Lo analiza analizar_log.py.
"""

import csv
import os
import time

import chess
import cv2
import numpy as np

import config
from estado_tablero import celda_a_casilla
from vision import contar_esquinas

CAMPOS_FRAME = ["frame", "t", "marco_ok", "n_piezas", "altura_mm", "nadir_x", "nadir_y", "error"]
CAMPOS_PIEZA = ["frame", "t", "casilla", "fila", "col", "simbolo", "cx", "cy", "dist_nadir_mm",
                "area", "vertices", "agudas", "circ", "relleno"]


def blobs_naranja(plano, area_min=200):
    """Misma mascara de tonos naranja que vision.analizar_formas_tablero (version del usuario)."""
    hsv = cv2.cvtColor(plano, cv2.COLOR_BGR2HSV)
    m = cv2.inRange(hsv, (0, 100, 60), (35, 255, 255)) | cv2.inRange(hsv, (172, 100, 60), (180, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    salida = []
    for c in cnts:
        a, p = cv2.contourArea(c), cv2.arcLength(c, True)
        if a < area_min or p == 0:
            continue
        M = cv2.moments(c)
        P = np.squeeze(c)
        n, agudas = contar_esquinas(P) if P.ndim == 2 and len(P) >= 3 else (0, 0)
        w, h = cv2.minAreaRect(c)[1]
        salida.append({"cx": M["m10"] / M["m00"], "cy": M["m01"] / M["m00"], "area": a,
                       "vertices": n, "agudas": agudas, "circ": 4 * np.pi * a / p ** 2,
                       "relleno": a / (w * h) if w * h else 0})
    return salida


class Registro:
    def __init__(self, carpeta="logs"):
        os.makedirs(carpeta, exist_ok=True)
        self.sesion = time.strftime("%Y%m%d_%H%M%S")
        self._ff = open(os.path.join(carpeta, f"frames_{self.sesion}.csv"), "w", newline="")
        self._fp = open(os.path.join(carpeta, f"piezas_{self.sesion}.csv"), "w", newline="")
        self.wf = csv.DictWriter(self._ff, CAMPOS_FRAME)
        self.wp = csv.DictWriter(self._fp, CAMPOS_PIEZA)
        self.wf.writeheader()
        self.wp.writeheader()
        self.n = 0
        self.t0 = time.time()
        print(f"Registro: logs/frames_{self.sesion}.csv y logs/piezas_{self.sesion}.csv")

    def registrar(self, obs, extra, imgs, error=""):
        self.n += 1
        t = round(time.time() - self.t0, 3)
        plano = imgs.get("plano") if imgs else None
        marco_ok = obs is not None and plano is not None
        nadir = extra.get("nadir_px") if extra else None
        piezas = blobs_naranja(plano) if marco_ok else []

        lado = config.LADO
        mm_px = (config.LADO_MARCO_MM or 240.0) / lado
        celda = lado / 8.0
        for b in piezas:
            fila = min(max(int(b["cy"] // celda), 0), 7)
            col = min(max(int(b["cx"] // celda), 0), 7)
            sq = celda_a_casilla(fila, col)
            dist = (np.hypot(b["cx"] - nadir[0], b["cy"] - nadir[1]) * mm_px) if nadir else ""
            self.wp.writerow({
                "frame": self.n, "t": t, "casilla": chess.square_name(sq), "fila": fila, "col": col,
                "simbolo": obs.get(sq, "vacio"), "cx": round(b["cx"], 1), "cy": round(b["cy"], 1),
                "dist_nadir_mm": round(dist, 1) if dist != "" else "",
                "area": int(b["area"]), "vertices": b["vertices"], "agudas": b["agudas"],
                "circ": round(b["circ"], 3), "relleno": round(b["relleno"], 3)})

        self.wf.writerow({
            "frame": self.n, "t": t, "marco_ok": int(marco_ok), "n_piezas": len(piezas),
            "altura_mm": extra.get("altura_camara_mm", "") if extra else "",
            "nadir_x": nadir[0] if nadir else "", "nadir_y": nadir[1] if nadir else "", "error": error})
        if self.n % 30 == 0:
            self._ff.flush()
            self._fp.flush()

    def cerrar(self):
        self._ff.close()
        self._fp.close()
        print(f"Registro cerrado: {self.n} frames en la sesion {self.sesion}")