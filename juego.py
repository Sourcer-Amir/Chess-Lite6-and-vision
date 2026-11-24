"""
Orquestador: une camara, vision, logica de ajedrez, motor y robot.
Todas las funciones publicas devuelven dict con tipos simples (para JSON y MATLAB).
"""

import json
import os
import time

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


SIN_ID = ("*", "W*", "B*")


class Votacion:
    """
    Identidad de cada pieza por votacion en vivo, casilla por casilla.
    - La primera figura conocida manda hasta que otra la empata o la supera.
    - Si la casilla queda vacia HUECO frames seguidos (con el marco visible), se olvida:
      la pieza se movio o la capturaron, y la siguiente que aparezca empieza de cero.
    - Las lecturas '*' (desconocida) solo confirman que la casilla esta ocupada.
    """
    HUECO = 5

    def __init__(self):
        self.reiniciar()

    def reiniciar(self):
        self.votos, self.lider, self.vacias = {}, {}, {}

    def actualizar(self, obs):
        for sq, s in obs.items():
            self.vacias[sq] = 0
            c = self.votos.setdefault(sq, {})
            self.lider.setdefault(sq, None)
            if s in SIN_ID:
                continue
            c[s] = c.get(s, 0) + 1
            if self.lider[sq] is None or c[s] > c[self.lider[sq]]:
                self.lider[sq] = s
        for sq in list(self.votos):
            if sq not in obs:
                self.vacias[sq] = self.vacias.get(sq, 0) + 1
                if self.vacias[sq] >= self.HUECO:
                    del self.votos[sq], self.lider[sq], self.vacias[sq]

    def ocupadas(self):
        """{casilla: simbolo votado o None si nunca se identifico}."""
        return dict(self.lider)


class Juego:
    def log(self, msg):
        """Mensaje con hora en la terminal y en logs/partida_<sesion>.log."""
        linea = f"[{time.strftime('%H:%M:%S')}] {msg}"
        print(linea, flush=True)
        try:
            os.makedirs("logs", exist_ok=True)
            with open(os.path.join("logs", f"partida_{self._sesion_log}.log"), "a") as f:
                f.write(linea + "\n")
        except Exception:
            pass

    def __init__(self, con_robot=True, con_motor=True):
        self._sesion_log = time.strftime("%Y%m%d_%H%M%S")
        self.pendiente = None          # jugada del robot que fallo a medias: {move, pasos, hechos}
        self.cam = Camara(config.CAM_INDICE, config.CAM_MODO, config.CAM_CONF)
        self.robot = None
        if con_robot:
            from robot import ControladorLite6
            self.robot = ControladorLite6(ip=config.ROBOT_IP)
            self.robot.log = self.log
            if hasattr(config, "ANGULOS_HOME"):
                self.robot.angulos_home = [float(a) for a in config.ANGULOS_HOME]
            self.log(f"Robot: home = {self.robot.angulos_home} grados (J1..J6)")
            self.robot.conectar()
            ruta9 = getattr(config, "CALIBRACION_9", "calibracion9.json")
            if ruta9 and os.path.exists(ruta9):
                with open(ruta9) as f:
                    self.robot.configurar_calibracion_9puntos(json.load(f)["puntos"],
                                                              dz=getattr(config, "DZ_CALIBRACION_9", 0.0))
                self.log(f"Robot: calibracion de 9 puntos ({ruta9})")
            else:
                self.robot.configurar_calibracion_3puntos(config.P1_IMG, config.P1_ROB, config.P2_IMG,
                                                          config.P2_ROB, config.P3_IMG, config.P3_ROB)
                self.log("Robot: calibracion de 3 puntos (config.py); para 9 puntos corre calibrar9.py")
        self.motor = None
        if con_motor:
            from motor import Motor
            self.motor = Motor(config.STOCKFISH_RUTA, config.STOCKFISH_TIEMPO)
        self.board = None
        self.i_cementerio = 0
        self.i_banco = {}
        self.ultima_vista = None
        self.votos = Votacion()
        self.robot_blancas = config.ROBOT_JUEGA_BLANCAS

    # ------------------------------------------------------------ vision
    def _procesar(self, img, suavizar=False, votar=False):
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
        obs = observacion_desde_matriz(matriz)
        if votar:
            self.votos.actualizar(obs)
        return obs, extra, {"M": M, "mask": mask, "plano": plano, "vista": vista}

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
    def iniciar(self, frames_si_no_hay_votos=30):
        """
        Arma la partida con la identidad votada de cada pieza y el ROBOT mueve primero.
        Se niega a jugar si alguna casilla ocupada nunca se identifico (ni una vez) o si la
        posicion no es valida. Si no hay votos (p. ej. llamado desde MATLAB, sin analisis en vivo),
        analiza primero 'frames_si_no_hay_votos' frames.
        """
        if not self.votos.ocupadas():
            for _ in range(frames_si_no_hay_votos):
                img = self.cam.leer()
                if img is not None:
                    try:
                        self._procesar(img, suavizar=True, votar=True)
                    except Exception:
                        pass
        ocupadas = self.votos.ocupadas()
        if not ocupadas:
            return {"ok": False, "error": "sin_piezas",
                    "mensaje": "No veo piezas en el tablero (o no veo el marco verde)."}
        faltan = sorted(chess.square_name(sq) for sq, s in ocupadas.items() if s is None)
        if faltan:
            self.log(f"Iniciar: casillas sin identificar {faltan}")
            return {"ok": False, "error": "piezas_sin_identificar", "casillas": faltan,
                    "mensaje": "No juego: estas casillas tienen una pieza que todavia no se ha "
                               "identificado ni una vez: " + ", ".join(faltan)}

        obs = {sq: s for sq, s in ocupadas.items()}
        board, avisos = tablero_desde_observacion(obs, blancas_mueven=self.robot_blancas)
        if avisos:
            avisos = self._explicar_status(board)
            self.log(f"Iniciar: posicion invalida ({', '.join(avisos)}) | votos {observacion_a_texto(obs)}")
            return {"ok": False, "error": "posicion_invalida", "avisos": avisos,
                    "piezas": observacion_a_texto(obs),
                    "mensaje": "No juego: " + ", ".join(avisos) + ". Lo que vote cada casilla: "
                               + str(observacion_a_texto(obs))}
        self.board = board
        self.i_cementerio, self.i_banco = 0, {}
        self.pendiente = None
        self.log(f"Partida iniciada | piezas: {observacion_a_texto(obs)} | FEN {board.fen()}")
        r = self.jugada_robot()
        r["inicio"] = {"fen": board.fen(), "piezas": observacion_a_texto(obs)}
        return r

    def iniciar_fen(self, fen):
        """Alternativa manual: arrancar desde un FEN escrito a mano."""
        self.board = chess.Board(fen)
        return {"ok": True, "fen": self.board.fen()}

    def jugada_humano(self):
        self._requiere_partida()
        obs, _ = self._observar()
        esperado = {sq: p.symbol() for sq, p in self.board.piece_map().items()}
        cambios = sorted(chess.square_name(sq) for sq in set(esperado) | set(obs)
                         if esperado.get(sq) != obs.get(sq))
        self.log(f"Humano: la camara ve {len(obs)} piezas; casillas distintas a lo esperado: {cambios or 'ninguna'}")
        m, info = inferir_jugada(self.board, obs)
        if m is None:
            self.log(f"Humano: jugada NO reconocida ({info.get('error')}) | detalle: {info}")
            return {"ok": False, "cambios": cambios, **info}
        self.log(f"Humano: jugada reconocida {m.uci()} (costo {info.get('costo')})")
        return self._aplicar(m)

    def turno(self):
        """Reconoce la jugada del humano y, si es legal y la partida sigue, el robot contesta.
        Si el robot tiene una jugada pendiente (fallo a medias), primero la reintenta."""
        if self.pendiente is not None or (self.board is not None and self.board.turn == self.robot_blancas):
            self.log("Turno: el robot tiene una jugada pendiente; se reintenta antes de leer al humano")
            r = self.jugada_robot()
            return {"humano": {"ok": False, "error": "robot_pendiente"}, "robot": r, **self.estado()}
        h = self.jugada_humano()
        if not h["ok"] or h.get("terminada"):
            return {"humano": h, **({} if not h["ok"] else self.estado())}
        r = self.jugada_robot()
        return {"humano": h, "robot": r, **self.estado()}

    def confirmar_jugada(self, uci):
        """Para cuando la vision es ambigua (p. ej. a que pieza promovio el humano)."""
        self._requiere_partida()
        m = chess.Move.from_uci(uci)
        if m not in self.board.legal_moves:
            return {"ok": False, "error": "ilegal", "uci": uci}
        return self._aplicar(m)

    def jugada_robot(self, uci=None):
        """Decide y ejecuta la jugada del robot. Si un paso falla (p. ej. choque), la jugada queda
        PENDIENTE: el siguiente llamado continua desde el paso que fallo, o se termina a mano
        con completar_a_mano(). El tablero interno solo se actualiza cuando todos los pasos salieron."""
        self._requiere_partida()
        if self.pendiente is not None:
            m, pasos, inicio = self.pendiente["move"], self.pendiente["pasos"], self.pendiente["hechos"]
            self.log(f"Robot: reintentando {m.uci()} desde el paso {inicio + 1}/{len(pasos)}")
        else:
            if self.board.is_game_over():
                return {"ok": False, "error": "partida_terminada", **self.estado()}
            if uci is None:
                if self.motor is None:
                    return {"ok": False, "error": "sin_motor"}
                uci = self.motor.mejor_jugada(self.board)
            m = chess.Move.from_uci(uci)
            if m not in self.board.legal_moves:
                self.log(f"Robot: el motor propuso una jugada ilegal {uci}")
                return {"ok": False, "error": "ilegal", "uci": uci}
            pasos, inicio = secuencia_robot(self.board, m), 0
            self.log(f"Robot: juega {m.uci()} ({tipo_jugada(self.board, m)}); pasos: "
                     + " | ".join(f"{o}->{d}" for o, d in pasos))

        if self.robot is not None:
            for i in range(inicio, len(pasos)):
                ori, des = pasos[i]
                self.log(f"Robot: paso {i + 1}/{len(pasos)}: {ori} -> {des}")
                if not self._ejecutar_paso(ori, des):
                    self.pendiente = {"move": m, "pasos": pasos, "hechos": i}
                    err = getattr(self.robot, "ultimo_error", None) or {}
                    aviso = ("la pieza puede haber quedado EN EL GRIPPER o caida cerca"
                             if err.get("lleva_pieza") else f"la pieza deberia seguir en {ori}")
                    self.log(f"Robot: la jugada {m.uci()} quedo PENDIENTE en el paso {i + 1}/{len(pasos)} "
                             f"({ori} -> {des}); {aviso}.")
                    self.log("   Opciones: ENTER = reintentar desde ese paso (antes acomoda la pieza en "
                             f"{ori} si se movio) | c = terminar la jugada a mano")
                    return {"ok": False, "error": "fallo_robot", "paso": i, "pasos": pasos, "uci": m.uci(),
                            "detalle_robot": err}
                self.log(f"Robot: paso {i + 1}/{len(pasos)} completado")
        self.pendiente = None
        r = self._aplicar(m)
        r["pasos"] = pasos
        self.log(f"Robot: jugada {m.uci()} terminada | FEN {self.board.fen()}")
        return r

    def completar_a_mano(self):
        """El humano termino a mano la jugada pendiente del robot (deja las piezas como deben quedar)."""
        if self.pendiente is None:
            return {"ok": False, "error": "sin_pendiente"}
        m = self.pendiente["move"]
        self.pendiente = None
        self.log(f"Robot: la jugada {m.uci()} se termino A MANO; se aplica al tablero interno")
        r = self._aplicar(m)
        r["a_mano"] = True
        return r

    def estado(self):
        if self.board is None:
            return {"ok": True, "iniciada": False}
        b = self.board
        r = {"ok": True, "iniciada": True, "fen": b.fen(),
             "turno": "blancas" if b.turn else "negras", "jaque": b.is_check(),
             "terminada": b.is_game_over(), "resultado": b.result() if b.is_game_over() else "*"}
        if b.is_game_over():
            r["mensaje_fin"] = self._mensaje_fin()
        return r

    @staticmethod
    def _explicar_status(board):
        """Traduce los codigos de chess.Board.status() a texto."""
        st = board.status()
        textos = [(chess.STATUS_NO_WHITE_KING, "falta el rey blanco"),
                  (chess.STATUS_NO_BLACK_KING, "falta el rey negro"),
                  (chess.STATUS_TOO_MANY_KINGS, "hay mas de un rey del mismo color"),
                  (chess.STATUS_TOO_MANY_WHITE_PIECES, "demasiadas piezas blancas"),
                  (chess.STATUS_TOO_MANY_BLACK_PIECES, "demasiadas piezas negras"),
                  (chess.STATUS_PAWNS_ON_BACKRANK, "hay peones en la primera u octava fila"),
                  (chess.STATUS_OPPOSITE_CHECK, "el rey del bando que no mueve esta en jaque"),
                  (chess.STATUS_TOO_MANY_CHECKERS, "jaque imposible"),
                  (chess.STATUS_IMPOSSIBLE_CHECK, "jaque imposible")]
        salida = [t for f, t in textos if st & f]
        return salida or [f"codigo {int(st)}"]

    def _mensaje_fin(self):
        b = self.board
        if b.is_checkmate():
            gana_robot = (not b.turn) == self.robot_blancas   # gana quien acaba de mover
            return "Jaque mate. Perdiste, gano el robot." if gana_robot else "Jaque mate. Felicidades, ganaste!"
        motivos = {chess.Termination.STALEMATE: "ahogado",
                   chess.Termination.INSUFFICIENT_MATERIAL: "material insuficiente",
                   chess.Termination.SEVENTYFIVE_MOVES: "regla de 75 jugadas",
                   chess.Termination.FIVEFOLD_REPETITION: "quintuple repeticion"}
        t = b.outcome()
        return f"Tablas por {motivos.get(t.termination, str(t.termination))}."

    def home(self):
        if self.robot:
            self.robot.ir_a_posicion_home()
        return {"ok": True}

    def cerrar(self):
        """Cierra todo aunque alguna parte falle (p. ej. Stockfish ya muerto tras Ctrl+C)."""
        for nombre, fn in (("camara", self.cam.cerrar),
                           ("motor", self.motor.cerrar if self.motor else None),
                           ("robot", self.robot.desconectar if self.robot else None)):
            if fn is None:
                continue
            try:
                fn()
            except Exception as e:
                print(f"Aviso al cerrar {nombre}: {e}")

    # ------------------------------------------------------------ internos
    def _requiere_partida(self):
        if self.board is None:
            raise RuntimeError("Primero llama a iniciar()")

    def _aplicar(self, m):
        tipo = tipo_jugada(self.board, m)
        self.board.push(m)
        if self.board.is_game_over():
            self.log(f"Fin de partida: {self._mensaje_fin()}")
        return {"ok": True, "uci": m.uci(), "tipo": tipo, **self.estado()}

    def _pose(self, lugar, simbolo):
        """Pose [mm, grados] de una casilla, del cementerio o del banco, con el ajuste de Z de la pieza."""
        if lugar == CEMENTERIO:
            if not config.CEMENTERIO_POSES:
                raise RuntimeError("CEMENTERIO_POSES esta vacio en config.py")
            # si hay menos lugares que capturas, se reutiliza el ultimo (p. ej. una sola caja)
            pose = list(config.CEMENTERIO_POSES[min(self.i_cementerio, len(config.CEMENTERIO_POSES) - 1)])
        elif lugar.startswith("BANCO:"):
            s = lugar.split(":")[1]
            pose = list(config.BANCO_POSES[s][self.i_banco.get(s, 0)])
        else:
            fila, col = casilla_a_celda(chess.parse_square(lugar))
            px, py = self.robot.casillero_a_pixel(fila, col, config.LADO)
            pose = self.robot.pixel_a_pose(px, py)
        pose[2] += config.DZ_POR_PIEZA.get(simbolo.lower(), 0.0)
        # Gripper siempre perpendicular al tablero (a 90 grados) para tomar y sobre todo para dejar:
        # inclinado, la pieza cae corrida. Se puede fijar en config.ORIENTACION_AGARRE = [roll, pitch, yaw];
        # por defecto roll 180, pitch 0 y el yaw de P1. ORIENTACION_AGARRE = False usa la interpolada.
        ori = getattr(config, "ORIENTACION_AGARRE", None)
        if ori is None:
            ori = [180.0, 0.0, config.P1_ROB[5]]
        if ori is not False:
            pose[3:6] = [float(a) for a in ori]
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