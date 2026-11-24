"""
Analiza los CSV de registro.py. Uso:
  python3 analizar_log.py                 -> la sesion mas reciente en logs/
  python3 analizar_log.py 20261120_170000 -> una sesion concreta
  python3 analizar_log.py todas           -> junta TODAS las sesiones de logs/ en un solo reporte
Identidad "verdadera" de cada pieza, sin etiquetarla a mano (votacion):
  - Se sigue cada casilla en el tiempo. Una presencia termina cuando la casilla queda vacia
    HUECO frames seguidos con el marco visible (la pieza se movio o fue capturada).
  - En cada presencia, la identidad es el simbolo conocido mas votado: el primero que aparece manda
    hasta que otro lo empata o lo supera. Las presencias de menos de MIN_FRAMES se ignoran (ruido).
  - Toda deteccion distinta de esa identidad es un error: '*' = desconocida, otra letra = confusion.
Imprime el reporte y lo guarda en logs/reporte_<sesion>.txt
"""

import csv
import glob
import os
import sys
from collections import Counter, defaultdict

HUECO = 5          # frames vacios seguidos para cerrar una presencia
MIN_FRAMES = 10    # presencias mas cortas se descartan
BINS_MM = [0, 40, 80, 120, 160, 200, 1000]


def leer(ruta):
    with open(ruta, newline="") as f:
        return list(csv.DictReader(f))


def sesion_reciente(carpeta="logs"):
    rutas = sorted(glob.glob(os.path.join(carpeta, "piezas_*.csv")))
    if not rutas:
        raise SystemExit("No hay registros en logs/")
    return os.path.basename(rutas[-1])[7:-4]


def presencias(frames, piezas):
    """Devuelve una lista de presencias: {casilla, filas (detecciones), identidad, votos}."""
    por_frame = defaultdict(list)
    for p in piezas:
        por_frame[int(p["frame"])].append(p)
    abiertas, vacias, cerradas = {}, defaultdict(int), []
    for fr in frames:
        if fr["marco_ok"] != "1":
            continue                       # sin marco no se sabe nada: no abre ni cierra
        n = int(fr["frame"])
        vistas = defaultdict(list)
        for p in por_frame.get(n, []):
            vistas[p["casilla"]].append(p)
        for cas, dets in vistas.items():
            abiertas.setdefault(cas, []).extend(dets)
            vacias[cas] = 0
        for cas in list(abiertas):
            if cas not in vistas:
                vacias[cas] += 1
                if vacias[cas] >= HUECO:
                    cerradas.append((cas, abiertas.pop(cas)))
    cerradas += list(abiertas.items())

    salida = []
    for cas, dets in cerradas:
        frames_distintos = len({d["frame"] for d in dets})
        if frames_distintos < MIN_FRAMES:
            continue
        votos = Counter(d["simbolo"] for d in dets)
        conocidos = [d["simbolo"] for d in dets if d["simbolo"] not in ("*", "vacio", "W*", "B*")]
        identidad = "?"
        if conocidos:
            # el primero manda hasta que otro lo empata o supera
            cuenta = Counter()
            for s in conocidos:
                cuenta[s] += 1
                if identidad == "?" or cuenta[s] > cuenta[identidad]:
                    identidad = s
        # tiempo hasta que el lider de la votacion es la identidad final y ya no cambia
        t_ini = float(dets[0]["t"])
        cuenta, lider, t_estable = Counter(), "?", None
        for d in dets:
            s_ = d["simbolo"]
            if s_ in ("*", "vacio", "W*", "B*"):
                continue
            cuenta[s_] += 1
            if lider == "?" or cuenta[s_] > cuenta[lider]:
                lider = s_
                t_estable = float(d["t"]) if lider == identidad else None
        espera = (t_estable - t_ini) if (t_estable is not None and identidad != "?") else None
        salida.append({"casilla": cas, "dets": dets, "identidad": identidad, "votos": votos,
                       "t_ini": t_ini, "espera": espera, "dur": float(dets[-1]["t"]) - t_ini})
    return salida


def pct(a, b):
    return f"{100 * a / b:5.1f}%" if b else "   - "


def todas_las_sesiones(carpeta="logs"):
    return [os.path.basename(r)[7:-4] for r in sorted(glob.glob(os.path.join(carpeta, "piezas_*.csv")))]


def reporte(sesiones, carpeta="logs"):
    """sesiones: un nombre o una lista. Con varias, las presencias se calculan por sesion y se juntan."""
    if isinstance(sesiones, str):
        sesiones = [sesiones]
    frames, pres, dt = [], [], []
    for ses in sesiones:
        f_ses = leer(os.path.join(carpeta, f"frames_{ses}.csv"))
        p_ses = leer(os.path.join(carpeta, f"piezas_{ses}.csv"))
        frames += f_ses
        pres += presencias(f_ses, p_ses)
        ts = [float(f["t"]) for f in f_ses]
        dt += [b - a for a, b in zip(ts, ts[1:]) if b > a]
    sesion = sesiones[0] if len(sesiones) == 1 else f"{len(sesiones)} sesiones ({sesiones[0]} a {sesiones[-1]})"
    L = []
    w = L.append

    n = len(frames)
    con_marco = sum(f["marco_ok"] == "1" for f in frames)
    con_piezas = sum(f["marco_ok"] == "1" and int(f["n_piezas"]) > 0 for f in frames)
    w(f"SESION {sesion}")
    w(f"Frames analizados: {n} | con marco: {con_marco} ({pct(con_marco, n)}) | "
      f"con marco Y piezas: {con_piezas} ({pct(con_piezas, n)})")
    dt = sorted(dt)
    if dt:
        med, p90 = dt[len(dt) // 2], dt[int(len(dt) * 0.9)]
        w(f"Tiempo por frame (captura + analisis + pantalla): mediana {med*1000:.0f} ms "
          f"({1/med:.1f} fps), 90% de los frames por debajo de {p90*1000:.0f} ms, max {dt[-1]*1000:.0f} ms")
    alturas = [float(f["altura_mm"]) for f in frames if f["altura_mm"]]
    if alturas:
        w(f"Altura de camara: media {sum(alturas)/len(alturas):.0f} mm, "
          f"min {min(alturas):.0f}, max {max(alturas):.0f}")

    w(f"\nPresencias de piezas (casilla ocupada >= {MIN_FRAMES} frames): {len(pres)}")
    for p in pres:
        tot = sum(p["votos"].values())
        esp = f"{p['espera']:.2f} s" if p["espera"] is not None else "nunca"
        w(f"  {p['casilla']} (desde t={p['t_ini']:.1f} s, {p['dur']:.1f} s): identidad {p['identidad']} | "
          f"identificada en {esp} | {tot} detecciones | votos {dict(p['votos'])}")
    esperas = sorted(p["espera"] for p in pres if p["espera"] is not None)
    if esperas:
        w(f"Tiempo hasta identificar: mediana {esperas[len(esperas)//2]:.2f} s, "
          f"max {esperas[-1]:.2f} s | sin identificar nunca: {sum(p['espera'] is None for p in pres)} de {len(pres)}")

    # Errores por identidad
    w("\nERRORES POR PIEZA (identidad por votacion)")
    w(f"  {'pieza':6s} {'detecc':>7s} {'desconoc':>9s} {'confund':>9s} {'acierto':>8s}  confundida con")
    por_id = defaultdict(Counter)
    for p in pres:
        por_id[p["identidad"]].update(d["simbolo"] for d in p["dets"])
    for ident, c in sorted(por_id.items(), key=lambda x: -sum(x[1].values())):
        tot = sum(c.values())
        desc = c["*"]
        conf = sum(v for s, v in c.items() if s not in (ident, "*"))
        otros = {s: v for s, v in c.items() if s not in (ident, "*")}
        w(f"  {ident:6s} {tot:7d} {pct(desc, tot):>9s} {pct(conf, tot):>9s} {pct(c[ident], tot):>8s}  {otros}")

    # Matriz de confusion
    simbolos = sorted({s for c in por_id.values() for s in c})
    if simbolos:
        w("\nMATRIZ DE CONFUSION (fila = identidad, columna = lo detectado)")
        w("        " + "".join(f"{s:>7s}" for s in simbolos))
        for ident, c in sorted(por_id.items()):
            w(f"  {ident:5s} " + "".join(f"{c[s]:7d}" for s in simbolos))

    # Falla por distancia al nadir (paralaje)
    w("\nDESCONOCIDAS SEGUN DISTANCIA AL NADIR (sin identidad '?')")
    bins = defaultdict(Counter)
    for p in pres:
        if p["identidad"] == "?":
            continue
        for d in p["dets"]:
            if d["dist_nadir_mm"] == "":
                continue
            x = float(d["dist_nadir_mm"])
            for a, b in zip(BINS_MM, BINS_MM[1:]):
                if a <= x < b:
                    bins[(a, b)]["tot"] += 1
                    bins[(a, b)]["mal"] += d["simbolo"] != p["identidad"]
                    break
    for (a, b), c in sorted(bins.items()):
        w(f"  {a:3d}-{b:<4d} mm: {c['tot']:6d} detecc | error {pct(c['mal'], c['tot'])}")

    # Mapa del tablero: % de error por casilla
    w("\nMAPA DE ERROR POR CASILLA (% de detecciones distintas de la identidad; . = sin datos)")
    celdas = defaultdict(Counter)
    for p in pres:
        for d in p["dets"]:
            k = (int(d["fila"]), int(d["col"]))
            celdas[k]["tot"] += 1
            celdas[k]["mal"] += d["simbolo"] != p["identidad"]
    w("        " + "".join(f"c{c:<4d}" for c in range(8)))
    for f in range(8):
        fila = []
        for c in range(8):
            t = celdas[(f, c)]
            fila.append(f"{100 * t['mal'] / t['tot']:4.0f} " if t["tot"] else "   . ")
        w(f"  f{f}  " + "".join(fila))

    # Rasgos por identidad (para ajustar el clasificador)
    w("\nRASGOS POR IDENTIDAD (vertices, circularidad, relleno y solidez: con esto se ajustan los umbrales)")
    for ident in sorted(por_id):
        if ident == "?":
            continue
        ag = Counter(int(d["agudas"]) for p in pres if p["identidad"] == ident for d in p["dets"])
        cs = [float(d["circ"]) for p in pres if p["identidad"] == ident for d in p["dets"]]
        rl = sorted(float(d["relleno"]) for p in pres if p["identidad"] == ident for d in p["dets"]
                    if d.get("relleno"))
        txt_r = (f" | relleno mediana {rl[len(rl)//2]:.2f} (5%: {rl[len(rl)//20]:.2f}, 95%: {rl[len(rl)*19//20]:.2f})"
                 if rl else "")
        so = sorted(float(d["solidez"]) for p in pres if p["identidad"] == ident for d in p["dets"]
                    if d.get("solidez"))
        txt_s = (f" | solidez mediana {so[len(so)//2]:.2f} (5%: {so[len(so)//20]:.2f}, 95%: {so[len(so)*19//20]:.2f})"
                 if so else "")
        ve = Counter(int(d["vertices"]) for p in pres if p["identidad"] == ident for d in p["dets"])
        en = Counter(d.get("entrantes") or "-" for p in pres if p["identidad"] == ident for d in p["dets"])
        w(f"  {ident}: entrantes {dict(en)} | vertices {dict(sorted(ve.items()))} | circ media {sum(cs)/len(cs):.2f} "
          f"(min {min(cs):.2f}, max {max(cs):.2f}){txt_r}{txt_s}")

    texto = "\n".join(L)
    print(texto)
    nombre = sesiones[0] if len(sesiones) == 1 else "todas"
    with open(os.path.join(carpeta, f"reporte_{nombre}.txt"), "w") as f:
        f.write(texto + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "todas":
        reporte(todas_las_sesiones())
    else:
        reporte(sys.argv[1] if len(sys.argv) > 1 else sesion_reciente())