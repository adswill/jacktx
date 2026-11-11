// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// fmrx: broadcast FM receiver for one station already mixed to 0 Hz (complex float32, about 250 kHz).
//   fmrx IN.cf32 RATE OUT.wav [--deemph US]
// Prints: level and quality, the 19 kHz stereo pilot, and RDS (PI, PS name, radio text, PTY) with block statistics.
// The audio is stereo when the station has a pilot (mono otherwise), 15 kHz low-pass, de-emphasis (50 us default), 16-bit WAV.
import Accelerate
import Foundation

func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }
let A = CommandLine.arguments
guard A.count >= 4, let fs = Double(A[2]) else { die("usage: fmrx IN.cf32 RATE OUT.wav [--deemph US]") }
let deUs = A.firstIndex(of: "--deemph").flatMap { Double(A[$0 + 1]) } ?? 50
guard let d = FileManager.default.contents(atPath: A[1]) else { die("cannot read \(A[1])") }
let n = d.count / 8
var I = [Float](repeating: 0, count: n), Q = I
d.withUnsafeBytes { raw in let p = raw.bindMemory(to: Float.self); for k in 0..<n { I[k] = p[2 * k]; Q[k] = p[2 * k + 1] } }

func lowpass(_ taps: Int, _ fc: Double, _ rate: Double) -> [Float] {
    var h = [Float](repeating: 0, count: taps); let m = Double(taps - 1) / 2; var s: Float = 0
    for i in 0..<taps { let x = Double(i) - m; let sinc = x == 0 ? 2 * fc / rate : sin(2 * Double.pi * fc / rate * x) / (Double.pi * x)
        let w = 0.54 - 0.46 * cos(2 * Double.pi * Double(i) / Double(taps - 1)); h[i] = Float(sinc * w); s += h[i] }
    return h.map { $0 / s }
}
func decim(_ x: [Float], _ h: [Float], _ D: Int) -> [Float] {
    let outN = (x.count - h.count) / D; guard outN > 0 else { return [] }
    var y = [Float](repeating: 0, count: outN); vDSP_desamp(x, vDSP_Stride(D), h, &y, vDSP_Length(outN), vDSP_Length(h.count)); return y
}

// ---- FM demodulation: phase difference of consecutive samples ----
var mpx = [Float](repeating: 0, count: n)
var pw: Double = 0
for k in 1..<n { let re = I[k] * I[k - 1] + Q[k] * Q[k - 1], im = Q[k] * I[k - 1] - I[k] * Q[k - 1]; mpx[k] = atan2(im, re); pw += Double(I[k] * I[k] + Q[k] * Q[k]) }
print(String(format: "level %.1f dBFS, %d samples at %.0f Hz (%.1f s)", 10 * log10(pw / Double(n) + 1e-20), n, fs, Double(n) / fs))

// ---- tones in the multiplex: pilot (19 kHz) and noise near it ----
func tone(_ f: Double) -> Double { var re = 0.0, im = 0.0; let w = 2 * Double.pi * f / fs; let m = min(n, Int(fs * 2))
    for k in 0..<m { re += Double(mpx[k]) * cos(w * Double(k)); im += Double(mpx[k]) * sin(w * Double(k)) }; return (re * re + im * im) / Double(m) / Double(m) }
let pil = tone(19000), ref = (tone(17500) + tone(20500) + tone(16800) + tone(21200)) / 4
let pilDb = 10 * log10(pil / ref + 1e-20)
print(String(format: "pilot 19 kHz: %.1f dB over the neighbouring multiplex (%@)", pilDb, pilDb > 15 ? "stereo station" : "no pilot: mono or too weak"))

// ---- audio: mono (L+R) and, with a pilot, stereo (L-R on the 38 kHz subcarrier, locked to twice the pilot phase) ----
let D1 = max(1, Int((fs / 50000).rounded())); let ars = fs / Double(D1)
let hA = lowpass(129, 15000, fs)
var M = decim(mpx, hA, D1)
var S = [Float](); var stereo = false
if pilDb > 15 {
    // pilot phase: one-pole low-pass of the multiplex mixed with 19 kHz (about 30 Hz wide)
    let w19 = 2 * Double.pi * 19000 / fs; let al = 1 - exp(-2 * Double.pi * 30 / fs); var pr = 0.0, pq = 0.0
    var sI = [Float](repeating: 0, count: n), sQ = sI
    for k in 0..<n { let ph = w19 * Double(k); let x = Double(mpx[k]); pr += al * (x * cos(ph) - pr); pq += al * (-x * sin(ph) - pq)
        let th = atan2(pq, pr); let c = 2 * (ph + th); sI[k] = Float(-2 * x * sin(c)); sQ[k] = Float(2 * x * cos(c)) }
    let SI = decim(sI, hA, D1), SQ = decim(sQ, hA, D1)
    var pI: Float = 0, pQ: Float = 0; let skip = min(SI.count, Int(ars / 4))   // let the pilot filter settle
    if SI.count > skip + 100 { vDSP_svesq(Array(SI[skip...]), 1, &pI, vDSP_Length(SI.count - skip)); vDSP_svesq(Array(SQ[skip...]), 1, &pQ, vDSP_Length(SQ.count - skip)) }
    var pM: Float = 0; vDSP_svesq(M, 1, &pM, vDSP_Length(M.count))
    print(String(format: "stereo: difference signal %.1f dB below the sum, %.1f dB above its quadrature (a correct lock gives well above 0)", 10 * log10(pM / max(pI, 1e-20)), 10 * log10(pI / max(pQ, 1e-20))))
    S = SI; stereo = true
}
let a = Float(exp(-1 / (ars * deUs * 1e-6)))
func deemph(_ x: inout [Float]) { var st: Float = 0; for k in 0..<x.count { st = a * st + (1 - a) * x[k]; x[k] = st }
    var mean: Float = 0; vDSP_meanv(x, 1, &mean, vDSP_Length(x.count)); for k in 0..<x.count { x[k] -= mean } }
var Lc = M, Rc = M
if stereo { for k in 0..<min(M.count, S.count) { Lc[k] = (M[k] + S[k]) / 2; Rc[k] = (M[k] - S[k]) / 2 } }
deemph(&Lc); deemph(&Rc)
var pk: Float = 1e-9; for k in 0..<Lc.count { pk = max(pk, abs(Lc[k]), abs(Rc[k])) }
let chans = stereo ? 2 : 1
var wav = Data(); func le<T: FixedWidthInteger>(_ v: T) { withUnsafeBytes(of: v.littleEndian) { wav.append(contentsOf: $0) } }
wav.append("RIFF".data(using: .ascii)!); le(UInt32(36 + Lc.count * 2 * chans)); wav.append("WAVEfmt ".data(using: .ascii)!); le(UInt32(16)); le(UInt16(1)); le(UInt16(chans))
le(UInt32(ars)); le(UInt32(ars) * UInt32(2 * chans)); le(UInt16(2 * chans)); le(UInt16(16)); wav.append("data".data(using: .ascii)!); le(UInt32(Lc.count * 2 * chans))
for k in 0..<Lc.count { le(Int16(max(-32767, min(32767, Lc[k] / pk * 0.8 * 32767)))); if stereo { le(Int16(max(-32767, min(32767, Rc[k] / pk * 0.8 * 32767)))) } }
FileManager.default.createFile(atPath: A[3], contents: wav)
print(String(format: "audio: %.0f Hz %@ WAV, %.1f s -> %@", ars, stereo ? "stereo" : "mono", Double(Lc.count) / ars, A[3]))

// ---- RDS: 57 kHz subcarrier, 1187.5 bit/s biphase ----
var bi = [Float](repeating: 0, count: n), bq = bi
let w57 = 2 * Double.pi * 57000 / fs
for k in 0..<n { let p = w57 * Double(k); bi[k] = mpx[k] * Float(cos(p)); bq[k] = -mpx[k] * Float(sin(p)) }
let D2 = max(1, Int((fs / 19000).rounded())); let rs = fs / Double(D2)
let h2 = lowpass(257, 2400, fs); let zi = decim(bi, h2, D2), zq = decim(bq, h2, D2); let m = zi.count
// carrier phase from the squared signal (BPSK), smoothed over about 0.2 s, then keep the in-phase part
var x = [Float](repeating: 0, count: m); var sr = 0.0, si = 0.0; let al = 1 / (rs * 0.2)
var prevPh = 0.0
for k in 0..<m { let re = Double(zi[k]), im = Double(zq[k]); sr += al * ((re * re - im * im) - sr); si += al * ((2 * re * im) - si)
    var ph = 0.5 * atan2(si, sr)
    while ph - prevPh > Double.pi / 2 { ph -= Double.pi }; while ph - prevPh < -Double.pi / 2 { ph += Double.pi }; prevPh = ph
    x[k] = Float(re * cos(ph) + im * sin(ph)) }
// The capture is cut into chunks of about 2 s. Each chunk gets its own symbol-timing phase and block alignment, so a
// gap in the recording (dropped samples) or a fade costs one chunk only.
func crc10(_ v: UInt32) -> UInt32 { var r: UInt32 = 0; for i in stride(from: 15, through: 0, by: -1) { let b = (v >> UInt32(i)) & 1; let top = (r >> 9) & 1; r = (r << 1) & 0x3FF; if (top ^ b) == 1 { r ^= 0x1B9 } }; return r }
let offA: UInt32 = 0x0FC, offB: UInt32 = 0x198, offC: UInt32 = 0x168, offC2: UInt32 = 0x350, offD: UInt32 = 0x1B4
var fix: [UInt32: UInt32] = [:]   // syndromes of error bursts of 1 or 2 bits
for pat in [UInt32(1), 3] { for sh in 0..<26 { let e = (pat << UInt32(sh)) & 0x3FFFFFF; let syn = crc10(e >> 10) ^ (e & 0x3FF); if fix[syn] == nil { fix[syn] = e } } }
let sps = rs / 1187.5
var cum = [Double](repeating: 0, count: m + 1); for k in 0..<m { cum[k + 1] = cum[k] + Double(x[k]) }
func seg(_ a: Double, _ b: Double) -> Double { let ia = max(0, min(m, Int(a.rounded()))), ib = max(0, min(m, Int(b.rounded()))); return cum[ib] - cum[ia] }
var pi: [UInt16: Int] = [:]; var psVotes = [[UInt16: Int]](repeating: [:], count: 4); var rtVotes = [[UInt32: Int]](repeating: [:], count: 16); var ptyVotes: [Int: Int] = [:]
var groups = 0, good = 0, corrected = 0, totalBlocks = 0
let chunkSym = 2376   // 2 s
var c0s = 0.0
while c0s + Double(chunkSym) * sps < Double(m) {
    var best = -1.0, bestPh = 0.0
    for s in 0..<32 { let off = c0s + Double(s) / 32 * sps; var acc = 0.0
        for k in 0..<chunkSym - 1 { let t = off + Double(k) * sps; acc += abs(seg(t, t + sps / 2) - seg(t + sps / 2, t + sps)) }
        if acc > best { best = acc; bestPh = off } }
    var bits = [UInt8](repeating: 0, count: chunkSym - 1); var prev = false
    for k in 0..<chunkSym - 1 { let t = bestPh + Double(k) * sps; let v = seg(t, t + sps / 2) - seg(t + sps / 2, t + sps) > 0; bits[k] = (k > 0 && v != prev) ? 1 : 0; prev = v }
    func word(_ p: Int) -> UInt32 { var w: UInt32 = 0; for i in 0..<26 { w = (w << 1) | UInt32(bits[p + i]) }; return w }
    func kind(_ w: UInt32) -> Int { let s = crc10(w >> 10) ^ (w & 0x3FF); return s == offA ? 0 : s == offB ? 1 : (s == offC || s == offC2) ? 2 : s == offD ? 3 : -1 }
    // alignment: bit phase 0..25 and group phase 0..3 with the most exact blocks
    var votes = [Int](repeating: 0, count: 104)
    for p in 0..<26 { var i = 0; while p + 26 * (i + 1) <= bits.count { let t = kind(word(p + 26 * i)); if t >= 0 { votes[p * 4 + ((i - t) % 4 + 4) % 4] += 1 }; i += 1 } }
    let bv = votes.max()!; let bi2 = votes.firstIndex(of: bv)!; let bp = bi2 / 4, ap = bi2 % 4
    let nb = (bits.count - bp) / 26; totalBlocks += nb
    if bv >= 6 {
        func block(_ i: Int, _ want: [UInt32]) -> UInt16? { guard i >= 0, i < nb else { return nil }; let w = word(bp + 26 * i)
            for o in want where crc10(w >> 10) ^ (w & 0x3FF) ^ o == 0 { return UInt16(w >> 10) }
            for o in want { if let e = fix[crc10(w >> 10) ^ (w & 0x3FF) ^ o] { corrected += 1; return UInt16((w ^ e) >> 10) } }
            return nil }
        var gi = ap - 4
        while gi < nb { let a0 = block(gi, [offA]), b0 = block(gi + 1, [offB]), cc = block(gi + 2, [offC, offC2]), d0 = block(gi + 3, [offD])
            good += [a0, b0, cc, d0].filter { $0 != nil }.count
            if let a0 = a0 { pi[a0, default: 0] += 1 }
            if let b0 = b0 { groups += 1; let gt = Int(b0 >> 12), ver = Int((b0 >> 11) & 1); ptyVotes[Int((b0 >> 5) & 31), default: 0] += 1
                if gt == 0, let d0 = d0 { psVotes[Int(b0 & 3)][d0, default: 0] += 1 }
                if gt == 2, ver == 0, let cc = cc, let d0 = d0 { rtVotes[Int(b0 & 15)][UInt32(cc) << 16 | UInt32(d0), default: 0] += 1 } }
            gi += 4 }
    }
    c0s += Double(chunkSym) * sps
}
var ps = [UInt8](repeating: 32, count: 8), psSeen = 0; var rt = [UInt8](repeating: 32, count: 64); var rtSeen = Set<Int>()
for ad in 0..<4 { if let t = psVotes[ad].max(by: { $0.value < $1.value }) { ps[2 * ad] = UInt8(t.key >> 8); ps[2 * ad + 1] = UInt8(t.key & 255); psSeen |= 1 << ad } }
for ad in 0..<16 { if let t = rtVotes[ad].max(by: { $0.value < $1.value }) { let v = t.key; rt[4 * ad] = UInt8(v >> 24); rt[4 * ad + 1] = UInt8((v >> 16) & 255); rt[4 * ad + 2] = UInt8((v >> 8) & 255); rt[4 * ad + 3] = UInt8(v & 255); rtSeen.insert(ad) } }
let pty = ptyVotes.max(by: { $0.value < $1.value })?.key ?? -1
let bestC = good; totalBlocks = max(1, totalBlocks)
func txt(_ b: [UInt8]) -> String { String(b.map { $0 >= 32 && $0 < 127 ? Character(UnicodeScalar($0)) : (($0 == 13 || $0 == 0) ? " " : "?") }).trimmingCharacters(in: .whitespaces) }
print(String(format: "RDS: %d of %d blocks valid (%.0f %%), %d repaired, %d groups", bestC, totalBlocks, 100 * Double(bestC) / Double(totalBlocks), corrected, groups))
if let top = pi.max(by: { $0.value < $1.value }), groups >= 3 {
    print(String(format: "RDS PI %04X  PTY %d  PS \"%@\"%@", top.key, pty, txt(ps), psSeen == 15 ? "" : " (incomplete)"))
    if !rtSeen.isEmpty { print("RDS radio text: \"\(txt(rt))\"") }
} else { print("RDS: no lock") }
