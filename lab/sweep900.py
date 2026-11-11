#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
"""sweep900: step one emission across 900 kHz and check it at every step.

The jack's lines ("teeth") sit every 512 kHz and each one carries copies of the audio tone at k x f (k odd). For a
target frequency this script picks the nearest tooth and the smallest k with k x f = distance, f <= 45 kHz. Played
in order, the chosen copy walks across the band in 10 kHz steps.

  sweep900.py tx OUT.wav                 audio: 1 s marker (20 kHz), then one step per second
  sweep900.py rx CAPTURE.cs8 OUT.csv     capture: hackrf_transfer -f 73950000 -s 2000000 (cs8). Needs lab/bin/zckrx
"""
import array, math, os, subprocess, sys, tempfile, wave
RATE = 96000; SR = 2e6; CENTER = 73.95e6; TOOTH0 = 73.728e6; SPACING = 512e3; DWELL = 1.0; MARK = 1.0
STEPS = [TOOTH0 + o * 1e3 for o in range(-450, 451, 10)]

def plan(F):
    T = TOOTH0 + round((F - TOOTH0) / SPACING) * SPACING; o = F - T
    if abs(o) < 4e3: return T, 0, 0.0, 0          # the tooth itself
    k = 1
    while abs(o) / k > 45e3: k += 2
    return T, k, abs(o) / k, (1 if o > 0 else -1)

def tx(out):
    seq = [(MARK, 20000.0)] + [(DWELL, plan(F)[2] or 20000.0) for F in STEPS] + [(0.5, 20000.0)]
    n = int(sum(d for d, _ in seq) * RATE); s = array.array("h", bytes(4 * n)); ph = 0.0; i = 0
    for d, f in seq:
        for _ in range(int(d * RATE)):
            ph += 2 * math.pi * f / RATE; v = int(0.89 * 32767 * math.sin(ph)); s[2 * i] = v; s[2 * i + 1] = v; i += 1
    w = wave.open(out, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(s.tobytes()); w.close()
    print("%d steps, %.0f s" % (len(STEPS), n / RATE))

def zck(path, chunk, freqs):
    here = os.path.dirname(os.path.abspath(__file__)); o = path + ".o"
    subprocess.run([os.path.join(here, "bin", "zckrx"), path, str(SR), str(chunk), o] + ["%.3f" % f for f in freqs], check=True, capture_output=True)
    a = array.array("f"); a.frombytes(open(o, "rb").read()); os.remove(o); nf = len(freqs); rows = len(a) // (2 * nf)
    return [[a[2 * (r * nf + j)] ** 2 + a[2 * (r * nf + j) + 1] ** 2 for j in range(nf)] for r in range(rows)]

def piece(cap, t0, dur, tmp):
    p = os.path.join(tmp, "p.cs8")
    with open(cap, "rb") as f:
        f.seek(int(t0 * SR) * 2); open(p, "wb").write(f.read(int(dur * SR) * 2))
    return p

def rx(cap, out):
    tmp = tempfile.mkdtemp(prefix="sw9")
    # 1. where does the marker end? power of the 20 kHz copies of the main tooth in 50 ms pieces of the first 8 s
    p = piece(cap, 0, 8, tmp); rows = zck(p, int(0.05 * SR), [TOOTH0 - CENTER - 265 + d for d in (-20000, 20000)])
    pw = [r[0] + r[1] for r in rows]; thr = (max(pw) + sorted(pw)[len(pw) // 4]) / 2
    on = [i for i, v in enumerate(pw) if v > thr]; t_mark = on[0] * 0.05
    # 2. the tooth's exact frequency during the marker (clock error), 1 Hz steps
    p = piece(cap, t_mark + 0.1, 0.8, tmp); cand = [TOOTH0 - CENTER + d for d in range(-600, 101, 2)]
    r = zck(p, int(0.8 * SR), cand)[0]; ft = CENTER + cand[r.index(max(r))]; ppm = (ft - TOOTH0) / TOOTH0
    # refine the marker end with the first step's own tone if needed: keep simple, steps start MARK after t_mark
    print("marker starts at %.2f s, tooth at %.6f MHz (%+.2f ppm)" % (t_mark, ft / 1e6, ppm * 1e6))
    res = []
    for i, F in enumerate(STEPS):
        T, k, f, side = plan(F); t0 = t_mark + MARK + i * DWELL + 0.1
        target = (T + side * k * f) * (1 + ppm) - CENTER if k else T * (1 + ppm) - CENTER
        span = [d * 1.25 for d in range(-32, 33)]                        # +-40 Hz in 1.25 Hz steps
        freqs = [target + d for d in span] + [target + 400 + d for d in span] + [target - 400 + d for d in span]
        rr = zck(piece(cap, t0, 0.8, tmp), int(0.8 * SR), freqs)[0]; n = len(span)
        sig = rr[:n]; ctl = rr[n:2 * n]; ref = rr[2 * n:]
        mean_noise = (sum(ctl) + sum(ref)) / (2 * n)
        res.append((F, T, k, f, 10 * math.log10(max(sig) / mean_noise), 10 * math.log10(max(ctl) / mean_noise)))
        print("%9.3f MHz  tooth %.3f  k=%2d  f=%6.0f Hz  signal %+5.1f dB  control %+5.1f dB" % (F / 1e6, T / 1e6, k, f, res[-1][4], res[-1][5]))
    with open(out, "w") as o:
        o.write("mhz,tooth_mhz,k,audio_hz,signal_db,control_db\n")
        for r in res: o.write("%.3f,%.3f,%d,%.0f,%.2f,%.2f\n" % (r[0] / 1e6, r[1] / 1e6, r[2], r[3], r[4], r[5]))
    c = sorted(r[5] for r in res); lim = c[int(len(c) * 0.95)]
    print("detected (above the 95 %% point of the control, %+.1f dB): %d of %d steps" % (lim, sum(1 for r in res if r[4] > lim), len(res)))

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "tx": tx(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "rx": rx(sys.argv[2], sys.argv[3])
    else: print(__doc__)
