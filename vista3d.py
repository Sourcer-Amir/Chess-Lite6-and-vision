"""
Ventana "Tablero 3D": el estado del juego en 3D con perspectiva y piezas de ajedrez reales
(estilo Staunton), dibujadas solo con OpenCV + NumPy.

Que muestra
- Antes de iniciar: lo que va votando cada casilla ('?' gris = ocupada pero aun sin identificar).
- Con la partida iniciada: el tablero del motor de ajedrez, flecha y casillas de la ultima jugada,
  rey en jaque en rojo, piezas capturadas por cada bando, turno y ultimo mensaje.
- El tablero imita al real: casillas blancas y negras, marco verde y grosor.
- Las piezas se dibujan como piezas de ajedrez normales (no como las fisicas del robot), para que
  se lea la partida de un vistazo sin importar con que formas y colores se impriman.

Controles (sobre la ventana)
- Arrastrar con el boton izquierdo: girar e inclinar.   - Rueda: acercar / alejar.
- Doble clic: volver a la vista inicial (desde el lado del humano).

Detalles de dibujo
- Camara en orbita alrededor del centro del tablero, proyeccion en perspectiva.
- Piezas = superficies de revolucion (perfil r-z girado) + cajas (almenas, cruz) + extrusion (caballo).
- Algoritmo del pintor con eliminacion de caras traseras; sombreado Lambert + luz ambiente.
- Se dibuja al doble de resolucion y se reduce (antialiasing). Solo se vuelve a dibujar si algo cambio.
"""

import math

import chess
import cv2
import numpy as np

import config

NOMBRE = {"k": "rey", "q": "reina", "r": "torre", "b": "alfil", "n": "caballo", "p": "peon"}
MARCO, GROSOR = 0.45, 0.22          # ancho del marco verde y grosor del tablero (unidades de casilla)
SEG = 18                            # segmentos alrededor de cada pieza

# Colores BGR
C_CLARA, C_OSCURA = (236, 240, 242), (52, 52, 58)
C_MARCO, C_CANTO = (64, 135, 42), (40, 85, 28)
C_PIEZA = {True: (200, 226, 244), False: (58, 52, 50), None: (150, 150, 150)}   # blancas, negras, '?'
C_ULTIMA, C_JAQUE, C_FLECHA = (40, 200, 240), (50, 50, 230), (0, 170, 255)
FONDO_ARRIBA, FONDO_ABAJO = (58, 48, 40), (24, 22, 20)
LUZ = np.array([-0.45, -0.35, 0.82])
LUZ = LUZ / np.linalg.norm(LUZ)
SS = 2                              # factor de antialiasing


# ================================================================ modelos de piezas (unidades de casilla)
def _esfera(zc, r, n=6, desde=-90, hasta=90):
    return [(r * math.cos(math.radians(a)), zc + r * math.sin(math.radians(a)))
            for a in np.linspace(desde, hasta, n)]


def _base(r=0.31):
    return [(0, 0), (r, 0), (r, 0.05), (r - 0.04, 0.08), (r - 0.03, 0.11), (r - 0.08, 0.14)]


PERFILES = {
    "p": _base(0.28) + [(0.12, 0.20), (0.09, 0.30), (0.15, 0.32), (0.15, 0.34), (0.08, 0.36)]
         + _esfera(0.45, 0.11, 6, -60, 90),
    "r": _base(0.31) + [(0.18, 0.20), (0.17, 0.48), (0.22, 0.52), (0.22, 0.62), (0.15, 0.62), (0.15, 0.58), (0, 0.58)],
    "b": _base(0.30) + [(0.12, 0.24), (0.09, 0.42), (0.16, 0.44), (0.16, 0.46), (0.10, 0.48)]
         + [(0.14 * math.cos(math.radians(a)), 0.62 + 0.17 * math.sin(math.radians(a)))
            for a in np.linspace(-60, 75, 6)] + _esfera(0.84, 0.04, 4, -30, 90),
    "q": _base(0.32) + [(0.13, 0.24), (0.09, 0.56), (0.17, 0.58), (0.17, 0.60), (0.11, 0.63),
                        (0.20, 0.80), (0.14, 0.82), (0.10, 0.84)] + _esfera(0.90, 0.06, 5, -40, 90),
    "k": _base(0.33) + [(0.14, 0.26), (0.10, 0.62), (0.18, 0.64), (0.18, 0.66), (0.12, 0.69),
                        (0.19, 0.86), (0.12, 0.92), (0, 0.94)],
    "n": _base(0.31) + [(0.20, 0.20), (0, 0.20)],
    "?": [(0, 0), (0.26, 0), (0.26, 0.40), (0, 0.40)],
}
# Cabeza del caballo: perfil lateral (adelante, altura); se extruye a lo ancho
CABEZA_N = [(-0.17, 0.20), (0.14, 0.20), (0.10, 0.34), (0.20, 0.46), (0.25, 0.56), (0.21, 0.62),
            (0.10, 0.60), (0.05, 0.70), (-0.02, 0.76), (-0.10, 0.72), (-0.16, 0.58), (-0.19, 0.38)]


class Vista3D:
    def __init__(self, tam=680, ventana="Tablero 3D"):
        self.tam = tam
        self.ventana = ventana
        self.az0 = math.pi if config.ROBOT_JUEGA_BLANCAS else 0.0   # vista inicial desde el lado del humano
        self.el0 = math.radians(48)
        self.dist0 = 14.0
        self.az, self.el, self.dist = self.az0, self.el0, self.dist0
        self._arrastre = None
        self._fondo = self._degradado()
        self._clave, self._ultima_img = None, None
        cv2.namedWindow(ventana, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(ventana, self._mouse)

    # ============================================================ interaccion
    def _mouse(self, evento, x, y, flags, _):
        if evento == cv2.EVENT_LBUTTONDOWN:
            self._arrastre = (x, y)
        elif evento == cv2.EVENT_MOUSEMOVE and self._arrastre and flags & cv2.EVENT_FLAG_LBUTTON:
            dx, dy = x - self._arrastre[0], y - self._arrastre[1]
            self.az -= dx * 0.008
            self.el = min(max(self.el + dy * 0.008, math.radians(12)), math.radians(89))
            self._arrastre = (x, y)
        elif evento == cv2.EVENT_LBUTTONUP:
            self._arrastre = None
        elif evento == cv2.EVENT_MOUSEWHEEL:
            self.dist = min(max(self.dist * (0.9 if flags > 0 else 1.1), 8.0), 30.0)
        elif evento == cv2.EVENT_LBUTTONDBLCLK:
            self.az, self.el, self.dist = self.az0, self.el0, self.dist0

    # ============================================================ camara
    def _camara(self):
        centro = np.array([4.0, 4.0, 0.0])
        cam = centro + self.dist * np.array([math.cos(self.el) * math.sin(self.az),
                                             -math.cos(self.el) * math.cos(self.az), math.sin(self.el)])
        adelante = (centro - cam) / np.linalg.norm(centro - cam)
        derecha = np.cross(adelante, [0, 0, 1.0])
        derecha /= np.linalg.norm(derecha)
        self._cam, self._R = cam, np.stack([derecha, np.cross(derecha, adelante), adelante])
        self._f = self.tam * SS * 1.08

    def _proy(self, P):
        """P (...,3) en coordenadas del tablero (x = columna, y = rango, z arriba) -> (uv int32, z_cam)."""
        P = np.asarray(P, float)
        d = (P - self._cam) @ self._R.T
        z = np.maximum(d[..., 2], 1e-3)
        c = self.tam * SS / 2
        uv = np.stack([c + self._f * d[..., 0] / z, c * 1.06 - self._f * d[..., 1] / z], axis=-1)
        return np.round(uv).astype(np.int32), z

    @staticmethod
    def _tono(color, k):
        return tuple(int(min(255, ch * k)) for ch in color)

    # ============================================================ mallas
    @staticmethod
    def _revolucion(cx, cy, perfil, n=SEG):
        """Quads (M,4,3) de la superficie que genera 'perfil' [(r, z)...] al girar alrededor de (cx, cy)."""
        p = np.array(perfil, float)
        ang = np.linspace(0, 2 * np.pi, n, endpoint=False)
        c, s = np.cos(ang), np.sin(ang)
        X = cx + p[:, 0:1] * c
        Y = cy + p[:, 0:1] * s
        Z = np.repeat(p[:, 1:2], n, axis=1)
        V = np.stack([X, Y, Z], axis=-1)                      # (perfil, angulo, 3)
        k1 = np.roll(np.arange(n), -1)
        q = np.stack([V[:-1, :], V[:-1, k1], V[1:, k1], V[1:, :]], axis=2)   # (P-1, n, 4, 3)
        return q.reshape(-1, 4, 3)

    @staticmethod
    def _caja(x0, x1, y0, y1, z0, z1):
        v = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                      [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], float)
        caras = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
        return v[np.array(caras)]

    @staticmethod
    def _extrusion(cx, cy, perfil, ancho, adelante):
        """Perfil lateral [(a, z)] extruido a lo ancho; 'adelante' = +1 mira hacia +y, -1 hacia -y.
        Devuelve (quads de los costados (M,4,3), [poligono izquierdo, poligono derecho])."""
        p = np.array(perfil, float)
        if np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]) < 0:
            p = p[::-1]
        y = cy + adelante * p[:, 0]
        izq = np.column_stack([np.full(len(p), cx - ancho / 2), y, p[:, 1]])
        der = np.column_stack([np.full(len(p), cx + ancho / 2), y, p[:, 1]])
        j = np.roll(np.arange(len(p)), -1)
        quads = np.stack([izq, izq[j], der[j], der], axis=1)
        return quads, [izq, der]

    def _malla_pieza(self, sq, s):
        """(quads, poligonos sueltos, centro) de la pieza con simbolo s en la casilla sq."""
        cx, cy = chess.square_file(sq) + 0.5, chess.square_rank(sq) + 0.5
        t = s.lower() if s != "?" else "?"
        quads = [self._revolucion(cx, cy, PERFILES[t])]
        sueltos = []
        if t == "r":                                            # almenas
            for a in np.linspace(0, 2 * np.pi, 6, endpoint=False):
                x, y = cx + 0.185 * math.cos(a), cy + 0.185 * math.sin(a)
                quads.append(self._caja(x - 0.045, x + 0.045, y - 0.045, y + 0.045, 0.62, 0.70))
        elif t == "k":                                          # cruz
            quads.append(self._caja(cx - 0.03, cx + 0.03, cy - 0.03, cy + 0.03, 0.94, 1.14))
            quads.append(self._caja(cx - 0.09, cx + 0.09, cy - 0.03, cy + 0.03, 1.04, 1.09))
        elif t == "n":                                          # cabeza, mirando al rival
            q, polys = self._extrusion(cx, cy, CABEZA_N, 0.20, 1 if s.isupper() else -1)
            quads.append(q)
            sueltos += polys
        return np.concatenate(quads), sueltos, np.array([cx, cy, 0.4])

    def _caras_pieza(self, sq, s, color):
        """Caras visibles ya sombreadas, de atras hacia adelante: [(uv, color)]."""
        quads, sueltos, centro = self._malla_pieza(sq, s)
        n = np.cross(quads[:, 2] - quads[:, 0], quads[:, 3] - quads[:, 1])
        largo = np.linalg.norm(n, axis=1)
        ok = largo > 1e-9
        quads, n = quads[ok], n[ok] / largo[ok, None]
        cent = quads.mean(axis=1)
        # caras orientadas hacia afuera del eje de la pieza cuando son laterales (cajas y extrusiones)
        radial = cent - np.array([centro[0], centro[1], 0.0]) * [1, 1, 0] - [0, 0, 0]
        radial[:, 2] = 0
        visibles = np.einsum("ij,ij->i", n, self._cam - cent) > 0
        quads, n, cent = quads[visibles], n[visibles], cent[visibles]
        uv, z = self._proy(quads)
        prof = z.mean(axis=1)
        luz = np.clip(n @ LUZ, 0, 1)
        caras = [(prof[i], uv[i], self._tono(color, 0.42 + 0.58 * luz[i])) for i in range(len(quads))]
        for poly in sueltos:                                    # costados del caballo (no convexos)
            normal = np.cross(poly[1] - poly[0], poly[2] - poly[0])
            normal /= (np.linalg.norm(normal) + 1e-9)
            if np.dot(normal, self._cam - poly.mean(axis=0)) < 0:
                normal = -normal
            uvp, zp = self._proy(poly)
            caras.append((zp.mean(), uvp, self._tono(color, 0.42 + 0.58 * max(0.0, float(normal @ LUZ)))))
        caras.sort(key=lambda c: -c[0])
        return caras

    # ============================================================ escena
    def _degradado(self):
        h = self.tam * SS
        t = np.linspace(0, 1, h)[:, None, None]
        col = (np.array(FONDO_ARRIBA, float) * (1 - t) + np.array(FONDO_ABAJO, float) * t).astype(np.uint8)
        return np.repeat(col, h, axis=1)

    def _tablero(self, img, resaltes):
        m, g = MARCO, GROSOR
        bloque = self._caja(-m, 8 + m, -m, 8 + m, -g, 0.0)
        n = np.cross(bloque[:, 2] - bloque[:, 0], bloque[:, 3] - bloque[:, 1])
        cent = bloque.mean(axis=1)
        for i in np.argsort(-np.linalg.norm(cent - self._cam, axis=1)):
            if np.dot(n[i], self._cam - cent[i]) <= 0 or n[i][2] > 0.5:
                continue
            uv, _ = self._proy(bloque[i])
            k = 0.42 + 0.58 * max(0.0, float(n[i] @ LUZ / np.linalg.norm(n[i])))
            cv2.fillConvexPoly(img, uv, self._tono(C_CANTO, k), cv2.LINE_AA)
        uv, _ = self._proy([[-m, -m, 0], [8 + m, -m, 0], [8 + m, 8 + m, 0], [-m, 8 + m, 0]])
        cv2.fillConvexPoly(img, uv, self._tono(C_MARCO, 0.42 + 0.58 * LUZ[2] + 0.05), cv2.LINE_AA)
        for sq in chess.SQUARES:
            f, r = chess.square_file(sq), chess.square_rank(sq)
            uv, _ = self._proy([[f, r, 0], [f + 1, r, 0], [f + 1, r + 1, 0], [f, r + 1, 0]])
            base = C_CLARA if (f + r) % 2 else C_OSCURA
            color = tuple(int(0.45 * b + 0.55 * c) for b, c in zip(base, resaltes[sq])) if sq in resaltes else base
            cv2.fillConvexPoly(img, uv, color, cv2.LINE_AA)
        uv, _ = self._proy([[0, 0, 0], [8, 0, 0], [8, 8, 0], [0, 8, 0]])
        cv2.polylines(img, [uv], True, (30, 60, 20), SS, cv2.LINE_AA)
        for i in range(8):
            for txt, p in ((chr(97 + i), [i + 0.5, -m / 2, 0.0]), (chr(97 + i), [i + 0.5, 8 + m / 2, 0.0]),
                           (str(i + 1), [-m / 2, i + 0.5, 0.0]), (str(i + 1), [8 + m / 2, i + 0.5, 0.0])):
                uv, z = self._proy([p])
                esc = max(0.35, min(0.9, 9.0 / z[0])) * SS * 0.55
                (w, h), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, esc, SS)
                cv2.putText(img, txt, (int(uv[0][0] - w / 2), int(uv[0][1] + h / 2)), cv2.FONT_HERSHEY_SIMPLEX,
                            esc, (225, 240, 220), SS, cv2.LINE_AA)

    def _sombras(self, img, piezas):
        capa = img.copy()
        ang = np.linspace(0, 2 * np.pi, 20, endpoint=False)
        dx, dy = -LUZ[0] / LUZ[2] * 0.3, -LUZ[1] / LUZ[2] * 0.3
        for sq in piezas:
            cx, cy = chess.square_file(sq) + 0.5 + dx, chess.square_rank(sq) + 0.5 + dy
            pts = np.column_stack([cx + 0.33 * np.cos(ang), cy + 0.33 * np.sin(ang), np.zeros(20)])
            uv, _ = self._proy(pts)
            cv2.fillConvexPoly(capa, uv, (15, 15, 15), cv2.LINE_AA)
        cv2.addWeighted(capa, 0.35, img, 0.65, 0, img)

    def _flecha(self, img, movida):
        a = np.array([chess.square_file(movida.from_square) + 0.5, chess.square_rank(movida.from_square) + 0.5])
        b = np.array([chess.square_file(movida.to_square) + 0.5, chess.square_rank(movida.to_square) + 0.5])
        d = b - a
        L = np.linalg.norm(d)
        if L < 1e-6:
            return
        d /= L
        n = np.array([-d[1], d[0]])
        w, cab = 0.09, 0.32
        pts = [a + n * w, b - d * cab + n * w, b - d * cab + n * w * 2.6, b,
               b - d * cab - n * w * 2.6, b - d * cab - n * w, a - n * w]
        uv, _ = self._proy(np.column_stack([np.array(pts), np.full(len(pts), 0.01)]))
        capa = img.copy()
        cv2.fillPoly(capa, [uv], C_FLECHA, cv2.LINE_AA)
        cv2.addWeighted(capa, 0.75, img, 0.25, 0, img)

    @staticmethod
    def _capturadas(board):
        """{True: simbolos capturados POR las blancas, False: ... por las negras}."""
        cap = {True: [], False: []}
        b = board.root()
        for m in board.move_stack:
            if b.is_capture(m):
                sq = m.to_square
                if b.is_en_passant(m):
                    sq = chess.square(chess.square_file(m.to_square), chess.square_rank(m.from_square))
                p = b.piece_at(sq)
                if p:
                    cap[b.turn].append(p.symbol())
            b.push(m)
        return cap

    # ============================================================ render
    def _estado(self, juego):
        b = juego.board
        if b is not None:
            return b, {sq: p.symbol() for sq, p in b.piece_map().items()}
        return None, {sq: (s or "?") for sq, s in juego.votos.ocupadas().items()}

    def render(self, juego, mensaje=""):
        self._camara()
        img = self._fondo.copy()
        b, piezas = self._estado(juego)
        ultima, resaltes = None, {}
        if b is not None:
            if b.move_stack:
                ultima = b.peek()
                resaltes = {ultima.from_square: C_ULTIMA, ultima.to_square: C_ULTIMA}
            if b.is_check():
                resaltes[b.king(b.turn)] = C_JAQUE

        self._tablero(img, resaltes)
        if ultima:
            self._flecha(img, ultima)
        self._sombras(img, piezas)

        orden = []
        for sq, s in piezas.items():
            c = np.array([chess.square_file(sq) + 0.5, chess.square_rank(sq) + 0.5, 0.3])
            orden.append((float(np.linalg.norm(c - self._cam)), sq, s))
        orden.sort(key=lambda t: -t[0])
        for _, sq, s in orden:
            color = C_PIEZA[None] if s == "?" else C_PIEZA[s.isupper()]
            for _, uv, col in self._caras_pieza(sq, s, color):
                cv2.fillPoly(img, [uv], col, cv2.LINE_AA)
        for _, sq, s in orden:                                  # '?' sobre las no identificadas
            if s == "?":
                uv, _ = self._proy([[chess.square_file(sq) + 0.5, chess.square_rank(sq) + 0.5, 0.7]])
                cv2.putText(img, "?", (int(uv[0][0]) - 9 * SS, int(uv[0][1]) + 9 * SS), cv2.FONT_HERSHEY_SIMPLEX,
                            0.9 * SS, (0, 0, 0), 4 * SS, cv2.LINE_AA)
                cv2.putText(img, "?", (int(uv[0][0]) - 9 * SS, int(uv[0][1]) + 9 * SS), cv2.FONT_HERSHEY_SIMPLEX,
                            0.9 * SS, (120, 220, 255), 2 * SS, cv2.LINE_AA)

        img = cv2.resize(img, (self.tam, self.tam), interpolation=cv2.INTER_AREA)
        self._textos(img, b, mensaje)
        return img

    def _textos(self, img, b, mensaje):
        fuente = cv2.FONT_HERSHEY_SIMPLEX
        cv2.rectangle(img, (0, 0), (self.tam, 34), (18, 18, 18), -1)
        if b is None:
            linea, color = "Sin iniciar: piezas votadas ('?' = sin identificar). Presiona i", (200, 200, 200)
        elif b.is_game_over():
            linea, color = "Partida terminada: " + b.result(), (120, 220, 255)
        else:
            robot = b.turn == config.ROBOT_JUEGA_BLANCAS
            linea = "Turno del ROBOT" if robot else "TU TURNO: mueve y presiona ENTER"
            color = (90, 200, 255) if robot else (120, 240, 140)
            if b.is_check():
                linea += "   JAQUE"
        cv2.putText(img, linea, (12, 23), fuente, 0.6, color, 1, cv2.LINE_AA)
        if b is not None and b.move_stack:
            txt = f"jugada {len(b.move_stack)}: {b.peek().uci()}"
            (w, _), _ = cv2.getTextSize(txt, fuente, 0.5, 1)
            cv2.putText(img, txt, (self.tam - w - 12, 23), fuente, 0.5, (190, 190, 190), 1, cv2.LINE_AA)
        if b is not None:
            cap = self._capturadas(b)
            y = 56
            for blancas, quien in ((config.ROBOT_JUEGA_BLANCAS, "Robot capturo"),
                                   (not config.ROBOT_JUEGA_BLANCAS, "Tu capturaste")):
                cuenta = {}
                for s in cap[blancas]:
                    cuenta[NOMBRE[s.lower()]] = cuenta.get(NOMBRE[s.lower()], 0) + 1
                lista = ", ".join(f"{v} {k}" if v > 1 else k for k, v in cuenta.items()) or "-"
                cv2.putText(img, f"{quien}: {lista}", (12, y), fuente, 0.45, (200, 200, 200), 1, cv2.LINE_AA)
                y += 20
        cv2.rectangle(img, (0, self.tam - 50), (self.tam, self.tam), (18, 18, 18), -1)
        if mensaje:
            cv2.putText(img, mensaje[:90], (12, self.tam - 28), fuente, 0.47, (0, 215, 255), 1, cv2.LINE_AA)
        cv2.putText(img, "Arrastra: girar | rueda: zoom | doble clic: vista inicial", (12, self.tam - 9), fuente,
                    0.4, (140, 140, 140), 1, cv2.LINE_AA)

    def mostrar(self, juego, mensaje=""):
        """Dibuja solo si cambio algo (estado, mensaje o vista); si no, deja la imagen anterior."""
        b, piezas = self._estado(juego)
        clave = (b.fen() if b is not None else tuple(sorted(piezas.items())), mensaje,
                 round(self.az, 3), round(self.el, 3), round(self.dist, 2))
        if clave != self._clave:
            self._clave = clave
            self._ultima_img = self.render(juego, mensaje)
            cv2.imshow(self.ventana, self._ultima_img)