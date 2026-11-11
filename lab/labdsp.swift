// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// labdsp: fast spectrum and down-conversion of SDR captures for the jacktx wideband lab (Accelerate/vDSP).
//   labdsp psd  --rate R [--nfft N] [--seg SEC] [--skip SEC] [--dur SEC] [--fmt cs8|cu8|cf32] [--in FILE|-] --out FILE.f32
//        Welch PSD (Hann, no overlap) per segment of SEC seconds; writes rows of N float32 dB values, fft-shifted
//        (row index 0 = -R/2). Prints one line per segment: index, median dB, max dB.
//   labdsp ddc  --rate R --shift HZ --decim D [--fmt ...] [--in FILE|-] [--skip SEC] [--dur SEC] --out FILE.cf32
//        Mixes by -shift, low-passes (windowed sinc, 0.4 x output rate) and decimates by D; writes complex float32.
//   labdsp synth --rate R --center HZ --line HZ --seconds S --out FILE.cs8 [--wav FILE] [--m 0.3] [--noise 0.01]
//        [--skirt DB] [--seed N]  synthetic capture: clock line AM-modulated by the WAV (both images), optional shaped
//        noise skirt around the line, white noise. For --dry-run of the lab chain.
import Accelerate
import Foundation

let A = CommandLine.arguments
func opt(_ k: String) -> String? { if let i = A.firstIndex(of: k), i + 1 < A.count { return A[i + 1] }; return nil }
func optD(_ k: String, _ d: Double) -> Double { opt(k).flatMap(Double.init) ?? d }
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }

// ---------------- input: interleaved IQ from a file or stdin, converted to float ----------------
final class IQReader {
    let fh: FileHandle; let fmt: String; var buf = Data()
    init(_ path: String, _ fmt: String) {
        self.fmt = fmt
        if path == "-" { fh = FileHandle.standardInput } else { guard let f = FileHandle(forReadingAtPath: path) else { die("cannot open \(path)") }; fh = f }
    }
    var bytesPerSample: Int { fmt == "cf32" ? 8 : 2 }
    /// Reads up to n complex samples into re/im; returns the count (0 at end).
    func read(_ n: Int, _ re: inout [Float], _ im: inout [Float]) -> Int {
        let want = n * bytesPerSample
        while buf.count < want { let d = fh.readData(ofLength: max(1 << 20, want - buf.count)); if d.isEmpty { break }; buf.append(d) }
        let have = min(want, buf.count) / bytesPerSample; if have == 0 { return 0 }
        buf.withUnsafeBytes { (p: UnsafeRawBufferPointer) in
            if fmt == "cf32" {
                let f = p.bindMemory(to: Float.self)
                for i in 0..<have { re[i] = f[2 * i]; im[i] = f[2 * i + 1] }
            } else if fmt == "cu8" {
                let b = p.bindMemory(to: UInt8.self)
                for i in 0..<have { re[i] = (Float(b[2 * i]) - 127.5) / 128; im[i] = (Float(b[2 * i + 1]) - 127.5) / 128 }
            } else {
                let b = p.bindMemory(to: Int8.self)
                for i in 0..<have { re[i] = Float(b[2 * i]) / 128; im[i] = Float(b[2 * i + 1]) / 128 }
            }
        }
        buf.removeFirst(have * bytesPerSample)
        return have
    }
    func skip(_ n: Int) { var r = [Float](repeating: 0, count: 1 << 16), i = r; var left = n; while left > 0 { let k = read(min(left, 1 << 16), &r, &i); if k == 0 { break }; left -= k } }
}

// ---------------- complex FFT (vDSP DFT) ----------------
final class FFT {
    let n: Int; let setup: vDSP_DFT_Setup
    init(_ n: Int) { self.n = n; setup = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(n), .FORWARD)! }
    func run(_ ri: [Float], _ ii: [Float], _ ro: inout [Float], _ io: inout [Float]) { vDSP_DFT_Execute(setup, ri, ii, &ro, &io) }
}

func hann(_ n: Int) -> [Float] { var w = [Float](repeating: 0, count: n); vDSP_hann_window(&w, vDSP_Length(n), Int32(vDSP_HANN_NORM)); return w }

func cmdPSD() {
    let rate = optD("--rate", 20e6), nfft = Int(optD("--nfft", 65536)), seg = optD("--seg", 0), dur = optD("--dur", 0)
    let rd = IQReader(opt("--in") ?? "-", opt("--fmt") ?? "cs8"); guard let out = opt("--out") else { die("--out FILE") }
    if let s = opt("--skip").flatMap(Double.init) { rd.skip(Int(s * rate)) }
    let fft = FFT(nfft), w = hann(nfft)
    var wsum: Float = 0; vDSP_svesq(w, 1, &wsum, vDSP_Length(nfft))
    var re = [Float](repeating: 0, count: nfft), im = re, ro = re, io = re, acc = [Float](repeating: 0, count: nfft), mag = re
    let perSeg = seg > 0 ? max(1, Int(seg * rate) / nfft) : Int.max
    let total = dur > 0 ? Int(dur * rate) / nfft : Int.max
    FileManager.default.createFile(atPath: out, contents: nil); let oh = FileHandle(forWritingAtPath: out)!
    var frames = 0, inSeg = 0, segIdx = 0
    func flush() {
        guard inSeg > 0 else { return }
        var row = [Float](repeating: 0, count: nfft); let h = nfft / 2
        let norm = 1 / (Float(inSeg) * wsum)
        for k in 0..<nfft { row[(k + h) % nfft] = 10 * log10(max(acc[k] * norm, 1e-20)) }
        oh.write(row.withUnsafeBufferPointer { Data(buffer: $0) })
        var s = row.sorted(); let med = s[nfft / 2]; s.removeAll()
        print(String(format: "seg %d frames %d median %.2f dB max %.2f dB", segIdx, inSeg, med, row.max()!))
        segIdx += 1; inSeg = 0; for k in 0..<nfft { acc[k] = 0 }
    }
    while frames < total {
        let k = rd.read(nfft, &re, &im); if k < nfft { break }
        vDSP_vmul(re, 1, w, 1, &re, 1, vDSP_Length(nfft)); vDSP_vmul(im, 1, w, 1, &im, 1, vDSP_Length(nfft))
        fft.run(re, im, &ro, &io)
        ro.withUnsafeMutableBufferPointer { rp in io.withUnsafeMutableBufferPointer { ip in
            var z = DSPSplitComplex(realp: rp.baseAddress!, imagp: ip.baseAddress!); vDSP_zvmags(&z, 1, &mag, 1, vDSP_Length(nfft)) } }
        vDSP_vadd(acc, 1, mag, 1, &acc, 1, vDSP_Length(nfft))
        frames += 1; inSeg += 1
        if inSeg >= perSeg { flush() }
    }
    flush(); oh.closeFile()
    if segIdx == 0 { die("no complete FFT frame in the input") }
}

func cmdDDC() {
    let rate = optD("--rate", 20e6), shift = optD("--shift", 0), D = Int(optD("--decim", 20)), dur = optD("--dur", 0)
    let rd = IQReader(opt("--in") ?? "-", opt("--fmt") ?? "cs8"); guard let out = opt("--out") else { die("--out FILE") }
    if let s = opt("--skip").flatMap(Double.init) { rd.skip(Int(s * rate)) }
    let half = 8 * D, L = 2 * half + 1, fc = 0.4 / Double(D)              // cutoff 0.4 x output rate (cycles/sample)
    var taps = [Float](repeating: 0, count: L)
    for i in 0..<L { let t = Double(i - half); let s = t == 0 ? 2 * fc : sin(2 * .pi * fc * t) / (.pi * t)
        taps[i] = Float(s * (0.42 - 0.5 * cos(2 * .pi * Double(i) / Double(L - 1)) + 0.08 * cos(4 * .pi * Double(i) / Double(L - 1)))) }
    let tsum = taps.reduce(0, +); for i in 0..<L { taps[i] /= tsum }
    let blk = D * 4096; var re = [Float](repeating: 0, count: blk), im = re
    var hr = [Float](repeating: 0, count: L - 1), hi = hr                // filter history
    var ph = 0.0; let dph = -2 * .pi * shift / rate
    FileManager.default.createFile(atPath: out, contents: nil); let oh = FileHandle(forWritingAtPath: out)!
    var done = 0; let lim = dur > 0 ? Int(dur * rate) : Int.max
    while done < lim {
        let k = rd.read(min(blk, lim - done), &re, &im); if k == 0 { break }; done += k
        var xr = hr + [Float](repeating: 0, count: k), xi = hi + [Float](repeating: 0, count: k)
        for i in 0..<k { let c = Float(cos(ph)), s = Float(sin(ph)); xr[L - 1 + i] = re[i] * c - im[i] * s; xi[L - 1 + i] = re[i] * s + im[i] * c
            ph += dph; if ph > .pi { ph -= 2 * .pi } else if ph < -.pi { ph += 2 * .pi } }
        let nout = k / D; var o = [Float](repeating: 0, count: 2 * nout)
        for j in 0..<nout { var a: Float = 0, b: Float = 0
            xr.withUnsafeBufferPointer { p in vDSP_dotpr(p.baseAddress! + j * D, 1, taps, 1, &a, vDSP_Length(L)) }
            xi.withUnsafeBufferPointer { p in vDSP_dotpr(p.baseAddress! + j * D, 1, taps, 1, &b, vDSP_Length(L)) }
            o[2 * j] = a; o[2 * j + 1] = b }
        oh.write(o.withUnsafeBufferPointer { Data(buffer: $0) })
        let used = nout * D; hr = Array(xr[used..<(used + L - 1)]); hi = Array(xi[used..<(used + L - 1)])
        if k % D != 0 { break }
    }
    oh.closeFile()
}

// ---------------- synthetic capture for --dry-run ----------------
func readWavMono(_ path: String) -> (rate: Double, x: [Float]) {
    let url = URL(fileURLWithPath: path)
    guard let d = try? Data(contentsOf: url), d.count > 44 else { die("cannot read \(path)") }
    func u16(_ o: Int) -> Int { Int(d[o]) | Int(d[o + 1]) << 8 }
    func u32(_ o: Int) -> Int { u16(o) | u16(o + 2) << 16 }
    var o = 12, fmtTag = 1, ch = 2, rate = 96000, bits = 16, dataOff = 0, dataLen = 0
    while o + 8 <= d.count {
        let id = String(bytes: d[o..<(o + 4)], encoding: .ascii) ?? "", sz = u32(o + 4)
        if id == "fmt " { fmtTag = u16(o + 8); ch = u16(o + 10); rate = u32(o + 12); bits = u16(o + 22) }
        if id == "data" { dataOff = o + 8; dataLen = min(sz, d.count - o - 8); break }
        o += 8 + sz + (sz & 1)
    }
    let bps = bits / 8, n = dataLen / (bps * ch); var x = [Float](repeating: 0, count: n)
    d.withUnsafeBytes { (p: UnsafeRawBufferPointer) in
        for i in 0..<n { let b = dataOff + i * bps * ch
            if fmtTag == 3 && bits == 32 { x[i] = p.load(fromByteOffset: b, as: Float.self) }
            else if bits == 16 { x[i] = Float(Int16(bitPattern: UInt16(p[b]) | UInt16(p[b + 1]) << 8)) / 32768 }
            else if bits == 24 { let v = Int32(p[b]) << 8 | Int32(p[b + 1]) << 16 | Int32(p[b + 2]) << 24; x[i] = Float(v) / 2147483648 }
            else if bits == 32 { x[i] = Float(p.load(fromByteOffset: b, as: Int32.self)) / 2147483648 } } }
    return (Double(rate), x)
}

func cmdSynth() {
    let rate = optD("--rate", 2e6), center = optD("--center", 6.144e6), line = optD("--line", 6.144e6), secs = optD("--seconds", 1)
    let m = Float(optD("--m", 0.3)), noise = Float(optD("--noise", 0.01)), skirt = optD("--skirt", -999)
    guard let out = opt("--out") else { die("--out FILE") }
    var g = UInt64(optD("--seed", 1)); func rnd() -> Float { g = g &* 6364136223846793005 &+ 1442695040888963407; return Float(Int64(bitPattern: g >> 11) & 0xFFFFF) / Float(0x100000) - 0.5 }
    func gauss() -> Float { (rnd() + rnd() + rnd() + rnd()) * 1.7 }
    var audio: [Float] = [], arate = 96000.0
    if let w = opt("--wav") { (arate, audio) = readWavMono(w) }
    let n = Int(rate * secs); var o = [Int8](repeating: 0, count: 2 * n)
    // shaped skirt: white noise through a 3rd-order high-pass (difference) so it rises away from the line, scaled to --skirt dB
    var d1: Float = 0, d2: Float = 0, d3: Float = 0; let sk = skirt > -900 ? Float(pow(10, skirt / 20)) : 0
    let w = 2 * Double.pi * (line - center) / rate
    for k in 0..<n {
        var a: Float = 0
        if !audio.isEmpty { let t = Double(k) * arate / rate; let i = Int(t) % audio.count; let fr = Float(t - floor(t)); a = audio[i] * (1 - fr) + audio[(i + 1) % audio.count] * fr }
        let wn = gauss(); let h1 = wn - d1; d1 = wn; let h2 = h1 - d2; d2 = h1; let h3 = h2 - d3; d3 = h2
        let env = 0.4 * (1 + m * a) + sk * h3
        let ph = w * Double(k); let re = env * Float(cos(ph)) + noise * gauss(), im = env * Float(sin(ph)) + noise * gauss()
        o[2 * k] = Int8(max(-127, min(127, (re * 127).rounded()))); o[2 * k + 1] = Int8(max(-127, min(127, (im * 127).rounded())))
    }
    try! o.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: URL(fileURLWithPath: out))
}

switch A.count > 1 ? A[1] : "" {
case "psd": cmdPSD()
case "ddc": cmdDDC()
case "synth": cmdSynth()
default: die("usage: labdsp psd|ddc|synth ... (see the header of labdsp.swift)")
}
