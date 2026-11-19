"""Wrapper de Stockfish (UCI). En la Pi: sudo apt install stockfish."""

import chess
import chess.engine


class Motor:
    def __init__(self, ruta="stockfish", tiempo=1.0):
        self.tiempo = tiempo
        self.eng = chess.engine.SimpleEngine.popen_uci(ruta)

    def mejor_jugada(self, board):
        """Devuelve la jugada en UCI. El tablero debe ser valido (un rey por bando)."""
        return self.eng.play(board, chess.engine.Limit(time=self.tiempo)).move.uci()

    def cerrar(self):
        self.eng.quit()
