#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
"""jackrx: receive side of jacktx for a HackRF (or a recorded IQ file).

  python3 -I jackrx.py fm 93.9                 one broadcast FM station: audio to a WAV, stereo pilot, RDS name and text
  python3 -I jackrx.py sweep                   the whole FM band (87.5-108 MHz): spectrum, every station, RDS of the strongest
  python3 -I jackrx.py sweep --band 60-80      any band: spectrum and the strongest signals (no FM decoding outside 87.5-108)
  python3 -I jackrx.py auxwatch                live readout while trying plugs: says when the Mac shows an input on the jack
  python3 -I jackrx.py auxloop                 self-test: the jack plays tones while its own input records them
  python3 -I jackrx.py aux                     the headphone jack as an input (only when the Mac offers one): spectrum up to
                                               48 kHz, VLF stations, and FM stations that fold into the audio band

Options: --secs N (capture length, default 12 for fm, 10 per window for sweep), --lna N --vga N --amp 0|1 (default: automatic),
         --out FILE.wav, --html FILE.html (sweep picture), --decode N (stations to decode in a sweep, default 12),
         --file FILE --center MHZ [--rate HZ] [--format cs8|cu8]  work from a recording instead of the radio.

The HackRF runs at 10 Msps (the HackRF Pro's centre frequency is exact up to 10 Msps and at 20 Msps only). The two helper
programs fmtool and fmrx are built from the .swift files next to this script on first use (needs the Xcode command line tools).
"""
import array, math, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
RATE = 10_000_000


def die(msg):
    sys.exit("jackrx: " + msg)


def helper(name):
    os.makedirs(CACHE, exist_ok=True)
    src, exe = os.path.join(HERE, name + ".swift"), os.path.join(CACHE, name)
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        if not shutil.which("swiftc"):
            die("swiftc not found: install the Xcode command line tools (xcode-select --install)")
        subprocess.run(["swiftc", "-O", src, "-o", exe], check=True, stderr=subprocess.DEVNULL)
    return exe


def opt(args, key, default=None):
    return args[args.index(key) + 1] if key in args and args.index(key) + 1 < len(args) else default


def capture(path, center_hz, secs, lna, vga, amp):
    """One hackrf_transfer run. Returns the average power in dBFS that the tool reports (None if not found)."""
    if not shutil.which("hackrf_transfer"):
        die("hackrf_transfer not found (brew install hackrf)")
    cmd = ["hackrf_transfer", "-r", path, "-f", str(int(center_hz)), "-s", str(RATE), "-n", str(int(RATE * secs)),
           "-l", str(lna), "-g", str(vga), "-a", str(amp)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if not os.path.exists(path) or os.path.getsize(path) < 100000:
        die("the HackRF gave no samples. Is it plugged in and not open in another program?\n" + p.stderr[-300:])
    m = re.findall(r"average power (-?[0-9.]+) dBfs", p.stderr + p.stdout)
    return float(m[-1]) if m else None


def auto_gain(center_hz, args, tmp):
    """Pick gains so the 8-bit converter sits at about -25 dBFS: enough bits for weak stations, no overload by strong ones."""
    if opt(args, "--lna") or opt(args, "--vga"):
        return int(opt(args, "--lna", 16)), int(opt(args, "--vga", 24)), int(opt(args, "--amp", 0))
    lna, vga, amp = 16, 24, int(opt(args, "--amp", 0))
    probe = os.path.join(tmp, "probe.cs8")
    for _ in range(4):
        pw = capture(probe, center_hz, 0.3, lna, vga, amp)
        if pw is None or -30 <= pw <= -20:
            break
        step = 8 if abs(pw + 25) > 9 else 4
        if pw > -20:
            if vga - step >= 0: vga -= step
            elif lna > 0: lna -= 8
            else: break
        else:
            if vga + step <= 46: vga += step
            elif lna < 40: lna += 8
            elif amp == 0 and "--amp" not in args: amp = 1
            else: break
    return lna, vga, amp


def psd_db(path, fmt, rate, nfft=8192, navg=200):
    out = path + ".psd"
    subprocess.run([helper("fmtool"), "psd", path, fmt, str(rate), str(nfft), str(navg), out], check=True, capture_output=True)
    a = array.array("f"); a.frombytes(open(out, "rb").read()); os.remove(out)
    return [10 * math.log10(max(v, 1e-20)) for v in a]


def decode_station(path, fmt, rate, center_hz, freq_hz, wav, tmp):
    """Mix one station to 0 Hz, demodulate, return a dict with level, pilot, RDS fields."""
    cf = os.path.join(tmp, "st.cf32")
    subprocess.run([helper("fmtool"), "front", path, fmt, str(rate), str(int(round(freq_hz - center_hz))), "250000", "110000", cf],
                   check=True, capture_output=True)
    out = subprocess.run([helper("fmrx"), cf, "250000", wav], capture_output=True, text=True).stdout
    r = {"freq": freq_hz, "text": out, "ps": "", "rt": "", "pi": "", "blocks": 0, "pilot": 0.0, "level": 0.0}
    m = re.search(r"level (-?[0-9.]+) dBFS", out);            r["level"] = float(m.group(1)) if m else 0.0
    m = re.search(r"pilot 19 kHz: (-?[0-9.]+) dB", out);       r["pilot"] = float(m.group(1)) if m else 0.0
    m = re.search(r"blocks valid \((\d+) %\)", out);           r["blocks"] = int(m.group(1)) if m else 0
    m = re.search(r'RDS PI ([0-9A-F]{4})\s+PTY (\d+)\s+PS "([^"]*)"', out)
    if m: r["pi"], r["ps"] = m.group(1), m.group(3)
    m = re.search(r'RDS radio text: "([^"]*)"', out);          r["rt"] = m.group(1) if m else ""
    return r


def source(args, center_hz, secs, tmp, tag):
    """Returns (path, format, rate, centre). Either the recording given with --file or a fresh HackRF capture."""
    f = opt(args, "--file")
    if f:
        c = opt(args, "--center")
        if not c: die("--file needs --center MHZ (the recording's centre frequency)")
        return f, opt(args, "--format", "cs8"), int(float(opt(args, "--rate", RATE))), float(c) * 1e6
    lna, vga, amp = auto_gain(center_hz, args, tmp)
    path = os.path.join(tmp, tag + ".cs8")
    pw = capture(path, center_hz, secs, lna, vga, amp)
    print("captured %.0f s at %.3f MHz, 10 Msps (LNA %d, VGA %d, amp %s, average %s dBFS)" %
          (secs, center_hz / 1e6, lna, vga, "on" if amp else "off", "?" if pw is None else "%.1f" % pw))
    return path, "cs8", RATE, center_hz


def cmd_fm(args):
    try: f = float(args[1]) * 1e6
    except (IndexError, ValueError): die("usage: jackrx.py fm FREQ_MHZ   (for example: fm 93.9)")
    wav = opt(args, "--out", os.path.join(os.getcwd(), "fm-%.1f.wav" % (f / 1e6)))
    with tempfile.TemporaryDirectory(prefix="jackrx") as tmp:
        # the station sits 1 MHz above the centre, away from the radio's own spike at the centre
        path, fmt, rate, center = source(args, f - 1e6, float(opt(args, "--secs", 12)), tmp, "fm")
        r = decode_station(path, fmt, rate, center, f, wav, tmp)
    print(r["text"].rstrip())
    return 0


def find_stations(db, rate, center, grid=100e3, half=75e3, thr=8.0):
    """Channel power on the 100 kHz raster; stations are local maxima above the floor."""
    n = len(db); binw = rate / n; lin = [10 ** (v / 10) for v in db]
    lo, hi = center - rate * 0.42, center + rate * 0.42     # skip the filter skirts
    chans = []
    f = math.ceil(lo / grid) * grid
    while f <= hi:
        k1 = int((f - half - center) / binw + n / 2); k2 = int((f + half - center) / binw + n / 2)
        if abs(f - center) > 30e3:                            # the centre spike is not a station
            chans.append((f, 10 * math.log10(sum(lin[k1:k2]) / max(1, k2 - k1))))
        f += grid
    floor = sorted(p for _, p in chans)[max(0, len(chans) // 5)]
    out = []
    for i, (f, p) in enumerate(chans):
        left = chans[i - 1][1] if i else -999; right = chans[i + 1][1] if i + 1 < len(chans) else -999
        if p > floor + thr and p >= left and p >= right:
            out.append((f, p - floor))
    return out, floor


def cmd_sweep(args):
    band = opt(args, "--band", "87.5-108")
    try: lo, hi = [float(x) * 1e6 for x in band.split("-")]
    except ValueError: die("--band LOW-HIGH in MHz, for example --band 87.5-108")
    is_fm = lo >= 87e6 and hi <= 108.5e6
    ndec = int(opt(args, "--decode", 12 if is_fm else 0))
    secs = float(opt(args, "--secs", 10 if ndec else 2))
    html = opt(args, "--html", os.path.join(os.getcwd(), "sweep-%s.html" % band))
    step = 8e6; centers = []; c = lo + step / 2
    while c - step / 2 < hi: centers.append(c); c += step
    spec = []; stations = []
    with tempfile.TemporaryDirectory(prefix="jackrx") as tmp:
        if opt(args, "--file"): centers = [float(opt(args, "--center", 0)) * 1e6]
        for c in centers:
            path, fmt, rate, center = source(args, c, secs, tmp, "sw")
            db = psd_db(path, fmt, rate)
            n = len(db); binw = rate / n
            for k in range(int(n * 0.08), int(n * 0.92)):      # usable 84 % of each window
                fq = center + (k - n / 2) * binw
                if lo <= fq <= hi and (not opt(args, "--file") or True): spec.append((fq, db[k]))
            found, floor = find_stations(db, rate, center, thr=8.0 if is_fm else 10.0)
            found = [(f, s) for f, s in found if lo <= f <= hi and abs(f - center) <= step / 2 + 50e3]
            for f, snr in sorted(found, key=lambda t: -t[1])[:ndec if ndec else 0]:
                r = decode_station(path, fmt, rate, center, f, os.path.join(tmp, "x.wav"), tmp); r["snr"] = snr; stations.append(r)
            for f, snr in found:
                if not any(abs(s["freq"] - f) < 1 for s in stations):
                    stations.append({"freq": f, "snr": snr, "ps": "", "rt": "", "pi": "", "blocks": 0, "pilot": 0.0})
            if not opt(args, "--file"): os.remove(path)
    spec.sort(); stations.sort(key=lambda s: s["freq"])
    # the same station can show up in two windows or on two neighbouring raster points: keep the stronger
    uniq = []
    for s in stations:
        if uniq and abs(uniq[-1]["freq"] - s["freq"]) < 150e3:
            if s["snr"] > uniq[-1]["snr"]: uniq[-1] = s
        else: uniq.append(s)
    print("\n%-10s %7s  %-6s %-5s %-9s %s" % ("MHz", "dB", "pilot", "PI", "name", "radio text"))
    for s in uniq:
        print("%-10.1f %+6.1f  %-6s %-5s %-9s %s" % (s["freq"] / 1e6, s["snr"], "stereo" if s["pilot"] > 15 else "", s["pi"], s["ps"], s["rt"]))
    print("\n%d signals in %s MHz. To listen to one: python3 -I jackrx.py fm FREQ" % (len(uniq), band))
    write_html(html, band, spec, uniq)
    if is_fm:
        import json
        os.makedirs(CACHE, exist_ok=True)
        json.dump([{"mhz": round(x["freq"] / 1e6, 2), "name": x["ps"], "db": round(x["snr"], 1)} for x in uniq], open(os.path.join(CACHE, "last-fm-sweep.json"), "w"))
    print("spectrum picture: " + html)
    return 0


def write_html(path, band, spec, stations):
    # reduce to about 1600 points (maximum per column keeps narrow carriers visible)
    if not spec: return
    f0, f1 = spec[0][0], spec[-1][0]; W = 1600; cols = [-999.0] * W
    for f, v in spec:
        i = min(W - 1, int((f - f0) / (f1 - f0) * (W - 1)))
        if v > cols[i]: cols[i] = v
    last = min(v for v in cols if v > -900)
    cols = [v if v > -900 else last for v in cols]
    marks = [[round(s["freq"] / 1e6, 2), s["ps"] or "", round(s["snr"], 1)] for s in stations]
    doc = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>jackrx sweep %s MHz</title>
<style>body{margin:0;background:#0b0f14;color:#d8e1ea;font:14px system-ui,sans-serif}h1{font-size:16px;margin:12px 16px}
canvas{display:block;width:100%%;height:360px}table{border-collapse:collapse;margin:8px 16px}td,th{padding:2px 10px;text-align:left}
th{color:#8aa}</style><h1>jackrx sweep, %s MHz</h1><canvas id="c" width="1600" height="360"></canvas><table id="t"></table>
<script>const F0=%f,F1=%f,D=%s,M=%s;const c=document.getElementById('c'),g=c.getContext('2d');
const lo=Math.min(...D)-2,hi=Math.max(...D)+6;const y=v=>340-(v-lo)/(hi-lo)*320,x=f=>(f-F0)/(F1-F0)*1599;
g.fillStyle='#0b0f14';g.fillRect(0,0,1600,360);g.strokeStyle='#233';g.fillStyle='#8aa';g.font='12px sans-serif';
for(let f=Math.ceil(F0);f<=F1;f+=Math.max(1,Math.round((F1-F0)/20))){g.beginPath();g.moveTo(x(f),0);g.lineTo(x(f),340);g.stroke();g.fillText(f,x(f)+2,354)}
g.strokeStyle='#4fd1ff';g.beginPath();D.forEach((v,i)=>i?g.lineTo(i,y(v)):g.moveTo(i,y(v)));g.stroke();
g.fillStyle='#ffd166';M.forEach(m=>{if(m[1]){g.save();g.translate(x(m[0])+4,y(D[Math.round(x(m[0]))])-6);g.rotate(-Math.PI/3);g.fillText(m[1],0,0);g.restore()}});
document.getElementById('t').innerHTML='<tr><th>MHz</th><th>dB over floor</th><th>name</th></tr>'+M.map(m=>`<tr><td>${m[0].toFixed(1)}</td><td>${m[2]}</td><td>${m[1]}</td></tr>`).join('');
</script>""" % (band, band, f0 / 1e6, f1 / 1e6, "[" + ",".join("%.1f" % v for v in cols) + "]", repr(marks).replace("'", '"'))
    open(path, "w").write(doc)


# ---------------------------------------------------------------- the jack as an input
VLF = [(16.4, "JXN Norway"), (17.2, "SAQ Sweden"), (18.1, "RDL Russia"), (18.2, "VTX India"), (19.6, "GQD UK"), (19.8, "NWC Australia"),
       (20.27, "ICV Italy"), (20.9, "FTA France"), (21.4, "NPM Hawaii"), (21.75, "HWU France"), (22.1, "GQD UK"), (22.2, "JJI Japan"),
       (23.4, "DHO38 Germany"), (24.0, "NAA USA"), (24.8, "NLK USA"), (25.2, "NML USA"), (26.7, "TBB Turkey"), (37.5, "TFK Iceland"),
       (40.0, "JJY Japan"), (45.9, "NSY Italy"), (60.0, "MSF UK / WWVB / JJY"), (68.5, "BPC China"), (77.5, "DCF77 Germany")]

AUX_HELP = """The Mac offers no input on the headphone jack right now.
It only creates one when the plug has a microphone contact with a microphone-like load on it (about 1-2 kOhm to ground).
A plain 3-pole aux plug shorts that contact to ground inside the socket, so nothing at the free end can change it.
What works:
  1. a 4-pole (3 black rings) cable: 1-2 kOhm between the sleeve and the ring next to it on the free end; the wire goes on the sleeve
  2. a headset splitter (mic + headphones to one 4-pole plug) with a microphone, or that resistor, in its mic socket
  3. experiment: pull a 3-pole plug out by one notch (about 3 mm) and put the resistor between ring and sleeve of the free end
Run this command again after each try: it shows at once whether the input appeared."""


def _fft(re, im):
    n = len(re); j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit: j ^= bit; bit >>= 1
        j |= bit
        if i < j: re[i], re[j] = re[j], re[i]; im[i], im[j] = im[j], im[i]
    ln = 2
    while ln <= n:
        ang = -2 * math.pi / ln; wr, wi = math.cos(ang), math.sin(ang)
        for i in range(0, n, ln):
            cr, ci = 1.0, 0.0
            for k in range(i, i + ln // 2):
                m = k + ln // 2; tr = re[m] * cr - im[m] * ci; ti = re[m] * ci + im[m] * cr
                re[m] = re[k] - tr; im[m] = im[k] - ti; re[k] += tr; im[k] += ti
                cr, ci = cr * wr - ci * wi, cr * wi + ci * wr
        ln <<= 1


def aux_spectrum(x, nfft=16384):
    """Averaged power spectrum (dB) of a real signal, bins 0..nfft/2."""
    win = [0.5 - 0.5 * math.cos(2 * math.pi * i / nfft) for i in range(nfft)]; acc = [0.0] * (nfft // 2); blocks = 0
    for st in range(0, len(x) - nfft + 1, nfft):
        re = [x[st + i] * win[i] for i in range(nfft)]; im = [0.0] * nfft; _fft(re, im)
        for k in range(nfft // 2): acc[k] += re[k] * re[k] + im[k] * im[k]
        blocks += 1
        if blocks >= 24: break
    return [10 * math.log10(max(v / max(1, blocks), 1e-30)) for v in acc]


def fm_folds(rate, stations):
    """FM stations that the converter's fast sampler (128 x the audio rate) would fold into the audio band."""
    clk = 128.0 * (44100 if rate in (44100, 88200) else 48000); out = []
    for mhz, name in stations:
        k = round(mhz * 1e6 / clk); off = mhz * 1e6 - k * clk
        if abs(off) < rate / 2: out.append((mhz, name, k, off))
    return out


def cmd_aux(args):
    exe = helper("auxin")
    devs = [l.split("\t") for l in subprocess.run([exe, "list"], capture_output=True, text=True).stdout.splitlines() if l]
    uid = opt(args, "--uid")
    jack = [d for d in devs if d[3] == "1"]
    print("input devices: " + "; ".join("%s (%s)" % (d[1], d[0]) for d in devs))
    if not uid:
        if not jack:
            print(AUX_HELP); return 1
        uid = jack[0][0]; print("the jack's input is present: %s" % jack[0][1])
    if uid == "BuiltInMicrophoneDevice": die("the built-in microphone is never recorded")
    dev = next((d for d in devs if d[0] == uid), None)
    if not dev: die("no input device with UID " + uid)
    secs = float(opt(args, "--secs", 6)); stations = []
    try:
        import json
        stations = [(s["mhz"], s["name"]) for s in json.load(open(os.path.join(CACHE, "last-fm-sweep.json")))]
    except (OSError, ValueError): stations = [(f, "") for f in (91.5, 92.0, 93.0, 93.9, 97.1)]
    outdir = opt(args, "--outdir", os.getcwd())
    for rate in [int(r) for r in dev[2].split() if int(r) in (44100, 48000, 88200, 96000)]:
        raw = os.path.join(outdir, "aux-%d.f32" % rate)
        r = subprocess.run([exe, "rec", uid, str(rate), str(secs), raw], capture_output=True, text=True)
        if r.returncode: print("%d Hz: %s" % (rate, r.stderr.strip())); continue
        x = array.array("f"); x.frombytes(open(raw, "rb").read())
        if not x or max(abs(v) for v in x) == 0: print("%d Hz: recorded silence (all zeros)" % rate); continue
        db = aux_spectrum(x); n = len(db); binw = rate / 2 / n; floor = sorted(db)[n // 2]
        print("\n== %d Hz: %.1f s, peak %.1f dBFS, noise floor %.1f dB per %.1f Hz bin" % (rate, len(x) / rate, 20 * math.log10(max(abs(v) for v in x)), floor, binw))
        pk = sorted([k for k in range(3, n - 1) if db[k] > floor + 10 and db[k] >= db[k - 1] and db[k] >= db[k + 1]], key=lambda k: -db[k])[:14]
        for k in sorted(pk):
            f = k * binw; tag = next((nm for khz, nm in VLF if abs(f - khz * 1e3) < 120), "")
            if f < 1000 and min(abs(f - h * 50) for h in range(1, 21)) < 2 * binw: tag = "mains hum (50 Hz harmonic)"
            print("   %9.1f Hz  +%.1f dB  %s" % (f, db[k] - floor, tag))
        if not pk: print("   no carrier more than 10 dB over the floor")
        folds = fm_folds(rate, stations)
        for mhz, name, k, off in folds:
            kb = int(abs(off) / binw); band = db[max(1, kb - int(15e3 / binw)):min(n, kb + int(15e3 / binw))]
            print("   FM %.1f MHz %s: harmonic %d of the %.4f MHz sampler puts it at %.1f kHz -> %+.1f dB over the floor there"
                  % (mhz, name, k, 128 * (44100 if rate in (44100, 88200) else 48000) / 1e6, abs(off) / 1e3, sorted(band)[len(band) // 2] - floor))
            wav = os.path.join(outdir, "aux-fm-%.1f-%d.wav" % (mhz, rate))
            r2 = subprocess.run([helper("auxfm"), raw, str(rate), str(off), wav], capture_output=True, text=True)
            for ln in r2.stdout.splitlines(): print("      " + ln)
            print("      a pilot lock above about 0.3 means the station really is in the recording (a real station gave 0.54, noise 0.10); listen to " + wav)
        if not folds: print("   no known FM station folds into the audio band at this rate")
    return 0



def cmd_auxloop(args):
    """Self-test: the jack plays a tone while the jack's own input records. Two things can show up in the recording:
    the tone itself (plain audio leaking from the output wires to the mic wire) and, if the input's fast sampler folds
    radio frequencies into the audio band, nothing new at this frequency (the 6.144 MHz line folds to 0 Hz and its audio
    sidebands fold back onto the tone). The two are told apart by level against frequency: audio leakage through the
    cable grows with frequency, a folded line does not, and by the phase jumps of the tone when the plug is moved."""
    exe = helper("auxin"); jack = os.path.join(CACHE, "jackaudio")
    devs = [l.split("\t") for l in subprocess.run([exe, "list"], capture_output=True, text=True).stdout.splitlines() if l]
    uid = opt(args, "--uid") or next((d[0] for d in devs if d[3] == "1"), None)
    if not uid: print(AUX_HELP); return 1
    if not os.path.exists(jack): die("run jacktx.py once first (it builds the playback helper)")
    import wave
    rate = int(opt(args, "--rate", 96000)); outdir = opt(args, "--outdir", os.getcwd())
    print("tone Hz : level in the recording (dB over the floor) : level with the output silent")
    for tone in (1000, 5000, 10000, 20000, 30000, 40000):
        res = []
        for amp in (0.89, 0.0):
            wav = os.path.join(outdir, "loop.wav"); n = int(rate * 4.0); a = array.array("h", bytes(4 * n))
            for i in range(n):
                v = int(amp * 32767 * math.sin(2 * math.pi * tone * i / rate)); a[2 * i] = v; a[2 * i + 1] = v
            w = wave.open(wav, "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(rate); w.writeframes(a.tobytes()); w.close()
            subprocess.run([jack, "set", str(rate)], capture_output=True)
            pl = subprocess.Popen([jack, "play", wav], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            import time; time.sleep(1.0)
            raw = os.path.join(outdir, "loop.f32"); subprocess.run([exe, "rec", uid, str(rate), "2", raw], capture_output=True); pl.wait()
            x = array.array("f"); x.frombytes(open(raw, "rb").read())
            if not x or max(abs(v) for v in x) == 0: res.append(None); continue
            db = aux_spectrum(x); nb = len(db); k = int(tone / (rate / 2) * nb); floor = sorted(db)[nb // 2]
            res.append(max(db[max(0, k - 3):k + 4]) - floor)
        print("%7d : %s : %s" % (tone, "silence" if res[0] is None else "%+.1f" % res[0], "silence" if res[1] is None else "%+.1f" % res[1]))
    return 0



def jack_state():
    """What the Mac currently thinks is in the jack: (input present, output present, the codec's last detection)."""
    exe = helper("auxin")
    devs = [l.split("\t") for l in subprocess.run([exe, "list"], capture_output=True, text=True).stdout.splitlines() if l]
    has_in = any(d[3] == "1" for d in devs)
    out = subprocess.run(["system_profiler", "SPAudioDataType"], capture_output=True, text=True).stdout
    has_out = "External Headphones" in out or "Headphones" in out
    reg = subprocess.run(["ioreg", "-l", "-w0"], capture_output=True, text=True).stdout
    det = ""
    m = re.findall(r'"headset info"=\{([^}]*)\}', reg)
    if m:
        mic = re.search(r'"microphone"=(Yes|No)', m[-1]); det = "codec says microphone: " + (mic.group(1) if mic else "?")
    return has_in, has_out, det


def cmd_auxwatch(args):
    """Live readout while trying plugs and resistors: one line every time the Mac's view of the jack changes."""
    import time
    secs = float(opt(args, "--secs", 900)); t0 = time.time(); last = None
    print("watching the headphone jack for %d s (Ctrl+C to stop). Try a connection, wait 2 s, look here." % secs)
    while time.time() - t0 < secs:
        st = jack_state()
        if st != last:
            has_in, has_out, det = st
            print("%s  plug detected: %-3s  INPUT: %-12s %s" % (time.strftime("%H:%M:%S"), "yes" if has_out else "no",
                  "YES, present" if has_in else "no", det), flush=True)
            if has_in: print("          the input is there. Keep the connection as it is and run: python3 -I jackrx.py aux", flush=True)
            last = st
        time.sleep(1.0)
    return 0



def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__); return 0
    if args[0] in ("fm", "wfm", "rds"): return cmd_fm(args)
    if args[0] == "sweep": return cmd_sweep(args)
    if args[0] == "aux": return cmd_aux(args)
    if args[0] == "auxloop": return cmd_auxloop(args)
    if args[0] == "auxwatch": return cmd_auxwatch(args)
    die("unknown command %r (fm, sweep, aux)" % args[0])


if __name__ == "__main__":
    sys.exit(main())
