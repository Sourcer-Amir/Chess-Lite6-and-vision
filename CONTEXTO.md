# CONTEXTO DEL PROYECTO: Ajedrez ZED 2 + Lite6 + MATLAB
Última actualización: 2026-11-20 (noche). Próxima sesión en el laboratorio: **lunes**.

> Pega este archivo al empezar un chat nuevo, junto con **solo** el archivo de código que se va a cambiar.
> Si se necesita otro archivo, se piden sus firmas (sección 5), no el archivo completo.
>
> **REGLAS DEL USUARIO**
> - **NO entregar código completo salvo que lo pida explícitamente** ("pásame todo el código" = sí lo pidió). Por defecto: discutir, explicar cambios puntuales y ahorrar tokens.
> - Para depurar en el equipo: dar **solo comandos de terminal** y pedir la salida, sin texto largo.
> - Responder en español. Contestar lo que se pregunta; **no volver a preguntar lo ya respondido** (está en este archivo).
> - Si algo no se pudo probar, decirlo. No presentar suposiciones como datos.
> - **Cuando el usuario ya probó algo físicamente, su resultado manda: no insistir** (p. ej. clasificar por tamaño quedó descartado por él).
> - **MATLAB va al final:** no mencionarlo ni tocar `servidor.py`/`ajedrez.m` mientras lo básico no funcione.
> - Si manda un **video**, revisar **todos los fotogramas a la tasa nativa** (un evento de 50 ms se pierde al muestrear a 2 fps).
> - No inventar elementos de la escena (pasó con una "cinta morada" que no existía).

## 1. Objetivo
Un brazo UFactory Lite6 juega ajedrez contra un humano. Una ZED 2 ve el tablero desde arriba.
- La partida **puede empezar en cualquier posición**. Debe soportar capturas, enroque, captura al paso, promoción, jaque y mate.
- **Todo debe poder llamarse desde MATLAB** (requisito obligatorio, se hace al final).

## 2. Hardware y plataforma (CONFIRMADO)
| Elemento | Dato |
|---|---|
| Cámara | **ZED 2**, serie **20157429** (se probaron 2 unidades, equivalentes). |
| Calibración de fábrica | `SN20157429.conf` (`wget "https://calib.stereolabs.com/?SN=20157429"`). `LEFT_CAM_2K`: fx=1070.28, fy=1070.5, cx=1081.32, cy=624.312 |
| Modo | **2K: 4416x1242 side by side** (2208x1242 por ojo), YUYV, V4L2, 15 FPS. Solo ojo izquierdo. Resolución verificada como real (bytes por USB, formato negociado, prueba de ruido en 2 cámaras; prueba indirecta). |
| Controles V4L2 de la ZED | brightness/contrast/saturation/gain 0-8 (def. 4), gamma 1-500, sharpness 0-8, white_balance_automatic, **power_line_frequency = 1 (50 Hz) por defecto: en México poner 2 (60 Hz)**. Se pierden al reconectar. Ej.: `v4l2-ctl -d /dev/videoN -c power_line_frequency=2 -c saturation=6 -c gain=5`. Pendiente: guardarlos en config y aplicarlos al abrir. |
| Tablero | Cuadro interno verde **24x24 cm** (marco al ras de las casillas, casillas de 30 mm). Cámara ~24-40 cm (solvePnP da 270-400 mm según la sesión). |
| Piezas actuales | Base delgada (0.5 cm) + prisma de agarre (se rediseñó más bajo); todas **naranjas**: cuadrado, pentágono, círculos (varios). |
| Robot | Lite6, IP `172.23.254.167`, sensibilidad de colisión 3, offset de Z **+8 mm** (confirmado). Repetibilidad de fábrica ±0.5 mm, encoders absolutos multivuelta. |
| Plataforma | Desarrollo en PC Linux (12 núcleos). **Destino final: Raspberry Pi 5** (4 núcleos, sin GPU NVIDIA). |

### Problemas resueltos (no repetir)
1. **USB 2 vs 3:** en USB 2 solo sale 1344x376. Debe ir en USB 3 **directo** (`lsusb -t` → 5000M).
2. **Desconexiones de la ZED cada 14-24 s:** era el **autosuspend del USB**. Regla permanente `/etc/udev/rules.d/50-zed.rules` (creada) + `echo -1 | sudo tee /sys/module/usbcore/parameters/autosuspend`.
3. **`/dev/videoN` cambia** al reiniciar/reconectar (a veces abre la webcam ACER). Arreglo: `CAM_INDICE = "auto"` (busca "ZED" en `/sys/class/video4linux/*/name`). Ya funciona.
4. **Líneas verdes horizontales: RESUELTO.** Causa demostrada: **OpenCV usaba los 12 núcleos** y el driver USB no alcanzaba a recibir completos los frames de 2K (datos faltantes = verde). Pruebas: atraso sin CPU (sleep) → 0 líneas; remap con todos los núcleos → 30 % de frames con línea; con 1 núcleo → 0.5 %. Barrido 2^n: 1-8 hilos limpios (14-15 fps), desde 16 → 8-37 % con línea y ~10 fps. Más buffer (BUFFERSIZE=4) **empeoró** (71 %). **Arreglo aplicado por el usuario: `cv2.setNumThreads(4)`** (en la Pi probablemente 2). `frame_corrupto` en `camara.py` revisa 1 de cada 8 filas (se le escapan líneas delgadas); quedó como respaldo.
5. **Stockfish no instalado** → `main.py` falla sin `--sin-motor`. `sudo apt install stockfish` (ruta típica `/usr/games/stockfish`, si no está en PATH ponerla en `STOCKFISH_RUTA`).
6. **Terminal:** el `venv` de `p3` es copia del de `p2` (avisos de Qt apuntan a `p2/venv`). En cada terminal: `source venv/bin/activate`. `QFontDatabase` es inofensivo.
7. **Robot en error** (`ControllerError code 2`, "not ready to move"): limpiar en UFactory Studio; para probar solo cámara usar `--sin-robot`.

### Luz
Con luz de tarde el anillo verde se corta y el marco se pierde (en una sesión solo 35 % de frames con marco, altura de solvePnP hasta 1576 mm). Recomendado: **luz propia constante y difusa** sobre el tablero. Alternativas: bajar `lower_green` en `obtener_homografia_por_color` (p. ej. `[35, 40, 30]` en vez de `[35, 50, 50]`), subir saturación de la cámara.

## 3. Decisiones tomadas (NO volver a proponer)
- **YOLO:** descartado por cómputo en la Pi (plan B lejano: YOLO nano NCNN/ONNX).
- **Seguimiento solo por diferencias de ocupación:** descartado como único método.
- **Suavizado agresivo y Convex Hull para contar vértices:** descartados.
- **ZED SDK:** no viable (NVIDIA). Solo OpenCV + NumPy sobre V4L2.
- **Clasificar por TAMAÑO de pieza: DESCARTADO por el usuario** (lo probó: la cámara no da resolución suficiente). No insistir.
- **Análisis siempre sobre la imagen original completa**; el recorte es solo para mostrar.
- **Interfaz de apuntado:** cuadrado guía y cruz **fijos** al centro, nada dinámico.
- **El robot siempre mueve primero** en la partida. `s`, `v`, `h`, `r`(viejo) eliminados del menú.
- **Gripper siempre a 90°** (vertical) al tomar y dejar.
- **Usar los dos ojos de la ZED (uno por mitad del tablero):** evaluado; mejora ~20 % el paralaje en esquinas pero duplica el cómputo. No se hizo; antes: nadir centrado y cámara más alta.

## 4. Visión y piezas
### Clasificación actual (vision.py entregado completo, basado en el original + cambios)
- Máscara: solo tonos naranja/rojo/amarillo (`inRange (0,100,60)-(35,255,255)` OR `(172,100,60)-(180,255,255)`).
- **Clasificación por RELLENO** = área / rectángulo mínimo (`cv2.minAreaRect`) + circularidad. El conteo de esquinas ya no decide (era inestable: el mismo cuadrado daba 1-7 esquinas agudas; la apertura morfológica 5x5 redondea las esquinas de 108° del pentágono).
- Mapeo actual (forma → nombre en vision.py → símbolo en `config.NOMBRE_A_SIMBOLO`):
  - cuadrado → `'Rey Blanco'` → `'K'`
  - pentágono → `'Rey Negro'` → `'k'`
  - círculo → `'Torre Blanca'` → `'R'` (puede haber varias)
  - Las llaves del diccionario deben ser **idénticas** a los nombres de vision.py; la mayúscula/minúscula del **valor** decide el color.
- **Datos reales (sesión 20261120_180405)**: relleno cuadrado 0.93-0.95 (100 % acierto), círculo 0.78-0.80 (93 %), **pentágono 0.74-0.81, mediana 0.75 (38 %)** → el pentágono real se traslapa con el círculo.
- **Umbrales recomendados con esos datos** (el usuario debe aplicarlos en vision.py si no lo hizo): `relleno >= 0.88` → Rey Blanco; `>= 0.77` → Torre Blanca; si no → Rey Negro. El pentágono seguirá fallando parcialmente; es límite de la forma.

### Diseño de las piezas que faltan (PENDIENTE de confirmar por el usuario)
- El usuario planea **4 formas × 3 colores = 12 combinaciones** (regla del producto, no permutación) = 6 tipos × 2 bandos.
- Propuesta de Claude (sin pentágono): formas **círculo, cuadrado, triángulo, cruz** (relleno ~0.79 / ~0.94 / ~0.50 / ~0.56; triángulo y cruz se separan por circularidad ~0.60 vs ~0.44, valores teóricos sin probar). Colores **naranja, azul, magenta** (lejos del verde del marco y del blanco/negro del tablero).
- Reparto propuesto: naranja = robot (círculo peón, cuadrado torre, triángulo rey, cruz reina); azul = humano (mismo orden); magenta compartido (círculo alfil robot, cuadrado caballo robot, triángulo alfil humano, cruz caballo humano).
- Prisma de agarre: igual en todas (misma Z de agarre), idealmente en blanco o negro para que la máscara solo vea la base.
- Antes de imprimir las 32: imprimir una de cada forma/color nuevo y validar con `registro.py` + `analizar_log.py`. Luego `vision.py` debe clasificar también por color (máscara con azul y magenta).

### Otros
- `ALTURA_CARA_MM = 5` (rectificar al plano de la base).
- Paralaje: el error crece con la distancia al **nadir** (no al centro de la imagen). En una sesión el nadir salió en [283, 567] (ideal [400, 400]) → cámara inclinada. Centrar el nadir reduce ~26 % el paralaje en esquinas. Subir la cámara también ayuda (el marco debe seguir viéndose como anillo cerrado en el panel 2).

## 5. Archivos y firmas (estado actual en la carpeta p3)
| Archivo | Estado | Contenido |
|---|---|---|
| `config.py` | del usuario | IP, poses P1-P3, cámara (`CAM_INDICE="auto"`, `CAM_MODO="2K"`, `CAM_CONF`), `LADO_MARCO_MM=240`, `ALTURA_CARA_MM=5`, `CAM_FRAMES_MEDIANA`, `ALTURA_GUIA_MM=280`, `SUAVIZADO_EN_VIVO=0.3`, `NOMBRE_A_SIMBOLO`, `ROBOT_JUEGA_BLANCAS=True`, orientación casillas, cementerio/banco (vacíos), Stockfish. Opcional: `ORIENTACION_AGARRE` (por defecto [180, 0, yaw de P1]; `False` = interpolada). |
| `camara.py` | entregado + `cv2.setNumThreads(4)` del usuario | `indice_por_nombre`, `frame_corrupto`, `leer_conf`, `Camara(indice|"auto", modo, conf)`: `leer()`, `leer_estable(n)`, `.K`, `.descartados`, `cerrar()` |
| `vision.py` | entregado completo | `obtener_homografia_por_color`, `analizar_formas_tablero` (relleno), `dibujar_tablero` (nombres nuevos), `contar_esquinas`, `douglas_peucker`, `nombre_color`, `detectar_piezas_auditoria` (no se usa) |
| `geometria.py` | estable | `esquinas_desde_homografia`, `pose_camara`, `homografia_a_altura`, `centro_camara`, `punto_base` |
| `estado_tablero.py` | estable | `celda_a_casilla`, `casilla_a_celda`, `observacion_desde_matriz`, `tablero_desde_observacion`, `inferir_jugada`, `secuencia_robot`, `tipo_jugada` |
| `juego.py` | entregado | `Votacion` (por casilla: primera figura conocida manda hasta que otra la empata/supera; se olvida tras 5 frames vacíos). `Juego`: `_procesar(img, suavizar, votar)`, `iniciar()` (usa votos; se niega si alguna casilla nunca se identificó o la posición es inválida, explicando en palabras; el robot hace la primera jugada), `turno()` (jugada humana + respuesta del robot), `jugada_humano`, `jugada_robot(uci=None)`, `estado()` (con `mensaje_fin`), `_mensaje_fin` (ganaste/perdiste/tablas), `_explicar_status`, `_pose` (orientación fija a 90°). |
| `main.py` | entregado | Ventanas **"Monitor"** (2x2: en vivo con guía fija, máscara verde, rectificado, piezas) y **"Tablero 3D"**. Análisis en vivo arranca solo. Teclas: **i** iniciar, **ENTER** tu turno, **ESPACIO** pausar análisis/registro, **q** salir. Fin de partida: mensaje y cierre. |
| `vista3d.py` | entregado | Tablero 3D con perspectiva, piezas Staunton (revolución + almenas/cruz/caballo), marco verde, sombras, flecha de última jugada, jaque en rojo, capturas por bando. Mouse: arrastrar gira, rueda zoom, doble clic reinicia. Antes de iniciar muestra votos ('?' gris). Solo redibuja si algo cambia (~90 ms por cuadro con 32 piezas). |
| `registro.py` | entregado | Con el análisis activo guarda `logs/frames_<sesion>.csv` y `logs/piezas_<sesion>.csv` (casilla, símbolo, posición, distancia al nadir, área, vértices, agudas, circularidad, **relleno**). Lo llama `main.py`. |
| `analizar_log.py` | entregado | `python3 analizar_log.py [sesion]`: frames con marco, presencias por casilla (votación), tiempo hasta identificar, errores por pieza, matriz de confusión, error por distancia al nadir, mapa 8x8, rasgos por identidad (agudas, circ, relleno). |
| `simulacion.py` | entregado | Piloto sin equipo: lógica real de `juego.py` + ventana 3D con cámara/robot/humano simulados. Por defecto partida completa (32 piezas); `--mini` (rey + 2 torres vs rey); `--rapido`. Usa Stockfish si está, si no un motor sencillo. Probado: termina en mate. |
| `robot.py` | sin cambios | `ControladorLite6`: `conectar`, `configurar_calibracion_3puntos`, `pixel_a_pose` (+8 mm), `casillero_a_pixel`, `mover_pieza` (termina en home), `visitar_pose`, gripper |
| `motor.py`, `pruebas_sin_equipo.py` | estables | Stockfish; pruebas de lógica y geometría |
| `zed_stream.py` | entregado | Stream mínimo 4416x1242 con log de FPS (15.1 estable) |
| `servidor.py`, `ajedrez.m` | sin probar | Para MATLAB (al final). Tienen comando `turno`. |
| `zed_2k.py` | sin probar | Versión 2K de un script viejo; depende de `main1.py` (nunca visto) |

Convenciones de símbolos: `'P'..'k'` (mayúscula = blancas), `'*'` = ocupada sin identificar. Fuera del tablero: `'CEMENTERIO'`, `'BANCO:Q'`.
Cómo se corre: `source venv/bin/activate` → `python3 main.py` (`--sin-robot`, `--sin-motor` para probar por partes).

## 6. Robot: calibración y precisión
```
P1_IMG=[0,0]     P1_ROB=[189.5,-67.6,79.5,177.9,-8.7,-0.7]    arriba-izq, cerca de la base
P2_IMG=[800,0]   P2_ROB=[188.8,140.8,78.5,177.2,-6.2,-2.2]    arriba-der, cerca de la base
P3_IMG=[800,800] P3_ROB=[341.0,141.3,65.0,175.1,-54.7,4.7]    abajo-der, el más lejano
```
- Poses en mm y grados; al xArm van en radianes. px → robot +Y, py → robot +X.
- **El robot SÍ llega vertical al lado lejano** (en Studio: X=387.5, pitch −10.5°). El pitch −54.7° de P3 **no fue forzado por el alcance**; se grabó así.
- **Problema actual: el robot no deja bien las piezas.** Análisis:
  1. **La cámara no influye en dónde suelta**: el destino sale de `casillero_a_pixel` + calibración fija; la imagen solo decide qué jugada es.
  2. **Causa más probable: orientación fija a 90° + TCP sin configurar.** Si el TCP del gripper está en 0, las poses grabadas son de la brida. P3 se grabó inclinado; al soltar vertical, la punta queda corrida ~L·sen(46°) en horizontal y ~L·(1−cos 46°) en altura (L = largo del gripper; con L≈70-80 mm → ~50 mm y ~20-25 mm, estimado). Encaja con la calibración no cuadrada (208 mm vs 152 mm para un tablero de 240).
  3. **Posible desfase de media casilla:** P_IMG [0,0], [800,0], [800,800] son las **esquinas del tablero**; si P1-P3 se grabaron en el **centro de la casilla de esquina**, los P_IMG correctos son [50,50], [750,50], [750,750].
  4. El amigo del usuario, con el mismo brazo, tuvo que grabar posiciones a mano porque "no se mueve los mm que manda el SDK": consistente con **buena repetibilidad pero exactitud absoluta pobre** (modelo cinemático/TCP), no con sensores dañados.
- **Prueba sugerida:** 10 veces a la misma casilla con `visitar_pose` y marcar; si cae igual → robot bien, el error es calibración/agarre.
- **Orientación del tablero:** depende del color del robot (blancas). Verificar `FILA0_ES_RANGO_1`/`COL0_ES_A` con una pieza en a1.

## 7. PLAN DEL LUNES (acordado)
1. **Revisar/configurar el TCP del gripper en Studio** (Settings → TCP). Comprobar: rotar el gripper sin que se mueva la punta.
2. **Opción A (acordada):** grabar **9 puntos** (4 esquinas, centro de cada lado, centro) con el gripper **vertical** y la punta exactamente en el punto físico que corresponde a su coordenada en píxeles; interpolar entre ellos en lugar de la afín de 3 puntos. (Código pendiente: Claude ofreció prepararlo.)
3. **Tecla `r` = "repetir" con corrección (propuesta del usuario, pendiente de programar):** tras soltar y volver a home, el usuario presiona `r`; la visión mide dónde quedó realmente la pieza (plano rectificado, ~0.3 mm/px; no hace falta la nube de puntos), el robot vuelve por ella **a su posición real**, la suelta de nuevo corregida y guarda una **corrección por casilla** en archivo (`corrección += k·error`, k≈0.7: control proporcional iterativo; el usuario lo pensó como PD, la derivada no aporta en movimientos discretos). Con el tiempo el error baja a la repetibilidad (±0.5 mm).
4. Aplicar los umbrales de relleno (sección 4) y probar con `registro.py`.
5. Instalar Stockfish y jugar una partida real con las piezas actuales (K cuadrado, k pentágono, R círculos).

## 8. Lógica de ajedrez (implementado)
- Inicio con votos; turno = jugada humana comparando lo observado contra el tablero tras cada jugada legal (costos: ocupación 3, color 2, tipo 1; tolerancia 2) + respuesta del robot.
- `secuencia_robot`: captura (capturada al cementerio primero), al paso, enroque (rey y torre), promoción (peón al cementerio, pieza del banco). Z por tipo en `DZ_POR_PIEZA`.
- Revisión de `ChessLogic.py` (EDGE-tronics): reemplazado; tenía bugs en captura al paso, promoción y etiquetas de enroque.
- MATLAB: no corre en la Pi (ARM); arquitectura MATLAB en PC → TCP → `servidor.py` en la Pi (al final).

## 9. Pendientes
1. Lunes: TCP, 9 puntos (opción A), tecla `r` con corrección por casilla (sección 7).
2. Confirmar el diseño de piezas (4 formas × 3 colores) y adaptar `vision.py` a colores.
3. Poses de cementerio y banco de promoción; `DZ_POR_PIEZA`.
4. Guardar los controles de la cámara (60 Hz, saturación, ganancia) en config y aplicarlos al abrir.
5. Luz constante.
6. En la Pi: Stockfish, regla udev/autosuspend, `cv2.setNumThreads(2)`, memoria (`CAM_FRAMES_MEDIANA` ≤ 15).
7. Al final: MATLAB (versión, IP de la Pi, probar `servidor.py`/`ajedrez.m`).