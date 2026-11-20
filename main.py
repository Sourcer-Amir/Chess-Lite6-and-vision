"""
Modo de pruebas con teclado (sin MATLAB). Uso: python3 main.py [--sin-robot] [--sin-motor]
Una sola ventana "Monitor" con 4 paneles: 1 en vivo (recorte cuadrado con el marco y una mira),
2 mascara verde, 3 tablero rectificado, 4 piezas detectadas.
  ESPACIO : activar/desactivar el analisis continuo     v : lectura estable (mediana de frames)
  i : iniciar partida desde lo que ve la camara         h : reconocer jugada humana
  r : jugada del robot (Stockfish)                      s : estado       q : salir
"""

import sys
import cv2
import numpy as np
import config
from juego import Juego
from registro import Registro
from vision import obtener_homografia_por_color

P = 440   # lado de cada panel en pantalla


def _cuadrado(img, lado=P):
    """Recorte cuadrado centrado (si no lo es), reducido a lado x lado y en BGR."""
    h, w = img.shape[:2]
    if w != h:
        x0 = (w - h) // 2
        img = img[:, x0:x0 + h]
    img = cv2.resize(img, (lado, lado))
    return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR) if img.ndim == 2 else img.copy()


def _rotulo(panel, texto, color=(255, 255, 255), y=24):
    cv2.putText(panel, texto, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return panel


def panel_vivo(frame, M, extra, K):
    """Copia reducida del recorte central. Cuadrado guia y cruz FIJOS (no siguen al tablero)."""
    h = frame.shape[0]
    img = _cuadrado(frame)
    f = K[0, 0] if K is not None else 1070.0
    lado_px = min(h, f * (config.LADO_MARCO_MM or 240.0) / config.ALTURA_GUIA_MM) * (P / h)
    c, m = P // 2, int(lado_px / 2)
    cv2.rectangle(img, (c - m, c - m), (c + m, c + m), (0, 255, 255), 1)
    cv2.drawMarker(img, (c, c), (255, 255, 255), cv2.MARKER_CROSS, 30, 1)
    estado, color = ("marco OK", (0, 255, 0)) if M is not None else ("SIN MARCO", (0, 0, 255))
    _rotulo(img, "1 En vivo: " + estado, color)
    if "altura_camara_mm" in extra:
        _rotulo(img, f"h = {extra['altura_camara_mm']} mm", (255, 255, 255), P - 10)
    return img


def panel_img(img, titulo, texto_vacio="ESPACIO: analisis"):
    if img is None:
        p = np.zeros((P, P, 3), np.uint8)
        cv2.putText(p, texto_vacio, (20, P // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (160, 160, 160), 1)
    else:
        p = _cuadrado(img)
    return _rotulo(p, titulo)


def construir_monitor(frame, analisis, juego, registro=None):
    extra, imgs, error = {}, {}, None
    if analisis:
        try:
            obs, extra, imgs = juego._procesar(frame, suavizar=True)
            if registro:
                registro.registrar(obs, extra, imgs)
        except Exception as e:           # p. ej. solvePnP fallo en un frame ruidoso
            error = str(e)
            M, mask = obtener_homografia_por_color(frame, config.LADO)
            imgs = {"M": M, "mask": mask}
            if registro:
                registro.registrar(None, {}, imgs, error=error[:80])
        M, mask = imgs.get("M"), imgs.get("mask")
    else:
        M, mask = obtener_homografia_por_color(frame, config.LADO)
    p1 = panel_vivo(frame, M, extra, juego.cam.K)
    p2 = panel_img(mask, "2 Mascara verde")
    p3 = panel_img(imgs.get("plano"), "3 Tablero rectificado", "sin marco" if analisis else "ESPACIO: analisis")
    p4 = panel_img(imgs.get("vista"), "4 Piezas detectadas", "sin marco" if analisis else "ESPACIO: analisis")
    if error:
        _rotulo(p4, error[:48], (0, 0, 255), P - 10)
    return np.vstack([np.hstack([p1, p2]), np.hstack([p3, p4])])


def main():
    juego = Juego(con_robot="--sin-robot" not in sys.argv, con_motor="--sin-motor" not in sys.argv)
    print(__doc__)
    acciones = {
        ord("v"): juego.leer_tablero,
        ord("i"): lambda: juego.iniciar(blancas_mueven=not config.ROBOT_JUEGA_BLANCAS),
        ord("h"): juego.jugada_humano,
        ord("r"): juego.jugada_robot,
        ord("s"): juego.estado,
    }
    analisis = False
    registro = Registro()
    cv2.namedWindow("Monitor", cv2.WINDOW_AUTOSIZE)
    try:
        while True:
            frame = juego.cam.leer()
            if frame is not None:
                cv2.imshow("Monitor", construir_monitor(frame, analisis, juego, registro))
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla == 32:
                analisis = not analisis
                print("Analisis continuo:", "ACTIVO" if analisis else "apagado")
            elif tecla in acciones:
                try:
                    print(acciones[tecla]())
                except Exception as e:
                    print(f"Error: {e}")
    finally:
        registro.cerrar()
        juego.cerrar()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()