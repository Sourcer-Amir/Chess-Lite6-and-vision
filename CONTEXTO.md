# CONTEXTO DEL PROYECTO: Ajedrez ZED 2 + Lite6 + MATLAB

> Pega este archivo al empezar un chat nuevo, junto con **solo** el archivo de código que se va a cambiar.
> Si se necesita otro archivo, se piden sus firmas de funciones (sección 5), no el archivo completo.

## 1. Objetivo
Un brazo UFactory Lite6 juega ajedrez contra un humano. Una cámara ZED 2 ve el tablero desde arriba.
- La partida **puede empezar en cualquier posición** (avanzada o irregular).
- Hay que soportar todas las reglas: capturas, enroque, captura al paso, promoción, jaque y mate.
- **Todo debe poder llamarse desde MATLAB** (requisito obligatorio del proyecto).

## 2. Hardware y plataforma (CONFIRMADO)
| Elemento | Dato |
|---|---|
| Cámara | **ZED 2** (no 2i, confirmado por el usuario) |
| Conexión | USB 3.0, V4L2, índice 2 (`/dev/video2`), YUYV, 2560x720 side by side, 15 FPS, BUFFERSIZE=1 |
| Ojo usado | Solo el izquierdo, `frame[:, :w//2]` |
| Montaje | Apunta hacia abajo al centro del tablero. Puede moverse, así que la homografía se recalcula en cada lectura. |
| Robot | Lite6, IP `172.23.254.167`, gripper Lite6, sensibilidad de colisión 3 |
| Plataforma | Desarrollo en PC. **Destino final: Raspberry Pi 5** (sin GPU NVIDIA) |

Modos ZED por USB 3 (por lente): 2.2K 2208x1242 a 15 · 1080p 1920x1080 a 30/15 · 720p 1280x720 a 60/30/15 · WVGA 672x376 a 100/60/30/15. Focal fija de 2.12 mm, FOV aprox. 110°×70°, baseline de 120 mm.
Historial: con USB 2.0 solo salía 1344x376. Hubo problemas de permisos y puerto ocupado que se resolvieron desconectando y validando índices.

## 3. Decisiones tomadas (NO volver a proponer)
- **YOLO:** descartado por el costo de cómputo en la RPi 5, no por principio. Plan B si la clasificación clásica falla: un YOLO nano en NCNN u ONNX, entrenado en la PC.
- **Seguimiento solo por diferencias de ocupación:** descartado como único método (costo de rastrear piezas; la partida puede empezar avanzada).
- **Suavizado agresivo y Convex Hull:** descartados, porque destruyen los vértices.
- **ZED SDK:** no viable (requiere NVIDIA). Solo OpenCV + NumPy sobre V4L2.
- **Offset de Z en `pixel_a_pose`: +8 mm** (confirmado).
- No se necesita tiempo real: se analiza con la escena quieta y el brazo en home.
- Código modular para ahorrar tokens.

## 4. Piezas
- Figuras geométricas simples, **naranjas**, impresas en 3D. Hoy existen 3 de un equipo; falta imprimir el resto.
- Clasificación actual (`vision.analizar_formas_tablero`): acepta color naranja, rojo o amarillo y cuenta esquinas agudas (<120°): 4 = `'Reina Negra'`, 5 = `'Rey Negro'`, 0 con circularidad >0.80 = `'Rey Blanco'`. Los nombres mezclan colores aunque todas son naranjas.
- Al diseñar las que faltan: 6 formas muy distintas vistas desde arriba (círculo, triángulo, cuadrado, pentágono, hexágono, cruz o estrella) y **otro color** para el otro bando. Evitar verde (marco) y café (`detectar_piezas_auditoria`).
- Problema identificado: el paralaje y las paredes laterales deforman la silueta, que sale `'Desconocido'`. Solución implementada: corregir la distorsión del lente y rectificar el plano de las caras superiores (ver `geometria.py`).

## 5. Archivos y firmas
| Archivo | Estado | Contenido |
|---|---|---|
| `config.py` | NUEVO, se edita seguido | IP, poses, cámara, medidas, orientación, cementerio y banco, mapa nombre→símbolo, Stockfish, puerto |
| `vision.py` | sin cambios | `obtener_homografia_por_color(img, lado)->(M,mask)`, `analizar_formas_tablero(plano)->(img, matriz 8x8 de nombres)`, `dibujar_tablero(plano, matriz)`, `contar_esquinas`, `douglas_peucker`, `nombre_color`, `detectar_piezas_auditoria` (no se usa) |
| `robot.py` | sin cambios | `ControladorLite6`: `conectar()`, `configurar_calibracion_3puntos(...)`, `pixel_a_pose(px,py)->[x,y,z,r,p,y]` (+8 mm), `casillero_a_pixel(f,c,lado)`, `mover_pieza(pose_o,pose_d)` (termina en home), `ir_a_posicion_home()`, gripper |
| `camara.py` | NUEVO, estable | `Camara(indice, modo, ruta_conf)`: `.leer()`, `.leer_estable(n)` (mediana tras vaciar el buffer), `.K`, `.cerrar()`. `leer_conf(ruta, modo)->(K, dist)` |
| `geometria.py` | NUEVO, estable | `esquinas_desde_homografia(M)`, `pose_camara(esq, lado_mm, K)->(R,t)`, `homografia_a_altura(R,t,K,lado_mm,h)`, `centro_camara(...)->(nadir_px, altura_mm)`, `punto_base(contorno, nadir)` |
| `estado_tablero.py` | NUEVO, estable | `celda_a_casilla`, `casilla_a_celda`, `observacion_desde_matriz(matriz)->{sq: símbolo}`, `tablero_desde_observacion(obs, blancas_mueven, enroques='auto', al_paso)`, `inferir_jugada(board, obs)->(Move|None, info)`, `secuencia_robot(board, move)->[(ori, des)]`, `tipo_jugada` |
| `motor.py` | NUEVO, estable | `Motor(ruta, tiempo).mejor_jugada(board)->uci` |
| `juego.py` | NUEVO, medio | `Juego(con_robot, con_motor)`: `leer_tablero`, `iniciar`, `iniciar_fen`, `jugada_humano`, `confirmar_jugada(uci)`, `jugada_robot(uci=None)`, `estado`, `home`, `cerrar`. Todo devuelve dict JSON. |
| `servidor.py` | NUEVO, estable | TCP, una línea JSON por petición `{"cmd","args"}`, puerto 5005. Flags `--sin-robot`, `--sin-motor` |
| `ajedrez.m` | NUEVO | Cliente MATLAB: `r = ajedrez('jugada_robot')`, etc. Hay que editar la IP de la Pi |
| `main.py` | REEMPLAZADO | Modo teclado: v leer, i iniciar, h humano, r robot, s estado, q salir |
| `pruebas_sin_equipo.py` | NUEVO | Prueba lógica y geometría sin equipo (todo pasa) |

Convenciones de símbolos en la observación: `'P'..'k'` (mayúscula = blancas), `'*'` = ocupada sin identificar, `'W*'`/`'B*'` = solo se sabe el color. Lugares fuera del tablero: `'CEMENTERIO'`, `'BANCO:Q'`.

## 6. Convenciones y calibración
- Poses en **mm y grados** (como Studio). Al xArm se mandan en radianes.
- Plano rectificado de 800x800; matriz `[fila, col]`; fila 0 = arriba de la imagen = lado de la base del robot. px → robot +Y, py → robot +X.
- Orientación casilla↔celda en `config.FILA0_ES_RANGO_1` y `COL0_ES_A` (**VERIFICAR** con una pieza en a1).
```
P1_IMG=[0,0]     P1_ROB=[189.5,-67.6,79.5,177.9,-8.7,-0.7]    arriba-izq, cerca de la base
P2_IMG=[800,0]   P2_ROB=[188.8,140.8,78.5,177.2,-6.2,-2.2]    arriba-der, cerca de la base
P3_IMG=[800,800] P3_ROB=[341.0,141.3,65.0,175.1,-54.7,4.7]    abajo-der, el más lejano
```
- Los puntos **no se midieron con la misma orientación**. P3 es el más lejano y el robot no alcanza a llegar ahí con el gripper vertical, así que el pitch de −54.7° es forzado por el alcance.

## 7. Cómo funciona ahora (implementado)
1. **Visión:** `leer_estable` (mediana de 5 frames) → corrección de distorsión (si hay `.conf`) → marco verde → M. Si hay `K`, `LADO_MARCO_MM` y `ALTURA_CARA_MM`: `solvePnP` → homografía del plano de las caras → `analizar_formas_tablero` sobre ese plano (forma real y casilla correcta sin paralaje). Si falta algo, usa el plano del tablero como antes. Cada lectura guarda `ultima_vista.jpg`.
2. **Inicio:** `iniciar()` lee el tablero completo y arma el tablero. Enroques en `'auto'`: se conceden si el rey y la torre están en su casilla original. Turno y captura al paso se pasan como argumentos. También existe `iniciar_fen(fen)`.
3. **Jugada humana:** se compara lo observado con el tablero esperado tras **cada jugada legal**. Gana la de menor costo (ocupación 3, color 2, tipo 1; tolerancia 2). Cubre enroque, captura al paso y promoción. Si el tipo de pieza promovida no se ve, devuelve `promocion_ambigua` y se resuelve con `confirmar_jugada('e7e8q')`.
4. **Jugada del robot:** `secuencia_robot` convierte la jugada en pasos. Captura: primero la pieza capturada al cementerio. Al paso: retira el peón en (columna de destino, rango de origen). Enroque: rey y luego torre. Promoción: peón al cementerio y pieza del banco al destino. Z ajustada por tipo de pieza (`DZ_POR_PIEZA`). El tablero solo se actualiza si todos los pasos salieron bien.
5. **MATLAB:** MATLAB no corre en la Pi (ARM no soportado) y `mcc` no genera binarios para ARM64. Python no se compila. Arquitectura: **MATLAB en la PC → TCP → `servidor.py` en la Pi**. Alternativa: `raspi` + `system()` por SSH (el Support Package soporta la Pi 5 desde R2024b, solo con OS de 32 bits).

## 8. Revisión de `ChessLogic.py` (EDGE-tronics, pasado por el usuario)
Sus funciones `moveAnalysis` y `sequenceGenerator` quedaron **reemplazadas** por `estado_tablero.py`. Bugs encontrados:
- **Captura al paso mal calculada:** usa siempre la columna de origen −1 (blancas) o +1 (negras). Falla cuando se captura hacia el otro lado. Lo correcto es la columna de destino.
- **Promoción:** no saca el peón ni trae la pieza nueva; solo mueve el peón.
- Enroque largo de negras etiquetado como "White Queen Side Castling".
- `moveAnalysis` solo acepta de 2 a 4 casillas cambiadas y depende del orden que le dé la visión.
- El resto del repo: visión solo por diferencias, sin identificar piezas, así que asume una posición conocida. Ideas reutilizadas: revisar obstrucciones (mano encima) y vaciar el buffer antes de capturar.

## 9. Sospechas y bugs pendientes
- **Calibración no cuadrada:** P1→P2 = 208.4 mm y P2→P3 = 152.2 mm para 800 px cada uno. Hipótesis: si el **TCP offset** del gripper no está configurado en Studio, la pose es de la brida y la inclinación de 46° extra desplaza la punta unos 0.66·L (≈56 mm con L≈85 mm). Revisar antes de volver a calibrar. Mejora: 4 puntos con homografía o mínimos cuadrados.
- `ir_a_posicion_home` no revisa el código de retorno. `mover_pieza` vuelve a home en cada paso (lento pero seguro).
- Con solo 3 piezas, el tablero no es válido (faltan reyes): Stockfish fallará. Para probar, usar `jugada_robot(uci=...)`.
- El servidor no tiene autenticación: usar solo en red local.

## 10. Checklist para cuando haya equipo
1. `pip install chess` y `sudo apt install stockfish`. Correr `python3 pruebas_sin_equipo.py`.
2. Descargar `SN<serie>.conf` y ponerlo en `config.CAM_CONF`.
3. Medir y llenar: `LADO_MARCO_MM` (cuadro interno verde), `ALTURA_CARA_MM`, `DZ_POR_PIEZA`, `CEMENTERIO_POSES`, `BANCO_POSES`.
4. `python3 main.py --sin-robot --sin-motor` y luego `v`: revisar `ultima_vista.jpg` y la altura de cámara que se imprime (sirve para comprobar `LADO_MARCO_MM`).
5. Verificar la orientación con una pieza en a1.
6. Revisar el TCP offset en Studio y volver a calibrar.
7. Con robot: `jugada_robot(uci=...)` en una casilla simple. Luego la prueba desde MATLAB con `ajedrez.m`.

## 11. Preguntas abiertas
1. Tamaño de casilla en mm, altura de cada pieza y altura de la cámara.
2. ¿El robot juega con motor o solo ejecuta jugadas indicadas? ¿Con qué bando?
3. Color del otro bando y formas de las piezas que faltan.
4. ¿Se aprueba el enfoque de la sección 7 (lectura inicial + comparación contra jugadas legales)?
5. ¿Dónde van el cementerio y el banco de promoción?
6. MATLAB: ¿qué versión? ¿Corre en una PC en red con la Pi? ¿Solo llama funciones o también debe calcular algo?
7. ¿El TCP offset del gripper está configurado en Studio?
