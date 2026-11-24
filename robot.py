"""
Controlador cartesiano para manipulador Lite6.
- Calibracion pixel del plano rectificado (800x800) -> pose del robot, de dos formas:
  * 3 puntos: transformacion afin para X, Y y un plano para Z, roll, pitch, yaw.
  * 9 puntos (malla 3x3, preferida): interpolacion bilineal por cuadrante; corrige errores
    del brazo que cambian segun la zona del tablero. Se graba con calibrar9.py.
- Manejo de errores por paso
Todas las poses de entrada: [x, y, z, roll, pitch, yaw] con mm y GRADOS (como en UFactory Studio).
"""

import math
import time
import cv2
import numpy as np
from xarm.wrapper import XArmAPI

ALTURA_SEGURA = 40.0        # mm sobre el punto
VEL_LINEAL = 80.0           # mm/s en set_position
VEL_ARTICULAR_DEG = 30.0    # deg/s en movimientos articulares


class ControladorLite6:
    def __init__(self, ip="172.23.254.167"):
        self.ip = ip
        self.arm = None
        self.matriz_afin = None
        self.coef = None
        self.malla = None          # calibracion de 9 puntos: (xs, ys, poses 3x3x6)
        self.calibrado = False
        # Postura de descanso (grados). Verifica en Studio que sean grados y no radianes.
        self.angulos_home = [0.0, 0.4, -0.3, 2.5, 0.0, -1.1]

    # ------------------------------------------------------------------ conexion
    def conectar(self, sensibilidad_colision=3):
        self.arm = XArmAPI(self.ip)
        self.arm.clean_warn()
        self.arm.clean_error()
        self.arm.motion_enable(True)
        self.arm.set_mode(0)
        self.arm.set_state(0)
        time.sleep(1)
        self.arm.set_collision_sensitivity(sensibilidad_colision)

    def desconectar(self):
        if self.arm:
            self.arm.set_state(4)
            self.arm.disconnect()

    def _preparar(self):
        self.arm.clean_warn()
        self.arm.clean_error()
        self.arm.motion_enable(True)
        self.arm.set_mode(0)
        self.arm.set_state(0)
        time.sleep(0.2)

    # ---------------------------------------------------------------- calibracion
    def configurar_calibracion_3puntos(self, p1_img, p1_pose, p2_img, p2_pose, p3_img, p3_pose):
        """Cada pose: [x, y, z, roll, pitch, yaw] en mm y grados."""
        pts_src = np.array([p1_img, p2_img, p3_img], dtype=np.float32)
        pts_dst = np.array([p1_pose[:2], p2_pose[:2], p3_pose[:2]], dtype=np.float32)
        self.matriz_afin = cv2.getAffineTransform(pts_src, pts_dst)

        A = np.array([[p1_img[0], p1_img[1], 1.0],
                      [p2_img[0], p2_img[1], 1.0],
                      [p3_img[0], p3_img[1], 1.0]], dtype=float)
        poses = np.array([p1_pose, p2_pose, p3_pose], dtype=float)
        poses[:, 3] %= 360.0  # roll continuo alrededor de +-180
        # valor = a*px + b*py + c
        self.coef = {nombre: np.linalg.solve(A, poses[:, i])
                     for nombre, i in (("z", 2), ("roll", 3), ("pitch", 4), ("yaw", 5))}
        self.calibrado = True

    def configurar_calibracion_9puntos(self, puntos, dz=0.0):
        """
        puntos: lista de 9 dicts {"px", "py", "pose": [x, y, z, roll, pitch, yaw]} (mm y grados)
        sobre una malla 3x3 (3 valores distintos de px y 3 de py). Ver calibrar9.py.
        dz: mm que se suman a Z. Los 9 puntos se graban YA a la altura de agarre, asi que por
        defecto es 0 (el +8 de la calibracion de 3 puntos no aplica aqui).
        """
        self.dz_malla = float(dz)
        xs = sorted({float(p["px"]) for p in puntos})
        ys = sorted({float(p["py"]) for p in puntos})
        if len(xs) != 3 or len(ys) != 3 or len(puntos) != 9:
            raise ValueError("La calibracion de 9 puntos necesita una malla 3x3")
        poses = np.zeros((3, 3, 6))
        for p in puntos:
            pose = np.array(p["pose"], float)
            pose[3] %= 360.0                       # roll continuo alrededor de +-180
            poses[ys.index(float(p["py"])), xs.index(float(p["px"]))] = pose
        self.malla = (np.array(xs), np.array(ys), poses)
        self.calibrado = True

    def _pose_malla(self, px, py):
        """Interpolacion bilineal en el cuadrante de la malla 3x3 que contiene (px, py).
        Fuera de la malla (p. ej. casillas de la orilla) extrapola con el cuadrante mas cercano."""
        xs, ys, poses = self.malla
        i = 0 if px < xs[1] else 1
        j = 0 if py < ys[1] else 1
        tx = (px - xs[i]) / (xs[i + 1] - xs[i])
        ty = (py - ys[j]) / (ys[j + 1] - ys[j])
        p = ((1 - tx) * (1 - ty) * poses[j, i] + tx * (1 - ty) * poses[j, i + 1]
             + (1 - tx) * ty * poses[j + 1, i] + tx * ty * poses[j + 1, i + 1])
        return [float(v) for v in p]

    def pixel_a_pose(self, px, py):
        """Devuelve [x, y, z, roll, pitch, yaw] (mm y grados) para un pixel del plano.
        Usa la malla de 9 puntos si esta cargada; si no, la calibracion de 3 puntos."""
        if self.malla is not None:
            x, y, z, roll, pitch, yaw = self._pose_malla(px, py)
            if roll > 180.0:
                roll -= 360.0
            return [x, y, z + self.dz_malla, roll, pitch, yaw]
        x, y = self.matriz_afin.dot(np.array([px, py, 1.0]))

        def v(k):
            a, b, c = self.coef[k]
            return float(a * px + b * py + c)

        roll = v("roll")
        if roll > 180.0:
            roll -= 360.0
        return [float(x), float(y), v("z")+8.0, roll, v("pitch"), v("yaw")]

    def casillero_a_pixel(self, fila, col, lado=800):
        tam = lado / 8.0
        return (col * tam) + tam / 2.0, (fila * tam) + tam / 2.0

    # ------------------------------------------------------------------ movimiento
    @staticmethod
    def _a_rad(pose):
        return [pose[0], pose[1], pose[2]] + [math.radians(a) for a in pose[3:6]]

    @staticmethod
    def _arriba(pose, dz=ALTURA_SEGURA):
        q = list(pose)
        q[2] += dz
        return q

    def _mover(self, pose_rad):
        """Movimiento lineal. pose_rad = [x, y, z, roll, pitch, yaw] con angulos en radianes."""
        code = self.arm.set_position(x=pose_rad[0], y=pose_rad[1], z=pose_rad[2],
                                     roll=pose_rad[3], pitch=pose_rad[4], yaw=pose_rad[5],
                                     speed=VEL_LINEAL, is_radian=True, wait=True)
        if code != 0:
            print(f"set_position fallo (code {code}) | error: {self.arm.error_code} "
                  f"| warn: {self.arm.warn_code} | pose: {[round(v, 2) for v in pose_rad]}")
        return code == 0

    def _ir_articular(self, pose_rad):
        """Va a una pose cartesiana mediante IK y movimiento articular (evita trayectorias lineales imposibles)."""
        code_ik, angulos = self.arm.get_inverse_kinematics(
            pose_rad, input_is_radian=True, return_is_radian=True)
        if code_ik != 0:
            print(f"Error cinematico (code {code_ik}): pose fuera de alcance o singular: "
                  f"{[round(v, 2) for v in pose_rad]}")
            return False
        code = self.arm.set_servo_angle(angle=angulos, speed=math.radians(VEL_ARTICULAR_DEG),
                                        is_radian=True, wait=True)
        if code != 0:
            print(f"Error de motor en movimiento articular (code {code}) | error: {self.arm.error_code}")
            return False
        return True

    def ir_a_posicion_home(self):
        if not self.arm:
            return
        self._preparar()
        self.arm.set_servo_angle(angle=self.angulos_home, speed=VEL_ARTICULAR_DEG,
                                 is_radian=False, wait=True)

    def visitar_pose(self, pose_grados, espera=2.0):
        """Para pruebas: sube a pose segura, baja al punto, espera y vuelve a subir."""
        if not self.arm:
            print("Robot no conectado.")
            return False
        self._preparar()
        p = self._a_rad(pose_grados)
        p_up = self._arriba(p)
        if not self._ir_articular(p_up):
            return False
        if not self._mover(p):
            return False
        time.sleep(espera)
        return self._mover(p_up)

    def mover_pieza(self, pose_origen, pose_destino):
        """Toma en pose_origen y suelta en pose_destino (poses en mm y grados)."""
        if not self.arm:
            print("Robot no conectado.")
            return False
        self._preparar()

        o = self._a_rad(pose_origen)
        d = self._a_rad(pose_destino)
        o_up, d_up = self._arriba(o), self._arriba(d)

        # 1. Abrir gripper y aproximacion articular sobre el origen
        self.abrir_gripper()
        if not self._ir_articular(o_up):
            return False

        # 2. Descenso al origen y agarre
        if not self._mover(o):
            return False
        self.cerrar_gripper()

        # 3. Elevacion y traslado (sin detener el gripper: se mantiene cerrado)
        for paso in (o_up, d_up, d):
            if not self._mover(paso):
                return False

        # 4. Soltar en destino y elevar
        self.abrir_gripper()
        if not self._mover(d_up):
            return False
        self.detener_gripper()

        # 5. Home
        self.ir_a_posicion_home()
        return True

    # ------------------------------------------------------------------ gripper
    def abrir_gripper(self, espera=1.0):
        self.arm.open_lite6_gripper()
        time.sleep(espera)

    def cerrar_gripper(self, espera=1.5):
        self.arm.close_lite6_gripper()
        time.sleep(espera)

    def detener_gripper(self):
        self.arm.stop_lite6_gripper()