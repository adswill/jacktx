#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
"""zck: zero-crossing keying test. The jack's RF lines are switched by the SIGN of the audio, so a sine at f puts
square-wave sidebands at f, 3f, 5f ... around every line. Keying f between two values makes a frequency-shift signal
whose k-th copy is k times as wide. This script makes the audio, and reads the message back from a HackRF capture,
separately for each harmonic, to show how far from the line the information can still be recovered.

  zck.py tx OUT.wav "TEXT"            audio for the jack (96 kHz)
  zck.py rx SPECTROGRAM.f32 "TEXT"    decode; the spectrogram is labdsp psd --rate 2e6 --nfft 32768 --seg 0.016384
"""
import array, math, sys, wave
import os
NF = int(os.environ.get('ZCK_FRAMES', '4'))    # spectrogram frames per symbol: 4 = 15.3 bit/s, 8 = 7.6 bit/s
RATE = 96000; F0, F1 = 37000.0, 44000.0; FRAME = 32768 / 2e6; SYM = NF * FRAME
LINE = 18.432e6; CENTER = 18.7e6; NFFT = 32768; SR = 2e6
SYNC = [int(b) for b in "0010110111010100"]

def bits_of(text):
    pre = [1, 0] * 12
    data = [int(b) for ch in text.encode() for b in format(ch, "08b")]
    return pre + SYNC + data

def tx(out, text):
    bits = bits_of(text); n = int((len(bits) * SYM + 1.0) * RATE); s = array.array("h", bytes(4 * n)); ph = 0.0
    for i in range(n):
        t = i / RATE - 0.5; k = int(t / SYM); f = (F1 if bits[k] else F0) if 0 <= t and k < len(bits) else F0
        ph += 2 * math.pi * f / RATE; v = int(0.89 * 32767 * math.sin(ph)); s[2 * i] = v; s[2 * i + 1] = v
    w = wave.open(out, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(s.tobytes()); w.close()
    print("%d symbols, %.1f s, %.2f bit/s, tones %.0f / %.0f Hz" % (len(bits), n / RATE, 1 / SYM, F0, F1))

def rx(sg, text):
    a = array.array("f"); a.frombytes(open(sg, "rb").read()); rows = len(a) // NFFT; bits = bits_of(text)
    lin = lambda r, k: 10 ** (a[r * NFFT + k] / 10)
    # the line itself: strongest bin near the nominal frequency, averaged over time
    k0 = int((LINE - CENTER) / SR * NFFT + NFFT / 2)
    avg = [sum(lin(r, k) for r in range(0, rows, 8)) for k in range(k0 - 30, k0 + 31)]
    kc = k0 - 30 + avg.index(max(avg)); fc = CENTER + (kc - NFFT / 2) * SR / NFFT; ppm = (fc - LINE) / LINE
    print("line at %.6f MHz (%+.1f ppm), %d spectrogram rows" % (fc / 1e6, ppm * 1e6, rows))
    def band(r, f):   # power near one frequency, in units of the local noise
        k = int(round((f - CENTER) / SR * NFFT + NFFT / 2))
        if k < 8 or k > NFFT - 8: return 0.0
        return max(lin(r, k - 1), lin(r, k), lin(r, k + 1))
    def noise(f):
        k = int(round((f - CENTER) / SR * NFFT + NFFT / 2)); v = sorted(lin(r, k + d) for r in range(0, rows, 16) for d in (-9, -7, 7, 9)); return v[len(v) // 2]
    def metric(k, side):   # per row: (power at the 1-tone) - (power at the 0-tone), noise-normalised
        f1 = fc + side * k * F1 * (1 + ppm); f0 = fc + side * k * F0 * (1 + ppm); n1, n0 = noise(f1), noise(f0)
        if n1 <= 0 or n0 <= 0: return None
        return [band(r, f1) / n1 - band(r, f0) / n0 for r in range(rows)]
    ks = [1, 3, 5, 7, 9, 11, 13]
    m = {(k, s): metric(k, s) for k in ks for s in (-1, 1)}
    def decide(keys, off, start):
        out = []
        for i in range(len(bits)):
            r0 = start + off + NF * i
            if r0 + NF > rows: return None
            out.append(1 if sum(m[key][r] / key[0] for key in keys if m[key] for r in range(r0 + 1, r0 + NF - 1)) > 0 else 0)   # inner frames, weight 1/k
        return out
    # timing from the strongest copies: the alignment that best matches the known preamble and sync word
    head = bits[:40]; best = (-1, 0, 0)
    for start in range(0, rows - NF * len(bits), 1):
        d = decide([(1, -1), (1, 1)], 0, start)
        if d is None: break
        sc = sum(1 for x, y in zip(d[:40], head) if x == y)
        if sc > best[0]: best = (sc, start, 0)
    print("sync: %d of 40 header bits at row %d" % (best[0], best[1]))
    start = best[1]
    def report(name, keys):
        d = decide(keys, 0, start)
        if d is None: print("%-34s capture too short" % name); return
        err = sum(1 for x, y in zip(d, bits) if x != y); pay = d[40:]
        txt = bytes(int("".join(map(str, pay[i:i + 8])), 2) for i in range(0, len(pay) - 7, 8)).decode("latin1")
        print("%-34s %3d bit errors of %d   text: %r" % (name, err, len(bits), "".join(c if 32 <= ord(c) < 127 else "?" for c in txt)))
    report("all copies", [(k, -1) for k in ks] + [(1, 1), (3, 1)])
    for k in ks:
        report("k=%2d only (line -%3.0f / -%3.0f kHz)" % (k, k * F0 / 1e3, k * F1 / 1e3), [(k, -1)])
    for kmin in (3, 5, 7, 9):
        report("only beyond %3.0f kHz (k >= %d)" % (kmin * F0 / 1e3, kmin), [(k, -1) for k in ks if k >= kmin])

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "tx": tx(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 4 and sys.argv[1] == "rx": rx(sys.argv[2], sys.argv[3])
    else: print(__doc__)
