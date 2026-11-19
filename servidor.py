"""
Servidor TCP para que MATLAB llame al sistema (corre en la Raspberry Pi).
Protocolo: una linea JSON por peticion -> una linea JSON de respuesta.
  {"cmd": "jugada_robot", "args": {"uci": "e7e5"}}
Sin autenticacion: usar solo en una red local de confianza.
Uso: python3 servidor.py [--sin-robot] [--sin-motor]
"""

import json
import socket
import sys
import traceback

import config
from juego import Juego


def main():
    juego = Juego(con_robot="--sin-robot" not in sys.argv, con_motor="--sin-motor" not in sys.argv)
    acciones = {
        "estado": juego.estado,
        "leer_tablero": juego.leer_tablero,
        "iniciar": juego.iniciar,
        "iniciar_fen": juego.iniciar_fen,
        "jugada_humano": juego.jugada_humano,
        "confirmar_jugada": juego.confirmar_jugada,
        "jugada_robot": juego.jugada_robot,
        "home": juego.home,
    }

    srv = socket.create_server((config.SERVIDOR_HOST, config.SERVIDOR_PUERTO))
    print(f"Escuchando en el puerto {config.SERVIDOR_PUERTO}")
    try:
        while True:
            conn, dir_cliente = srv.accept()
            print(f"Cliente: {dir_cliente}")
            with conn, conn.makefile("rwb") as f:
                for linea in f:
                    try:
                        msg = json.loads(linea)
                        r = acciones[msg["cmd"]](**msg.get("args", {}))
                    except KeyError as e:
                        r = {"ok": False, "error": f"comando desconocido: {e}"}
                    except Exception as e:
                        traceback.print_exc()
                        r = {"ok": False, "error": str(e)}
                    f.write((json.dumps(r) + "\n").encode())
                    f.flush()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()
        juego.cerrar()


if __name__ == "__main__":
    main()
