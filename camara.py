"""
Captura de la ZED 2 por V4L2 (sin ZED SDK) y correccion de distorsion del ojo izquierdo
con la calibracion de fabrica SN<serie>.conf (descargable de calib.stereolabs.com).
El mapa de correccion se calcula UNA vez: depende del lente y la resolucion, no de la posicion.
"""

import configparser
import time
import cv2
import numpy as np

MODOS = {"2K": (4416, 1242), "FHD": (3840, 1080), "HD": (2560, 720), "VGA": (1344, 376)}


def leer_conf(ruta, modo):
    """Devuelve (K, dist) del ojo izquierdo para el modo dado."""
    cp = configparser.ConfigParser()
    if not cp.read(ruta):
        raise FileNotFoundError(ruta)
    s = cp[f"LEFT_CAM_{modo}"]
    K = np.array([[float(s["fx"]), 0, float(s["cx"])],
                  [0, float(s["fy"]), float(s["cy"])],
                  [0, 0, 1]], dtype=np.float64)
    dist = np.array([float(s.get(k, 0)) for k in ("k1", "k2", "p1", "p2", "k3")], dtype=np.float64)
    return K, dist


class Camara:
    def __init__(self, indice=2, modo="HD", ruta_conf=None, fps=15):
        ancho, alto = MODOS[modo]
        self.cap = cv2.VideoCapture(indice, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, ancho)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, alto)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            raise RuntimeError(f"No se pudo abrir la camara en el indice {indice}")

        self.K, self.mapas = None, None
        if ruta_conf:
            self.K, dist = leer_conf(ruta_conf, modo)
            tam = (ancho // 2, alto)
            self.mapas = cv2.initUndistortRectifyMap(self.K, dist, None, self.K, tam, cv2.CV_16SC2)
        else:
            print("Aviso: sin archivo .conf, la imagen no se corrige y no hay K para solvePnP")

    def leer(self):
        """Un frame del ojo izquierdo, corregido si hay calibracion. None si falla."""
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None
        izq = frame[:, :frame.shape[1] // 2]
        if self.mapas is not None:
            izq = cv2.remap(izq, self.mapas[0], self.mapas[1], cv2.INTER_LINEAR)
        return izq

    def leer_estable(self, n=5, descartar=3):
        """Mediana de n frames, tras descartar los que quedaron en el buffer."""
        for _ in range(descartar):
            self.cap.grab()
        frames = []
        intentos = 0
        while len(frames) < n and intentos < n * 4:
            f = self.leer()
            intentos += 1
            if f is not None:
                frames.append(f)
            else:
                time.sleep(0.01)
        if not frames:
            return None
        return np.median(np.stack(frames), axis=0).astype(np.uint8)

    def cerrar(self):
        self.cap.release()
