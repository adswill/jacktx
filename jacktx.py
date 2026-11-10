#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Kristijonas Adomaitis. Based on jacktx by Kristijonas Adomaitis - https://github.com/adswill/jacktx
# jacktx.py - transmit test signals out of a MacBook headphone jack. The DAC clock leaks at 6.144 MHz
# (96 kHz output rate); audio at f appears as RF at 6.144 MHz + f (usable f 2..46 kHz). Python stdlib + ffmpeg/afconvert/afplay.
#   python3 -I jacktx.py -<mode> [--level -1] [--render-only]      python3 -I jacktx.py --selftest
# Windows/Linux: playback via winsound / aplay / sounddevice, --clock MHZ for the chip's clock, -find to locate it (see README).
import array, math, os
# ---- common helpers (merged into jacktx.py) ----
import array, math

RATE = 96000

# 5x7 bitmap font, own design. Each glyph: 7 rows, 5 bits per row (MSB = left column).
_FONT = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "00000 00000 00000 00000 00000 00000 00000", ".": "00000 00000 00000 00000 00000 01100 01100",
    ",": "00000 00000 00000 00000 01100 00100 01000", ":": "00000 01100 01100 00000 01100 01100 00000",
    "-": "00000 00000 00000 11111 00000 00000 00000", "/": "00001 00001 00010 00100 01000 10000 10000",
    "+": "00000 00100 00100 11111 00100 00100 00000", "=": "00000 00000 11111 00000 11111 00000 00000",
    "'": "00100 00100 01000 00000 00000 00000 00000", "!": "00100 00100 00100 00100 00100 00000 00100",
    "?": "01110 10001 00001 00010 00100 00000 00100", "(": "00010 00100 01000 01000 01000 00100 00010",
    ")": "01000 00100 00010 00010 00010 00100 01000", "#": "01010 01010 11111 01010 11111 01010 01010",
}


def text_mask(text, scale=1):
    """Render text with the 5x7 font: returns (width, height, rows) where rows[y][x] is 0 or 1. 1 column gap between glyphs."""
    text = text.upper()
    w = max(1, len(text) * 6 - 1) * scale; h = 7 * scale
    rows = [[0] * w for _ in range(h)]
    for ci, ch in enumerate(text):
        g = _FONT.get(ch, _FONT["?"]).split()
        for gy in range(7):
            for gx in range(5):
                if g[gy][gx] == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            rows[gy * scale + sy][(ci * 6 + gx) * scale + sx] = 1
    return w, h, rows


def draw_text(img, x0, y0, text, scale, color):
    """img: list of rows of pixels (any value type); writes `color` where the text is set."""
    w, h, m = text_mask(text, scale)
    H = len(img); W = len(img[0])
    for y in range(h):
        if 0 <= y0 + y < H:
            row = img[y0 + y]; mr = m[y]
            for x in range(w):
                if mr[x] and 0 <= x0 + x < W: row[x0 + x] = color
# ---- digital modes: FT8, WSPR, APRS, POCSAG (merged into jacktx.py after part_common.py) ----
# Ported from OnAir core/src/hfdig (FT8/WSPR), core/src/packet/packet_gen.cpp, core/src/pager (pager_gen.cpp, pager_proto.cpp).
import array, math, os

# (174,91) LDPC generator rows (83 x 91 bits, MSB first, hex), from ft8_lib ft8/constants.c (Karlis Goba, MIT) as used in
# OnAir's hfdig_ftx_tables.cpp; the same as WSJT-X ldpc_174_91_c_generator.f90 (K1JT et al., GPL-3).
_FT8_GEN = (
    "8329ce11bf31eaf509f27fc0", "761c264e25c2593354931320", "dc265902fb277c6410a1bdc0",
    "1b3f417858cd2dd33ec7f620", "09fda4fee04195fd034783a0", "077cccc11b8873ed5c3d48a0",
    "29b62afe3ca036f4fe1a9da0", "6054faf5f35d96d3b0c8c3e0", "e20798e4310eed27884ae900",
    "775c9c08e80e26ddae563180", "b0b811028c2bf997213487c0", "18a0c9231fc60adf5c5ea320",
    "76471e8302a0721e01b12b80", "ffbccb80ca8341fafb47b2e0", "66a72a158f9325a2bf671700",
    "c4243689fe85b1c51363a180", "0dff739414d1a1b34b1c2700", "15b48830636c8b99894972e0",
    "29a89c0d3de81d665489b0e0", "4f126f37fa51cbe61bd6b940", "99c47239d0d97d3c84e09400",
    "1919b75119765621bb4f1e80", "09db12d731faee0b86df6b80", "488fc33df43fbdeea4eafb40",
    "827423ee40b675f756eb5fe0", "abe197c484cb74757144a9a0", "2b500e4bc0ec5a6d2bdbdd00",
    "c474aa53d702187616693600", "8eba1a13db3390bd6718cec0", "753844673a27782cc42012e0",
    "06ff83a145c37035a5c12680", "3b37417858cc2dd33ec3f620", "9a4a5a28ee17ca9c324842c0",
    "bc29f465309c977e89610a40", "2663ae6ddf8b5ce2bb294880", "46f231efe457034c18144180",
    "3fb2ce85abe9b0c72e06fbe0", "de87481f282c153971a0a2e0", "fcd7ccf23c69fa99bba14120",
    "f0261447e9490ca8e474cec0", "4410115818196f95cdd70120", "088fc31df4bfbde2a4eafb40",
    "b8fef1b6307729fb0a078c00", "5afea7acccb77bbc9d99a900", "49a7016ac653f65ecdc90760",
    "1944d085be4e7da8d6cc7d00", "251f62adc4032f0ee7140020", "56471f8702a0721e00b12b80",
    "2b8e4923f2dd51e2d537fa00", "6b550a40a66f4755de95c260", "a18ad28d4e27fe92a4f6c840",
    "10c2e586388cb82a3d807580", "ef34a41817ee02133db2eb00", "7e9c0c54325a9c15836e0000",
    "3693e572d1fde4cdf079e860", "bfb2cec5abe1b0c72e07fbe0", "7ee18230c583cccc57d4b080",
    "a066cb2fedafc9f526641260", "bb23725abc47cc5f4cc4cd20", "ded9dba3bee40c59b5609b40",
    "d9a7016ac653e6decdc90360", "9ad46aed5f707f280ab5fc40", "e5921c77822587316d7d3c20",
    "4f14da8242a8b86dca733520", "8b8b507ad467d4441df770e0", "22831c9cf1169467ad04b680",
    "213b838fe2ae54c38ee71800", "5d926b6dd71f085181a4e120", "66ab79d4b29ee6e69509e560",
    "958148682d748a38dd68baa0", "b8ce020cf069c32a723ab140", "f4331d6d461607e957527460",
    "6da23ba424b9596133cf9c80", "a636bcbc7b30c5fbeae67fe0", "5cb0d86a07df654a9089a200",
    "f11f106848780fc9ecdd80a0", "1fbb5364fb8d2c9d730d5ba0", "fcb86bc70a50c9d02a5d0340",
    "a534433029eac15f322e34c0", "c989d9c7c3d3b8c55d751300", "7bb38b2f0186d46643ae9620",
    "2644ebadeb44b9467d1f42c0", "608cc857594bfbb55d696000",
)
# Parity checks: the 1-origin codeword bits of each of the 83 checks (0 = unused), ft8_lib ft8/constants.c (MIT) / WSJT-X.
_FT8_NM = (
    (4, 31, 59, 91, 92, 96, 153), (5, 32, 60, 93, 115, 146, 0), (6, 24, 61, 94, 122, 151, 0), (7, 33, 62, 95, 96, 143, 0), (8, 25, 63, 83, 93, 96, 148), (6, 32, 64, 97, 126, 138, 0),
    (5, 34, 65, 78, 98, 107, 154), (9, 35, 66, 99, 139, 146, 0), (10, 36, 67, 100, 107, 126, 0), (11, 37, 67, 87, 101, 139, 158), (12, 38, 68, 102, 105, 155, 0), (13, 39, 69, 103, 149, 162, 0),
    (8, 40, 70, 82, 104, 114, 145), (14, 41, 71, 88, 102, 123, 156), (15, 42, 59, 106, 123, 159, 0), (1, 33, 72, 106, 107, 157, 0), (16, 43, 73, 108, 141, 160, 0), (17, 37, 74, 81, 109, 131, 154),
    (11, 44, 75, 110, 121, 166, 0), (45, 55, 64, 111, 130, 161, 173), (8, 46, 71, 112, 119, 166, 0), (18, 36, 76, 89, 113, 114, 143), (19, 38, 77, 104, 116, 163, 0), (20, 47, 70, 92, 138, 165, 0),
    (2, 48, 74, 113, 128, 160, 0), (21, 45, 78, 83, 117, 121, 151), (22, 47, 58, 118, 127, 164, 0), (16, 39, 62, 112, 134, 158, 0), (23, 43, 79, 120, 131, 145, 0), (19, 35, 59, 73, 110, 125, 161),
    (20, 36, 63, 94, 136, 161, 0), (14, 31, 79, 98, 132, 164, 0), (3, 44, 80, 124, 127, 169, 0), (19, 46, 81, 117, 135, 167, 0), (7, 49, 58, 90, 100, 105, 168), (12, 50, 61, 118, 119, 144, 0),
    (13, 51, 64, 114, 118, 157, 0), (24, 52, 76, 129, 148, 149, 0), (25, 53, 69, 90, 101, 130, 156), (20, 46, 65, 80, 120, 140, 170), (21, 54, 77, 100, 140, 171, 0), (35, 82, 133, 142, 171, 174, 0),
    (14, 30, 83, 113, 125, 170, 0), (4, 29, 68, 120, 134, 173, 0), (1, 4, 52, 57, 86, 136, 152), (26, 51, 56, 91, 122, 137, 168), (52, 84, 110, 115, 145, 168, 0), (7, 50, 81, 99, 132, 173, 0),
    (23, 55, 67, 95, 172, 174, 0), (26, 41, 77, 109, 141, 148, 0), (2, 27, 41, 61, 62, 115, 133), (27, 40, 56, 124, 125, 126, 0), (18, 49, 55, 124, 141, 167, 0), (6, 33, 85, 108, 116, 156, 0),
    (28, 48, 70, 85, 105, 129, 158), (9, 54, 63, 131, 147, 155, 0), (22, 53, 68, 109, 121, 174, 0), (3, 13, 48, 78, 95, 123, 0), (31, 69, 133, 150, 155, 169, 0), (12, 43, 66, 89, 97, 135, 159),
    (5, 39, 75, 102, 136, 167, 0), (2, 54, 86, 101, 135, 164, 0), (15, 56, 87, 108, 119, 171, 0), (10, 44, 82, 91, 111, 144, 149), (23, 34, 71, 94, 127, 153, 0), (11, 49, 88, 92, 142, 157, 0),
    (29, 34, 87, 97, 147, 162, 0), (30, 50, 60, 86, 137, 142, 162), (10, 53, 66, 84, 112, 128, 165), (22, 57, 85, 93, 140, 159, 0), (28, 32, 72, 103, 132, 166, 0), (28, 29, 84, 88, 117, 143, 150),
    (1, 26, 45, 80, 128, 147, 0), (17, 27, 89, 103, 116, 153, 0), (51, 57, 98, 163, 165, 172, 0), (21, 37, 73, 138, 152, 169, 0), (16, 47, 76, 130, 137, 154, 0), (3, 24, 30, 72, 104, 139, 0),
    (9, 40, 90, 106, 134, 151, 0), (15, 58, 60, 74, 111, 150, 163), (18, 42, 79, 144, 146, 152, 0), (25, 38, 65, 99, 122, 160, 0), (17, 42, 75, 129, 170, 172, 0),
)
# WSPR sync vector, from WSJT-X wsprd.c / wsprsim_utils.c (K1JT, GPL-3), cross-checked against JTEncode (Etherkit) in OnAir.
_WSPR_SYNC = "110000001000111000100101111000000010010100000010110011010001101000011010101010010010110001101010001000001001001110110011010001110000010100110000000110101100011000"

# ---------------------------------------------------------------- shared small helpers of the digital modes

def _aprs_mhz(audio_hz):
    return "%.6f MHz" % ((CLOCK_HZ + audio_hz) / 1e6)


def _aprs_cache(cache_dir, name, build):
    """array('f') cached as raw float32 in cache_dir (rebuilt when missing)."""
    path = os.path.join(cache_dir, name + ".f32") if cache_dir else None
    if path and os.path.exists(path):
        a = array.array("f")
        with open(path, "rb") as f:
            a.frombytes(f.read())
        return a
    a = build()
    if path:
        os.makedirs(cache_dir, exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            a.tofile(f)
        os.replace(path + ".tmp", path)
    return a


def _aprs_fm(freq_dev, rate, fc, ramp_s=0.002):
    """Real FM signal cos(2 pi fc t + theta), theta the integral of freq_dev (Hz per sample), short on/off ramps."""
    n = len(freq_dev)
    out = array.array("f", bytes(4 * n))
    k = 2 * math.pi / rate
    w0 = k * fc
    th = 0.0
    nr = max(1, int(ramp_s * rate))
    cos = math.cos
    for i in range(n):
        th += w0 + k * freq_dev[i]
        if th > 1e4:
            th = math.fmod(th, 2 * math.pi)
        out[i] = cos(th)
    for i in range(min(nr, n // 2)):
        g = 0.5 * (1 - math.cos(math.pi * i / nr))
        out[i] *= g
        out[n - 1 - i] *= g
    return out


def _aprs_fmdemod(x, rate, fc):
    """Test-only FM discriminator: mix to 0 Hz, moving average that nulls 2 fc, phase difference -> Hz per sample."""
    n_avg = 12
    for n in range(8, 64):
        v = 2 * fc * n / rate
        if round(v) >= 1 and abs(v - round(v)) < 1e-9:
            n_avg = n
            break
    w = 2 * math.pi * fc / rate
    re = [x[i] * math.cos(w * i) for i in range(len(x))]
    im = [-x[i] * math.sin(w * i) for i in range(len(x))]
    def mavg(a):
        o = [0.0] * len(a); s = 0.0
        for i, v in enumerate(a):
            s += v
            if i >= n_avg: s -= a[i - n_avg]
            o[i] = s
        return o
    re, im = mavg(re), mavg(im)
    f = [0.0] * len(x)
    for i in range(1, len(x)):
        a = re[i] * re[i - 1] + im[i] * im[i - 1]
        b = im[i] * re[i - 1] - re[i] * im[i - 1]
        f[i] = math.atan2(b, a) * rate / (2 * math.pi)
    return f, n_avg // 2


# ---------------------------------------------------------------- FT8 (ported from OnAir hfdig_ftx.cpp / hfdig_ftx_msg.cpp / hfdig_ftx_tables.cpp)
# Algorithms after WSJT-X (K1JT et al., GPL-3: genft8.f90, encode174_91.f90, crc14.cpp, packjt77.f90) and ft8_lib (K. Goba, MIT).

_FT8_COSTAS = (3, 1, 4, 0, 6, 5, 2)      # WSJT-X genft8.f90 / ft8_lib constants.c
_FT8_GRAY = (0, 1, 3, 2, 5, 6, 4, 7)     # WSJT-X genft8.f90 / ft8_lib constants.c
_FT8_A1 = " 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FT8_A2 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FT8_A3 = "0123456789"
_FT8_A4 = " ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_FT8_NTOK, _FT8_MAX22 = 2063592, 4194304
_FT8_GENI = tuple(int(r, 16) >> 5 for r in _FT8_GEN)   # 91-bit rows


def _ft8_basecall(call):
    n = len(call)
    if n < 3: return -1
    if n <= 6 and call[2].isdigit(): c6 = call
    elif n <= 5 and call[1].isdigit(): c6 = " " + call
    else: return -1
    c6 = (c6 + "      ")[:6]
    try:
        i = (_FT8_A1.index(c6[0]), _FT8_A2.index(c6[1]), _FT8_A3.index(c6[2]),
             _FT8_A4.index(c6[3]), _FT8_A4.index(c6[4]), _FT8_A4.index(c6[5]))
    except ValueError:
        return -1
    for k in (3, 4):
        if c6[k] == " " and c6[k + 1] != " ": return -1
    return ((((i[0] * 36 + i[1]) * 10 + i[2]) * 27 + i[3]) * 27 + i[4]) * 27 + i[5]


def _ft8_pack28(t):
    if t in ("DE", "QRZ", "CQ"): return ("DE", "QRZ", "CQ").index(t)
    n = _ft8_basecall(t)
    return -1 if n < 0 else _FT8_NTOK + _FT8_MAX22 + n


def _ft8_pack77(msg):
    """Standard message (i3 = 1): 'CQ CALL GRID4' or 'CALL1 CALL2 GRID4'. Returns 77 bits (MSB first)."""
    t = msg.upper().split()
    if len(t) != 3: raise ValueError("only 'CQ CALL GRID' / 'CALL CALL GRID' are packed here")
    c1, c2, g = _ft8_pack28(t[0]), _ft8_pack28(t[1]), t[2]
    if c1 < 0 or c2 < 0 or len(g) != 4 or not ("A" <= g[0] <= "R" and "A" <= g[1] <= "R" and g[2:].isdigit()):
        raise ValueError("cannot pack " + msg)
    g15 = ((ord(g[0]) - 65) * 18 + (ord(g[1]) - 65)) * 100 + int(g[2]) * 10 + int(g[3])
    v = c1
    v = (v << 1) | 0           # r1
    v = (v << 28) | c2
    v = (v << 1) | 0           # r1
    v = (v << 1) | 0           # R1
    v = (v << 15) | g15
    v = (v << 3) | 1           # i3 = 1
    return [(v >> (76 - i)) & 1 for i in range(77)]


def _ft8_unpack77(b):
    v = 0
    for x in b: v = (v << 1) | x
    i3 = v & 7; g15 = (v >> 3) & 0x7FFF; c2 = (v >> 20) & 0xFFFFFFF; c1 = (v >> 49) & 0xFFFFFFF
    if i3 != 1: return ""
    def call(n):
        if n < 3: return ("DE", "QRZ", "CQ")[n]
        n -= _FT8_NTOK + _FT8_MAX22
        if n < 0: return "?"
        s = [""] * 6
        s[5] = _FT8_A4[n % 27]; n //= 27
        s[4] = _FT8_A4[n % 27]; n //= 27
        s[3] = _FT8_A4[n % 27]; n //= 27
        s[2] = _FT8_A3[n % 10]; n //= 10
        s[1] = _FT8_A2[n % 36]; n //= 36
        s[0] = _FT8_A1[n]
        return "".join(s).strip()
    a, r = divmod(g15, 100)
    grid = chr(65 + a // 18) + chr(65 + a % 18) + str(r // 10) + str(r % 10)
    return "%s %s %s" % (call(c1), call(c2), grid)


def _ft8_crc14(bits77):
    """CRC-14 (poly 0x2757) over the 77 bits + 5 zeros, augmented (WSJT-X boost::augmented_crc<14,0x2757>), as OnAir crc14()."""
    r = 0
    for i in range(96):
        top = (r >> 13) & 1
        r = ((r << 1) | (bits77[i] if i < 77 else 0)) & 0x3FFF
        if top: r ^= 0x2757
    return r


def _ft8_encode174(bits77):
    c = _ft8_crc14(bits77)
    cw = list(bits77) + [(c >> (13 - i)) & 1 for i in range(14)]
    m = 0
    for x in cw: m = (m << 1) | x
    cw += [bin(row & m).count("1") & 1 for row in _FT8_GENI]
    return cw


def _ft8_tones(bits77):
    cw = _ft8_encode174(bits77)
    t = [0] * 79
    for k in range(7):
        t[k] = t[36 + k] = t[72 + k] = _FT8_COSTAS[k]
    for j in range(58):
        v = cw[3 * j] * 4 + cw[3 * j + 1] * 2 + cw[3 * j + 2]
        t[7 + j if j < 29 else 43 + j - 29] = _FT8_GRAY[v]
    return t, cw


def _ft8_wave(tones, rate, f0, amp=1.0):
    """GFSK as OnAir addWave(): BT 2.0 Gaussian frequency pulse, 6.25 Hz spacing, 0.16 s symbols, 1/8-symbol cosine ramps."""
    nsps = int(round(0.16 * rate)); nsym = len(tones); total = nsym * nsps
    c = math.pi * math.sqrt(2.0 / math.log(2.0)) * 2.0          # pi sqrt(2/ln2) * BT
    # dev(u) = t0 + sum_k (t_k - t_{k-1}) G(u - k), G the Gaussian-smoothed step; G is 0 / 1 beyond 1 symbol
    G = [0.5 * (1 + math.erf(c * (d / nsps))) for d in range(-nsps, nsps)]
    dev = [0.0] * total
    for k in range(nsym):
        a = k * nsps
        dev[a:a + nsps] = [float(tones[k])] * nsps
    for k in range(1, nsym):
        dl = tones[k] - tones[k - 1]
        if not dl: continue
        b = k * nsps
        for i in range(-nsps, nsps):     # replace the hard step by the smooth one
            dev[b + i] += dl * (G[i + nsps] - (1.0 if i >= 0 else 0.0))
    out = array.array("f", bytes(4 * total))
    kk = 2 * math.pi / rate; ph = 0.0; r8 = nsps / 8.0; cos = math.cos
    for n in range(total):
        env = 1.0
        if n < r8: env = 0.5 * (1 - math.cos(math.pi * n / r8))
        elif n > total - r8: env = 0.5 * (1 - math.cos(math.pi * (total - n) / r8))
        out[n] = amp * env * cos(ph)
        ph += kk * (f0 + 6.25 * dev[n])
        if ph > 1e4: ph = math.fmod(ph, 2 * math.pi)
    return out


_FT8_MSG = "CQ K1ABC FN42"
_FT8_AUDIO = 12000.0      # tone 0; USB dial = 6.144 MHz + 12000 - 1500 Hz


def mode_ft8(rate, cache_dir):
    tones, _ = _ft8_tones(_ft8_pack77(_FT8_MSG))
    def build():
        sig = _ft8_wave(tones, rate, _FT8_AUDIO)
        pad = int(13.0 * rate) - len(sig)
        return sig + array.array("f", bytes(4 * max(0, pad)))
    s = _aprs_cache(cache_dir, "ft8-%d-%s" % (rate, _FT8_MSG.replace(" ", "_")), build)
    return {"samples": s, "cycle": 15, "phase": 0.5, "tune": [
        "FT8 \"%s\": tones %s .. %s (8-GFSK, 6.25 Hz spacing, 50 Hz wide)" % (_FT8_MSG, _aprs_mhz(_FT8_AUDIO), _aprs_mhz(_FT8_AUDIO + 43.75)),
        "Tune USB, dial %s: the signal sits at 1500 Hz audio. OnAir mode: FT8." % _aprs_mhz(_FT8_AUDIO - 1500),
        "Sent every 15 s slot from +0.5 s (UTC); the Mac clock must be within ~1 s."]}


# ---------------------------------------------------------------- WSPR (ported from OnAir hfdig_wspr.cpp; after WSJT-X wsprsim_utils.c, K1JT, GPL-3)

_WSPR_P1, _WSPR_P2 = 0xF2D05351, 0xE4613C47   # K=32 r=1/2 polynomials (WSJT-X wsprsim_utils.c, JTEncode)
_WSPR_MSG = "K1ABC FN42 10"
_WSPR_AUDIO = 12000.0     # centre of the 4 tones; USB dial = 6.144 MHz + 12000 - 1500 Hz


def _wspr_code(c):
    if c.isdigit(): return ord(c) - 48
    if "A" <= c <= "Z": return ord(c) - 55
    if c == " ": return 36
    return -1


def _wspr_pack(msg):
    """Type 1 message 'CALL GRID4 DBM' -> 50 bits (MSB first)."""
    call, g, p = msg.upper().split()
    p = int(p)
    if len(call) > 2 and call[2].isdigit(): s = call
    elif len(call) > 1 and call[1].isdigit() and len(call) <= 5: s = " " + call
    else: raise ValueError("bad call")
    s = (s + "      ")[:6]
    n = _wspr_code(s[0]); n = n * 36 + _wspr_code(s[1]); n = n * 10 + _wspr_code(s[2])
    for k in range(3, 6): n = n * 27 + (_wspr_code(s[k]) - 10)
    m = (179 - 10 * (ord(g[0]) - 65) - int(g[2])) * 180 + 10 * (ord(g[1]) - 65) + int(g[3])
    m = m * 128 + p + 64
    return [(n >> (27 - i)) & 1 for i in range(28)] + [(m >> (21 - i)) & 1 for i in range(22)]


def _wspr_rev8(j):
    return int("{:08b}".format(j)[::-1], 2)


def _wspr_symbols(msg):
    d = _wspr_pack(msg)
    coded = []; reg = 0
    for i in range(81):
        reg = ((reg << 1) | (d[i] if i < 50 else 0)) & 0xFFFFFFFF
        coded.append(bin(reg & _WSPR_P1).count("1") & 1)
        coded.append(bin(reg & _WSPR_P2).count("1") & 1)
    ch = [0] * 162; p = 0
    for j in range(256):
        r = _wspr_rev8(j)
        if r < 162:
            ch[r] = coded[p]; p += 1
    return [int(_WSPR_SYNC[i]) + 2 * ch[i] for i in range(162)]


def _wspr_wave(sym, rate, fcentre, amp=1.0):
    nsps = int(round(8192.0 / 12000.0 * rate)); sp = 12000.0 / 8192.0
    f0 = fcentre - 1.5 * sp
    out = array.array("f")
    ph = 0.0; cos = math.cos; k = 2 * math.pi / rate
    for s in sym:
        w = k * (f0 + s * sp)
        out.extend([amp * cos(ph + w * i) for i in range(nsps)])
        ph = math.fmod(ph + w * nsps, 2 * math.pi)
    nr = int(0.005 * rate)
    for i in range(nr):
        g = 0.5 * (1 - math.cos(math.pi * i / nr)); out[i] *= g; out[-1 - i] *= g
    return out


def mode_wspr(rate, cache_dir):
    sym = _wspr_symbols(_WSPR_MSG)
    s = _aprs_cache(cache_dir, "wspr-%d-%s" % (rate, _WSPR_MSG.replace(" ", "_")), lambda: _wspr_wave(sym, rate, _WSPR_AUDIO))
    return {"samples": s, "cycle": 120, "phase": 1.0, "tune": [
        "WSPR \"%s\": centre %s, 4-FSK 1.465 Hz spacing, ~6 Hz wide, 110.6 s" % (_WSPR_MSG, _aprs_mhz(_WSPR_AUDIO)),
        "Tune USB, dial %s: the signal sits at 1500 Hz audio. OnAir mode: WSPR." % _aprs_mhz(_WSPR_AUDIO - 1500),
        "Starts at every even UTC minute + 1 s; decodes appear after the 2-minute slot."]}


# ---------------------------------------------------------------- APRS: AX.25 UI frame, Bell 202 AFSK, FM (as OnAir packet_gen.cpp)

_APRS_SRC, _APRS_DST, _APRS_PATH = "N0CALL-9", "APRS", ["WIDE1-1"]
_APRS_INFO = "!5128.67N/00000.09W>TEST VIA HEADPHONE JACK"   # 51.478 N 0.0015 W (Greenwich), symbol '>' (car)
_APRS_AUDIO = 20000.0
_APRS_DEV = 3500.0


def _aprs_fcs(data):
    """CRC-16-CCITT reflected (X.25): init 0xFFFF, poly 0x8408, final xor 0xFFFF."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def _aprs_addr(s, last, cbit):
    call, _, ssid = s.partition("-")
    b = [ord(c) << 1 for c in (call + "      ")[:6]]
    b.append(0x60 | (int(ssid or 0) << 1) | (0x80 if cbit else 0) | (1 if last else 0))
    return b


def _aprs_frame(src=_APRS_SRC, dst=_APRS_DST, path=_APRS_PATH, info=_APRS_INFO):
    f = _aprs_addr(dst, False, True) + _aprs_addr(src, not path, False)
    for i, p in enumerate(path): f += _aprs_addr(p, i == len(path) - 1, False)
    f += [0x03, 0xF0] + [ord(c) for c in info]
    c = _aprs_fcs(f)
    return f + [c & 0xFF, c >> 8]


def _aprs_hdlc_bits(frame, lead_flags, tail_flags=3):
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    bits = flag * lead_flags
    ones = 0
    for b in frame:
        for k in range(8):
            x = (b >> k) & 1
            bits.append(x)
            if x:
                ones += 1
                if ones == 5: bits.append(0); ones = 0
            else:
                ones = 0
    return bits + flag * tail_flags


def aprs_burst(rate, offset_hz, dev=_APRS_DEV):
    bits = _aprs_hdlc_bits(_aprs_frame(), lead_flags=45)       # 45 flags = 300 ms
    spb = rate / 1200.0
    fd = []; lev = 1; tph = 0.0; acc = 0.0; k = 2 * math.pi / rate
    for b in bits:
        if b == 0: lev ^= 1                                      # NRZI: a 0 is a change
        acc += spb; n = int(acc); acc -= n
        w = k * (1200.0 if lev else 2200.0)
        for _ in range(n):
            tph += w
            fd.append(dev * math.sin(tph))
        tph = math.fmod(tph, 2 * math.pi)
    return _aprs_fm(fd, rate, offset_hz)


def mode_aprs(rate, cache_dir):
    b = aprs_burst(rate, _APRS_AUDIO)
    s = b + array.array("f", bytes(4 * (int(10 * rate) - len(b))))
    return {"samples": s, "cycle": None, "phase": 0.0, "tune": [
        "APRS (AFSK): NFM at %s, deviation +-3.5 kHz, ~12 kHz wide (12.5 kHz channel)" % _aprs_mhz(_APRS_AUDIO),
        "OnAir mode: APRS (AFSK). %s>%s,%s position 51.48 N 0.00 W (Greenwich) every 10 s; map pin '%s'."
        % (_APRS_SRC, _APRS_DST, ",".join(_APRS_PATH), _APRS_SRC)]}


# ---------------------------------------------------------------- POCSAG 1200 (as OnAir pager_proto.cpp pocsagBits / pager_gen.cpp)

_POCSAG_SYNC, _POCSAG_IDLE = 0x7CD215D8, 0x7A89C197
_POCSAG_RIC, _POCSAG_FN = 1234567, 3
_POCSAG_TEXT = "TEST VIA HEADPHONE JACK"
_POCSAG_AUDIO = 20000.0
_POCSAG_DEV = 4500.0


def _pocsag_word(data21):
    """BCH(31,21) with g(x) = x^10+x^9+x^8+x^6+x^5+x^3+1 (0x769), then even parity in the last bit."""
    c = data21 << 10
    for i in range(30, 9, -1):
        if c & (1 << i): c ^= 0x769 << (i - 10)
    w = ((data21 << 10) | c) << 1
    return w | (bin(w).count("1") & 1)


def _pocsag_check(w):
    """True when the 32-bit word has BCH syndrome 0 and even parity."""
    if bin(w).count("1") & 1: return False
    c = w >> 1
    for i in range(30, 9, -1):
        if c & (1 << i): c ^= 0x769 << (i - 10)
    return c == 0


def _pocsag_bits(ric=_POCSAG_RIC, fn=_POCSAG_FN, text=_POCSAG_TEXT, preamble=576):
    batches = [[_POCSAG_IDLE] * 16]; p = 0
    slot = 2 * (ric & 7)
    p = slot
    words = [_pocsag_word((((ric >> 3) & 0x3FFFF) << 2) | (fn & 3))]
    bits = []
    for ch in text + "\x04":                       # EOT at the end, as OnAir
        c = ord(ch) & 0x7F
        bits += [(c >> k) & 1 for k in range(7)]
    while len(bits) % 20: bits.append(0)
    for i in range(0, len(bits), 20):
        d = 1 << 20
        for k in range(20): d |= bits[i + k] << (19 - k)
        words.append(_pocsag_word(d))
    for w in words:
        if p == 16: batches.append([_POCSAG_IDLE] * 16); p = 0
        batches[-1][p] = w; p += 1
    out = [(i & 1) ^ 1 for i in range(preamble)]   # 1010...
    for bt in batches:
        for w in [_POCSAG_SYNC] + bt: out += [(w >> i) & 1 for i in range(31, -1, -1)]
    return out


def pocsag_burst(rate, offset_hz, dev=_POCSAG_DEV, baud=1200):
    """FSK, a 1 is the lower frequency (OnAir pager_gen.cpp); the frequency moves over 30 % either side of a bit edge."""
    bits = _pocsag_bits()
    spb = rate / baud
    n = int(round(len(bits) * spb))
    lv = [(-dev if bits[min(len(bits) - 1, int(i / spb))] else dev) for i in range(n)]
    m = max(1, int(0.6 * spb))                     # box filter: a linear move over 60 % of a bit
    fd = [0.0] * n; s = 0.0
    for i in range(n + m // 2):
        s += lv[min(i, n - 1)]
        if i >= m: s -= lv[min(i - m, n - 1)]
        j = i - m // 2
        if 0 <= j < n: fd[j] = s / min(m, i + 1)
    return _aprs_fm(fd, rate, offset_hz)


def mode_pocsag(rate, cache_dir):
    # 512 baud (about 4 dB less signal needed than 1200) on the 12.5 kHz channel raster (6.1625 MHz), so the whole-span
    # pager decoders, which look for carriers on that raster, find it too
    off = 18500.0
    b = pocsag_burst(rate, off, baud=512)
    s = b + array.array("f", bytes(4 * (int(10 * rate) - len(b))))
    return {"samples": s, "cycle": None, "phase": 0.0, "tune": [
        "POCSAG 512: FSK at %s, +-4.5 kHz shift, ~12 kHz wide (a 1 = the lower frequency)" % _aprs_mhz(off),
        "OnAir mode: POCSAG. Capcode %d, function %d, alphanumeric \"%s\", every 10 s." % (_POCSAG_RIC, _POCSAG_FN, _POCSAG_TEXT)]}


# ---------------------------------------------------------------- self-test

def selftest_digi():
    res = []
    def add(name, ok, detail): res.append((name, bool(ok), detail))

    # AX.25 FCS against the published X.25 check value, then a full loopback through FM + AFSK demodulation
    add("AX.25 FCS vector", _aprs_fcs(b"123456789") == 0x906E, "CRC-16/X.25 of '123456789' = 0x%04X (want 0x906E)" % _aprs_fcs(b"123456789"))
    rate = 96000
    frame = _aprs_frame()
    x = aprs_burst(rate, _APRS_AUDIO)
    f, dly = _aprs_fmdemod(x, rate, _APRS_AUDIO)
    spb = rate / 1200.0; nbits = int(len(x) / spb); lv = []
    for b in range(nbits):
        a0 = int(b * spb) + dly; a1 = min(len(f), int((b + 1) * spb) + dly)
        def mag(fr):
            w = 2 * math.pi * fr / rate
            c = sum(f[i] * math.cos(w * i) for i in range(a0, a1)); s = sum(f[i] * math.sin(w * i) for i in range(a0, a1))
            return c * c + s * s
        lv.append(1 if mag(1200) > mag(2200) else 0)
    raw = [1 if lv[i] == lv[i - 1] else 0 for i in range(1, len(lv))]
    s = "".join(map(str, raw)); flag = "01111110"
    got = None; i = s.find(flag)
    while i >= 0 and s.startswith(flag, i + 8): i += 8           # skip the preamble flags
    if i >= 0:
        j = s.find(flag, i + 8); body = s[i + 8:j]
        ub = []; ones = 0; skip = False
        for ch in body:
            if skip: skip = False; ones = 0; continue
            ub.append(int(ch)); ones = ones + 1 if ch == "1" else 0
            if ones == 5: skip = True
        got = [sum(ub[k + q] << q for q in range(8)) for k in range(0, len(ub) - 7, 8)]
    ok = got == frame and _aprs_fcs(got[:-2]) == got[-2] | (got[-1] << 8)
    add("APRS AFSK loopback", ok, "FM+AFSK demodulated %s bytes, FCS %s, info '%s'" % (
        len(got) if got else 0, "ok" if ok else "BAD", bytes(got[16 + 7:-2]).decode("ascii", "replace") if got else ""))

    # POCSAG: the known idle and sync words, every codeword of the page, and an FSK loopback of all bits
    add("POCSAG idle/sync words", _pocsag_check(_POCSAG_IDLE) and _pocsag_word(_POCSAG_IDLE >> 11) == _POCSAG_IDLE and _pocsag_check(_POCSAG_SYNC),
        "0x7A89C197 re-encodes from its 21 data bits and has syndrome 0; sync 0x7CD215D8 syndrome 0")
    bits = _pocsag_bits()
    words = [int("".join(map(str, bits[k:k + 32])), 2) for k in range(576, len(bits), 32)]
    add("POCSAG BCH+parity", all(_pocsag_check(w) for w in words), "%d codewords, all syndrome 0 and even parity" % len(words))
    msgw = [w for k, w in enumerate(words) if k % 17 and (w >> 31) & 1]
    tb = []
    for w in msgw: tb += [(w >> (30 - q)) & 1 for q in range(20)]
    txt = "".join(chr(sum(tb[k + q] << q for q in range(7))) for k in range(0, len(tb) - 6, 7)).split("\x04")[0]
    addr = [w for k, w in enumerate(words) if k % 17 and not (w >> 31) & 1 and w != _POCSAG_IDLE][0]
    k_addr = words.index(addr) % 17 - 1
    ric = (((addr >> 13) & 0x3FFFF) << 3) | (k_addr // 2)
    add("POCSAG page parse", txt == _POCSAG_TEXT and ric == _POCSAG_RIC and ((addr >> 11) & 3) == _POCSAG_FN,
        "RIC %d fn %d text '%s'" % (ric, (addr >> 11) & 3, txt))
    x = pocsag_burst(rate, _POCSAG_AUDIO)
    f, dly = _aprs_fmdemod(x, rate, _POCSAG_AUDIO)
    spb = rate / 1200.0
    rb = [1 if f[min(len(f) - 1, int((k + 0.5) * spb) + dly)] < 0 else 0 for k in range(len(bits))]
    nerr = sum(a != b for a, b in zip(rb, bits))
    add("POCSAG FSK loopback", nerr == 0, "%d bits demodulated, %d errors" % (len(bits), nerr))

    # FT8: packing round trip, CRC-14, LDPC parity with the independent parity-check table, tone demodulation
    b77 = _ft8_pack77(_FT8_MSG)
    tones, cw = _ft8_tones(b77)
    crc = 0
    for q in range(14): crc = (crc << 1) | cw[77 + q]
    add("FT8 pack/unpack", _ft8_unpack77(b77) == _FT8_MSG, "'%s' -> 77 bits -> '%s'" % (_FT8_MSG, _ft8_unpack77(b77)))
    add("FT8 CRC-14", crc == _ft8_crc14(cw[:77]), "CRC 0x%04X" % crc)
    bad = sum(sum(cw[v - 1] for v in row if v) & 1 for row in _FT8_NM)
    add("FT8 LDPC parity", bad == 0, "%d of 83 parity checks fail (WSJT-X/ft8_lib Nm table, independent of the generator)" % bad)
    # the same check for the OnAir test message, so the tables are pinned to a second message
    _, cw2 = _ft8_tones(_ft8_pack77("CQ K1ABC FN42"))
    bad2 = sum(sum(cw2[v - 1] for v in row if v) & 1 for row in _FT8_NM)
    add("FT8 LDPC parity (CQ K1ABC FN42)", bad2 == 0, "%d checks fail" % bad2)
    tr = 12000; w = _ft8_wave(tones, tr, 1500.0); nsps = 1920; dem = []
    for k in range(79):
        a0, a1 = k * nsps + nsps // 4, k * nsps + 3 * nsps // 4
        best = max(range(8), key=lambda t: (sum(w[i] * math.cos(2 * math.pi * (1500 + 6.25 * t) * i / tr) for i in range(a0, a1)) ** 2 +
                                            sum(w[i] * math.sin(2 * math.pi * (1500 + 6.25 * t) * i / tr) for i in range(a0, a1)) ** 2))
        dem.append(best)
    add("FT8 GFSK tones", dem == tones and tones[:7] == list(_FT8_COSTAS),
        "79 tones demodulated from the waveform match; Costas %s; tones %s" % ("".join(map(str, tones[:7])), "".join(map(str, tones))))

    # WSPR: sync bits, inverse of the interleaver and the convolutional code, unpack back to the message
    sym = _wspr_symbols(_WSPR_MSG)
    sync_ok = all((s & 1) == int(_WSPR_SYNC[i]) for i, s in enumerate(sym))
    ch = [s >> 1 for s in sym]; coded = []
    for j in range(256):
        r = _wspr_rev8(j)
        if r < 162: coded.append(ch[r])
    reg = 0; data = []; conv_ok = True
    for i in range(81):
        b = coded[2 * i] ^ (bin((reg << 1) & _WSPR_P1 & 0xFFFFFFFF).count("1") & 1)   # P1 has bit 0 set: the new bit
        reg = ((reg << 1) | b) & 0xFFFFFFFF
        if bin(reg & _WSPR_P2).count("1") & 1 != coded[2 * i + 1]: conv_ok = False
        data.append(b)
    conv_ok = conv_ok and not any(data[50:])
    n = int("".join(map(str, data[:28])), 2); m = int("".join(map(str, data[28:50])), 2)
    pw = m % 128 - 64; mg = m // 128; hi, lo = divmod(mg, 180)
    grid = chr(65 + (179 - hi) // 10) + chr(65 + lo // 10) + str((179 - hi) % 10) + str(lo % 10)
    cs = [""] * 6
    for k in (5, 4, 3): cs[k] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ "[n % 27]; n //= 27
    cs[2] = str(n % 10); n //= 10
    al = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ "
    cs[1] = al[n % 36]; n //= 36; cs[0] = al[n]
    back = "%s %s %d" % ("".join(cs).strip(), grid, pw)
    add("WSPR symbols", sync_ok and conv_ok and back == _WSPR_MSG,
        "162 symbols: sync LSBs match the WSJT-X vector, conv code inverts cleanly with 31 zero tail bits, unpack '%s'" % back)
    tr = 12000; w = _wspr_wave(sym, tr, 1500.0); nsps = 8192; sp = 12000 / 8192.0; dem = []
    for k in range(162):
        a0, a1 = k * nsps + 1024, k * nsps + nsps - 1024
        pw4 = []
        for t in range(4):
            fr = 1500 - 1.5 * sp + t * sp; wv = 2 * math.pi * fr / tr
            c = sum(w[i] * math.cos(wv * i) for i in range(a0, a1, 2)); s2 = sum(w[i] * math.sin(wv * i) for i in range(a0, a1, 2))
            pw4.append(c * c + s2 * s2)
        dem.append(pw4.index(max(pw4)))
    add("WSPR 4-FSK tones", dem == sym, "162 tones demodulated from the waveform match")
    return res
# ---- RS41 radiosonde and NOAA APT (merged into jacktx.py after part_common.py) ----
# Ported from OnAir's own generators: core/src/sonde/sonde_rs41.cpp + sonde_gen.cpp (RS41) and core/src/wxsat/wxsat_gen.cpp (APT).
import array, math, os, struct, time

# ================================================================== RS41
# XOR mask and header bytes: rs1729/RS demod/mod/rs41mod.c (mask[MASK_LEN], rs41_header_bytes), GPL-3, credit Zilog80 (rs1729).
_RS41_MASK = bytes([
    0x96, 0x83, 0x3E, 0x51, 0xB1, 0x49, 0x08, 0x98, 0x32, 0x05, 0x59, 0x0E, 0xF9, 0x44, 0xC6, 0x26,
    0x21, 0x60, 0xC2, 0xEA, 0x79, 0x5D, 0x6D, 0xA1, 0x54, 0x69, 0x47, 0x0C, 0xDC, 0xE8, 0x5C, 0xF1,
    0xF7, 0x76, 0x82, 0x7F, 0x07, 0x99, 0xA2, 0x2C, 0x93, 0x7C, 0x30, 0x63, 0xF5, 0x10, 0x2E, 0x61,
    0xD0, 0xBC, 0xB4, 0xB6, 0x06, 0xAA, 0xF4, 0x23, 0x78, 0x6E, 0x3B, 0xAE, 0xBF, 0x7B, 0x4C, 0xC1])
_RS41_HEADER = bytes([0x86, 0x35, 0xF4, 0x40, 0x93, 0xDF, 0x1A, 0x60])
_RS41_LEN = 320
_RS41_CALFRAMES = 51
_RS41_BAUD = 4800.0
_RS41_DEV = 2400.0           # OnAir sonde_gen.cpp kSpecs: RS41 deviation 2400 Hz
_RS41_AUDIO_HZ = 15000.0     # audio centre: RF 6.159 MHz
_RS41_SERIAL = "JACKTX1"
_RS41_LAT, _RS41_LON = 51.4779, -0.0015

# GF(256), x^8 + x^4 + x^3 + x^2 + 1, generator roots alpha^0..alpha^23 (as OnAir's port of rs41mod.c)
_RS41_EXP = [0] * 512
_RS41_LOG = [0] * 256
_x = 1
for _i in range(255):
    _RS41_EXP[_i] = _x; _RS41_LOG[_x] = _i
    _x <<= 1
    if _x & 0x100: _x ^= 0x11D
for _i in range(255, 512): _RS41_EXP[_i] = _RS41_EXP[_i - 255]


def _rs41_mul(a, b):
    return _RS41_EXP[_RS41_LOG[a] + _RS41_LOG[b]] if a and b else 0


def _rs41_gen():
    g = [0] * 25; g[0] = 1; deg = 0
    for r in range(24):
        for j in range(deg + 1, 0, -1): g[j] = g[j - 1] ^ _rs41_mul(g[j], _RS41_EXP[r])
        g[0] = _rs41_mul(g[0], _RS41_EXP[r]); deg += 1
    return g


_RS41_GEN = _rs41_gen()


def _rs41_parity(data):
    k = len(data); r = [0] * (24 + k); r[24:] = list(data)
    for i in range(24 + k - 1, 23, -1):
        c = r[i]
        if not c: continue
        for j in range(25): r[i - 24 + j] ^= _rs41_mul(c, _RS41_GEN[j])
    return r[:24]


def _rs41_syndromes(cw):
    out = []
    for j in range(24):
        s = 0; aj = _RS41_EXP[j]
        for i in range(len(cw) - 1, -1, -1): s = _rs41_mul(s, aj) ^ cw[i]
        out.append(s)
    return out


def _rs41_crc16(b):
    rem = 0xFFFF
    for v in b:
        rem ^= v << 8
        for _ in range(8): rem = ((rem << 1) ^ 0x1021) & 0xFFFF if rem & 0x8000 else (rem << 1) & 0xFFFF
    return rem


# sondegeo (WGS-84)
_RS41_A, _RS41_E2 = 6378137.0, 6.69437999014e-3


def _rs41_lla2ecef(lat, lon, h):
    la, lo = math.radians(lat), math.radians(lon)
    n = _RS41_A / math.sqrt(1 - _RS41_E2 * math.sin(la) ** 2)
    return ((n + h) * math.cos(la) * math.cos(lo), (n + h) * math.cos(la) * math.sin(lo), (n * (1 - _RS41_E2) + h) * math.sin(la))


def _rs41_enu2ecef(lat, lon, e, n, u):
    la, lo = math.radians(lat), math.radians(lon)
    return (-math.sin(lo) * e - math.sin(la) * math.cos(lo) * n + math.cos(la) * math.cos(lo) * u,
            math.cos(lo) * e - math.sin(la) * math.sin(lo) * n + math.cos(la) * math.sin(lo) * u,
            math.cos(la) * n + math.sin(la) * u)


def _rs41_atmos(alt):
    h = alt / 1000.0
    t = 15 - 6.5 * h if h < 11 else (-56.5 if h < 20 else -56.5 + (h - 20))
    rh = 80.0 * math.exp(-h / 3.5) if h < 11 else 3.0
    return t, rh


# calibration offsets inside the 816-byte calibration area (rs41mod.c get_PTU, via OnAir rs41MakeCal)
_RS41_OF_RF1, _RS41_OF_RF2, _RS41_OF_CO1, _RS41_OF_CALT1, _RS41_OF_CALH = 61, 65, 77, 89, 117


def _rs41_make_cal(freq_hz):
    c = bytearray(_RS41_CALFRAMES * 16)
    steps = int(round((freq_hz / 1000.0 - 400000.0) / 10.0))
    if 0 <= steps < 1024:                       # announced frequency (6 MHz is out of range: leave zero)
        c[2] = (steps & 3) << 6; c[3] = steps >> 2
    c[32 + 7] = 0xFF; c[32 + 8] = 0xFF        # kill timer off
    def pf(o, v): c[o:o + 4] = struct.pack("<f", v)
    pf(_RS41_OF_RF1, 750.0); pf(_RS41_OF_RF2, 1100.0)
    pf(_RS41_OF_CO1, -245.38665); pf(_RS41_OF_CO1 + 4, 0.234898627); pf(_RS41_OF_CO1 + 8, 1.04790903e-5)
    pf(_RS41_OF_CALT1, 1.0); pf(_RS41_OF_CALT1 + 4, 0.0); pf(_RS41_OF_CALT1 + 8, 0.0)
    pf(_RS41_OF_CALH, 42.0); pf(_RS41_OF_CALH + 4, 0.0)
    return bytes(c)


def _rs41_ptu_counts(cal, temp_c, rh):
    f = lambda o: struct.unpack("<f", cal[o:o + 4])[0]
    rf1, rf2 = f(_RS41_OF_RF1), f(_RS41_OF_RF2)
    co = [f(_RS41_OF_CO1 + 4 * i) for i in range(3)]; ca = [f(_RS41_OF_CALT1 + 4 * i) for i in range(3)]
    calh = f(_RS41_OF_CALH)
    tf1, tf2, hf1, hf2 = 132630, 193349, 464547, 532098
    target = temp_c / (1.0 + ca[2]) - ca[1] - co[0]
    R = target / co[1]
    for _ in range(20): R -= (co[1] * R + co[2] * R * R - target) / (co[1] + 2 * co[2] * R)
    Rc = R / ca[0]
    g = (tf2 - tf1) / (rf2 - rf1)
    Rb = (tf1 * rf2 - tf2 * rf1) / (tf2 - tf1)
    m = [0] * 12
    m[0] = int(round(g * (Rc + Rb))); m[1] = tf1; m[2] = tf2
    fac = 1.0
    if temp_c < -20: fac *= 1.0 + (-20 - temp_c) / 100.0
    if temp_c < -40: fac *= 1.0 + (-40 - temp_c) / 120.0
    fh = (((rh / fac) + temp_c / 5.5) / 100.0 + 7.5) / (350.0 / calh)
    m[3] = int(round(hf1 + fh * (hf2 - hf1))); m[4] = hf1; m[5] = hf2
    m[6], m[7], m[8] = m[0], tf1, tf2
    return m


def _rs41_frame(frame_no, t_unix, lat, lon, alt, v_e, v_n, v_up, cal, subframe, serial=_RS41_SERIAL):
    """One 320-byte RS41 frame (before the XOR mask), same layout as OnAir's rs41Frame()."""
    f = bytearray(_RS41_LEN)
    f[0:8] = _RS41_HEADER
    f[0x38] = 0x0F
    def block(pos, bid, ln): f[pos] = bid; f[pos + 1] = ln
    def seal(pos):
        ln = f[pos + 1]; c = _rs41_crc16(f[pos + 2:pos + 2 + ln])
        f[pos + 2 + ln] = c & 255; f[pos + 3 + ln] = c >> 8
    temp, rh = _rs41_atmos(alt)
    # 0x79 status: frame counter, serial, battery, calibration subframe
    block(0x39, 0x79, 0x28); d = 0x3B
    f[d] = frame_no & 255; f[d + 1] = (frame_no >> 8) & 255
    s = (serial + " " * 8)[:8].encode("ascii"); f[d + 2:d + 10] = s
    f[d + 10] = 29                                                   # 2.9 V
    f[d + 11:d + 23] = bytes([0x00, 0x00, 0x03, 0x00, 0x00, 0x0a, 0x00, 0x00, 0x2f, 0x00, 0x07, 0x32])
    sub = subframe % _RS41_CALFRAMES
    f[d + 23] = sub; f[d + 24:d + 40] = cal[sub * 16:sub * 16 + 16]
    seal(0x39)
    # 0x7A PTU
    block(0x65, 0x7A, 42)
    for i, v in enumerate(_rs41_ptu_counts(cal, temp, rh)):
        f[0x67 + 3 * i] = v & 255; f[0x68 + 3 * i] = (v >> 8) & 255; f[0x69 + 3 * i] = (v >> 16) & 255
    seal(0x65)
    # 0x7C GPS week and time of week, satellite table
    block(0x93, 0x7C, 30)
    gps = t_unix + 18 - 315964800.0
    week = int(gps // 604800.0); tow = int(round((gps - week * 604800.0) * 1000.0))
    f[0x95] = week & 255; f[0x96] = week >> 8
    f[0x97:0x9B] = struct.pack("<I", tow)
    for i in range(12):
        if i < 9: f[0x9B + 2 * i] = 1 + 2 * i; f[0x9C + 2 * i] = 0xB0 + i
        else: f[0x9B + 2 * i] = 0xFF; f[0x9C + 2 * i] = 0
    seal(0x93)
    # 0x7D raw GPS measurements (not used by the receiver): zeros
    block(0xB5, 0x7D, 89); seal(0xB5)
    # 0x7B ECEF position (cm) and velocity (cm/s)
    block(0x112, 0x7B, 21)
    x, y, z = _rs41_lla2ecef(lat, lon, alt)
    vx, vy, vz = _rs41_enu2ecef(lat, lon, v_e, v_n, v_up)
    f[0x114:0x120] = struct.pack("<iii", int(round(x * 100)), int(round(y * 100)), int(round(z * 100)))
    cl = lambda v: max(-32767, min(32767, int(round(v * 100))))
    f[0x120:0x126] = struct.pack("<hhh", cl(vx), cl(vy), cl(vz))
    f[0x126] = 9; f[0x127] = 0x04; f[0x128] = 0x10
    seal(0x112)
    # 0x76 padding
    block(0x12B, 0x76, 17); seal(0x12B)
    # Reed-Solomon (255,231) shortened, two interleaved codewords: data = even / odd bytes from 0x38, parity at 8 and 32
    k = (_RS41_LEN - 56) // 2
    for w in range(2):
        f[8 + 24 * w:8 + 24 * w + 24] = bytes(_rs41_parity([f[56 + 2 * i + w] for i in range(k)]))
    return bytes(f)


def _rs41_symbols(frame, preamble=True):
    s = [i & 1 for i in range(320)] if preamble else []
    for i, v in enumerate(frame):
        b = v ^ _RS41_MASK[i & 63]
        s.extend((b >> k) & 1 for k in range(8))                    # LSB first
    return s


def _rs41_burst(sym, rate, f0, out, start):
    """GFSK as OnAir's sonde generator: NRZ through two one-pole filters at 0.75 x baud, phase-continuous FM, 0.5 ms ramp.
    Adds a real signal cos(2 pi f0 t + phi) into out[start:]."""
    a = 1.0 - math.exp(-2 * math.pi * 0.75 * _RS41_BAUD / rate)
    ar = 1.0 - math.exp(-1.0 / (0.0005 * rate))
    spb = rate / _RS41_BAUD
    n_on = int(len(sym) * spb); n_tail = int(0.004 * rate)
    w0 = 2 * math.pi * f0 / rate; kd = 2 * math.pi * _RS41_DEV / rate
    lp1 = lp2 = 0.0; ph = 0.0; env = 0.0; cos = math.cos
    nsym = len(sym)
    for i in range(n_on + n_tail):
        if i < n_on:
            lvl = 1.0 if sym[int(i / spb)] else -1.0; tgt = 1.0
        else:
            lvl = 0.0; tgt = 0.0
        lp1 += a * (lvl - lp1); lp2 += a * (lp1 - lp2)
        ph += w0 + kd * lp2
        env += (tgt - env) * ar
        j = start + i
        if j < len(out): out[j] += env * cos(ph)
    return n_on + n_tail


def mode_sonde(rate=RATE, cache_dir=None, seconds=60):
    t0 = time.time()
    cal = _rs41_make_cal(403.0e6)              # announced frequency field: 403.00 MHz (6.159 MHz cannot be expressed)
    out = array.array("f", bytes(4 * int(seconds * rate)))
    vup, ve = 5.0, 3.0
    alt0 = 50.0
    for k in range(seconds):
        alt = alt0 + vup * k
        lon = _RS41_LON + ve * k / (111320.0 * math.cos(math.radians(_RS41_LAT)))
        fr = _rs41_frame(1000 + k, t0 + k, _RS41_LAT, lon, alt, ve, 0.0, vup, cal, k)
        _rs41_burst(_rs41_symbols(fr), rate, _RS41_AUDIO_HZ, out, int((k + 0.05) * rate))
    rf = CLOCK_HZ + _RS41_AUDIO_HZ
    return {"samples": out, "cycle": None, "phase": 0, "tune": [
        "RS41 radiosonde, serial %s, 4800 baud GFSK +-2.4 kHz (standard; OnAir sonde_gen.cpp:31, slicer is sign-based after a fixed +-10 kHz filter, sonde_rx.cpp:44), ~12 kHz wide, one frame a second" % _RS41_SERIAL,
        "RF %.4f MHz (audio %.0f Hz). OnAir mode: Radiosonde (sonde). It scans its whole capture for carriers," % (rf / 1e6, _RS41_AUDIO_HZ),
        "  so tune the centre a bit off it (e.g. %.3f MHz, 2 Msps or more). The mirror at %.4f MHz is the same sonde, inverted"
        % ((CLOCK_HZ - 44000) / 1e6, (CLOCK_HZ - _RS41_AUDIO_HZ) / 1e6),
        "  (OnAir decodes inverted RS41 too). Map pin: Greenwich 51.48 N 0.00 W, climbing 5 m/s from 50 m, drifting east 3 m/s.",
        "  Loop %d s: temperature/humidity appear once calibration subframes 3..7 have arrived (~8 s)." % seconds]}


def _rs41_selftest():
    res = []
    cal = _rs41_make_cal(403.0e6)
    fr = _rs41_frame(1234, 1.7e9, _RS41_LAT, _RS41_LON, 500.0, 3.0, 0.0, 5.0, cal, 3)
    k = (_RS41_LEN - 56) // 2
    ok = True
    for w in range(2):
        cw = list(fr[8 + 24 * w:8 + 24 * w + 24]) + [fr[56 + 2 * i + w] for i in range(k)]
        if any(_rs41_syndromes(cw)): ok = False
    res.append(("RS41 Reed-Solomon (2 interleaved codewords, syndromes zero)", ok, ""))
    pos, nb, good = 0x39, 0, True
    while pos + 4 <= len(fr):
        bid, bl = fr[pos], fr[pos + 1]
        if bid < 0x76 or bid > 0x8F: break
        crc = fr[pos + 2 + bl] | (fr[pos + 3 + bl] << 8)
        if crc != _rs41_crc16(fr[pos + 2:pos + 2 + bl]): good = False
        nb += 1; pos += bl + 4
    res.append(("RS41 CRC-16 of every block", good and nb == 6 and pos == _RS41_LEN, "%d blocks" % nb))
    sym = _rs41_symbols(fr, False)
    back = bytes((sum(sym[8 * i + b] << b for b in range(8))) ^ _RS41_MASK[i & 63] for i in range(_RS41_LEN))
    res.append(("RS41 XOR mask round trip", back == fr, ""))
    # GFSK loopback: modulate, then FM-discriminate and integrate per bit, find the header, unmask and check RS
    rate = RATE; sy = _rs41_symbols(fr)
    out = array.array("f", bytes(4 * int(0.7 * rate)))
    st = 1000
    _rs41_burst(sy, rate, _RS41_AUDIO_HZ, out, st)
    w = 2 * math.pi * _RS41_AUDIO_HZ / rate
    # mix to baseband, 3-pole lowpass ~6 kHz, discriminator
    al = 1 - math.exp(-2 * math.pi * 6000 / rate)
    i1 = q1 = i2 = q2 = i3 = q3 = 0.0; pi_ = pq = 0.0; disc = []
    for n, v in enumerate(out):
        c, s = math.cos(w * n), -math.sin(w * n)
        i1 += al * (v * c - i1); q1 += al * (v * s - q1)
        i2 += al * (i1 - i2); q2 += al * (q1 - q2)
        i3 += al * (i2 - i3); q3 += al * (q2 - q3)
        disc.append(math.atan2(q3 * pi_ - i3 * pq, i3 * pi_ + q3 * pq)); pi_, pq = i3, q3
    spb = rate / _RS41_BAUD
    hdr = 0
    for b in bytes(h ^ m for h, m in zip(_RS41_HEADER, _RS41_MASK)):
        for kk in range(8): hdr = (hdr << 1) | ((b >> kk) & 1)
    found = None
    for off in range(int(spb)):                   # pick the bit phase whose header search hits
        bits = []
        t = st + off
        while t + spb < len(disc):
            bits.append(1 if sum(disc[int(t):int(t + spb)]) > 0 else 0); t += spb
        sr = 0
        for i, bt in enumerate(bits):
            sr = ((sr << 1) | bt) & ((1 << 64) - 1)
            if i >= 63 and bin(sr ^ hdr).count("1") <= 1:
                found = (off, i + 1, bits); break
        if found: break
    if not found:
        res.append(("RS41 GFSK loopback: header found and frame decodes", False, "no header"))
        return res
    off, p, bits = found
    body = bits[p:p + (_RS41_LEN - 8) * 8]
    rx = bytearray(_RS41_HEADER) + bytearray(
        (sum(body[8 * i + b] << b for b in range(8))) ^ _RS41_MASK[(i + 8) & 63] for i in range(len(body) // 8))
    errs = sum(1 for a, b in zip(rx, fr) if a != b)
    ok = len(rx) == _RS41_LEN and all(
        not any(_rs41_syndromes(list(rx[8 + 24 * w2:8 + 24 * w2 + 24]) + [rx[56 + 2 * i + w2] for i in range(k)])) for w2 in range(2))
    res.append(("RS41 GFSK loopback: header found and frame decodes", ok, "%d byte errors" % errs))
    return res


# ================================================================== NOAA APT
_APT_AUDIO_HZ = 24000.0      # FM centre: RF 6.168 MHz; Carson 2 x (8 + 4.5) kHz = 25 kHz -> 11.5 .. 36.5 kHz
# Peak deviation 8 kHz, not the satellites' 17 kHz. OnAir's APT chain: fixed 18 kHz receive FIR (wxsat_rx.cpp:391), discriminator scaled by
# 17 kHz (wxsat_rx.cpp:838), then AptDecoder sync search by normalised correlation and black/white levels taken from the sync pulses
# (wxsat_apt.cpp:56-70, 72-87): a smaller deviation only lowers the amplitude, no level threshold except the status light (rx.cpp:792, 0.02).
# Simulated with that 36 kHz filter: 8 kHz keeps lock at 0-3 dB CNR (corr 0.72-0.80) where 17 kHz drops (0.52-0.69, threshold clicks),
# 5 kHz and below lose lock at 0 dB; pixel SNR at 10 dB CNR: 8 kHz 30 dB, 17 kHz 36 dB.
_APT_DEV = 8000.0
_APT_LINES = 128             # one full telemetry frame (16 wedges x 8 lines), 64 s
_APT_SYNC_A = [0, 0, 0, 0, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0]


def _apt_noise(seed, w, h, cell):
    """Smooth value noise in 0..1 on a w x h grid, lattice spacing `cell` pixels."""
    import random
    rnd = random.Random(seed)
    gw, gh = w // cell + 2, h // cell + 2
    g = [[rnd.random() for _ in range(gw)] for _ in range(gh)]
    out = []
    for y in range(h):
        fy = y / cell; iy = int(fy); ty = fy - iy; ty = ty * ty * (3 - 2 * ty)
        r0, r1 = g[iy], g[iy + 1]; row = []
        for x in range(w):
            fx = x / cell; ix = int(fx); tx = fx - ix; tx = tx * tx * (3 - 2 * tx)
            a = r0[ix] + (r0[ix + 1] - r0[ix]) * tx; b = r1[ix] + (r1[ix + 1] - r1[ix]) * tx
            row.append(a + (b - a) * ty)
        out.append(row)
    return out


def _apt_images(lines):
    W = 909
    n1, n2, n3 = _apt_noise(7, W, lines, 64), _apt_noise(11, W, lines, 20), _apt_noise(23, W, lines, 32)
    n4 = _apt_noise(31, W, lines, 9)
    vis = [[0.0] * W for _ in range(lines)]; ir = [[0.0] * W for _ in range(lines)]
    for y in range(lines):
        for x in range(W):
            land = 0.65 * n1[y][x] + 0.35 * n2[y][x] - 0.04 * math.cos(2 * math.pi * x / W)   # a continent-ish mass
            cloud = max(0.0, (0.6 * n3[y][x] + 0.4 * n4[y][x]) - 0.52) * 3.0
            if land > 0.56:                               # land; a lighter coastline band
                v = 0.42 + 0.25 * (land - 0.56) + (0.12 if land < 0.575 else 0.0); t = 0.30 - 0.2 * (land - 0.56)
            else:
                v = 0.10 + 0.08 * land; t = 0.42
            v = min(1.0, v + cloud); t = min(1.0, t + 0.9 * cloud)
            vis[y][x] = v; ir[y][x] = t
    # big "ONAIR" in both channels, and a small caption
    tw = 29 * 10
    draw_text(vis, (W - tw) // 2, max(2, (lines - 70) // 2 - 10), "ONAIR", 10, 0.98)
    draw_text(ir, (W - tw) // 2, max(2, (lines - 70) // 2 - 10), "ONAIR", 10, 0.98)
    cap = "TEST VIA MACBOOK HEADPHONE JACK"
    draw_text(vis, (W - (len(cap) * 6 - 1) * 2) // 2, lines - 18, cap, 2, 0.98)
    draw_text(ir, (W - (len(cap) * 6 - 1) * 2) // 2, lines - 18, cap, 2, 0.98)
    return vis, ir


_APT_WEDGES = [1 / 8, 2 / 8, 3 / 8, 4 / 8, 5 / 8, 6 / 8, 7 / 8, 1.0, 0.0]       # 1..8 grey steps, 9 zero modulation


def _apt_telemetry(line, ch):
    wedge = (line // 8) % 16
    if wedge < 9: return _APT_WEDGES[wedge]
    if wedge == 15: return 0.30 if ch == 0 else 0.62           # channel ID wedge (visible ch 2 / IR ch 4-ish)
    return [0.35, 0.36, 0.37, 0.38, 0.33, 0.40][wedge - 9]    # thermistors, back scan, patch: plausible greys


def _apt_line_words(line, vis, ir):
    w = []
    w += [0.95 if v else 0.05 for v in _APT_SYNC_A]                               # sync A: 7 cycles 1040 Hz
    w += [0.05 if (line % 120) < 2 else 0.25] * 47
    w += vis[line]
    w += [_apt_telemetry(line, 0)] * 45
    w += [0.95 if (i % 5) >= 2 else 0.05 for i in range(39)]                       # sync B: 7 pulses 832 pps
    w += [0.95 if (line % 120) < 2 else 0.75] * 47
    w += ir[line]
    w += [_apt_telemetry(line, 1)] * 45
    return w


def _apt_render(rate, lines, vis, ir):
    words = []
    for ln in range(lines): words += _apt_line_words(ln % len(vis), vis, ir)
    n = int(len(words) * rate / 4160.0)
    out = array.array("f", bytes(4 * n))
    sn = [math.sin(2 * math.pi * i / 1024) for i in range(1024)]
    st_sub = 2400.0 / rate * 1024; st_w = 4160.0 / rate
    w0 = 2 * math.pi * _APT_AUDIO_HZ / rate; kd = 2 * math.pi * _APT_DEV / rate
    ph = 0.0; sp = 0.0; cos = math.cos; tp = 2 * math.pi
    for i in range(n):
        env = 0.1 + 0.85 * words[int(i * st_w)]          # OnAir genApt: env = 0.1 + 0.85 * word
        m = env * sn[int(sp) & 1023]; sp += st_sub
        ph += w0 + kd * m
        if ph > 1e4: ph -= tp * 1591
        out[i] = cos(ph)
    return out


def mode_noaa(rate=RATE, cache_dir=None, lines=_APT_LINES):
    path = os.path.join(cache_dir, "noaa_v2_%d_%d.f32" % (rate, lines)) if cache_dir else None
    out = None
    if path and os.path.exists(path):
        out = array.array("f"); out.frombytes(open(path, "rb").read())
    if out is None:
        vis, ir = _apt_images(lines)
        out = _apt_render(rate, lines, vis, ir)
        if path:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as fh: fh.write(out.tobytes())
    rf = CLOCK_HZ + _APT_AUDIO_HZ
    return {"samples": out, "cycle": None, "phase": 0, "tune": [
        "NOAA APT weather image: FM +-8 kHz (weak-signal choice; satellites use +-17), 2400 Hz AM subcarrier, 4160 words/s, 2 lines/s, %d-line loop (%d s)" % (lines, lines // 2),
        "RF %.4f MHz (audio %.0f Hz), occupies ~%.4f..%.4f MHz (Carson ~25 kHz)" % (rf / 1e6, _APT_AUDIO_HZ, (rf - 12500) / 1e6, (rf + 12500) / 1e6),
        "OnAir mode: Weather satellites -> NOAA APT, default settings. Its receive filter is fixed at +-18 kHz (wxsat_rx.cpp:391) and the",
        "  decoder is level-independent (wxsat_apt.cpp:56-87), so +-8 kHz decodes at lower amplitude; in sims it holds lock down to ~0-3 dB",
        "  CNR, better than +-17 kHz (FM threshold clicks). Channel A = visible (sea dark, land grey, clouds and ONAIR white), channel B = IR. Image builds line by line."]}


def _apt_selftest():
    rate = RATE
    vis, ir = _apt_images(8)
    x = _apt_render(rate, 4, vis, ir)
    # FM demod: mix with the centre, 3-pole lowpass ~12 kHz, discriminator, scale by deviation
    w = 2 * math.pi * _APT_AUDIO_HZ / rate
    al = 1 - math.exp(-2 * math.pi * 14000 / rate)
    i1 = q1 = i2 = q2 = 0.0; pi_ = 1.0; pq = 0.0; aud = []
    for n, v in enumerate(x):
        c, s = math.cos(w * n), -math.sin(w * n)
        i1 += al * (v * c - i1); q1 += al * (v * s - q1); i2 += al * (i1 - i2); q2 += al * (q1 - q2)
        aud.append(math.atan2(q2 * pi_ - i2 * pq, i2 * pi_ + q2 * pq) / (2 * math.pi * _APT_DEV / rate)); pi_, pq = i2, q2
    # AM demod at 2400 Hz (box over one subcarrier period, as OnAir's AptDecoder), resample to 4160
    box = int(round(rate / 2400.0)); ring = [0j] * box; bs = 0j; rp = 0; env = []; ph = 0.0; dph = 2 * math.pi * 2400 / rate
    take = 0.0; ratio = rate / 4160.0
    for v in aud:
        m = v * complex(math.cos(ph), -math.sin(ph)); ph += dph
        bs += m - ring[rp]; ring[rp] = m; rp = (rp + 1) % box
        take += 1.0
        if take >= ratio: take -= ratio; env.append(abs(bs) * 2 / box)
    t = [p - sum(_APT_SYNC_A) / 39.0 for p in _APT_SYNC_A]
    def corr(at):
        seg = env[at:at + 39]; mu = sum(seg) / 39; e = sum((s - mu) ** 2 for s in seg)
        return sum((s - mu) * tt for s, tt in zip(seg, t)) / math.sqrt(e * sum(tt * tt for tt in t)) if e > 0 else 0
    cs = [corr(a) for a in range(len(env) - 40)]
    peaks = [a for a in range(1, len(cs) - 1) if cs[a] > 0.8 and cs[a] >= cs[a - 1] and cs[a] >= cs[a + 1]]
    gaps = [b - a for a, b in zip(peaks, peaks[1:])]
    ok = len(peaks) >= 3 and all(abs(g - 2080) <= 3 for g in gaps)
    return [("NOAA APT loopback: FM+AM demod, sync A every 0.5 s", ok, "peaks at %s" % peaks[:5])]


def selftest_sat():
    return _rs41_selftest() + _apt_selftest()
# ---- DVB-S2 (merged into jacktx.py) ----
# DVB-S2 transmitter, QPSK 1/4, short FECFRAME (16200), pilots on, roll-off 0.20, ported from OnAir core/src/dvbs/dvbs_tx.cpp + dvbs_s2.cpp
# (BBHEADER, BB scrambling, BCH, LDPC, mapping, PLHEADER, pilots, PL scrambling). Clause numbers: ETSI EN 302 307-1 V1.3.1.
# The symbol rate is 32 ksym/s = exactly 3 audio samples per symbol at 96 kHz; the complex baseband is put on a real carrier at +24 kHz (fs/4),
# so the passband sample n is +I, -Q, -I, +Q of the shaped baseband in turn. One loop = 94 PLFRAMEs = exactly 187 TS packets (24.59 s), so the
# stream, the CRC-8 chain, the RRC filter (circular) and the carrier all continue seamlessly when the file repeats.
import array, math, os, subprocess

_S2_RS = 32000.0            # symbols per second
_S2_ROLL = 0.20             # RO field 10
_S2_FC = 24000.0            # audio centre (fs/4 at 96 kHz)
_S2_N, _S2_K, _S2_KBCH = 16200, 3240, 3072      # short frame, rate 1/4 (table 5b)
_S2_M = _S2_N - _S2_K                           # 12960 parity bits, q = 36
_S2_Q = 36
_S2_MODCOD = 1                                  # QPSK 1/4 (table 12)
_S2_SLOTS = _S2_N // 2 // 90                    # 90 slots of 90 symbols
_S2_FRAME = 90 * (_S2_SLOTS + 1) + 36 * ((_S2_SLOTS - 1) // 16)   # 8370 symbols with pilots
_S2_DFL = (_S2_KBCH - 80) // 8 * 8              # 2992 bits = 374 bytes per data field
_S2_VER = "dvbs2-v3"

# LDPC short frame, rate 1/4: addresses of the parity accumulators, one row per 360 information bits.
# Source: ETSI EN 302 307 V1.3.1 (2012-11), annex C, table C.1 (nldpc = 16200), as carried in OnAir core/src/dvbs/dvbs_ldpc_tables.cpp (kS1_4).
_S2_LDPC_S14 = [
    [6295, 9626, 304, 7695, 4839, 4936, 1660, 144, 11203, 5567, 6347, 12557],
    [10691, 4988, 3859, 3734, 3071, 3494, 7687, 10313, 5964, 8069, 8296, 11090],
    [10774, 3613, 5208, 11177, 7676, 3549, 8746, 6583, 7239, 12265, 2674, 4292],
    [11869, 3708, 5981, 8718, 4908, 10650, 6805, 3334, 2627, 10461, 9285, 11120],
    [7844, 3079, 10773],
    [3385, 10854, 5747],
    [1360, 12010, 12202],
    [6189, 4241, 2343],
    [9840, 12726, 4977],
]

# BCH short frame minimal polynomials g1..g12 over GF(2^14) (coefficient of x^0 first), EN 302 307 table 6b, as in OnAir rust/onair_fec/src/bch_tables.rs
_S2_BCH_SHORT = ["110101000000001", "100000101001001", "111000100110001", "100010011010101", "101010101101011", "100100011100011",
                 "101001110011011", "100001001111001", "111100000110001", "100100100101101", "100010000001101", "101101100111001"]
_S2_SOF = 0x18D2E82
_S2_PLS_G = [0x90AC2DDD, 0x55555555, 0x33333333, 0x0F0F0F0F, 0x00FF00FF, 0x0000FFFF, 0xFFFFFFFF]
_S2_PLS_SCR = 0x719D83C953422DFA


def _s2_crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8): crc = ((crc << 1) ^ 0xD5) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


_s2_cache = {}


def _s2_bb_prbs():
    if "prbs" not in _s2_cache:
        s = [0] + [int(c) for c in "100101010000000"]; v = bytearray(_S2_KBCH)
        for i in range(_S2_KBCH):
            fb = s[14] ^ s[15]; v[i] = fb; s = [0, fb] + s[1:15]
        _s2_cache["prbs"] = v
    return _s2_cache["prbs"]


def _s2_bch_gen():
    if "bchg" not in _s2_cache:
        g = 1
        for p in _S2_BCH_SHORT:
            m = sum(1 << i for i, c in enumerate(p) if c == "1"); r = 0; a = g; k = 0
            while m >> k:
                if (m >> k) & 1: r ^= a << k
                k += 1
            g = r
        assert g.bit_length() - 1 == 168
        # byte table for the remainder register (MSB first), deg 168
        tab = []
        for b in range(256):
            r = b << 160
            for _ in range(8): r = (r << 1) ^ g if r & (1 << 167) else r << 1
            tab.append(r & ((1 << 168) - 1))
        _s2_cache["bchg"] = (g, tab)
    return _s2_cache["bchg"]


def _s2_bch_parity(bits):
    """bits: kbch message bits (first = highest power). Returns 168 parity bits (remainder of m(x) x^168 mod g(x), highest first)."""
    g, tab = _s2_bch_gen(); r = 0; mask = (1 << 168) - 1
    for i in range(0, len(bits), 8):
        byte = 0
        for b in bits[i:i + 8]: byte = (byte << 1) | b
        r = ((r << 8) & mask) ^ tab[(r >> 160) ^ byte]
    return [(r >> (167 - i)) & 1 for i in range(168)]


def _s2_ldpc_masks():
    if "ldpc" not in _s2_cache:
        masks = []
        for g, row in enumerate(_S2_LDPC_S14):
            for j in range(360):
                v = 0
                for x in row: v ^= 1 << ((x + j * _S2_Q) % _S2_M)
                masks.append(v)
        _s2_cache["ldpc"] = masks
    return _s2_cache["ldpc"]


def _s2_prefix_xor(v, nbits):
    s = 1
    while s < nbits: v ^= v << s; s <<= 1
    return v & ((1 << nbits) - 1)


def _s2_ldpc_parity(info):
    masks = _s2_ldpc_masks(); p = 0
    for i, b in enumerate(info):
        if b: p ^= masks[i]
    p = _s2_prefix_xor(p, _S2_M)               # p_j ^= p_(j-1) (the accumulator, clause 5.3.2)
    return [(p >> j) & 1 for j in range(_S2_M)]


def _s2_rn(n=0):
    """PL scrambling R(i) in 0..3 for the symbols after the PLHEADER (clause 5.5.4), Gold code n."""
    key = ("rn", n)
    if key not in _s2_cache:
        N = (1 << 18) - 1; need = _S2_FRAME + 131072 + 10
        L = min(N, need + n)
        xs = bytearray(L); ys = bytearray(L); xs[0] = 1
        for i in range(18): ys[i] = 1
        for i in range(L - 18):
            xs[i + 18] = xs[i + 7] ^ xs[i]; ys[i + 18] = ys[i + 10] ^ ys[i + 7] ^ ys[i + 5] ^ ys[i]
        z = lambda i: xs[(i + n) % N] ^ ys[i % N]
        _s2_cache[key] = bytes(2 * z((i + 131072) % N) + z(i) for i in range(_S2_FRAME - 90))
    return _s2_cache[key]


def _s2_plheader(modcod, short, pilots):
    """90 symbols as (sI, sQ) sign bits (component = +a for 0, -a for 1). pi/2 BPSK, clause 5.5.2."""
    v = (modcod & 31) << 2 | (2 if short else 0) | (1 if pilots else 0)
    c = 0
    for i in range(7):
        if (v >> (7 - i)) & 1: c ^= _S2_PLS_G[i]
    w = 0
    for k in range(32):
        y = (c >> (31 - k)) & 1; w = (w << 1) | y; w = (w << 1) | (y ^ (v & 1))
    w ^= _S2_PLS_SCR
    bits = [(_S2_SOF >> (25 - j)) & 1 for j in range(26)] + [(w >> (63 - k)) & 1 for k in range(64)]
    return [((1 - y) if j & 1 else y, y) for j, y in enumerate(bits)]


def _s2_bbheader(syncd):
    by = bytes([3 << 6 | 1 << 5 | 1 << 4 | 2, 0, 1504 >> 8, 1504 & 255, _S2_DFL >> 8, _S2_DFL & 255, 0x47, syncd >> 8, syncd & 255])
    by += bytes([_s2_crc8(by)])
    return [(by[i >> 3] >> (7 - (i & 7))) & 1 for i in range(80)]


def _s2_encode_frame(field, syncd):
    """field: 374 bytes of user packets. Returns (codeword bits, symbol sign bits sI list, sQ list) for one PLFRAME."""
    bb = _s2_bbheader(syncd) + [(field[i >> 3] >> (7 - (i & 7))) & 1 for i in range(_S2_DFL)]
    bb += [0] * (_S2_KBCH - len(bb))
    prbs = _s2_bb_prbs(); bb = [a ^ b for a, b in zip(bb, prbs)]
    info = bb + _s2_bch_parity(bb)
    cw = info + _s2_ldpc_parity(info)
    # QPSK: no bit interleaver (s2BitInterleave copies for QPSK); label = (b0 b1), I from b0, Q from b1, 0 -> positive (figure 9)
    hdr = _s2_plheader(_S2_MODCOD, True, True); rn = _s2_rn(0)
    sI = [h[0] for h in hdr]; sQ = [h[1] for h in hdr]
    i = 0; si = 0
    for slot in range(_S2_SLOTS):
        for _ in range(90):
            a, b = cw[2 * si], cw[2 * si + 1]; si += 1
            r = rn[i]; i += 1
            if r == 0: sI.append(a); sQ.append(b)
            elif r == 1: sI.append(1 - b); sQ.append(a)
            elif r == 2: sI.append(1 - a); sQ.append(1 - b)
            else: sI.append(b); sQ.append(1 - a)
        if (slot + 1) % 16 == 0 and slot + 1 < _S2_SLOTS:
            for _ in range(36):          # pilot (1+j)/sqrt2, scrambled
                r = rn[i]; i += 1
                sI.append((0, 1, 1, 0)[r]); sQ.append((0, 0, 1, 1)[r])
    return cw, sI, sQ


def _s2_frames(stream, nframes):
    """stream: the transmitted user packets back to back (byte 0 of each = CRC-8 of the previous packet), starting at a packet start."""
    sI, sQ, cws = [], [], []
    fb = _S2_DFL // 8
    for f in range(nframes):
        off = (-f * fb) % 188
        syncd = off * 8 if off * 8 < _S2_DFL else 65535
        cw, a, b = _s2_encode_frame(stream[f * fb:(f + 1) * fb], syncd)
        sI += a; sQ += b; cws.append(cw)
    return cws, sI, sQ


def _s2_user_packets(packets):
    """TS packets (188 bytes, sync 0x47) -> the UP stream with the sync byte replaced by the CRC-8 of the previous packet (clause 5.1.4); cyclic."""
    out = bytearray(); prev = _s2_crc8(packets[-1][1:])
    for p in packets:
        out.append(prev); out += p[1:]; prev = _s2_crc8(p[1:])
    return bytes(out)


def _s2_rrc_taps(sps=3, half=8):
    a = _S2_ROLL; taps = {}
    for m in range(-half * sps, half * sps):
        t = m / sps
        if t == 0: h = 1 - a + 4 * a / math.pi
        elif abs(abs(4 * a * t) - 1) < 1e-9:
            h = a / math.sqrt(2) * ((1 + 2 / math.pi) * math.sin(math.pi / (4 * a)) + (1 - 2 / math.pi) * math.cos(math.pi / (4 * a)))
        else:
            h = (math.sin(math.pi * t * (1 - a)) + 4 * a * t * math.cos(math.pi * t * (1 + a))) / (math.pi * t * (1 - (4 * a * t) ** 2))
        taps[m] = h * (0.5 + 0.5 * math.cos(math.pi * m / (half * sps)))     # Hann window over +-8 symbols
    return taps


def _s2_shape(sI, sQ, sps=3, half=8):
    """Circular RRC shaping at 3 samples per symbol, then the fs/4 carrier: out[n] = I cos(pi n/2) - Q sin(pi n/2). Peak-normalised."""
    h = _s2_rrc_taps(sps, half); A = 1 / math.sqrt(2)
    # out[3k+p] = sum_{d=-8..7} x[k-d] h(3d+p); 16-bit window, bit j = symbol k+8-j (low byte d=-8..-1, high byte d=0..7)
    TL = [[0.0] * 256 for _ in range(sps)]; TH = [[0.0] * 256 for _ in range(sps)]
    for p in range(sps):
        for v in range(256):
            lo = hi = 0.0
            for j in range(8):
                sg = -A if (v >> j) & 1 else A
                lo += sg * h[3 * (j - 8) + p]; hi += sg * h[3 * j + p]
            TL[p][v] = lo; TH[p][v] = hi
    n = len(sI); out = array.array("f", bytes(4 * sps * n))
    wi = sum(sI[(8 - j) % n] << j for j in range(16)); wq = sum(sQ[(8 - j) % n] << j for j in range(16))
    TL0, TL1, TL2 = TL; TH0, TH1, TH2 = TH; M = 0xFFFF
    for k in range(n):
        li, hi_ = wi & 255, wi >> 8; lq, hq = wq & 255, wq >> 8
        b = 3 * k
        # carrier phase of sample b+p is (b+p) % 4: 0 +I, 1 -Q, 2 -I, 3 +Q
        for p, (tl, th) in enumerate(((TL0, TH0), (TL1, TH1), (TL2, TH2))):
            c = (b + p) & 3
            if c == 0: out[b + p] = tl[li] + th[hi_]
            elif c == 1: out[b + p] = -(tl[lq] + th[hq])
            elif c == 2: out[b + p] = -(tl[li] + th[hi_])
            else: out[b + p] = tl[lq] + th[hq]
        nx = (k + 9) % n
        wi = ((wi << 1) | sI[nx]) & M; wq = ((wq << 1) | sQ[nx]) & M
    pk = max(max(out), -min(out)) or 1.0
    for i in range(len(out)): out[i] /= pk
    return out


def _s2_video_frames(seconds, fps=2, W=160, H=120):
    """Raw RGB frames: colour bars, a moving bar and box, big ONAIR, the text, and a loop clock."""
    bars = [(235, 235, 235), (235, 235, 16), (16, 235, 235), (16, 235, 16), (235, 16, 235), (235, 16, 16), (16, 16, 235), (16, 16, 16)]
    bg = bytearray(W * H * 3)
    for y in range(H):
        for x in range(W):
            if y < 40: c = bars[x * 8 // W]
            elif y < 52: v = 16 + x * 219 // (W - 1); c = (v, v, v)
            else: c = (10, 20, 60)
            o = (y * W + x) * 3; bg[o:o + 3] = bytes(c)
    def blit(img, x0, y0, text, scale, col):
        w, h, m = text_mask(text, scale)
        for yy in range(h):
            if 0 <= y0 + yy < H:
                for xx in range(w):
                    if m[yy][xx] and 0 <= x0 + xx < W:
                        o = ((y0 + yy) * W + x0 + xx) * 3; img[o:o + 3] = col
    stat = bytearray(bg)
    blit(stat, (W - 87) // 2, 56, "ONAIR", 3, b"\xff\xd0\x20")
    blit(stat, (W - 53) // 2, 82, "ONAIR VIA", 1, b"\xff\xff\xff")
    blit(stat, (W - 83) // 2, 91, "HEADPHONE JACK", 1, b"\xff\xff\xff")
    frames = []
    nf = int(math.ceil(seconds * fps))
    for f in range(nf):
        img = bytearray(stat); t = f / fps
        bx = int((W - 8) * (0.5 + 0.5 * math.sin(2 * math.pi * t / 8)))
        for y in range(0, 40):
            o = (y * W + bx) * 3; img[o:o + 24] = b"\x00\x00\x00" * 8
        clk = "T+%02d:%04.1f" % (int(t) // 60, t % 60)
        blit(img, 4, 110, clk, 1, b"\x20\xff\x20")
        blit(img, W - 4 - 5 * 6 + 1, 110, "%05d" % f, 1, b"\xff\xff\x20")
        frames.append(bytes(img))
    return frames


def _s2_make_ts(cache_dir, npk, seconds, muxrate):
    """ffmpeg: H.264 160x120 2 fps 6 kbit/s, CBR MPEG-TS at muxrate; returns exactly npk 188-byte packets (null padded / cut)."""
    path = os.path.join(cache_dir, "%s.ts" % _S2_VER)
    if not os.path.exists(path):
        frames = _s2_video_frames(seconds - 1.5)       # a little shorter than the loop, so the TS fits and is null padded, never cut
        cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "160x120",
               "-r", "2", "-i", "pipe:0", "-c:v", "libx264", "-preset", "veryslow", "-profile:v", "high", "-pix_fmt", "yuv420p",
               "-b:v", "6k", "-maxrate", "6500", "-bufsize", "24k", "-g", "8", "-keyint_min", "8", "-sc_threshold", "0", "-x264-params", "nal-hrd=cbr",
               "-f", "mpegts", "-muxrate", str(int(muxrate)), "-pat_period", "2", "-sdt_period", "4", "-pcr_period", "400",
               "-mpegts_service_id", "1", "-metadata", "service_name=ONAIR JACK", "-metadata", "service_provider=ONAIR", path + ".tmp"]
        subprocess.run(cmd, input=b"".join(frames), check=True)
        os.replace(path + ".tmp", path)
    data = open(path, "rb").read()
    pk = [data[i:i + 188] for i in range(0, len(data) - 187, 188) if data[i] == 0x47]
    null = bytes([0x47, 0x1F, 0xFF, 0x10]) + b"\xff" * 184
    got = len(pk)
    pk = (pk + [null] * npk)[:npk]
    return pk, got


def _s2_loop_dims():
    fb = _S2_DFL // 8; g = math.gcd(fb, 188)
    nframes = 188 // g; npk = fb // g          # 94 frames carry exactly 187 packets
    return nframes, npk


def mode_dvbs2(rate, cache_dir):
    if rate != 96000: raise SystemExit("DVB-S2 needs the 96 kHz output (3 samples per symbol)")
    os.makedirs(cache_dir, exist_ok=True)
    nframes, npk = _s2_loop_dims()
    assert (nframes * _S2_FRAME * 3) % 4 == 0      # the fs/4 carrier closes over the loop
    secs = nframes * _S2_FRAME / _S2_RS
    netrate = _S2_RS * _S2_DFL / _S2_FRAME
    cpath = os.path.join(cache_dir, "%s.f32" % _S2_VER)
    if os.path.exists(cpath):
        out = array.array("f"); out.frombytes(open(cpath, "rb").read()); info = "cached"
    else:
        pk, got = _s2_make_ts(cache_dir, npk, secs, math.floor(netrate))
        stream = _s2_user_packets(pk)
        _, sI, sQ = _s2_frames(stream, nframes)
        out = _s2_shape(sI, sQ)
        with open(cpath + ".tmp", "wb") as f: out.tofile(f)
        os.replace(cpath + ".tmp", cpath)
        info = "ffmpeg gave %d TS packets, loop holds %d" % (got, npk)
    rf = CLOCK_HZ + _S2_FC; bw = _S2_RS * (1 + _S2_ROLL)
    tune = ["DVB-S2 at %.6f MHz: QPSK 1/4, short frames (16200), pilots on, roll-off %.2f, %.1f ksym/s, %.1f kHz wide (%.1f-%.1f kHz audio)"
            % (rf / 1e6, _S2_ROLL, _S2_RS / 1e3, bw / 1e3, (_S2_FC - bw / 2) / 1e3, (_S2_FC + bw / 2) / 1e3),
            "TS %.0f bit/s: H.264 160x120 2 fps 6 kbit/s test card 'ONAIR VIA HEADPHONE JACK', service 'ONAIR JACK'; loop %.1f s = %d PLFRAMEs = %d TS packets (%s)"
            % (netrate, secs, nframes, npk, info),
            "OnAir: DVB-S/S2 mode, symbol rate set by hand to 0.032 Msym/s (Auto will not find it: the spectrum search floor is 60 ksym/s).",
            "CAVEAT: the released OnAir UI clamps a manual symbol rate to >= 0.050 Msym/s (app/dvbs/dvbs_ui.cpp:696); 50 ksym/s needs 60 kHz and does",
            "not fit the 2-46 kHz window, so as released OnAir cannot decode this one. The upper copy (%.3f MHz) is upright; the mirror below is inverted." % (rf / 1e6)]
    return {"samples": out, "tune": tune, "cycle": None, "phase": 0}


# ---------------------------------------------------------------- self test: encode, shape, then receive from the audio samples
def _s2_bch_ok(info):
    g, _ = _s2_bch_gen(); v = 0
    for b in info: v = (v << 1) | b
    # remainder of the whole BCH codeword polynomial
    L = len(info)
    for i in range(L - 1, 167, -1):
        if (v >> i) & 1: v ^= g << (i - 168)
    return v == 0


def _s2_ldpc_ok(cw):
    """H c = 0 with H in the accumulator form, checked bit by bit from the address table (independent of the mask encoder)."""
    chk = bytearray(_S2_M)
    for g, row in enumerate(_S2_LDPC_S14):
        for j in range(360):
            b = cw[g * 360 + j]
            if b:
                for x in row: chk[(x + j * _S2_Q) % _S2_M] ^= 1
    p = cw[_S2_K:]
    for j in range(_S2_M):
        if chk[j] ^ p[j] ^ (p[j - 1] if j else 0): return False
    return True


def _s2_receive(audio, nframes):
    """Matched filter + fs/4 down-conversion at the known symbol instants, hard decisions, PL descramble, take the systematic bits,
    BB descramble, check the BBHEADER CRC, and cut the user packets out (sync byte restored, CRC-8 checked)."""
    h = _s2_rrc_taps(); n = len(audio); nsym = n // 3
    hs = sorted(h.items())
    cosv = (1, 0, -1, 0); sinv = (0, 1, 0, -1)
    rn = _s2_rn(0); hdr = _s2_plheader(_S2_MODCOD, True, True)
    prbs = _s2_bb_prbs(); fields = []; errs = 0
    for f in range(nframes):
        base = f * _S2_FRAME; dI = []; dQ = []
        for s in range(_S2_FRAME):
            c = 3 * (base + s); yi = yq = 0.0
            for m, t in hs:
                x = audio[(c + m) % n]; ph = (c + m) & 3
                yi += x * cosv[ph] * t; yq -= x * sinv[ph] * t
            dI.append(1 if yi < 0 else 0); dQ.append(1 if yq < 0 else 0)
        errs += sum(1 for k in range(90) if (dI[k], dQ[k]) != hdr[k])
        cw = []; i = 0; o = 90
        for slot in range(_S2_SLOTS):
            for _ in range(90):
                a, b = dI[o], dQ[o]; r = rn[i]; o += 1; i += 1
                if r == 0: cw += [a, b]
                elif r == 1: cw += [b, 1 - a]
                elif r == 2: cw += [1 - a, 1 - b]
                else: cw += [1 - b, a]
            if (slot + 1) % 16 == 0 and slot + 1 < _S2_SLOTS: o += 36; i += 36
        bb = [a ^ b for a, b in zip(cw[:_S2_KBCH], prbs)]
        by = bytes(sum(bb[8 * q + j] << (7 - j) for j in range(8)) for q in range(10))
        if _s2_crc8(by[:9]) != by[9]: return None, "BBHEADER CRC fail in frame %d" % f
        syncd = by[7] << 8 | by[8]
        fields.append((syncd, bytes(sum(bb[80 + 8 * q + j] << (7 - j) for j in range(8)) for q in range(_S2_DFL // 8))))
    stream = b"".join(fl for _, fl in fields)
    start = fields[0][0] // 8
    pk = []; prev = None; crcbad = 0
    for p0 in range(start, len(stream) - 187, 188):
        up = stream[p0:p0 + 188]
        if prev is not None and _s2_crc8(prev[1:]) != up[0]: crcbad += 1
        pk.append(b"\x47" + up[1:]); prev = up
    return pk, "header symbol errors %d, CRC-8 errors %d" % (errs, crcbad)


def selftest_dvbs2():
    res = []
    # synthetic TS packets (PID 0x100, counter, pattern) - no ffmpeg needed
    packets = [bytes([0x47, 0x41, 0x00, 0x10 | (i & 15)]) + bytes(((i * 7 + j) * 13) & 255 for j in range(184)) for i in range(20)]
    stream = _s2_user_packets(packets)
    nf = 4                              # 4 frames = a whole number of carrier cycles, so the circular test wraps cleanly
    cws, sI, sQ = _s2_frames(stream + stream, nf)
    res.append(("DVB-S2 BCH(3240,3072) remainder 0", all(_s2_bch_ok(c[:_S2_K]) for c in cws), "%d frames" % nf))
    res.append(("DVB-S2 LDPC(16200,3240) H*c = 0", all(_s2_ldpc_ok(c) for c in cws), "%d frames, accumulator form" % nf))
    bad = list(cws[0]); bad[_S2_K + 5] ^= 1
    res.append(("DVB-S2 LDPC check sees a flipped bit", not _s2_ldpc_ok(bad), ""))
    res.append(("DVB-S2 frame length", len(sI) == nf * _S2_FRAME, "%d symbols per PLFRAME" % _S2_FRAME))
    audio = _s2_shape(sI, sQ)
    got, det = _s2_receive(audio, nf)
    want = (packets + packets)[:len(got)] if got else []
    ok = bool(got) and got == want and "CRC-8 errors 0" in det and "symbol errors 0" in det
    res.append(("DVB-S2 TS loopback from audio (RRC, fs/4, descramble)", ok, "%d packets back, %s" % (len(got or []), det)))
    return res


# ---- tone generators, analog and HF modes, framework (merged into jacktx.py) ----
import subprocess, sys, time, wave, signal, struct

CLOCK_HZ = 6.144e6
MAC = sys.platform == "darwin"
WIN = sys.platform == "win32"
_FFMPEG_MAC = "/opt/homebrew/bin/ffmpeg"
SONG = ""   # set with --audio FILE
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
HF_SHIFT = 10000.0      # HF audio modes (SSTV, WEFAX): USB dial = 6.144 MHz + 10 kHz, the tones sit 10 kHz higher in the jack's audio

_SIN_N = 4096
_SIN = array.array("f", [math.sin(2 * math.pi * i / _SIN_N) for i in range(_SIN_N)])


def mhz(audio_hz):
    return "%.6f MHz" % ((CLOCK_HZ + audio_hz) / 1e6)


def tone_segments(segs, rate=RATE, shift=0.0, amp=1.0):
    """Phase-continuous FSK from (frequency Hz, duration s) segments; frequency 0 = silence. Fractional durations are carried over."""
    out = array.array("f"); acc = 0; t_acc = 0.0
    tab = _SIN; scale = 2 ** 32 / rate; mask = 0xFFFFFFFF
    for f, dur in segs:
        t_acc += dur * rate
        n = int(t_acc); t_acc -= n
        if f <= 0:
            out.extend(array.array("f", bytes(4 * n))); continue
        inc = int((f + shift) * scale)
        blk = array.array("f", [0.0]) * n
        for i in range(n):
            acc = (acc + inc) & mask
            blk[i] = tab[acc >> 20]
        if amp != 1.0:
            blk = array.array("f", [v * amp for v in blk])
        out.extend(blk)
    return out


def _cached(name, key, build):
    """build() -> array('f'); stored as raw float32 under CACHE with the key in the file name."""
    os.makedirs(CACHE, exist_ok=True)
    if SONG and os.path.exists(SONG):                  # audio renders depend on the file: put its identity in the key
        import hashlib
        st = os.stat(SONG)
        key += "-" + hashlib.sha1(("%s|%d|%d" % (os.path.abspath(SONG), st.st_size, int(st.st_mtime))).encode()).hexdigest()[:10]
    p = os.path.join(CACHE, "%s-%s.f32" % (name, key))
    if os.path.exists(p):
        a = array.array("f")
        with open(p, "rb") as f: a.frombytes(f.read())
        return a
    a = build()
    with open(p + ".tmp", "wb") as f: a.tofile(f)
    os.replace(p + ".tmp", p)
    return a


# ---------------- RTTY (port of lfrtty.py) ----------------
_RTTY_LTRS = {"A": 3, "B": 25, "C": 14, "D": 9, "E": 1, "F": 13, "G": 26, "H": 20, "I": 6, "J": 11, "K": 15, "L": 18, "M": 28,
              "N": 12, "O": 24, "P": 22, "Q": 23, "R": 10, "S": 5, "T": 16, "U": 7, "V": 30, "W": 19, "X": 29, "Y": 21, "Z": 17}
_RTTY_FIGS = {"1": 23, "2": 19, "3": 1, "4": 10, "5": 16, "6": 21, "7": 7, "8": 6, "9": 24, "0": 22, "-": 3, "?": 25, ":": 14,
              ".": 28, ",": 12, "/": 29, "(": 15, ")": 18, "'": 11}
_RTTY_TEXT = ("RYRYRYRYRY\nCQ CQ CQ DE N0CALL N0CALL\nTEST VIA HEADPHONE JACK 6.156 MHZ\n"
              "THE QUICK BROWN FOX JUMPS OVER THE LAZY DOG 0123456789\n")
_RTTY_SPACE = 12000.0


def rtty_codes(text):
    codes, shift = [31, 31], "L"
    for ch in text.upper():
        if ch == "\n": codes += [8, 2]; continue
        if ch == " ": codes.append(4); continue
        if ch in _RTTY_LTRS:
            if shift != "L": codes.append(31); shift = "L"
            codes.append(_RTTY_LTRS[ch])
        elif ch in _RTTY_FIGS:
            if shift != "F": codes.append(27); shift = "F"
            codes.append(_RTTY_FIGS[ch])
    return codes


def rtty_segments(text, space, shift=170.0, baud=45.45, lead=30.0, tail=20.0):
    mark = space + shift; segs = [(mark, lead / baud)]
    for c in [31] * 10 + rtty_codes(text):
        segs.append((space, 1 / baud))
        for k in range(5): segs.append((mark if (c >> k) & 1 else space, 1 / baud))
        segs.append((mark, 1.5 / baud))
    segs.append((mark, tail / baud))
    return segs


def rtty_decode_segments(segs, space):
    """Loopback check: read the bit sequence back out of the segment list and decode ITA2."""
    bits = []; baud_t = 1 / 45.45
    for f, d in segs: bits += [1 if f > space else 0] * max(1, int(round(d / baud_t * 2)))   # half-bit resolution
    inv_l = {v: k for k, v in _RTTY_LTRS.items()}; inv_f = {v: k for k, v in _RTTY_FIGS.items()}
    out = []; i = 0; figs = False
    while i < len(bits) - 14:
        if bits[i] == 1 and bits[i + 1] == 0:
            i += 1; c = 0
            for k in range(5): c |= bits[i + 2 + 2 * k + 1] << k    # middle of each data bit
            if bits[i + 13] != 1: i += 1; continue
            if c == 31: figs = False
            elif c == 27: figs = True
            elif c == 4: out.append(" ")
            elif c == 8: pass
            elif c == 2: out.append("\n")
            else: out.append((inv_f if figs else inv_l).get(c, "?"))
            i += 13                      # to the last half of the stop bit
        else: i += 1
    return "".join(out)


def mode_rtty(rate, cache_dir):
    s = _cached("rtty", "v1", lambda: tone_segments(rtty_segments(_RTTY_TEXT * 3, _RTTY_SPACE), rate))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "RTTY 45.45 baud, 170 Hz shift, ITA2: space %s, mark %s (mark is the higher RF)" % (mhz(_RTTY_SPACE), mhz(_RTTY_SPACE + 170)),
        "OnAir: HF digital -> RTTY 45/170. USB dial %s puts space at 2125 Hz / mark 2295 Hz audio (turn on Reverse if it prints garbage)"
        % mhz(_RTTY_SPACE - 2125),
        "Width ~250 Hz. Loop ~%.0f s." % (len(s) / rate)]}


# ---------------- SSTV Martin M1 ----------------
def _sstv_picture():
    """320 x 256 RGB test card: colour bars, grey gradient, big ONAIR, callsign and the text."""
    W, H = 320, 256
    img = [[(10, 20, 90)] * W for _ in range(H)]
    bars = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0)]
    for y in range(0, 56):
        img[y] = [bars[x * 8 // W] for x in range(W)]
    for y in range(56, 80):                                   # grey ramp
        img[y] = [(x * 255 // (W - 1),) * 3 for x in range(W)]
    for y in range(80, 92):                                   # colour ramp red -> blue
        img[y] = [(255 - x * 255 // (W - 1), 64, x * 255 // (W - 1)) for x in range(W)]
    draw_text(img, (W - 29 * 9) // 2 + 4, 106, "ONAIR", 9, (0, 0, 0))     # shadow
    draw_text(img, (W - 29 * 9) // 2, 102, "ONAIR", 9, (255, 200, 0))
    draw_text(img, (W - 47 * 3) // 2, 176, "JACKTX", 3, (255, 255, 255))
    draw_text(img, (W - 95 * 2) // 2, 206, "TEST VIA MACBOOK", 2, (120, 255, 120))
    draw_text(img, (W - 83 * 2) // 2, 228, "HEADPHONE JACK", 2, (120, 255, 120))
    return img


def sstv_segments(img, vis=44, line_ms=146.432):
    """Martin M1 (J. L. Barber N7CXI timings, as OnAir's hfdig_sstv_modes.h): VIS header, then per line sync 4.862 ms 1200 Hz,
    porch 0.572 ms 1500 Hz, green, 0.572 gap, blue, 0.572 gap, red, 0.572 gap. 1500 Hz black .. 2300 Hz white."""
    segs = [(0, 0.4), (1900, 0.3), (1200, 0.01), (1900, 0.3), (1200, 0.03)]
    par = 0
    for k in range(7):
        b = (vis >> k) & 1; par ^= b; segs.append((1100 if b else 1300, 0.03))
    segs += [(1100 if par else 1300, 0.03), (1200, 0.03)]
    W = len(img[0]); px = line_ms / 1000 / W
    for row in img:
        segs += [(1200, 0.004862), (1500, 0.000572)]
        for comp in (1, 2, 0):
            for p in row: segs.append((1500 + 800 * p[comp] / 255.0, px))
            segs.append((1500, 0.000572))
    segs.append((0, 1.5))
    return segs


def mode_sstv(rate, cache_dir):
    s = _cached("sstv", "v1", lambda: tone_segments(sstv_segments(_sstv_picture()), rate, HF_SHIFT))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "SSTV Martin M1 (VIS 44), 320x256 colour test card, %.0f s per picture" % (len(s) / rate),
        "USB dial %s (tones 1500-2300 Hz audio, sync 1200 Hz); RF %s .. %s" % (mhz(HF_SHIFT), mhz(HF_SHIFT + 1100), mhz(HF_SHIFT + 2300)),
        "OnAir: HF digital -> SSTV (auto VIS). Width ~1.2 kHz, constant envelope."]}


# ---------------- WEFAX 120 LPM / IOC 576 ----------------
_WEFAX_LINE_S = 0.5
_WEFAX_PX = 1810                    # IOC 576: pi * 576 = 1809.6 pixels per line


def _wefax_map(lines):
    """A simple synoptic chart: white paper, black coast, isobars, highs/lows, title."""
    W = _WEFAX_PX
    img = [[255] * W for _ in range(lines)]
    def put(x, y, v=0):
        if 0 <= y < lines and 0 <= x < W: img[y][x] = v
    # coastline: a wiggly curve
    for x in range(W):
        y = int(lines * 0.55 + lines * 0.12 * math.sin(x / 140.0) + lines * 0.05 * math.sin(x / 37.0))
        for d in range(2): put(x, y + d)
        for yy in range(y + 2, lines, 6):                    # hatched land
            if (x + yy) % 12 == 0: put(x, yy, 120)
    # isobars around a low and a high
    for cx, cy, lab in ((W * 0.3, lines * 0.35, "L"), (W * 0.72, lines * 0.5, "H")):
        for r in range(40, 400, 60):
            n = int(2 * math.pi * r * 1.2)
            for k in range(n):
                a = 2 * math.pi * k / n
                put(int(cx + r * math.cos(a) * 1.4), int(cy + r * math.sin(a) * 0.35))
        draw_text(img, int(cx) - 15, int(cy) - 21, lab, 6, 0)
    # cold front with triangles
    for x in range(int(W * 0.35), int(W * 0.6)):
        y = int(lines * 0.25 + (x - W * 0.35) * 0.18)
        put(x, y); put(x, y + 1)
        if x % 50 < 12:
            for t in range(12 - x % 50): put(x, y - t)
    for x in range(0, W, 120): # grid ticks
        for y in range(0, lines, 3): put(x, y, 180)
    draw_text(img, 40, 6, "JACKTX WEFAX  TEST VIA HEADPHONE JACK", 3, 0)
    draw_text(img, 40, lines - 30, "SURFACE ANALYSIS  TEST CHART", 3, 0)
    return img


def wefax_segments(lines=180):
    px = _WEFAX_LINE_S / _WEFAX_PX
    segs = []
    for _ in range(int(5 * 300)):                         # start tone: black/white at 300 Hz for 5 s (IOC 576)
        segs += [(2300, 1 / 600), (1500, 1 / 600)]
    for _ in range(60):                                   # 30 s phasing: white pulse (5 % of the line) then black
        segs += [(2300, _WEFAX_LINE_S * 0.05), (1500, _WEFAX_LINE_S * 0.95)]
    for row in _wefax_map(lines):
        run_v, run_n = row[0], 0
        for v in row:                                     # merge equal pixels into one segment (fast)
            if v == run_v: run_n += 1
            else: segs.append((1500 + 800 * run_v / 255.0, run_n * px)); run_v, run_n = v, 1
        segs.append((1500 + 800 * run_v / 255.0, run_n * px))
    for _ in range(int(5 * 450)):                         # stop tone: 450 Hz for 5 s, then 10 s black
        segs += [(2300, 1 / 900), (1500, 1 / 900)]
    segs.append((1500, 10.0))
    return segs


def mode_wefax(rate, cache_dir):
    s = _cached("wefax", "v1", lambda: tone_segments(wefax_segments(), rate, HF_SHIFT))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "WEFAX 120 LPM, IOC 576, start 300 Hz / phasing / stop 450 Hz, 180-line weather chart (%.0f s)" % (len(s) / rate),
        "USB dial %s (1500 black .. 2300 white, centre 1900 Hz audio = %s)" % (mhz(HF_SHIFT - 1900 + 1900 - 0), mhz(HF_SHIFT + 1900)),
        "OnAir: Marine -> WEFAX (or HF fax), 120 LPM IOC 576. Width ~1 kHz, constant envelope."]}


# ---------------- spectrum art ----------------
def _specart_rows():
    """Rows (bottom row first, as the waterfall scrolls down) of a 100-column picture: an antenna logo and ONAIR."""
    w, h, m = text_mask("ONAIR", 3)                # 87 x 21
    W = 100; rows = [[0] * W for _ in range(h + 18)]
    for y in range(h): rows[y + 18][6:6 + w] = m[y][:W - 6]
    # logo above the text: a mast with three arcs each side
    cx = 50
    for y in range(2, 16): rows[y][cx] = 1
    for r in (4, 8, 12):
        for k in range(-40, 41):
            a = math.radians(k)
            x = int(round(cx + r * math.sin(a))); y = int(round(8 - r * 0.45 * math.cos(a)))
            if 0 <= y < 18: rows[y][x] = 1
            x2 = int(round(cx - r * math.sin(a)))
            if 0 <= y < 18: rows[y][x2] = 1
    rows.reverse()
    return rows


def mode_specart(rate, cache_dir, base=19000.0, spacing=100.0, row_s=0.12):
    """Each row is a sum of tones on a 100 Hz grid, so one 10 ms period is computed and repeated (cheap); rows crossfade."""
    def build():
        rows = _specart_rows(); W = len(rows[0])
        per = int(rate / spacing)                        # 960 samples = one period of every tone on the grid
        reps = max(1, int(row_s * spacing))
        out = array.array("f"); ph = [(k * k * 0.618) % 1 * 2 * math.pi for k in range(W)]   # Newman phases: low crest factor
        for row in rows + [[0] * W] * 8:
            on = [k for k in range(W) if row[k]]
            if not on: out.extend(array.array("f", bytes(4 * per * reps))); continue
            g = 1.0 / math.sqrt(len(on))
            per_blk = [0.0] * per
            for k in on:
                w = 2 * math.pi * (base + k * spacing) / rate; p = ph[k]
                for i in range(per): per_blk[i] += math.sin(w * i + p)
            blk = array.array("f", [v * g for v in per_blk]) * reps
            ramp = per // 4
            for i in range(ramp):                       # fade each row in and out to keep the waterfall clean
                f = 0.5 - 0.5 * math.cos(math.pi * i / ramp); blk[i] *= f; blk[-1 - i] *= f
            out.extend(blk)
        pk = max(1e-9, max(abs(v) for v in out))
        return array.array("f", [v / pk for v in out])
    s = _cached("specart", "v1", build)
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "Waterfall art: logo + ONAIR, %s .. %s (10 kHz wide), %.1f s per picture, looping" % (mhz(base), mhz(base + 99 * spacing), len(s) / rate),
        "OnAir: any mode's waterfall (e.g. Spectrum / General) centred near %s, span >= 20 kHz, slow scroll; text reads upright"
        " when new lines enter at the top." % mhz(base + 5000)]}


# ---------------- audio modes via ffmpeg ----------------
def _ff(af, rate, seconds=None, src=None):
    """Decode the audio file (--audio) through an ffmpeg filter chain to mono float32 at `rate`."""
    src = src or SONG
    if not src: sys.exit("this mode plays an audio file: add --audio FILE (any format ffmpeg reads)")
    if not os.path.exists(src): sys.exit("audio file not found: " + src)
    cmd = [ffmpeg_path(), "-v", "error", "-i", src]
    if seconds: cmd += ["-t", str(seconds)]
    cmd += ["-ac", "1", "-af", "aresample=%d,%s" % (rate, af), "-ar", str(rate), "-f", "f32le", "-"]   # filter at the output rate
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    a = array.array("f"); a.frombytes(raw[: len(raw) // 4 * 4]); return a


def _lp(f, n=4): return ",".join(["lowpass=f=%d" % f] * n)
def _hp(f, n=2): return ",".join(["highpass=f=%d" % f] * n)
_COMP = "acompressor=threshold=0.05:ratio=8:attack=5:release=200:makeup=4:knee=4"
_LIM = "alimiter=limit=0.9:attack=2:release=50:level=false"


def am_chain(rate, fc, af_hz, mod=0.95, seconds=None):
    """Own carrier at fc, heavy compression + limiter, audio band-limited after the limiter, then hard-clipped at the modulation peak."""
    chain = ",".join([_hp(50), _lp(af_hz), _COMP, "acompressor=threshold=0.2:ratio=20:attack=1:release=60:makeup=2", "volume=3", _LIM,
                      _lp(af_hz, 3), "aeval=max(-1\\,min(1\\,val(0)/0.9))",
                      "aeval=(1+%.3f*val(0))*cos(2*PI*%.1f*t)/(1+%.3f)" % (mod, fc, mod)])
    return _ff(chain, rate, seconds)


def fm_chain(rate, fc, dev, af_hz, pre_us=0, seconds=None):
    """FM in ffmpeg: compressed, band-limited audio -> leaky integrator (aiir) -> cos(w0 t + k * integral)."""
    parts = [_hp(30), _lp(af_hz)]
    if pre_us:                                           # pre-emphasis: y = x - a x[n-1], gain-normalised by the limiter after it
        a = math.exp(-1 / (pre_us * 1e-6 * rate))
        parts.append("aiir=z=1 -%.6f:p=1:k=1:f=tf:r=d:e=dbl:n=0:mix=1" % a)
    parts += [_COMP, "volume=3", _LIM, _lp(af_hz, 3), "aeval=max(-1\\,min(1\\,val(0)/0.9))",
              "aiir=z=1:p=1 -0.999995:k=1:f=tf:r=d:e=dbl:n=0:mix=1",
              "aeval=cos(2*PI*%.1f*t+%.9f*val(0))" % (fc, 2 * math.pi * dev / rate)]
    return _ff(",".join(parts), rate, seconds)


def mode_am(rate, cache_dir):
    # the DAC clock leak at 6.144 MHz is the carrier and costs no output power, so all of it goes into the sidebands:
    # band-limited, heavily compressed and limited audio, no carrier of our own (a separate carrier wastes most of the output power)
    chain = ",".join([_hp(50), _lp(7000), _COMP, "acompressor=threshold=0.2:ratio=20:attack=1:release=60:makeup=2", "volume=3", _LIM,
                      _lp(7000, 3), "aeval=max(-1\\,min(1\\,val(0)/0.9))"])
    s = _cached("am", "v5clock", lambda: _ff(chain, rate, None))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "AM at %s (the DAC clock is the carrier), 14 kHz wide (audio 50 Hz - 7 kHz, heavy compression + limiter)" % mhz(0),
        "OnAir: Analog -> AM, bandwidth 14-16 kHz (narrower, e.g. 9 kHz, is quieter in noise and still fine)."]}


def mode_nfm(rate, cache_dir):
    s = _cached("nfm", "v4", lambda: fm_chain(rate, 24000.0, 8000.0, 6000))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "NFM at %s, deviation +-8 kHz, audio to 6 kHz, compressed (Carson ~28 kHz: %s .. %s)" % (mhz(24000), mhz(10000), mhz(38000)),
        "OnAir: Analog -> NFM, bandwidth 25-30 kHz. De-emphasis: OFF (no pre-emphasis is applied)."]}


def mode_wfm(rate, cache_dir):
    s = _cached("wfm", "v4", lambda: fm_chain(rate, 24000.0, 17000.0, 10000, pre_us=50))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "WFM at %s, deviation +-17 kHz, audio to 10 kHz, 50 us pre-emphasis (Carson ~54 kHz; the jack window is 2-46 kHz)" % mhz(24000),
        "OnAir: Analog -> WFM (mono), bandwidth ~50 kHz, de-emphasis 50 us.",
        "Warning: at ~25 dB tone SNR this is likely below the FM threshold (+-15 kHz is usually invisible). Prefer -nfm or -am."]}


def mode_usb(rate, cache_dir, dial=12000.0):
    chain = ",".join([_hp(100, 4), _lp(3500, 4), _COMP, "acompressor=threshold=0.2:ratio=20:attack=1:release=60:makeup=2", "volume=2.5", _LIM,
                      _hp(100, 2), _lp(3500, 4),
                      # SSB by phasing: afreqshift is an IIR (all-pass pair) Hilbert shifter, so only the upper sideband appears
                      "afreqshift=shift=%.1f:level=1" % dial])
    s = _cached("usb", "v4", lambda: _ff(chain, rate))
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "USB voice/music, dial (suppressed carrier) %s, audio 100-3500 Hz -> RF %s .. %s" % (mhz(dial), mhz(dial + 100), mhz(dial + 3500)),
        "OnAir: Analog -> USB, filter 3.5 kHz."]}


def mode_multi(rate, cache_dir, seconds=60):
    def build():
        am = am_chain(rate, 36000.0, 4500, seconds=seconds)
        n = len(am)
        rt = tone_segments(rtty_segments(_RTTY_TEXT * 4, 8000.0), rate)
        burst = aprs_burst(rate, 20000.0)
        out = array.array("f", [0.45 * v for v in am])
        for i in range(min(n, len(rt))): out[i] += 0.25 * rt[i]
        p = int(2 * rate)
        while p + len(burst) < n:                          # an APRS packet every 10 s
            for i, v in enumerate(burst): out[p + i] += 0.25 * v
            p += 10 * rate
        return out
    s = _cached("multi", "v3", build)
    return {"samples": s, "cycle": None, "phase": 0, "tune": [
        "One headphone jack, three stations:",
        "  AM music at %s, 9 kHz wide (audio to 4.5 kHz) -> OnAir Analog -> AM" % mhz(36000),
        "  RTTY 45.45/170: space %s, mark %s -> OnAir HF digital -> RTTY, USB dial %s" % (mhz(8000), mhz(8170), mhz(8000 - 2125)),
        "  APRS 1200 Bd AFSK on NFM +-3.5 kHz at %s, a packet every 10 s -> OnAir APRS (map pin)" % mhz(20000),
        "  Amplitude split 0.45 / 0.25 / 0.25 (each station is quieter than in its own mode)."]}
# ---------------- selftest ----------------
def selftest_main():
    res = []
    segs = rtty_segments(_RTTY_TEXT, _RTTY_SPACE)
    got = rtty_decode_segments(segs, _RTTY_SPACE)
    res.append(("RTTY ITA2 round trip", _RTTY_TEXT.strip() in got, repr(got[:60])))
    # RTTY waveform: measure the tone of a few bits with a Goertzel pair on the rendered audio
    wav = tone_segments(segs[:40], RATE)
    n = int(RATE / 45.45); i0 = int(RATE * 30 / 45.45) + n // 4
    def gz(x, f):
        w = 2 * math.cos(2 * math.pi * f / RATE); s1 = s2 = 0.0
        for v in x: s1, s2 = v + w * s1 - s2, s1
        return s1 * s1 + s2 * s2 - w * s1 * s2
    exp = [b for _, b in [(0, 0)]]
    ok = True; bits = []
    for k in range(7):
        blk = wav[i0 + k * n: i0 + k * n + n // 2]
        bits.append(1 if gz(blk, _RTTY_SPACE + 170) > gz(blk, _RTTY_SPACE) else 0)
    want = [0] + [(31 >> k) & 1 for k in range(5)] + [1]           # first LTRS after the lead: start, 11111, stop
    res.append(("RTTY FSK tones (Goertzel)", bits == want, "%s vs %s" % (bits, want)))
    img = _sstv_picture(); s = sstv_segments(img)
    dur = sum(d for _, d in s)
    res.append(("SSTV Martin M1 timing", abs(dur - (0.4 + 0.91 + 256 * 0.446446 + 1.5)) < 0.05, "%.2f s" % dur))
    return res


def selftest():
    t0 = time.time(); allres = []
    for name, fn in (("main", selftest_main), ("digi", selftest_digi), ("sat", selftest_sat), ("dvbs2", selftest_dvbs2)):
        try: r = fn()
        except Exception as e: r = [(name + " selftest crashed", False, repr(e))]
        allres += r
    for n, ok, d in allres: print("%-4s %-42s %s" % ("PASS" if ok else "FAIL", n, d))
    bad = sum(1 for _, ok, _ in allres if not ok)
    print("%d checks, %d failed, %.1f s" % (len(allres), bad, time.time() - t0))
    return 1 if bad else 0


# ---------------- output device, playback ----------------
def _helper():
    exe = os.path.join(CACHE, "jackaudio"); src = os.path.join(HERE, "jackaudio.swift")
    if not os.path.exists(exe) or os.path.getmtime(exe) < os.path.getmtime(src):
        os.makedirs(CACHE, exist_ok=True)
        print("building the CoreAudio helper (once)...")
        subprocess.run(["swiftc", "-O", src, "-o", exe], check=True)
    return exe


def device_info(exe):
    """The headphone jack itself (not the system output): name, present, nominal rate, volume."""
    out = subprocess.run([exe, "info"], check=True, stdout=subprocess.PIPE, text=True).stdout.strip().split("\t")
    return out[0], out[1] == "1", int(out[2]), float(out[3])


def set_rate(exe, r):
    out = subprocess.run([exe, "set", str(int(r))], check=True, stdout=subprocess.PIPE, text=True).stdout.strip().split("\t")
    return int(out[1])


def ffmpeg_path():
    """ffmpeg for the audio and DVB-S2 modes: the Homebrew one on macOS if present, else the first on PATH (ffmpeg.exe on Windows)."""
    import shutil
    if MAC and os.path.exists(_FFMPEG_MAC): return _FFMPEG_MAC
    p = shutil.which("ffmpeg")
    if not p:
        sys.exit("ffmpeg not found: install it and make sure it is on PATH (%s)."
                 % ("Windows: download a build, e.g. from ffmpeg.org, and add its bin folder to PATH" if WIN else "macOS: brew install ffmpeg; Linux: your package manager"))
    return p


# ---------------- find mode: locate the clock leak with an SDR ----------------
def find_candidates():
    """(MHz, why) candidate leak frequencies: sample rate x 64/128/256/512 within 1-30 MHz, plus common codec master clocks."""
    c = {}
    for fs in (44100, 48000, 96000, 192000):
        for k in (64, 128, 256, 512):
            f = fs * k / 1e6
            if 1.0 <= f <= 30.0: c.setdefault(round(f, 6), []).append("%g kHz x %d" % (fs / 1e3, k))
    for f in (24.576, 22.5792, 12.288, 11.2896, 6.144): c.setdefault(f, []).append("codec master clock")
    return sorted((f, ", ".join(w)) for f, w in c.items())


def mode_find(rate, cache_dir, period=10.0, lo=2000.0, hi=40000.0):
    """Slow triangle sweep lo -> hi -> lo over `period` s at a steady level, plus a 1 kHz beep at the start of each sweep."""
    n = int(period * rate); half = n // 2; s = array.array("f"); ph = 0.0
    for i in range(n):
        x = i / half if i < half else (n - i) / half            # 0 -> 1 -> 0
        ph += 2 * math.pi * (lo + (hi - lo) * x) / rate
        s.append(0.7 * math.sin(ph))
    for i in range(int(0.15 * rate)):                              # beep: marks the start of every sweep
        s[i] += 0.3 * math.sin(2 * math.pi * 1000.0 * i / rate)
    tune = ["Finder: sweep %d -> %d kHz and back every %g s at a steady level, beep at the start of each sweep." % (lo / 1e3, hi / 1e3, period),
            "With an SDR scan 1-30 MHz for a line that moves in step with the sweep (it moves up to %.0f kHz away from the clock, one copy each side)." % (hi / 1e3),
            "The line centre is the clock: pass it as --clock MHZ. Candidates to check first:"]
    for f, why in find_candidates(): tune.append("  %9.4f MHz  (%s)" % (f, why))
    return {"samples": s, "cycle": None, "phase": 0, "tune": tune}


# ---------------- playback on Windows / Linux ----------------
def _wav_info(path):
    with wave.open(path, "rb") as w: return w.getframerate(), w.getnframes() / float(w.getframerate())


class _WinPlayer:
    """winsound on the default output device; async + sleep so Ctrl+C is handled at once. loop=True repeats the WAV without a gap."""
    def __init__(self, wav, loop):
        import winsound
        self.ws = winsound; self.dur = _wav_info(wav)[1]; self.loop = loop; self.t_end = time.time() + self.dur; self.stopped = False
        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | (winsound.SND_LOOP if loop else 0)
        winsound.PlaySound(wav, flags)
    def poll(self): return None if not self.stopped and (self.loop or time.time() < self.t_end) else 0
    def wait(self, t=None):
        while self.poll() is None: time.sleep(0.1)
    def terminate(self): self.stopped = True; self.ws.PlaySound(None, 0)
    kill = terminate


class _SDPlayer:
    """sounddevice raw stream (no numpy) to a named device, in a thread; plays the WAV once."""
    def __init__(self, wav, device):
        import sounddevice as sd, threading
        self.t = threading.Thread(target=self._run, args=(sd, wav, device), daemon=True); self.stop = False; self.t.start()
    def _run(self, sd, wav, device):
        with wave.open(wav, "rb") as w:
            data = w.readframes(w.getnframes()); rate = w.getframerate()
        with sd.RawOutputStream(samplerate=rate, channels=2, dtype="int16", device=device) as st:
            step = 4 * 4096
            for i in range(0, len(data), step):
                if self.stop: return
                st.write(data[i:i + step])
    def poll(self): return None if self.t.is_alive() else 0
    def wait(self, t=None): self.t.join(t)
    def terminate(self): self.stop = True
    kill = terminate


def playback_plan(plat, wav, have_sd=False, device=None, aplay=None, exe=None):
    """Dry description of how a WAV is played: (kind, command list or None). Used by main() and testable without any audio."""
    if plat == "darwin": return "helper", [exe or "jackaudio", "play", wav]
    if device and have_sd: return "sounddevice", None
    if plat == "win32": return "winsound", None
    if aplay: return "aplay", [aplay, "-q"] + (["-D", device] if device else []) + [wav]
    return "none", None


def start_player(plan, wav, loop, device=None):
    kind, cmd = plan
    if kind in ("helper", "aplay"): return subprocess.Popen(cmd)
    if kind == "winsound": return _WinPlayer(wav, loop)
    if kind == "sounddevice": return _SDPlayer(wav, device)
    sys.exit("no way to play audio here: install aplay (alsa-utils) or pip install sounddevice")


def _have_sounddevice():
    try: import sounddevice; return True
    except Exception: return False


def other_os_setup(args, wav):
    """Windows/Linux: print what the user has to set up (the rate cannot be set from Python); returns (plan, device)."""
    import shutil
    device = args[args.index("--device") + 1] if "--device" in args else None
    have_sd = _have_sounddevice()
    if device == "list":
        if not have_sd: sys.exit("--device list needs: pip install sounddevice")
        import sounddevice as sd; print(sd.query_devices()); sys.exit(0)
    if device and not have_sd and WIN:
        print("note: --device needs the sounddevice package (pip install sounddevice); playing on the default output instead.")
        device = None
    rate = _wav_info(wav)[0]
    plan = playback_plan(sys.platform, wav, have_sd, device, shutil.which("aplay"))
    if plan[0] == "none": sys.exit("no way to play audio here: install aplay (alsa-utils) or pip install sounddevice")
    print("output: %s. The WAV is %d Hz and the sample rate cannot be set from here." % (
        "device '%s' via sounddevice" % device if plan[0] == "sounddevice" else "the default output device (%s)" % plan[0], rate))
    if WIN:
        print("  Set the output device to %d Hz: Settings > Sound > the device > Advanced > Default Format (%d Hz)." % (rate, rate))
        if plan[0] != "sounddevice": print("  Make the headphone jack the default output while transmitting (and keep its volume at 100 %).")
    else:
        print("  Make sure the card runs at %d Hz (e.g. aplay -D hw:... or your mixer/pipewire settings), and keep its volume at 100 %%." % rate)
    return plan, device


def write_wav(path, samples, level_db):
    pk = max(1e-9, max(abs(v) for v in samples)); g = 10 ** (level_db / 20) / pk * 32767
    pcm = array.array("h", [int(v * g) for v in samples])
    st = array.array("h", [0]) * (2 * len(pcm)); st[0::2] = pcm; st[1::2] = pcm
    with wave.open(path + ".tmp", "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE); w.writeframes(st.tobytes())
    os.replace(path + ".tmp", path)


MODES = ["am", "nfm", "wfm", "usb", "rtty", "sstv", "wefax", "specart", "aprs", "pocsag", "ft8", "wspr", "multi", "noaa", "sonde", "dvbs2", "find"]


def main():
    args = sys.argv[1:]
    if "--selftest" in args: sys.exit(selftest())
    level = -1.0
    global SONG
    if "--audio" in args:
        SONG = os.path.expanduser(args[args.index("--audio") + 1])
    if "--level" in args:
        level = float(args[args.index("--level") + 1])
    if level > 0: sys.exit("level above 0 dBFS refused")
    global CLOCK_HZ
    if "--clock" in args:
        try: CLOCK_HZ = float(args[args.index("--clock") + 1]) * 1e6
        except (IndexError, ValueError): sys.exit("--clock needs a number in MHz, e.g. --clock 12.288")
        if not 0.1e6 <= CLOCK_HZ <= 100e6: sys.exit("--clock MHZ out of range")
    mode = next((a[1:] for a in args if a.startswith("-") and not a.startswith("--") and a[1:] in MODES), None)
    if not mode:
        help_rows = [
            ("-am", "music, AM (DAC clock is the carrier)", "AM 6.144000 MHz, 14 kHz"),
            ("-nfm", "music, narrow FM", "NFM 6.168000 MHz, 25 kHz"),
            ("-wfm", "music, wide FM (weak)", "WFM 6.168000 MHz, 50 kHz"),
            ("-usb", "music, single sideband", "USB dial 6.156000 MHz"),
            ("-rtty", "RTTY text 45.45 bd / 170 Hz", "USB dial 6.153875 MHz (OnAir RTTY 6.156)"),
            ("-sstv", "SSTV colour picture (Martin M1)", "USB dial 6.154000 MHz"),
            ("-wefax", "weather fax map (120 LPM)", "USB dial 6.154000 MHz"),
            ("-specart", "ONAIR logo painted on the waterfall", "waterfall 6.163-6.173 MHz"),
            ("-aprs", "APRS position, map pin", "NFM 6.164000 MHz"),
            ("-pocsag", "pager message (512 bd)", "POCSAG 6.162500 MHz"),
            ("-ft8", "FT8 CQ every 15 s", "USB dial 6.154500 MHz"),
            ("-wspr", "WSPR beacon, even minutes", "USB dial 6.154500 MHz"),
            ("-multi", "AM + RTTY + APRS at once", "6.180 / 6.152 / 6.164 MHz"),
            ("-noaa", "NOAA APT weather-satellite image", "NOAA APT 6.168000 MHz"),
            ("-sonde", "RS41 weather balloon, map", "6.159000 MHz (centre off it)"),
            ("-dvbs2", "DVB-S2 video, 32 ksym/s", "6.168000 MHz (receiver must accept 32 ksym/s)"),
            ("-find", "sweep 2-40 kHz, to find the clock line", "scan 1-30 MHz for a line moving with the sweep"),
        ]
        print("jacktx: transmit test signals out of the headphone jack (DAC clock 6.144 MHz). Ctrl+C stops.")
        print("Based on jacktx by Kristijonas Adomaitis - https://github.com/adswill/jacktx (GPL-3.0-or-later)\n")
        print("usage: python3 -I jacktx.py -<mode> [--audio FILE] [--level -1] [--render-only] [--clock MHZ] [--device NAME]")
        print("       python3 -I jacktx.py --selftest")
        print("The frequencies below assume the 6.144 MHz clock of Apple silicon MacBooks; on other chips use -find, then --clock MHZ.\n")
        for f, what, tune in help_rows: print("  %-10s %-40s %s" % (f, what, tune))
        sys.exit(2)
    t0 = time.time()
    m = globals()["mode_" + mode](RATE, CACHE)
    wav = os.path.join(CACHE, "jacktx-%s.wav" % mode)
    os.makedirs(CACHE, exist_ok=True); write_wav(wav, m["samples"], level)
    print("rendered -%s: %.1f s loop in %.1f s -> %s" % (mode, len(m["samples"]) / RATE, time.time() - t0, wav))
    if not MAC and "--clock" not in args and mode != "find":
        print("note: the clock frequency is chip-specific. 6.144 MHz is the Apple silicon value and is only a guess here; "
              "run -find to locate the line, then use --clock MHZ.")
    print("TUNE (RF = %.3f MHz DAC clock + audio frequency; the mirror below the clock is inverted, ignore it):" % (CLOCK_HZ / 1e6))
    for line in m["tune"]: print("  " + line)
    if "--render-only" in args: return
    if MAC:
        exe = _helper(); device = None
        name, present, old, vol = device_info(exe)
        if not present:
            sys.exit("the headphone jack is not available: plug the cable in (the system output can stay on the speakers).")
        if vol < 0.99:
            print("note: the headphone jack's own volume is %d %%; set it to 100 %% for the strongest signal "
                  "(select External Headphones once in Sound settings, turn it up, then switch back to the speakers)." % round(vol * 100))
        now = set_rate(exe, RATE) if old != RATE else old
        if now != RATE:
            sys.exit("could not set %s to %d Hz (now %d)" % (name, RATE, now))
        print("output: the headphone jack directly, at %d Hz (was %d); the system output stays as it is. Ctrl+C to stop." % (now, old))
    else:
        plan, device = other_os_setup(args, wav); old = RATE; exe = None
        print("Ctrl+C to stop.")
    proc = [None]
    def stop(*_): raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        while True:
            if m["cycle"]:                                  # FT8 / WSPR: start on the UTC cycle + phase
                c = m["cycle"]; t = time.time()
                start = (math.floor((t - m["phase"]) / c) + 1) * c + m["phase"]
                if start - t > 2: print("waiting %.0f s for the next %d s slot" % (start - t, c))
                while time.time() < start - 0.02: time.sleep(min(0.2, max(0.0, start - time.time() - 0.02)))
                print(time.strftime("%H:%M:%S", time.gmtime()), "UTC  transmitting")
            if MAC: plan = playback_plan("darwin", wav, exe=exe)
            proc[0] = start_player(plan, wav, loop=not m["cycle"] and plan[0] == "winsound", device=device)
            proc[0].wait()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        if proc[0] and proc[0].poll() is None:
            proc[0].terminate()
            try: proc[0].wait(2)
            except Exception: proc[0].kill()
        if old != RATE:
            try: print("restored output rate to %d Hz" % set_rate(exe, old))
            except Exception as e: print("could not restore the output rate:", e)


if __name__ == "__main__":
    main()
