"""
Geometria del tablero: pose de la camara y homografia al plano de las caras superiores.
Al rectificar el plano Z = altura de la cara, las caras salen con su forma real y en la
casilla correcta (se elimina el paralaje); las paredes laterales quedan deformadas.
Marco del tablero: origen en la esquina sup-izq del cuadro interno verde, X a la derecha,
Y hacia abajo (en la imagen rectificada); Z apunta hacia la mesa, por eso la altura es -h.
"""

import cv2
import numpy as np


def esquinas_desde_homografia(M, lado=800):
    """Recupera las 4 esquinas en la imagen (sup-izq, sup-der, inf-der, inf-izq) a partir de M."""
    dst = np.float32([[0, 0], [lado - 1, 0], [lado - 1, lado - 1], [0, lado - 1]]).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(dst, np.linalg.inv(M)).reshape(4, 2)


def pose_camara(esquinas_img, lado_mm, K):
    """solvePnP con las 4 esquinas del marco. Devuelve (R, t) del marco del tablero a la camara."""
    obj = np.float32([[0, 0, 0], [lado_mm, 0, 0], [lado_mm, lado_mm, 0], [0, lado_mm, 0]])
    ok, rvec, tvec = cv2.solvePnP(obj, np.float32(esquinas_img), K, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        raise RuntimeError("solvePnP fallo")
    R, _ = cv2.Rodrigues(rvec)
    return R, tvec.reshape(3)


def homografia_a_altura(R, t, K, lado_mm, altura_mm, lado_px=800):
    """Homografia imagen -> plano rectificado (lado_px) del plano a altura_mm sobre el tablero."""
    H = K @ np.column_stack((R[:, 0], R[:, 1], R[:, 2] * (-altura_mm) + t))  # mm -> imagen
    s = (lado_px - 1) / lado_mm
    return np.diag([s, s, 1.0]) @ np.linalg.inv(H)


def centro_camara(R, t, lado_mm, lado_px=800):
    """Devuelve (nadir en px del plano rectificado, altura de la camara sobre el tablero en mm)."""
    C = -R.T @ t
    s = (lado_px - 1) / lado_mm
    return (float(C[0] * s), float(C[1] * s)), float(-C[2])


def punto_base(contorno, nadir_px):
    """Punto del contorno mas cercano al nadir: aproxima donde la pieza toca el tablero."""
    P = contorno.reshape(-1, 2).astype(np.float64)
    i = np.argmin(np.linalg.norm(P - np.asarray(nadir_px), axis=1))
    return tuple(P[i])
