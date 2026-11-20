import glob
import time
import cv2

ANCHO, ALTO, FPS = 4416, 1242, 15      # maxima resolucion de la ZED 2 (2.2K side by side)


def buscar_zed():
    rutas = sorted(glob.glob("/sys/class/video4linux/video*/name"), key=lambda r: int(r.split("/")[-2][5:]))
    for r in rutas:
        if "ZED" in open(r).read():
            return int(r.split("/")[-2][5:])
    return None


indice = buscar_zed()
if indice is None:
    raise SystemExit("No se encontro la ZED conectada")

cap = cv2.VideoCapture(indice, cv2.CAP_V4L2)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, ANCHO)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, ALTO)
cap.set(cv2.CAP_PROP_FPS, FPS)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
if not cap.isOpened():
    raise SystemExit(f"No se pudo abrir /dev/video{indice}")

print(f"ZED 2 en /dev/video{indice} | pidiendo {ANCHO}x{ALTO} @ {FPS} FPS | [q] para salir")

n, t0, avisado = 0, time.time(), False
while True:
    ok, frame = cap.read()
    if not ok or frame is None:
        time.sleep(0.01)
        continue

    h, w = frame.shape[:2]
    if not avisado:
        print(f"Recibiendo {w}x{h} ({w // 2}x{h} por ojo)")
        if (w, h) != (ANCHO, ALTO):
            print(f"AVISO: no es la maxima resolucion. Revisa que este en USB 3.0 (lsusb -t debe decir 5000M).")
        avisado = True

    n += 1
    if time.time() - t0 >= 1.0:
        print(f"FPS: {n / (time.time() - t0):.1f} | {w}x{h}")
        n, t0 = 0, time.time()

    cv2.imshow("ZED 2 (reducida solo para mostrar)", cv2.resize(frame, (1280, int(1280 * h / w))))
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()