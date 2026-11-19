"""
Modo de pruebas con teclado (sin MATLAB). Uso: python3 main.py [--sin-robot] [--sin-motor]
  v : leer tablero y mostrar     i : iniciar partida desde lo que ve la camara
  h : reconocer jugada humana    r : jugada del robot (Stockfish)
  s : estado                     q : salir
"""

import sys
import cv2
import config
from juego import Juego


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
    try:
        while True:
            vivo = juego.cam.leer()
            if vivo is not None:
                cv2.imshow("ZED 2 en vivo", vivo)
            if juego.ultima_vista is not None:
                cv2.imshow("Piezas detectadas", juego.ultima_vista)
            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord("q"):
                break
            if tecla in acciones:
                try:
                    print(acciones[tecla]())
                except Exception as e:
                    print(f"Error: {e}")
    finally:
        juego.cerrar()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
