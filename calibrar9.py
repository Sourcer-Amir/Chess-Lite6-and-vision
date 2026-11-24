"""
Calibracion del robot con 9 puntos (malla 3x3 sobre el tablero). Se corre una vez; el resultado
queda en calibracion9.json y juego.py lo carga solo (si no existe, usa P1-P3 de config.py).

Uso:
  python3 calibrar9.py            -> grabar los 9 puntos
  python3 calibrar9.py --probar   -> el robot visita los 9 puntos y algunas casillas para verificar

Antes de grabar
  1. Configura el TCP del gripper en UFactory Studio (Settings -> TCP) con el largo real del gripper.
     Comprobacion: si giras el gripper, la punta no debe moverse de lugar.
  2. Quita las piezas del tablero.

Como se graba cada punto
  - Los 9 puntos son CRUCES de lineas del tablero (esquinas compartidas por 4 casillas), faciles de
    apuntar: en el plano de 800 px estan en px, py = 100, 400 y 700.
  - El robot pasa a modo manual: lo mueves con la mano (o con el jog de Studio) hasta que la punta
    del gripper quede JUSTO sobre el cruce, con el gripper VERTICAL (apuntando hacia abajo) y a la
    MISMA ALTURA a la que grabaste P1-P3 (la de agarre). Presionas ENTER y se guarda la pose.
  - En cada punto: ENTER = guardar | r = volver a grabar el anterior | q = salir sin guardar.
"""

import json
import math
import sys
import time

import chess
import numpy as np

import config
from estado_tablero import celda_a_casilla
from robot import ControladorLite6

RUTA = getattr(config, "CALIBRACION_9", "calibracion9.json")
MALLA = (100.0, 400.0, 700.0)             # px y py de los cruces (lineas entre casillas)
MM_POR_PX = (config.LADO_MARCO_MM or 240.0) / config.LADO


def nombre_cruce(px, py):
    """Las 4 casillas que comparten el cruce (px, py), segun la orientacion de config.py."""
    c, f = int(px // 100), int(py // 100)
    casillas = sorted(chess.square_name(celda_a_casilla(ff, cc)) for ff in (f - 1, f) for cc in (c - 1, c))
    lado_v = {100.0: "arriba (lado de la base del robot)", 400.0: "centro", 700.0: "abajo (lado lejano)"}[py]
    lado_h = {100.0: "izquierda", 400.0: "centro", 700.0: "derecha"}[px]
    return f"cruce entre {', '.join(casillas)}  [{lado_v}, {lado_h} en la imagen]"


def revisar_vertical(pose):
    roll, pitch = pose[3], pose[4]
    desvio = max(abs(abs(roll) - 180.0), abs(pitch))
    if desvio > 5:
        print(f"   AVISO: el gripper no esta vertical (roll {roll:.1f}, pitch {pitch:.1f}). "
              "Conviene repetir este punto (r).")


def grabar():
    robot = ControladorLite6(ip=config.ROBOT_IP)
    robot.conectar()
    arm = robot.arm
    arm.set_mode(2)                         # modo manual: el brazo se mueve con la mano
    arm.set_state(0)
    time.sleep(0.5)
    print(__doc__)
    puntos = []
    orden = [(px, py) for py in MALLA for px in MALLA]
    k = 0
    try:
        while k < len(orden):
            px, py = orden[k]
            print(f"\nPunto {k + 1}/9: {nombre_cruce(px, py)}")
            r = input("   Lleva la punta al cruce y presiona ENTER (r = repetir anterior, q = salir): ").strip().lower()
            if r == "q":
                print("Salida sin guardar.")
                return
            if r == "r" and k > 0:
                puntos.pop()
                k -= 1
                continue
            code, pose = arm.get_position(is_radian=False)
            if code != 0:
                print(f"   No pude leer la posicion (code {code}). Intenta de nuevo.")
                continue
            pose = [round(float(v), 2) for v in pose]
            print(f"   Guardado: {pose}")
            revisar_vertical(pose)
            puntos.append({"px": px, "py": py, "pose": pose})
            k += 1
    finally:
        arm.set_mode(0)
        arm.set_state(0)
        robot.desconectar()

    with open(RUTA, "w") as f:
        json.dump({"puntos": puntos, "fecha": time.strftime("%Y-%m-%d %H:%M")}, f, indent=2)
    print(f"\nCalibracion guardada en {RUTA}")
    revisar_escala(puntos)


def revisar_escala(puntos):
    """Compara las distancias medidas entre cruces con las reales del tablero."""
    p = {(d["px"], d["py"]): np.array(d["pose"][:3]) for d in puntos}
    esperado = 600 * MM_POR_PX
    print(f"\nRevision de escala (entre cruces de las orillas deberia haber {esperado:.0f} mm):")
    for nombre, a, b in (("lado de arriba", (100, 100), (700, 100)), ("lado de abajo", (100, 700), (700, 700)),
                         ("lado izquierdo", (100, 100), (100, 700)), ("lado derecho", (700, 100), (700, 700))):
        d = float(np.linalg.norm(p[a][:2] - p[b][:2]))
        marca = "ok" if abs(d - esperado) < 6 else "REVISAR (TCP, punto mal apuntado o gripper inclinado)"
        print(f"   {nombre:15s}: {d:6.1f} mm  ({d - esperado:+.1f})  {marca}")
    alturas = [d["pose"][2] for d in puntos]
    print(f"   Z: de {min(alturas):.1f} a {max(alturas):.1f} mm (el tablero puede no estar plano si varia mucho)")


def probar():
    with open(RUTA) as f:
        puntos = json.load(f)["puntos"]
    revisar_escala(puntos)
    robot = ControladorLite6(ip=config.ROBOT_IP)
    robot.conectar()
    robot.configurar_calibracion_9puntos(puntos)
    yaw = config.P1_ROB[5]
    objetivos = [(d["px"], d["py"], "cruce grabado") for d in puntos]
    for nombre in ("a1", "h1", "a8", "h8", "e4", "d5"):
        from estado_tablero import casilla_a_celda
        fila, col = casilla_a_celda(chess.parse_square(nombre))
        px, py = robot.casillero_a_pixel(fila, col, config.LADO)
        objetivos.append((px, py, f"centro de {nombre}"))
    print("\nEl robot visitara cada punto con el gripper vertical. Quita las piezas del tablero.")
    try:
        for px, py, desc in objetivos:
            r = input(f"\nSiguiente: {desc} (px {px:.0f}, py {py:.0f}). ENTER = ir, q = salir: ").strip().lower()
            if r == "q":
                break
            pose = robot.pixel_a_pose(px, py)
            pose[3:6] = [180.0, 0.0, yaw]
            print(f"   pose: {[round(v, 1) for v in pose]}")
            if not robot.visitar_pose(pose, espera=2.5):
                print("   El robot no pudo llegar a esa pose.")
        robot.ir_a_posicion_home()
    finally:
        robot.desconectar()


if __name__ == "__main__":
    probar() if "--probar" in sys.argv else grabar()