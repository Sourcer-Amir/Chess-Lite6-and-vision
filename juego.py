"""
Orquestador: une camara, vision, logica de ajedrez, motor y robot.
Todas las funciones publicas devuelven dict con tipos simples (para JSON y MATLAB).
"""

import chess
import cv2
import numpy as np

import config
from camara import Camara
from geometria import esquinas_desde_homografia, pose_camara, homografia_a_altura, centro_camara
from vision import obtener_homografia_por_color, analizar_formas_tablero, dibujar_tablero
from estado_tablero import (CEMENTERIO, observacion_desde_matriz, observacion_a_texto,
                            tablero_desde_observacion, inferir_jugada, secuencia_robot,
                            tipo_jugada, casilla_a_celda)


class Juego:
    def __init__(self, con_robot=True, con_motor=True):
        self.cam = Camara(config.CAM_INDICE, config.CAM_MODO, config.CAM_CONF)
        self.robot = None
        if con_robot:
            from robot import ControladorLite6
            self.robot = ControladorLite6(ip=config.ROBOT_IP)
            self.robot.conectar()
            self.robot.configurar_calibracion_3puntos(config.P1_IMG, config.P1_ROB, config.P2_IMG,
                                                      config.P2_ROB, config.P3_IMG, config.P3_ROB)
        self.motor = None
        if con_motor:
            from motor import Motor
            self.motor = Motor(config.STOCKFISH_RUTA, config.STOCKFISH_TIEMPO)
        self.board = None
        self.i_cementerio = 0
        self.i_banco = {}
        self.ultima_vista = None

    # ------------------------------------------------------------ vision
    def _procesar(self, img, suavizar=False):
        """
        Procesa UN frame (sirve para tiempo real y para la lectura estable).
        Devuelve (obs | None, extra, imgs). imgs: M, mask y, si hay marco, plano y vista.
        """
        M, mask = obtener_homografia_por_color(img, config.LADO)
        if M is None:
            return None, {}, {"M": None, "mask": mask}
        if suavizar:
            M = self._suavizar(M)

        plano = cv2.warpPerspective(img, M, (config.LADO, config.LADO))
        extra = {}
        if self.cam.K is not None and config.LADO_MARCO_MM and config.ALTURA_CARA_MM:
            R, t = pose_camara(esquinas_desde_homografia(M, config.LADO), config.LADO_MARCO_MM, self.cam.K)
            Mh = homografia_a_altura(R, t, self.cam.K, config.LADO_MARCO_MM, config.ALTURA_CARA_MM, config.LADO)
            plano = cv2.warpPerspective(img, Mh, (config.LADO, config.LADO))
            nadir, altura = centro_camara(R, t, config.LADO_MARCO_MM, config.LADO)
            extra = {"altura_camara_mm": round(altura, 1), "nadir_px": [round(v) for v in nadir]}

        vis, matriz = analizar_formas_tablero(plano)
        vista = dibujar_tablero(vis, matriz)
        return observacion_desde_matriz(matriz), extra, {"M": M, "mask": mask, "plano": plano, "vista": vista}

    def _suavizar(self, M):
        """Promedio exponencial de las esquinas; si saltan mucho (movimiento real), se reinicia."""
        esq = esquinas_desde_homografia(M, config.LADO)
        prev = getattr(self, "_esq_prev", None)
        if prev is not None and np.abs(esq - prev).max() < 40:
            a = config.SUAVIZADO_EN_VIVO
            esq = (1 - a) * prev + a * esq
        self._esq_prev = esq
        dst = np.float32([[0, 0], [config.LADO - 1, 0], [config.LADO - 1, config.LADO - 1], [0, config.LADO - 1]])
        return cv2.getPerspectiveTransform(np.float32(esq), dst)

    def _observar(self):
        img = self.cam.leer_estable(config.CAM_FRAMES_MEDIANA)
        if img is None:
            raise RuntimeError("La camara no entrego imagen")
        obs, extra, imgs = self._procesar(img)
        if obs is None:
            raise RuntimeError("No se encontro el marco verde")
        self.ultima_vista = imgs["vista"]
        cv2.imwrite(config.IMAGEN_DEBUG, self.ultima_vista)
        return obs, extra

    def leer_tablero(self):
        obs, extra = self._observar()
        return {"ok": True, "piezas": observacion_a_texto(obs), **extra}

    # ------------------------------------------------------------ partida
    def iniciar(self, blancas_mueven=True, enroques="auto", al_paso="-"):
        obs, _ = self._observar()
        self.board, avisos = tablero_desde_observacion(obs, blancas_mueven, enroques, al_paso)
        self.i_cementerio, self.i_banco = 0, {}
        return {"ok": True, "fen": self.board.fen(), "avisos": avisos}

    def iniciar_fen(self, fen):
        """Alternativa manual: arrancar desde un FEN escrito a mano."""
        self.board = chess.Board(fen)
        return {"ok": True, "fen": self.board.fen()}

    def jugada_humano(self):
        self._requiere_partida()
        obs, _ = self._observar()
        m, info = inferir_jugada(self.board, obs)
        if m is None:
            return {"ok": False, **info}
        return self._aplicar(m)

    def confirmar_jugada(self, uci):
        """Para cuando la vision es ambigua (p. ej. a que pieza promovio el humano)."""
        self._requiere_partida()
        m = chess.Move.from_uci(uci)
        if m not in self.board.legal_moves:
            return {"ok": False, "error": "ilegal", "uci": uci}
        return self._aplicar(m)

    def jugada_robot(self, uci=None):
        self._requiere_partida()
        if self.board.is_game_over():
            return {"ok": False, "error": "partida_terminada", **self.estado()}
        if uci is None:
            if self.motor is None:
                return {"ok": False, "error": "sin_motor"}
            uci = self.motor.mejor_jugada(self.board)
        m = chess.Move.from_uci(uci)
        if m not in self.board.legal_moves:
            return {"ok": False, "error": "ilegal", "uci": uci}

        pasos = secuencia_robot(self.board, m)
        if self.robot is not None:
            for i, (ori, des) in enumerate(pasos):
                if not self._ejecutar_paso(ori, des):
                    return {"ok": False, "error": "fallo_robot", "paso": i, "pasos": pasos}
        r = self._aplicar(m)
        r["pasos"] = pasos
        return r

    def estado(self):
        if self.board is None:
            return {"ok": True, "iniciada": False}
        b = self.board
        return {"ok": True, "iniciada": True, "fen": b.fen(),
                "turno": "blancas" if b.turn else "negras", "jaque": b.is_check(),
                "terminada": b.is_game_over(), "resultado": b.result() if b.is_game_over() else "*"}

    def home(self):
        if self.robot:
            self.robot.ir_a_posicion_home()
        return {"ok": True}

    def cerrar(self):
        self.cam.cerrar()
        if self.motor:
            self.motor.cerrar()
        if self.robot:
            self.robot.desconectar()

    # ------------------------------------------------------------ internos
    def _requiere_partida(self):
        if self.board is None:
            raise RuntimeError("Primero llama a iniciar()")

    def _aplicar(self, m):
        tipo = tipo_jugada(self.board, m)
        self.board.push(m)
        return {"ok": True, "uci": m.uci(), "tipo": tipo, **self.estado()}

    def _pose(self, lugar, simbolo):
        """Pose [mm, grados] de una casilla, del cementerio o del banco, con el ajuste de Z de la pieza."""
        if lugar == CEMENTERIO:
            pose = list(config.CEMENTERIO_POSES[self.i_cementerio])
        elif lugar.startswith("BANCO:"):
            s = lugar.split(":")[1]
            pose = list(config.BANCO_POSES[s][self.i_banco.get(s, 0)])
        else:
            fila, col = casilla_a_celda(chess.parse_square(lugar))
            px, py = self.robot.casillero_a_pixel(fila, col, config.LADO)
            pose = self.robot.pixel_a_pose(px, py)
        pose[2] += config.DZ_POR_PIEZA.get(simbolo.lower(), 0.0)
        return pose

    def _ejecutar_paso(self, ori, des):
        if ori.startswith("BANCO:"):
            simbolo = ori.split(":")[1]
        else:
            simbolo = self.board.piece_at(chess.parse_square(ori)).symbol()
        ok = self.robot.mover_pieza(self._pose(ori, simbolo), self._pose(des, simbolo))
        if ok and des == CEMENTERIO:
            self.i_cementerio += 1
        if ok and ori.startswith("BANCO:"):
            self.i_banco[simbolo] = self.i_banco.get(simbolo, 0) + 1
        return ok