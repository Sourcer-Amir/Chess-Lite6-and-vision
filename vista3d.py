"""
Ventana "Tablero 3D": representacion del estado del juego con piezas en 3D (solo OpenCV).
- Antes de iniciar muestra lo que se va votando en cada casilla ('?' = ocupada, aun sin identificar).
- Con la partida iniciada muestra el tablero del motor de ajedrez (python-chess), la ultima
  jugada (amarillo) y el rey en jaque (rojo).
- Interactiva: arrastrar con el mouse gira la vista; doble clic la regresa a la inicial.
Cada pieza se dibuja como la pieza fisica: base delgada + prisma, con la forma de FORMA.
"""

import math

import chess
import cv2
import numpy as np

import config

# Forma vista desde arriba por simbolo (lados del poligono; 0 = circulo). Mismo mapeo que vision.py:
# cuadrado = Rey Blanco, pentagono = Rey Negro, circulo = Torre. El resto, para piezas futuras.
FORMA = {"K": 4, "k": 5, "R": 0, "r": 0, "Q": 6, "q": 6, "B": 3, "b": 3, "N": 8, "n": 8, "P": 0, "p": 0, "?": 0}

# Medidas en unidades de casilla (1 = lado de una casilla, 30 mm en el tablero real)
R_BASE, H_BASE = 0.40, 0.17      # base: ~24 mm de ancho, 5 mm de alto
R_PRISMA, H_PRISMA = 0.20, 0.50  # prisma de agarre
COLOR = {True: (215, 235, 245), False: (60, 60, 66), None: (150, 150, 150)}   # blancas, negras, '?'
CASILLA = {True: (225, 238, 240), False: (70, 95, 120)}                       # clara, oscura (BGR)
LUZ = np.array([0.4, -0.5, 0.77])


class Vista3D:
    def __init__(self, tam=640, ventana="Tablero 3D"):
        self.tam = tam
        self.ventana = ventana
        self.az0 = 0.0 if not config.ROBOT_JUEGA_BLANCAS else math.pi   # mirar desde el lado del humano
        self.el0 = math.radians(42)
        self.az, self.el = self.az0, self.el0
        self._arrastre = None
        cv2.namedWindow(ventana, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(ventana, self._mouse)

    # ------------------------------------------------------------ interaccion
    def _mouse(self, evento, x, y, flags, _):
        if evento == cv2.EVENT_LBUTTONDOWN:
            self._arrastre = (x, y)
        elif evento == cv2.EVENT_MOUSEMOVE and self._arrastre and flags & cv2.EVENT_FLAG_LBUTTON:
            dx, dy = x - self._arrastre[0], y - self._arrastre[1]
            self.az += dx * 0.01
            self.el = min(max(self.el + dy * 0.01, math.radians(10)), math.radians(90))
            self._arrastre = (x, y)
        elif evento == cv2.EVENT_LBUTTONUP:
            self._arrastre = None
        elif evento == cv2.EVENT_LBUTTONDBLCLK:
            self.az, self.el = self.az0, self.el0

    # ------------------------------------------------------------ proyeccion
    def _proy(self, P):
        """P: (N,3) en coordenadas del tablero (x = columna, y = rango, z arriba). -> (uv int, profundidad)."""
        P = np.asarray(P, float) - (4.0, 4.0, 0.0)
        c, s = math.cos(self.az), math.sin(self.az)
        X = P[:, 0] * c - P[:, 1] * s
        Y = P[:, 0] * s + P[:, 1] * c
        Z = P[:, 2]
        u = X
        v = -(Y * math.sin(self.el) + Z * math.cos(self.el))
        prof = Y * math.cos(self.el) - Z * math.sin(self.el)
        esc = self.tam / 12.5
        uv = np.stack([u * esc + self.tam / 2, v * esc + self.tam / 2 + 20], axis=1)
        return uv.astype(np.int32), prof

    def _normal_vista(self, n):
        """Intensidad de una cara segun su normal (en coordenadas del tablero)."""
        return 0.55 + 0.45 * max(0.0, float(np.dot(n, LUZ) / np.linalg.norm(LUZ)))

    @staticmethod
    def _tono(color, k):
        return tuple(int(min(255, ch * k)) for ch in color)

    # ------------------------------------------------------------ dibujo
    def _contorno(self, cx, cy, r, lados, n_circ=28):
        if lados == 0:
            ang = np.linspace(0, 2 * np.pi, n_circ, endpoint=False)
        else:
            ang = np.linspace(0, 2 * np.pi, lados, endpoint=False) - np.pi / 2
        return np.stack([cx + r * np.cos(ang), cy + r * np.sin(ang)], axis=1)

    def _prisma(self, img, base2d, z0, z1, color):
        n = len(base2d)
        abajo = np.column_stack([base2d, np.full(n, z0)])
        arriba = np.column_stack([base2d, np.full(n, z1)])
        caras = []
        for i in range(n):
            j = (i + 1) % n
            quad = np.array([abajo[i], abajo[j], arriba[j], arriba[i]])
            uv, prof = self._proy(quad)
            d = base2d[j] - base2d[i]
            normal = np.array([d[1], -d[0], 0.0])
            caras.append((prof.mean(), uv, self._normal_vista(normal)))
        for _, uv, k in sorted(caras, key=lambda c: -c[0]):
            cv2.fillConvexPoly(img, uv, self._tono(color, k), cv2.LINE_AA)
        uv, _ = self._proy(arriba)
        cv2.fillPoly(img, [uv], self._tono(color, self._normal_vista(np.array([0, 0, 1.0])) + 0.1), cv2.LINE_AA)
        cv2.polylines(img, [uv], True, self._tono(color, 0.45), 1, cv2.LINE_AA)

    def _pieza(self, img, sq, simbolo):
        cx, cy = chess.square_file(sq) + 0.5, chess.square_rank(sq) + 0.5
        lados = FORMA.get(simbolo, 0)
        color = COLOR[None] if simbolo == "?" else COLOR[simbolo.isupper()]
        r_base = R_BASE * (1.12 if lados == 4 else 1.0)
        self._prisma(img, self._contorno(cx, cy, r_base, lados), 0.0, H_BASE, color)
        self._prisma(img, self._contorno(cx, cy, R_PRISMA, lados), H_BASE, H_BASE + H_PRISMA, color)
        uv, _ = self._proy([[cx, cy, H_BASE + H_PRISMA + 0.35]])
        txt = "?" if simbolo == "?" else simbolo
        cv2.putText(img, txt, (int(uv[0][0]) - 7, int(uv[0][1]) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, txt, (int(uv[0][0]) - 7, int(uv[0][1]) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1, cv2.LINE_AA)

    def render(self, juego, mensaje=""):
        img = np.full((self.tam, self.tam, 3), 32, np.uint8)
        b = juego.board
        if b is not None:
            piezas = {sq: p.symbol() for sq, p in b.piece_map().items()}
            ult = b.peek() if b.move_stack else None
            resaltes = {ult.from_square: (0, 200, 230), ult.to_square: (0, 220, 255)} if ult else {}
            if b.is_check():
                resaltes[b.king(b.turn)] = (40, 40, 230)
        else:
            piezas = {sq: (s or "?") for sq, s in juego.votos.ocupadas().items()}
            resaltes = {}

        # marco verde (como el fisico) y casillas
        marco, _ = self._proy([[-0.35, -0.35, 0], [8.35, -0.35, 0], [8.35, 8.35, 0], [-0.35, 8.35, 0]])
        cv2.fillConvexPoly(img, marco, (70, 140, 40), cv2.LINE_AA)
        for sq in chess.SQUARES:
            f, r = chess.square_file(sq), chess.square_rank(sq)
            uv, _ = self._proy([[f, r, 0], [f + 1, r, 0], [f + 1, r + 1, 0], [f, r + 1, 0]])
            color = resaltes.get(sq, CASILLA[(f + r) % 2 == 1])
            cv2.fillConvexPoly(img, uv, color, cv2.LINE_AA)
        for i in range(8):
            for txt, p in ((chr(97 + i), [i + 0.5, -0.2, 0]), (str(i + 1), [-0.2, i + 0.5, 0])):
                uv, _ = self._proy([p])
                cv2.putText(img, txt, (int(uv[0][0]) - 5, int(uv[0][1]) + 5), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (255, 255, 255), 1, cv2.LINE_AA)

        # piezas, de la mas lejana a la mas cercana
        orden = []
        for sq, s in piezas.items():
            _, prof = self._proy([[chess.square_file(sq) + 0.5, chess.square_rank(sq) + 0.5, 0]])
            orden.append((prof[0], sq, s))
        for _, sq, s in sorted(orden, key=lambda t: -t[0]):
            self._pieza(img, sq, s)

        # textos
        if b is None:
            linea1 = "Sin iniciar: piezas votadas ('?' = sin identificar). Presiona i"
        else:
            robot = b.turn == config.ROBOT_JUEGA_BLANCAS
            linea1 = ("Turno del ROBOT" if robot else "TU turno: mueve y presiona ENTER") + \
                     (f" | ultima: {b.peek().uci()}" if b.move_stack else "") + (" | JAQUE" if b.is_check() else "")
        cv2.putText(img, linea1, (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        if mensaje:
            cv2.putText(img, mensaje[:80], (10, self.tam - 32), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 255), 1,
                        cv2.LINE_AA)
        cv2.putText(img, "Arrastra para girar | doble clic: vista inicial", (10, self.tam - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1, cv2.LINE_AA)
        return img

    def mostrar(self, juego, mensaje=""):
        cv2.imshow(self.ventana, self.render(juego, mensaje))