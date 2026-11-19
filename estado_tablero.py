"""
Logica de ajedrez pura: no usa camara ni robot, asi que se prueba sin equipo.
- Convierte la matriz 8x8 de vision a casillas y a un tablero de python-chess.
- Reconoce la jugada humana comparando lo observado con el resultado de cada jugada legal.
- Traduce una jugada a pasos fisicos para el robot (capturas, enroque, al paso, promocion).
"""

import chess
import config

CEMENTERIO = "CEMENTERIO"
COSTO_OCUPACION, COSTO_COLOR, COSTO_TIPO = 3, 2, 1
SIN_TIPO = ("*", "W*", "B*")


# ------------------------------------------------------------------ orientacion
def celda_a_casilla(fila, col):
    rango = fila if config.FILA0_ES_RANGO_1 else 7 - fila
    columna = col if config.COL0_ES_A else 7 - col
    return chess.square(columna, rango)


def casilla_a_celda(sq):
    rango, columna = chess.square_rank(sq), chess.square_file(sq)
    fila = rango if config.FILA0_ES_RANGO_1 else 7 - rango
    col = columna if config.COL0_ES_A else 7 - columna
    return fila, col


def observacion_desde_matriz(matriz):
    """Matriz 8x8 de nombres (vision.py) -> {casilla: simbolo}."""
    obs = {}
    for f in range(8):
        for c in range(8):
            v = matriz[f][c]
            if v is None:
                continue
            obs[celda_a_casilla(f, c)] = config.NOMBRE_A_SIMBOLO.get(v, "*")
    return obs


def observacion_a_texto(obs):
    return {chess.square_name(sq): s for sq, s in sorted(obs.items())}


# ------------------------------------------------------------------ tablero inicial
def tablero_desde_observacion(obs, blancas_mueven=True, enroques="auto", al_paso="-"):
    """
    Arma el tablero a partir de una lectura completa (la partida puede estar avanzada).
    enroques: 'auto' (se conceden si rey y torre estan en su casilla original), 'KQkq', '-', etc.
    Devuelve (board, avisos). Lanza ValueError si hay piezas sin identificar.
    """
    sin_id = [chess.square_name(sq) for sq, s in obs.items() if s in SIN_TIPO]
    if sin_id:
        raise ValueError(f"Piezas sin identificar en {sin_id}")

    b = chess.Board(None)
    for sq, s in obs.items():
        b.set_piece_at(sq, chess.Piece.from_symbol(s))
    b.turn = chess.WHITE if blancas_mueven else chess.BLACK

    if enroques == "auto":
        reglas = (("K", "e1", "h1", "K", "R"), ("Q", "e1", "a1", "K", "R"),
                  ("k", "e8", "h8", "k", "r"), ("q", "e8", "a8", "k", "r"))
        enroques = "".join(
            letra for letra, rey, torre, sr, st in reglas
            if b.piece_at(chess.parse_square(rey)) == chess.Piece.from_symbol(sr)
            and b.piece_at(chess.parse_square(torre)) == chess.Piece.from_symbol(st))
    b.set_castling_fen(enroques or "-")
    if al_paso and al_paso != "-":
        b.ep_square = chess.parse_square(al_paso)

    avisos = [] if b.is_valid() else [str(b.status())]
    return b, avisos


# ------------------------------------------------------------------ jugada humana
def _costo(pieza, o):
    if pieza is None and o is None:
        return 0
    if pieza is None or o is None:
        return COSTO_OCUPACION
    if o == "*":
        return 0
    if o in ("W*", "B*"):
        return 0 if pieza.color == (o == "W*") else COSTO_COLOR
    p = chess.Piece.from_symbol(o)
    return (COSTO_COLOR if p.color != pieza.color else 0) + \
           (COSTO_TIPO if p.piece_type != pieza.piece_type else 0)


def diferencia(board, obs):
    mapa = board.piece_map()
    return sum(_costo(mapa.get(sq), obs.get(sq)) for sq in set(mapa) | set(obs))


def inferir_jugada(board, obs, tolerancia=config.TOLERANCIA_JUGADA):
    """
    Busca la jugada legal cuyo tablero resultante se parece mas a lo observado.
    Devuelve (chess.Move | None, info). No modifica board.
    info['error'] puede ser: 'sin_cambio', 'sin_jugadas', 'no_coincide', 'ambigua', 'promocion_ambigua'.
    """
    base = diferencia(board, obs)
    cands = []
    for m in list(board.legal_moves):
        board.push(m)
        cands.append((diferencia(board, obs), m))
        board.pop()
    if not cands:
        return None, {"error": "sin_jugadas"}
    cands.sort(key=lambda x: x[0])
    mejor = cands[0][0]
    if base <= mejor:
        return None, {"error": "sin_cambio", "costo_sin_mover": base}
    if mejor > tolerancia:
        return None, {"error": "no_coincide", "costo": mejor, "mas_parecida": cands[0][1].uci()}
    empatadas = [m for d, m in cands if d == mejor]
    if len(empatadas) > 1:
        mismas = {(m.from_square, m.to_square) for m in empatadas}
        error = "promocion_ambigua" if all(m.promotion for m in empatadas) and len(mismas) == 1 else "ambigua"
        return None, {"error": error, "opciones": [m.uci() for m in empatadas]}
    return empatadas[0], {"costo": mejor}


# ------------------------------------------------------------------ jugada del robot
def tipo_jugada(board, move):
    if board.is_castling(move):
        return "enroque"
    if move.promotion:
        return "promocion"
    if board.is_en_passant(move):
        return "al_paso"
    if board.is_capture(move):
        return "captura"
    return "normal"


def secuencia_robot(board, move):
    """
    Pasos fisicos (origen, destino) para ejecutar move. Llamar ANTES de board.push(move).
    Origen/destino: nombre de casilla ('e4'), 'CEMENTERIO' o 'BANCO:<simbolo>'.
    """
    n = chess.square_name
    pasos = []

    if board.is_en_passant(move):
        # El peon capturado esta en la columna de destino y en el rango de origen.
        capturado = chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        pasos.append((n(capturado), CEMENTERIO))
    elif board.is_capture(move):
        pasos.append((n(move.to_square), CEMENTERIO))

    if board.is_castling(move):
        rango = chess.square_rank(move.from_square)
        t_ori, t_des = (7, 5) if board.is_kingside_castling(move) else (0, 3)
        pasos.append((n(move.from_square), n(move.to_square)))
        pasos.append((n(chess.square(t_ori, rango)), n(chess.square(t_des, rango))))
    elif move.promotion:
        simbolo = chess.Piece(move.promotion, board.turn).symbol()
        pasos.append((n(move.from_square), CEMENTERIO))
        pasos.append(("BANCO:" + simbolo, n(move.to_square)))
    else:
        pasos.append((n(move.from_square), n(move.to_square)))
    return pasos
