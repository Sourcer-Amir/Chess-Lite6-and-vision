"""
Configuracion del sistema. Es el UNICO archivo que deberia editarse seguido.
Los valores marcados con MEDIR o VERIFICAR hay que llenarlos con el equipo.
"""

# ------------------------------------------------------------------ robot
ROBOT_IP = "172.23.254.167"
ROBOT_JUEGA_BLANCAS = True

# Calibracion de 3 poses: pixel del plano rectificado (800x800) -> pose [mm, grados]
P1_IMG, P1_ROB = [0.0, 0.0], [189.5, -67.6, 79.5, 177.9, -8.7, -0.7]        # arriba-izq, cerca de la base
P2_IMG, P2_ROB = [800.0, 0.0], [188.8, 140.8, 78.5, 177.2, -6.2, -2.2]      # arriba-der, cerca de la base
P3_IMG, P3_ROB = [800.0, 800.0], [341.0, 141.3, 65.0, 175.1, -54.7, 4.7]    # abajo-der, lejos

# Ajuste de Z segun la pieza que se carga (mm, se suma al +8 de pixel_a_pose). MEDIR.
DZ_POR_PIEZA = {"p": 0.0, "n": 0.0, "b": 0.0, "r": 0.0, "q": 0.0, "k": 0.0}

# Lugares fuera del tablero: poses [x, y, z, roll, pitch, yaw] en mm y grados. MEDIR en Studio.
CEMENTERIO_POSES = []          # un hueco por pieza capturada, en orden de uso
BANCO_POSES = {                # piezas de reserva para promocion, por simbolo
    "Q": [], "R": [], "B": [], "N": [],
    "q": [], "r": [], "b": [], "n": [],
}

# ------------------------------------------------------------------ camara
CAM_INDICE = "auto"
CAM_MODO = "2K"               # "HD" = 2560x720, "2K" = 4416x1242, "FHD" = 3840x1080
CAM_CONF = "SN20157429.conf"   # ruta al SN<serie>.conf de Stereolabs; None = sin quitar distorsion
CAM_FRAMES_MEDIANA = 5         # frames que se promedian (mediana) en cada lectura
ALTURA_GUIA_MM = 280.0
SUAVIZADO_EN_VIVO = 0.3

# ------------------------------------------------------------------ tablero
LADO = 800                # lado del plano rectificado en px
LADO_MARCO_MM = 240.0     # lado del cuadro INTERNO del marco verde, en mm
ALTURA_CARA_MM = 5.0      # empieza con la base, no con la punta  orignal: altura de la cara superior de las piezas, en mm

# Orientacion: fila 0 de la matriz = arriba del plano rectificado (lado de la base del robot).
# VERIFICAR poniendo una pieza en a1 y mirando en que celda sale.
FILA0_ES_RANGO_1 = True        # True: la fila 0 es el rango 1
COL0_ES_A = True               # True: la columna 0 es la columna 'a'

# Nombre que devuelve vision.py -> simbolo de python-chess.
# El SIMBOLO decide la pieza y el color: mayuscula = blancas, minuscula = negras
# (K rey, Q reina, R torre, B alfil, N caballo, P peon).
# Las LLAVES deben ser identicas (con mayusculas) a los nombres que asigna
# vision.analizar_formas_tablero; si no coinciden, la pieza queda como '*'.
#   cuadrado  -> 'Rey Blanco'   -> 'K'
#   pentagono -> 'Rey Negro'    -> 'k'
#   circulo   -> 'Torre Blanca' -> 'R'  (puede haber varias)
# '*' = ocupada sin identificar, 'W*' / 'B*' = solo se sabe el color.
NOMBRE_A_SIMBOLO = {
    "Rey Blanco": "K",
    "Rey Negro": "k",
    "Torre Blanca": "R",
    "Desconocido": "*",
}

# ------------------------------------------------------------------ ajedrez
TOLERANCIA_JUGADA = 2          # errores de vision tolerados al reconocer la jugada humana
STOCKFISH_RUTA = "stockfish"   # en la Pi: sudo apt install stockfish
STOCKFISH_TIEMPO = 1.0         # segundos por jugada

# ------------------------------------------------------------------ servidor para MATLAB
SERVIDOR_HOST = "0.0.0.0"
SERVIDOR_PUERTO = 5005
IMAGEN_DEBUG = "ultima_vista.jpg"
