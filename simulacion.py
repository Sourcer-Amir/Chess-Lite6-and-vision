"""
Piloto SIN equipo: simula una partida completa para ver como debe funcionar el sistema.
Uso: python3 simulacion.py [--rapido] [--mini]
     (por defecto: partida completa con las 32 piezas; --mini: rey + 2 torres contra rey)

Que es real y que es simulado
- REAL: juego.py (votacion, iniciar, reconocer la jugada humana, turno, fin de partida),
        estado_tablero.py (reglas, capturas), la ventana "Tablero 3D" y los mensajes de main.py.
- SIMULADO: la camara (ve el tablero "fisico" con ruido: a veces no identifica una pieza),
            el brazo (las piezas se mueven solas), tus jugadas (las elige un jugador automatico)
            y Stockfish si no esta instalado (lo reemplaza un motor sencillo que busca el mate).

Fases
1. Votacion: la camara ve las piezas; las que aun no se identifican salen '?' en la ventana 3D.
   Se intenta iniciar antes de tiempo para mostrar que el sistema se niega a jugar.
2. Partida: el robot (blancas) abre; el "humano" (negras) contesta; cada turno
   se reconoce comparando lo que "ve" la camara contra las jugadas legales, como en el real.
   Una vez el humano presiona ENTER sin mover, para mostrar que el robot no se mueve.
3. Fin: jaque mate o tablas, con el mensaje final.
Teclas en la ventana 3D: ESPACIO pausa/reanuda, q sale. El mouse gira la vista como siempre.
"""

import random
import sys
import time

import chess
import cv2

import config
import juego as J
from main import mostrar_jugada
from vista3d import Vista3D

POSICION = ("8/8/8/4k3/8/8/8/R3K2R w - - 0 1" if "--mini" in sys.argv   # rey + 2 torres contra rey
            else chess.STARTING_FEN)                                       # partida completa
PAUSA = 0.4 if "--rapido" in sys.argv else 1.6   # segundos entre acciones
RUIDO = {"k": 0.75, "K": 0.35, "R": 0.05}       # probabilidad de que la camara no identifique la pieza
RUIDO_OTRAS = 0.25                              # para las demas piezas
VALOR = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
MAX_JUGADAS = 160
random.seed(7)


# ---------------------------------------------------------------- piezas simuladas del sistema
class CamaraSimulada:
    K = None
    def leer(self):
        return "frame"
    def cerrar(self):
        pass


class MotorSencillo:
    """Sustituto de Stockfish para la demo (no juega bien, solo para ver el flujo):
    mate en 1 si existe; si no, la jugada que mas material gana sin dejar la pieza colgada;
    sin capturas buenas, da jaque o desarrolla piezas; evita el ahogado."""
    def mejor_jugada(self, b):
        mejor, puntaje = None, None
        for m in list(b.legal_moves):
            ganado = 0
            if b.is_capture(m):
                cap = b.piece_at(m.to_square) or chess.Piece(chess.PAWN, not b.turn)
                ganado = VALOR[cap.piece_type]
            mio = VALOR[b.piece_at(m.from_square).piece_type]
            b.push(m)
            if b.is_checkmate():
                b.pop()
                return m.uci()
            colgada = b.is_attacked_by(b.turn, m.to_square) and not b.is_attacked_by(not b.turn, m.to_square)
            p = (ganado * 10 - colgada * mio * 10 + b.is_check() * 2
                 - b.legal_moves.count() * 0.05 - b.is_stalemate() * 1000
                 + (m.promotion == chess.QUEEN) * 80 + random.random())
            b.pop()
            if puntaje is None or p > puntaje:
                mejor, puntaje = m, p
        return mejor.uci()

    def cerrar(self):
        pass


def jugada_humana(b):
    """Jugador automatico para el humano (mas debil que el robot): a veces captura, si no juega al azar."""
    jugadas = list(b.legal_moves)
    capturas = [m for m in jugadas if b.is_capture(m) and not b.is_attacked_by(not b.turn, m.to_square)]
    if capturas and random.random() < 0.7:
        return random.choice(capturas)
    if b.legal_moves.count() and all(VALOR[p.piece_type] == 0 for p in b.piece_map().values() if p.color == b.turn):
        # solo le queda el rey: busca espacio
        def libertad(m):
            b.push(m)
            n = b.legal_moves.count()
            b.pop()
            return n + random.random()
        return max(jugadas, key=libertad)
    return random.choice(jugadas)


def crear_juego(fisico):
    """Juego real con camara, robot y vision simulados a partir del tablero 'fisico'."""
    g = J.Juego.__new__(J.Juego)
    g.cam, g.robot = CamaraSimulada(), None
    try:
        from motor import Motor
        g.motor = Motor(config.STOCKFISH_RUTA, 0.2)
        print("Motor: Stockfish")
    except Exception:
        g.motor = MotorSencillo()
        print("Motor: sencillo (Stockfish no esta instalado)")
    g.board, g.i_cementerio, g.i_banco, g.ultima_vista = None, 0, {}, None
    g.votos, g.robot_blancas = J.Votacion(), True

    def vision():
        """Lo que 've' la camara: cada pieza, a veces sin identificar ('*')."""
        return {sq: ("*" if random.random() < RUIDO.get(p.symbol(), RUIDO_OTRAS) else p.symbol())
                for sq, p in fisico.piece_map().items()}

    def procesar(img, suavizar=False, votar=False):
        obs = vision()
        if votar:
            g.votos.actualizar(obs)
        return obs, {}, {}

    g._procesar = procesar
    g._observar = lambda: (vision(), {})
    return g


# ---------------------------------------------------------------- demo
def main():
    print(__doc__)
    fisico = chess.Board(POSICION)
    g = crear_juego(fisico)
    vista = Vista3D()
    estado = {"pausa": False, "salir": False, "mensaje": "Fase 1: la camara esta votando las piezas..."}

    def esperar(seg):
        """Refresca la ventana durante 'seg' segundos (respetando pausa y salida)."""
        fin = time.time() + seg
        while time.time() < fin or estado["pausa"]:
            vista.mostrar(g, estado["mensaje"])
            t = cv2.waitKey(30) & 0xFF
            if t == ord("q"):
                estado["salir"] = True
                return False
            if t == 32:
                estado["pausa"] = not estado["pausa"]
                print("Pausa" if estado["pausa"] else "Reanudado")
        return True

    def decir(txt):
        print(txt)
        estado["mensaje"] = txt

    try:
        # ---- fase 1: votacion y un intento de iniciar antes de tiempo
        for _ in range(2):
            g._procesar(None, votar=True)
        if not esperar(PAUSA):
            return
        decir("[i] Intento de iniciar demasiado pronto...")
        if not esperar(PAUSA):
            return
        r = g.iniciar()
        if "inicio" in r:          # por suerte ya estaba todo identificado
            arrancado = r
        else:
            decir(r.get("mensaje", str(r)))
            arrancado = None
            while not esperar(0.15) is False:
                g._procesar(None, votar=True)
                if all(s for s in g.votos.ocupadas().values()):
                    break
            if estado["salir"]:
                return
            decir("Todas las piezas identificadas. [i] Iniciar.")
            if not esperar(PAUSA):
                return
            arrancado = g.iniciar()

        # ---- fase 2: partida
        print("Piezas:", arrancado["inicio"]["piezas"])
        estado["mensaje"] = mostrar_jugada("Robot", arrancado)
        fisico.push_uci(arrancado["uci"])                       # el brazo mueve la pieza
        fin = arrancado.get("mensaje_fin")

        olvido_mostrado = False
        while not fin and not estado["salir"]:
            if not esperar(PAUSA):
                return
            if not olvido_mostrado and len(g.board.move_stack) >= 3:
                # una vez: el humano presiona ENTER sin haber movido
                olvido_mostrado = True
                decir("Humano presiona [ENTER] sin mover...")
                if not esperar(PAUSA * 0.6):
                    return
                estado["mensaje"] = mostrar_jugada("Tu", g.turno()["humano"])
                if not esperar(PAUSA):
                    return
            m = jugada_humana(fisico)
            fisico.push(m)                                      # el humano mueve su pieza
            decir(f"Humano movio {m.uci()} y presiona [ENTER]...")
            if not esperar(PAUSA * 0.6):
                return
            r = g.turno()
            txt = mostrar_jugada("Tu", r["humano"])
            if "robot" in r:
                txt += " | " + mostrar_jugada("Robot", r["robot"])
                if r["robot"].get("ok"):
                    fisico.push_uci(r["robot"]["uci"])          # el brazo mueve la pieza
            estado["mensaje"] = txt
            fin = r.get("mensaje_fin")
            if len(g.board.move_stack) > MAX_JUGADAS:
                fin = "Demo cortada: demasiadas jugadas."

        # ---- fase 3: fin
        print("\n" + "=" * 50 + f"\n  {fin}\n" + "=" * 50)
        estado["mensaje"] = fin
        esperar(6)
    finally:
        if g.motor:
            g.motor.cerrar()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()