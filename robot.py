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
TOL_HOME_DEG = 1.0          # diferencia maxima (grados) para considerar que el robot esta en home


class ControladorLite6:
    def __init__(self, ip="172.23.254.167"):
        self.ip = ip
        self.arm = None
        self.matriz_afin = None
        self.coef = None
        self.malla = None          # calibracion de 9 puntos: (xs, ys, poses 3x3x6)
        self.ultimo_error = None   # dict con la etapa y los codigos del ultimo fallo de movimiento
        self.log = print           # juego.py lo reemplaza por su log con hora
        self.calibrado = False
        # Postura de descanso (grados, J1..J6). Se puede cambiar con config.ANGULOS_HOME.
        # Antes estaba [0, 0.4, -0.3, 2.5, 0, -1.1] (el 2.5 en J4): esa postura choca consigo misma.
        self.angulos_home = [0.0, 0.0, 2.5, 0.0, 0.0, 0.0]

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

    def _fallo(self, etapa, code, pose_rad=None, extra=""):
        """Guarda y reporta un fallo de movimiento con los codigos del controlador."""
        err = getattr(self.arm, "error_code", None)
        warn = getattr(self.arm, "warn_code", None)
        estado = getattr(self.arm, "state", None)
        self.ultimo_error = {"etapa": etapa, "code": code, "error_code": err, "warn_code": warn, "estado": estado,
                             "pose": None if pose_rad is None else
                             [round(v, 1) for v in pose_rad[:3]] + [round(math.degrees(a), 1) for a in pose_rad[3:6]]}
        self.log(f"ROBOT FALLO en '{etapa}': code {code} | error_code {err} | warn_code {warn} | estado {estado}"
                 f"{' | ' + extra if extra else ''}")
        if self.ultimo_error["pose"]:
            self.log(f"   pose pedida [mm, grados]: {self.ultimo_error['pose']}")
        if err:
            self.log("   (error_code distinto de 0: buscar el codigo en UFactory Studio; un choque "
                     "suele aparecer como error de colision / corriente anormal)")

    def _mover(self, pose_rad, etapa="movimiento lineal"):
        """Movimiento lineal. pose_rad = [x, y, z, roll, pitch, yaw] con angulos en radianes."""
        code = self.arm.set_position(x=pose_rad[0], y=pose_rad[1], z=pose_rad[2],
                                     roll=pose_rad[3], pitch=pose_rad[4], yaw=pose_rad[5],
                                     speed=VEL_LINEAL, is_radian=True, wait=True)
        if code != 0:
            self._fallo(etapa, code, pose_rad)
        return code == 0

    def _acercar(self, pose_rad, etapa):
        """Acercamiento desde home: primero en LINEA RECTA (el home ya tiene el gripper hacia abajo, asi
        la muneca no gira); si el controlador no puede, se usa la cinematica inversa como respaldo."""
        code = self.arm.set_position(x=pose_rad[0], y=pose_rad[1], z=pose_rad[2],
                                     roll=pose_rad[3], pitch=pose_rad[4], yaw=pose_rad[5],
                                     speed=VEL_LINEAL, is_radian=True, wait=True)
        if code == 0:
            return True
        self.log(f"   acercamiento lineal no posible en '{etapa}' (code {code}); se usa cinematica inversa")
        self._preparar()
        return self._ir_articular(pose_rad, etapa)

    def _ir_articular(self, pose_rad, etapa="aproximacion articular"):
        """Va a una pose cartesiana mediante IK y movimiento articular (evita trayectorias lineales imposibles).
        Si la cinematica inversa no encuentra solucion (p. ej. cerca de una singularidad con el gripper
        vertical), prueba la misma posicion con pequenos giros de orientacion; si nada funciona, intenta un
        movimiento lineal (el controlador a veces si llega asi, como paso con d1)."""
        variantes = [(0.0, 0.0), (1.0, 0.0), (-1.0, 0.0), (0.0, 3.0), (0.0, -3.0), (2.0, 5.0), (-2.0, -5.0)]
        for dpitch, dyaw in variantes:
            p = list(pose_rad)
            p[4] += math.radians(dpitch)
            p[5] += math.radians(dyaw)
            code_ik, angulos = self.arm.get_inverse_kinematics(p, input_is_radian=True, return_is_radian=True)
            if code_ik != 0:
                continue
            if (dpitch, dyaw) != (0.0, 0.0):
                self.log(f"   IK sin solucion exacta en '{etapa}'; se usa pitch {dpitch:+.0f} y yaw {dyaw:+.0f} grados")
            actual = self.angulos_actuales()
            if actual is not None:
                giros = [math.degrees(a) - b for a, b in zip(angulos[:6], actual)]
                grande = max(abs(g) for g in giros)
                self.log(f"   giro por articulacion en '{etapa}' (grados): "
                         + ", ".join(f"J{i + 1} {g:+.0f}" for i, g in enumerate(giros))
                         + ("   <-- GIRO GRANDE" if grande > 90 else ""))
            code = self.arm.set_servo_angle(angle=angulos, speed=math.radians(VEL_ARTICULAR_DEG),
                                            is_radian=True, wait=True)
            if code != 0:
                self._fallo(etapa, code, p, "movimiento articular")
                return False
            return True
        self.log(f"   IK sin solucion en '{etapa}' ni con orientacion ajustada; se intenta movimiento lineal")
        return self._mover(pose_rad, etapa + " (lineal)")

    def angulos_actuales(self):
        """Angulos reales de las 6 articulaciones en grados (None si no se pudieron leer)."""
        code, ang = self.arm.get_servo_angle(is_radian=False)
        if code != 0 or ang is None:
            return None
        return [float(a) for a in ang[:6]]

    def en_home(self, tol=TOL_HOME_DEG):
        ang = self.angulos_actuales()
        if ang is None:
            return False
        return max(abs(a - b) for a, b in zip(ang, self.angulos_home)) <= tol

    def ir_a_posicion_home(self, intentos=2):
        """Va al home (angulos fijos) y COMPRUEBA que llego. Registra la diferencia en el log."""
        if not self.arm:
            return False
        for k in range(intentos):
            self._preparar()
            code = self.arm.set_servo_angle(angle=self.angulos_home, speed=VEL_ARTICULAR_DEG,
                                            is_radian=False, wait=True)
            ang = self.angulos_actuales()
            dif = None if ang is None else max(abs(a - b) for a, b in zip(ang, self.angulos_home))
            if code == 0 and dif is not None and dif <= TOL_HOME_DEG:
                self.log(f"Home: OK (diferencia maxima {dif:.2f} grados)")
                return True
            self.log(f"Home: NO llego (intento {k + 1}/{intentos}) | code {code} | error_code "
                     f"{getattr(self.arm, 'error_code', None)} | diferencia maxima "
                     f"{'?' if dif is None else f'{dif:.2f}'} grados | angulos {None if ang is None else [round(a, 1) for a in ang]}")
        self.ultimo_error = {"etapa": "volver a home", "code": code,
                             "error_code": getattr(self.arm, "error_code", None), "lleva_pieza": False}
        return False

    def _revisar_llegada(self, pose_rad, etapa):
        """Compara la posicion pedida con la que reporta el robot y la registra (mm)."""
        code, pos = self.arm.get_position(is_radian=True)
        if code != 0 or pos is None:
            return
        d = [float(pos[i]) - float(pose_rad[i]) for i in range(3)]
        err = math.sqrt(sum(v * v for v in d))
        self.log(f"   llegada '{etapa}': error {err:.2f} mm (dx {d[0]:+.2f}, dy {d[1]:+.2f}, dz {d[2]:+.2f})"
                 + ("   <-- REVISAR" if err > 1.0 else ""))

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
        """Toma en pose_origen y suelta en pose_destino (poses en mm y grados).
        Si falla, deja en self.ultimo_error la etapa y los codigos, y 'lleva_pieza' indica si la pieza
        podria haber quedado en el gripper."""
        if not self.arm:
            self.log("Robot no conectado.")
            return False
        self.ultimo_error = None
        self._preparar()

        # 0. Salir siempre desde home: asi el brazo llega con la misma postura con la que se calibro
        if not self.en_home():
            self.log("   el robot no estaba en home: va primero a home")
            if not self.ir_a_posicion_home():
                return False

        o = self._a_rad(pose_origen)
        d = self._a_rad(pose_destino)
        o_up, d_up = self._arriba(o), self._arriba(d)

        def falla(lleva):
            if self.ultimo_error is not None:
                self.ultimo_error["lleva_pieza"] = lleva
            return False

        # 1. Abrir gripper y aproximacion articular sobre el origen
        self.abrir_gripper()
        if not self._acercar(o_up, "ir arriba del origen"):
            return falla(False)

        # 2. Descenso al origen y agarre
        if not self._mover(o, "bajar al origen"):
            return falla(False)
        self._revisar_llegada(o, "origen")
        self.cerrar_gripper()

        # 3. Elevacion y traslado (sin detener el gripper: se mantiene cerrado)
        for paso, etapa in ((o_up, "subir con la pieza"), (d_up, "trasladar arriba del destino"),
                            (d, "bajar al destino")):
            if not self._mover(paso, etapa):
                return falla(True)
        self._revisar_llegada(d, "destino")

        # 4. Soltar en destino y elevar
        self.abrir_gripper()
        if not self._mover(d_up, "subir despues de soltar"):
            return falla(False)
        self.detener_gripper()

        # 5. Home (comprobado; si no llega, el siguiente movimiento lo vuelve a intentar al inicio)
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