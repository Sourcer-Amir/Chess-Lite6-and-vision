"""
Modulo de vision por computadora para deteccion de formas y piezas sobre tablero rectificado.
"""

import cv2
import numpy as np


def obtener_homografia_por_color(img_bgr, lado=800):
    """
    Calcula la matriz de homografia para rectificar la perspectiva del tablero.
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower_green = np.array([35, 40, 30])
    upper_green = np.array([85, 255, 255])
    mask = cv2.inRange(hsv, lower_green, upper_green)

    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    cnts, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

    if not cnts or hierarchy is None:
        return None, mask

    candidatos_internos = []
    candidatos_generales = []

    for i, c in enumerate(cnts):
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.05 * peri, True)

        if len(approx) == 4 and cv2.contourArea(approx) > 10000:
            candidatos_generales.append(approx)
            if hierarchy[0][i][3] != -1:
                candidatos_internos.append(approx)

    pts = None

    if candidatos_internos:
        candidatos_internos = sorted(candidatos_internos, key=cv2.contourArea, reverse=True)
        pts = candidatos_internos[0].reshape(4, 2)
    elif len(candidatos_generales) >= 2:
        candidatos_generales = sorted(candidatos_generales, key=cv2.contourArea, reverse=True)
        pts = candidatos_generales[1].reshape(4, 2)
    elif len(candidatos_generales) == 1:
        pts = candidatos_generales[0].reshape(4, 2)
    else:
        return None, mask

    suma = pts.sum(axis=1)
    diferencia = np.diff(pts, axis=1)

    src = np.zeros((4, 2), dtype="float32")
    src[0] = pts[np.argmin(suma)]
    src[2] = pts[np.argmax(suma)]
    src[1] = pts[np.argmin(diferencia)]
    src[3] = pts[np.argmax(diferencia)]

    dst = np.array([
        [0, 0],
        [lado - 1, 0],
        [lado - 1, lado - 1],
        [0, lado - 1]
    ], dtype="float32")

    return cv2.getPerspectiveTransform(src, dst), mask


def nombre_color(rgb_median):
    """
    Convierte la mediana RGB (0 a 255) a HSV y devuelve el nombre del color.
    """
    rgb_img = np.uint8([[rgb_median]])
    hsv_img = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2HSV)
    h, s, v = hsv_img[0][0]

    h_grados = float(h) * 2.0
    s_norm = float(s) / 255.0
    v_norm = float(v) / 255.0

    if v_norm < 0.20:
        return 'negro'
    elif s_norm < 0.15 and v_norm > 0.80:
        return 'blanco'
    elif s_norm < 0.15:
        return 'gris'
    elif h_grados < 15 or h_grados >= 345:
        return 'rojo'
    elif h_grados < 33:
        return 'naranja'
    elif h_grados < 70:
        return 'amarillo'
    elif h_grados < 170:
        return 'verde'
    elif h_grados < 190:
        return 'cian'
    elif h_grados < 260:
        return 'azul'
    elif h_grados < 300:
        return 'morado'
    else:
        return 'rosa'


def douglas_peucker(P, tol):
    """
    Simplificacion recursiva de contornos Ramer Douglas Peucker.
    """
    n = len(P)
    keep = np.zeros(n, dtype=bool)
    keep[0] = True
    keep[-1] = True

    if n < 3:
        return keep

    a = P[0]
    b = P[-1]
    ab = b - a
    L = np.linalg.norm(ab)

    if L == 0:
        d = np.linalg.norm(P - a, axis=1)
    else:
        d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / L

    dmax = np.max(d)
    i = np.argmax(d)

    if dmax > tol:
        keep[:i + 1] = douglas_peucker(P[:i + 1], tol)
        keep[i:] = douglas_peucker(P[i:], tol)

    return keep


def contar_esquinas(P):
    """
    Cuenta vertices totales y esquinas agudas (menor a 120 grados) en un contorno cerrado.
    """
    diff_pts = np.diff(np.vstack((P, P[0])), axis=0)
    perim = np.sum(np.linalg.norm(diff_pts, axis=1))
    tol = 0.01 * perim

    distancias_al_origen = np.linalg.norm(P - P[0], axis=1)
    i2 = np.argmax(distancias_al_origen)

    curva1 = P[:i2 + 1]
    curva2 = np.vstack((P[i2:], P[0]))

    k1 = douglas_peucker(curva1, tol)
    k2 = douglas_peucker(curva2, tol)

    V = np.vstack((curva1[k1], curva2[k2]))
    indices_eliminar = [np.sum(k1), len(V) - 1]
    V = np.delete(V, indices_eliminar, axis=0)

    n = len(V)
    if n < 3:
        return n, 0

    v_sig = np.roll(V, -1, axis=0)
    v_ant = np.roll(V, 1, axis=0)

    a = v_sig - V
    b = v_ant - V

    dot_prod = np.sum(a * b, axis=1)
    norm_a = np.linalg.norm(a, axis=1)
    norm_b = np.linalg.norm(b, axis=1)

    den = norm_a * norm_b
    den[den == 0] = 1e-10

    cos_theta = np.clip(dot_prod / den, -1.0, 1.0)
    ang = np.degrees(np.arccos(cos_theta))

    n_agudas = int(np.sum(ang < 120))
    return n, n_agudas


def analizar_formas_tablero(plano_rectificado):
    """
    Segmenta figuras por saturacion, rellena huecos intrinsecos, cuenta vertices
    y clasifica cada figura naranja en una matriz de 8x8.
    """
    h, w = plano_rectificado.shape[:2]
    ch, cw = h // 8, w // 8
    matriz = np.empty((8, 8), dtype=object)

    hsv = cv2.cvtColor(plano_rectificado, cv2.COLOR_BGR2HSV)

    mask = cv2.bitwise_or(
        cv2.inRange(hsv, (0, 100, 60), (35, 255, 255)),
        cv2.inRange(hsv, (172, 100, 60), (180, 255, 255))
    )

    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is not None:
        for i, contour in enumerate(contours):
            if hierarchy[0][i][3] != -1:
                cv2.drawContours(mask, [contour], 0, 255, -1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        if cv2.contourArea(contour) < 200:
            cv2.drawContours(mask, [contour], 0, 0, -1)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    contornos_finales, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    img_resultado = plano_rectificado.copy()

    for cnt in contornos_finales:
        area = cv2.contourArea(cnt)
        perimetro = cv2.arcLength(cnt, True)
        if area == 0 or perimetro == 0:
            continue

        mask_obj = np.zeros(mask.shape, dtype=np.uint8)
        cv2.drawContours(mask_obj, [cnt], -1, 255, -1)
        b_med = np.median(plano_rectificado[:, :, 0][mask_obj == 255])
        g_med = np.median(plano_rectificado[:, :, 1][mask_obj == 255])
        r_med = np.median(plano_rectificado[:, :, 2][mask_obj == 255])
        color = nombre_color([r_med, g_med, b_med])

        if color not in ('naranja', 'rojo', 'amarillo'):
            continue

        P = np.squeeze(cnt)
        if P.ndim == 1:
            P = np.expand_dims(P, axis=0)

        _, n_agudas = contar_esquinas(P)
        circ = 4.0 * np.pi * area / (perimetro ** 2)

                # Clasificacion por forma vista desde arriba (ver NOMBRE_A_SIMBOLO en config.py):
        #   cuadrado  -> 4 esquinas agudas (<120 grados)      -> Rey Blanco
        #   pentagono -> 5 esquinas agudas                    -> Rey Negro
        #   circulo   -> 0 esquinas y circularidad > 0.80     -> Torre Blanca
        pieza = 'Desconocido'
        if n_agudas == 4:
            pieza = 'Rey Blanco'
        elif n_agudas == 5:
            pieza = 'Rey Negro'
        elif n_agudas == 0 and circ > 0.80:
            pieza = 'Torre Blanca'

        M = cv2.moments(cnt)
        if M["m00"] != 0:
            cX = int(M["m10"] / M["m00"])
            cY = int(M["m01"] / M["m00"])
        else:
            continue

        cv2.drawContours(img_resultado, [cnt], -1, (0, 255, 0), 2)
        cv2.putText(
            img_resultado,
            f"{pieza}",
            (cX - 45, cY),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 255),
            2
        )

        fila = min(max(cY // ch, 0), 7)
        col = min(max(cX // cw, 0), 7)
        matriz[fila, col] = pieza

    return img_resultado, matriz


def detectar_piezas_auditoria(plano_rectificado):
    """
    Audita la presencia de piezas marrones dentro de una matriz de 8x8 casillas.
    """
    hsv = cv2.cvtColor(plano_rectificado, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    ch, cw = h // 8, w // 8

    matriz = np.zeros((8, 8), dtype=int)
    centros_piezas = []

    lower_brown = np.array([5, 40, 20])
    upper_brown = np.array([35, 255, 255])
    mascara_marron = cv2.inRange(hsv, lower_brown, upper_brown)

    kernel_close = np.ones((35, 35), np.uint8)
    mascara_unida = cv2.morphologyEx(mascara_marron, cv2.MORPH_CLOSE, kernel_close)

    kernel_open = np.ones((5, 5), np.uint8)
    mascara_limpia = cv2.morphologyEx(mascara_unida, cv2.MORPH_OPEN, kernel_open)

    cnts, _ = cv2.findContours(mascara_limpia, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    for c in cnts:
        if cv2.contourArea(c) > 500:
            x, y, bw, bh = cv2.boundingRect(c)
            px = x + (bw // 2)
            py = y + bh - 5

            fila = min(max(py // ch, 0), 7)
            col = min(max(px // cw, 0), 7)

            matriz[fila, col] = 1
            centros_piezas.append((fila, col, px, py))

    return matriz, mascara_limpia, centros_piezas


def dibujar_tablero(plano, matriz):
    """
    Dibuja la reticula del tablero y los indicadores de deteccion de piezas.
    """
    vis = plano.copy()
    h, w = vis.shape[:2]
    ch, cw = h // 8, w // 8

    for i in range(9):
        cv2.line(vis, (0, i * ch), (w, i * ch), (0, 255, 0), 1)
        cv2.line(vis, (i * cw, 0), (i * cw, h), (0, 255, 0), 1)

    for r in range(8):
        for c in range(8):
            val = matriz[r, c]
            if val in ('Rey Blanco', 'Rey Negro', 'Torre Blanca') or val == 1:
                cx = c * cw + cw // 2
                cy = r * ch + ch // 2
                cv2.circle(vis, (cx, cy), 12, (0, 75, 150), -1)
                cv2.circle(vis, (cx, cy), 13, (0, 0, 0), 2)
    return vis