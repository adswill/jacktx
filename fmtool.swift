// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// Fast DSP helper for jacktx.py (the Python side has a slow pure-Python fallback).
//   fmtool front IN FMT RATE SHIFT_HZ OUTRATE CUTOFF_HZ OUT.cf32 [MAXSAMPLES]   mix SHIFT to 0, low-pass, decimate by round(RATE/OUTRATE)
//   fmtool psd IN FMT RATE NFFT NAVG OUT.f32 [SKIP_SAMPLES]                      averaged power spectrum (fftshifted, NFFT floats)
//   fmtool synth OUT FMT RATE SECONDS SIGMA SEED IN.cf32:RATE:OFFSET_HZ:GAIN ... render stations + complex noise to an IQ file
// FMT: cu8 cs8 cs16 cf32. Both front and psd print "clip FRACTION" (8-bit samples at the rails) on stdout.
import Foundation

func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }
let A = CommandLine.arguments
func bps(_ f: String) -> Int { switch f { case "cu8", "cs8": return 2; case "cs16": return 4; case "cf32": return 8; default: die("bad format \(f)") } }

func decode(_ d: Data, _ n: Int, _ fmt: String, _ I: inout [Float], _ Q: inout [Float]) -> Int {
    var clip = 0
    d.withUnsafeBytes { raw in
        switch fmt {
        case "cu8":
            let p = raw.bindMemory(to: UInt8.self)
            for k in 0..<n { let a = p[2*k], b = p[2*k+1]; I[k] = (Float(a) - 127.5) / 127.5; Q[k] = (Float(b) - 127.5) / 127.5; if a == 0 || a == 255 || b == 0 || b == 255 { clip += 1 } }
        case "cs8":
            let p = raw.bindMemory(to: Int8.self)
            for k in 0..<n { let a = p[2*k], b = p[2*k+1]; I[k] = Float(a) / 128; Q[k] = Float(b) / 128; if a == 127 || a == -128 || b == 127 || b == -128 { clip += 1 } }
        case "cs16":
            let p = raw.bindMemory(to: Int16.self)
            for k in 0..<n { I[k] = Float(p[2*k]) / 32768; Q[k] = Float(p[2*k+1]) / 32768 }
        default:
            let p = raw.bindMemory(to: Float.self)
            for k in 0..<n { I[k] = p[2*k]; Q[k] = p[2*k+1] }
        }
    }
    return clip
}

func sincTaps(_ n: Int, _ fc: Double) -> [Float] {   // fc = cutoff / rate, Blackman window, unity DC gain
    var t = [Double](repeating: 0, count: n); let m = Double(n - 1) / 2; var s = 0.0
    for i in 0..<n {
        let x = Double(i) - m; let sc = x == 0 ? 2 * fc : sin(2 * Double.pi * fc * x) / (Double.pi * x)
        let w = 0.42 - 0.5 * cos(2 * Double.pi * Double(i) / Double(n - 1)) + 0.08 * cos(4 * Double.pi * Double(i) / Double(n - 1))
        t[i] = sc * w; s += sc * w
    }
    return t.map { Float($0 / s) }
}

func fft(_ re: inout [Float], _ im: inout [Float]) {
    let n = re.count; var j = 0
    for i in 1..<n { var bit = n >> 1; while j & bit != 0 { j ^= bit; bit >>= 1 }; j ^= bit; if i < j { re.swapAt(i, j); im.swapAt(i, j) } }
    var len = 2
    while len <= n {
        let ang = -2 * Double.pi / Double(len); let wr = Float(cos(ang)), wi = Float(sin(ang))
        var i = 0
        while i < n {
            var cr: Float = 1, ci: Float = 0
            for k in 0..<(len / 2) {
                let a = i + k, b = i + k + len / 2
                let tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr
                re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti
                let nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr
            }
            i += len
        }
        len <<= 1
    }
}

struct RNG { var s: UInt64
    mutating func next() -> Double { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return Double(s >> 11) / Double(1 << 53) }
    mutating func gauss() -> Double { let u = max(next(), 1e-300), v = next(); return sqrt(-2 * log(u)) * cos(2 * Double.pi * v) } }

if A.count < 2 { die("usage: fmtool front|psd|synth ...") }
switch A[1] {
case "front":
    guard A.count >= 9 else { die("front IN FMT RATE SHIFT OUTRATE CUTOFF OUT [MAX]") }
    let fmt = A[3], rate = Double(A[4])!, shift = Double(A[5])!, outr = Double(A[6])!, cut = Double(A[7])!
    let D = max(1, Int((rate / outr).rounded())); let maxn = A.count > 9 ? Int(A[9])! : Int.max
    let trans = max(cut * 0.5, 15e3)
    var N = Int(3.8 * rate / trans) | 1; N = max(N, 4 * D + 1)
    let taps = sincTaps(N, (cut + trans / 2) / rate)
    guard let fh = FileHandle(forReadingAtPath: A[2]) else { die("cannot open \(A[2])") }
    FileManager.default.createFile(atPath: A[8], contents: nil); let oh = FileHandle(forWritingAtPath: A[8])!
    let B = 1 << 18; let b = bps(fmt)
    var I = [Float](repeating: 0, count: B), Q = I
    var bufI = [Float](), bufQ = [Float](); var pos = 0
    var phase = 0.0; let w = -2 * Double.pi * shift / rate; var total = 0, clipTot = 0
    var outBuf = [Float]()
    while total < maxn {
        guard let d = try? fh.read(upToCount: min(B, maxn - total) * b), d.count >= b else { break }
        let n = d.count / b
        clipTot += decode(d, n, fmt, &I, &Q)
        var c = 1.0, s = 0.0; let dc = cos(w), ds = sin(w)
        for k in 0..<n {
            if k & 1023 == 0 { let ph = phase + w * Double(k); c = cos(ph); s = sin(ph) }
            bufI.append(I[k] * Float(c) - Q[k] * Float(s)); bufQ.append(I[k] * Float(s) + Q[k] * Float(c))
            let c2 = c * dc - s * ds; s = s * dc + c * ds; c = c2
        }
        phase = (phase + w * Double(n)).truncatingRemainder(dividingBy: 2 * Double.pi)
        total += n
        outBuf.removeAll(keepingCapacity: true)
        let L = bufI.count
        bufI.withUnsafeBufferPointer { pI in bufQ.withUnsafeBufferPointer { pQ in taps.withUnsafeBufferPointer { pt in
            while pos + N <= L {
                var si: Float = 0, sq: Float = 0
                let bi = pI.baseAddress! + pos, bq = pQ.baseAddress! + pos
                for k in 0..<N { let t = pt[k]; si += t * bi[k]; sq += t * bq[k] }
                outBuf.append(si); outBuf.append(sq); pos += D
            }
        }}}
        bufI.removeFirst(pos); bufQ.removeFirst(pos); pos = 0
        outBuf.withUnsafeBytes { oh.write(Data($0)) }
    }
    print("clip \(Double(clipTot) / Double(max(total, 1)))")
case "psd":
    guard A.count >= 8 else { die("psd IN FMT RATE NFFT NAVG OUT [SKIP]") }
    let fmt = A[3], nfft = Int(A[5])!, navg = Int(A[6])!; let b = bps(fmt)
    guard let fh = FileHandle(forReadingAtPath: A[2]) else { die("cannot open \(A[2])") }
    let skip = A.count > 8 ? Int(A[8])! : 0
    let size = Int((try? FileManager.default.attributesOfItem(atPath: A[2])[.size] as? NSNumber)??.intValue ?? 0) / b - skip
    let blocks = max(1, min(navg, size / nfft)); let stride = blocks > 1 ? (size - nfft) / (blocks - 1) : 0
    var win = [Float](repeating: 0, count: nfft); var sw: Float = 0
    for i in 0..<nfft { win[i] = Float(0.5 - 0.5 * cos(2 * Double.pi * Double(i) / Double(nfft))); sw += win[i] * win[i] }
    var acc = [Double](repeating: 0, count: nfft); var I = [Float](repeating: 0, count: nfft), Q = I; var clip = 0
    for k in 0..<blocks {
        try? fh.seek(toOffset: UInt64((skip + k * stride) * b))
        guard let d = try? fh.read(upToCount: nfft * b), d.count >= nfft * b else { break }
        clip += decode(d, nfft, fmt, &I, &Q)
        var re = zip(I, win).map { $0 * $1 }, im = zip(Q, win).map { $0 * $1 }
        fft(&re, &im)
        for i in 0..<nfft { acc[i] += Double((re[i] * re[i] + im[i] * im[i]) / sw) }
    }
    var out = [Float](repeating: 0, count: nfft)
    for i in 0..<nfft { out[(i + nfft / 2) % nfft] = Float(acc[i] / Double(blocks)) }
    out.withUnsafeBytes { try? Data($0).write(to: URL(fileURLWithPath: A[7])) }
    print("clip \(Double(clip) / Double(blocks * nfft))")
case "synth":
    guard A.count >= 8 else { die("synth OUT FMT RATE SECONDS SIGMA SEED STATIONS...") }
    let fmt = A[3], R = Double(A[4])!, secs = Double(A[5])!, sigma = Double(A[6])!; var rng = RNG(s: UInt64(A[7])! &* 2654435761 &+ 88172645463325252)
    struct St { var x: [Float]; var r: Double; var f: Double; var g: Float }
    var st = [St]()
    for a in A[8...] {
        let p = a.split(separator: ":").map(String.init); guard p.count == 4, let d = FileManager.default.contents(atPath: p[0]) else { die("bad station \(a)") }
        var x = [Float](repeating: 0, count: d.count / 4); _ = x.withUnsafeMutableBytes { d.copyBytes(to: $0) }
        st.append(St(x: x, r: Double(p[1])!, f: Double(p[2])!, g: Float(p[3])!))
    }
    // 32-tap windowed-sinc interpolator, 256 sub-phases; cutoff 0.5 of each station's own rate
    let T = 32, PH = 256; var K = [[Float]](repeating: [Float](repeating: 0, count: T), count: PH)
    for p in 0..<PH { let fr = Double(p) / Double(PH); var s = 0.0
        for k in 0..<T { let x = Double(k - T / 2 + 1) - fr; let sc = x == 0 ? 1.0 : sin(Double.pi * x) / (Double.pi * x)
            let wv = 0.42 - 0.5 * cos(2 * Double.pi * (Double(k) + 0.5 - fr) / Double(T)) + 0.08 * cos(4 * Double.pi * (Double(k) + 0.5 - fr) / Double(T))
            K[p][k] = Float(sc * wv); s += sc * wv }
        K[p] = K[p].map { $0 / Float(s) } }
    let n = Int(R * secs); FileManager.default.createFile(atPath: A[2], contents: nil); let oh = FileHandle(forWritingAtPath: A[2])!
    let BS = 1 << 16; let bb = bps(fmt); var idx = 0; let sg = Float(sigma / 2).squareRoot()   // sigma = total complex noise variance
    var clipped = 0
    while idx < n {
        let m = min(BS, n - idx); var re = [Float](repeating: 0, count: m), im = re
        for s in st {
            let nin = s.x.count / 2
            for k in 0..<m {
                let t = Double(idx + k) / R; let u = t * s.r; let i0 = Int(u); let ph = Int((u - Double(i0)) * Double(PH))
                var a: Float = 0, bq: Float = 0
                if i0 - T / 2 + 1 >= 0 && i0 + T / 2 < nin {
                    K[ph].withUnsafeBufferPointer { kk in
                        for q in 0..<T { let j = i0 - T / 2 + 1 + q; a += kk[q] * s.x[2*j]; bq += kk[q] * s.x[2*j+1] } }
                }
                let th = 2 * Double.pi * (s.f * t).truncatingRemainder(dividingBy: 1.0); let c = Float(cos(th)), sn = Float(sin(th))
                re[k] += s.g * (a * c - bq * sn); im[k] += s.g * (a * sn + bq * c)
            }
        }
        var raw = Data(count: m * bb)
        raw.withUnsafeMutableBytes { rp in
            for k in 0..<m {
                let x = re[k] + sg * Float(rng.gauss()), y = im[k] + sg * Float(rng.gauss())
                switch fmt {
                case "cu8": let p = rp.bindMemory(to: UInt8.self); p[2*k] = UInt8(max(0, min(255, (127.5 + 127.5 * x).rounded()))); p[2*k+1] = UInt8(max(0, min(255, (127.5 + 127.5 * y).rounded())))
                    if abs(x) > 1 || abs(y) > 1 { clipped += 1 }
                case "cs8": let p = rp.bindMemory(to: Int8.self); p[2*k] = Int8(max(-128, min(127, (128 * x).rounded()))); p[2*k+1] = Int8(max(-128, min(127, (128 * y).rounded())))
                    if abs(x) > 0.99 || abs(y) > 0.99 { clipped += 1 }
                case "cs16": let p = rp.bindMemory(to: Int16.self); p[2*k] = Int16(max(-32768, min(32767, (32768 * x).rounded()))); p[2*k+1] = Int16(max(-32768, min(32767, (32768 * y).rounded())))
                default: let p = rp.bindMemory(to: Float.self); p[2*k] = x; p[2*k+1] = y }
            }
        }
        oh.write(raw); idx += m
    }
    print("clipped \(clipped)")
default: die("unknown command \(A[1])")
}
