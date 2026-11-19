"""Pruebas que no necesitan camara ni robot. Uso: python3 pruebas_sin_equipo.py"""

import chess
import cv2
import numpy as np

from estado_tablero import (inferir_jugada, secuencia_robot, tablero_desde_observacion,
                            celda_a_casilla, casilla_a_celda, CEMENTERIO)
from geometria import pose_camara, homografia_a_altura, centro_camara

sq = chess.parse_square


def obs_de(board):
    return {s: p.symbol() for s, p in board.piece_map().items()}


def jugada_vista(fen, uci, ocultar_tipo_en=None):
    """Simula que la camara ve el tablero tras uci y comprueba que se reconoce."""
    b = chess.Board(fen)
    despues = b.copy()
    despues.push_uci(uci)
    obs = obs_de(despues)
    if ocultar_tipo_en:
        obs[sq(ocultar_tipo_en)] = "*"
    return inferir_jugada(b, obs)


def probar_logica():
    # Reconocer jugadas humanas
    assert jugada_vista(chess.STARTING_FEN, "e2e4")[0].uci() == "e2e4"
    fen_enroque = "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1"
    for u in ("e1g1", "e1c1"):
        assert jugada_vista(fen_enroque, u)[0].uci() == u
    fen_negras = fen_enroque.replace(" w ", " b ")
    for u in ("e8g8", "e8c8"):
        assert jugada_vista(fen_negras, u)[0].uci() == u
    fen_ep = "4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1"
    assert jugada_vista(fen_ep, "e5d6")[0].uci() == "e5d6"
    fen_prom = "3r3k/4P3/8/8/8/8/8/4K3 w - - 0 1"
    assert jugada_vista(fen_prom, "e7d8n")[0].uci() == "e7d8n"
    m, info = jugada_vista(fen_prom, "e7e8q", ocultar_tipo_en="e8")
    assert m is None and info["error"] == "promocion_ambigua", info
    m, info = inferir_jugada(chess.Board(), obs_de(chess.Board()))
    assert info["error"] == "sin_cambio"

    # Tolerancia: la vision confunde el tipo de una pieza que no se movio
    b = chess.Board()
    d = b.copy(); d.push_uci("g1f3")
    obs = obs_de(d); obs[sq("d1")] = "K"
    assert inferir_jugada(b, obs)[0].uci() == "g1f3"

    # Secuencias del robot
    b = chess.Board(fen_ep)
    assert secuencia_robot(b, chess.Move.from_uci("e5d6")) == [("d5", CEMENTERIO), ("e5", "d6")]
    b = chess.Board("4k3/8/8/3Pp3/8/8/8/4K3 w - e6 0 1")   # al paso hacia la derecha
    assert secuencia_robot(b, chess.Move.from_uci("d5e6")) == [("e5", CEMENTERIO), ("d5", "e6")]
    b = chess.Board(fen_negras)
    assert secuencia_robot(b, chess.Move.from_uci("e8c8")) == [("e8", "c8"), ("a8", "d8")]
    b = chess.Board(fen_prom)
    assert secuencia_robot(b, chess.Move.from_uci("e7d8q")) == [("d8", CEMENTERIO), ("e7", CEMENTERIO), ("BANCO:Q", "d8")]

    # Lectura inicial de una partida avanzada
    obs = obs_de(chess.Board("r3k2r/8/8/8/8/8/8/4K2R w - - 0 1"))
    b, avisos = tablero_desde_observacion(obs, blancas_mueven=True)
    assert b.castling_xfen() == "Kkq" and not avisos
    for f in range(8):
        for c in range(8):
            assert casilla_a_celda(celda_a_casilla(f, c)) == (f, c)
    print("Logica de ajedrez: OK")


def probar_geometria():
    lado_mm, h = 400.0, 30.0
    K = np.array([[700, 0, 640], [0, 700, 360], [0, 0, 1]], float)
    rvec = np.array([0.15, -0.1, 0.05]); tvec = np.array([-180.0, -170.0, 650.0])
    obj = np.float32([[0, 0, 0], [lado_mm, 0, 0], [lado_mm, lado_mm, 0], [0, lado_mm, 0]])
    esquinas = cv2.projectPoints(obj, rvec, tvec, K, None)[0].reshape(4, 2)

    R, t = pose_camara(esquinas, lado_mm, K)
    Mh = homografia_a_altura(R, t, K, lado_mm, h)
    # Un punto a h mm SOBRE el tablero (Z negativa en este marco) debe caer sobre su X, Y real.
    p_img = cv2.projectPoints(np.float32([[100, 250, -h]]), rvec, tvec, K, None)[0].reshape(1, 1, 2)
    p_rect = cv2.perspectiveTransform(p_img, Mh).reshape(2)
    esperado = np.array([100, 250]) * (799 / lado_mm)
    assert np.allclose(p_rect, esperado, atol=0.5), (p_rect, esperado)
    _, altura = centro_camara(R, t, lado_mm)
    assert altura > 0
    print(f"Geometria: OK (altura de camara simulada {altura:.0f} mm)")


if __name__ == "__main__":
    probar_logica()
    probar_geometria()
