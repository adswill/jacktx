// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// auxfm: FM audio from what an audio input records when a broadcast station folds into the audio band.
//   auxfm IN.f32 RATE OFFSET_HZ OUT.wav [--deemph US]
// IN is real float32 at RATE (an audio recording). The station's carrier sits OFFSET_HZ from 0 after folding
// (signed: its distance from the sampler harmonic). A real recording cannot tell +f from -f, so the instantaneous
// frequency is measured as |f| and the sign is followed through the zero crossings of f. Parts of the signal that swing
// beyond RATE/2 are lost in the input's own filter: there the last good value is held.
import Accelerate
import Foundation
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }
let A = CommandLine.arguments
guard A.count >= 5, let fs = Double(A[2]), let off = Double(A[3]) else { die("usage: auxfm IN.f32 RATE OFFSET_HZ OUT.wav") }
let deUs = A.firstIndex(of: "--deemph").flatMap { Double(A[$0 + 1]) } ?? 50
guard let d = FileManager.default.contents(atPath: A[1]) else { die("cannot read \(A[1])") }
let n = d.count / 4; var x = [Float](repeating: 0, count: n); d.withUnsafeBytes { let p = $0.bindMemory(to: Float.self); for k in 0..<n { x[k] = p[k] } }
// optional low-pass first (--lp HZ), to remove a strong tone above the band of interest
if let lpHz = A.firstIndex(of: "--lp").flatMap({ Double(A[$0 + 1]) }) {
    let tl = 257; var hl = [Float](repeating: 0, count: tl); let ml = Double(tl - 1) / 2; var sm: Float = 0
    for i in 0..<tl { let t = Double(i) - ml; let sc = t == 0 ? 2 * lpHz / fs : sin(2 * Double.pi * lpHz / fs * t) / (Double.pi * t); hl[i] = Float(sc * (0.54 - 0.46 * cos(2 * Double.pi * Double(i) / Double(tl - 1)))); sm += hl[i] }
    hl = hl.map { $0 / sm }; var y = [Float](repeating: 0, count: n - tl); vDSP_conv(x, 1, Array(hl.reversed()), 1, &y, 1, vDSP_Length(n - tl), vDSP_Length(tl)); x = y }
// optional cleaning (--clean): removes mains hum (below 3 kHz) and the Mac's own USB tones near 8 and 16 kHz,
// which would otherwise dominate the recording and hide a weak folded station
if A.contains("--clean") {
    let tl = 1025; let ml = Double(tl - 1) / 2
    func lp(_ fc: Double) -> [Double] { var h = [Double](repeating: 0, count: tl); var sm = 0.0
        for i in 0..<tl { let t = Double(i) - ml; let sc = t == 0 ? 2 * fc / fs : sin(2 * Double.pi * fc / fs * t) / (Double.pi * t); h[i] = sc * (0.54 - 0.46 * cos(2 * Double.pi * Double(i) / Double(tl - 1))); sm += h[i] }
        return h.map { $0 / sm } }
    let a3 = lp(3000), b1 = lp(7600), b2 = lp(8600), c1 = lp(15700), c2 = lp(16500)
    var h = [Float](repeating: 0, count: tl); for i in 0..<tl { h[i] = Float((i == Int(ml) ? 1.0 : 0.0) - a3[i] - (b2[i] - b1[i]) - (c2[i] - c1[i])) }
    var y = [Float](repeating: 0, count: x.count - tl); vDSP_conv(x, 1, Array(h.reversed()), 1, &y, 1, vDSP_Length(x.count - tl), vDSP_Length(tl)); x = y }
let n2 = x.count
// analytic signal: Hilbert FIR (odd taps, Hamming), delay (T-1)/2
let T = 129, mid = (T - 1) / 2; var h = [Float](repeating: 0, count: T)
for i in 0..<T { let k = i - mid; if k % 2 != 0 { h[i] = Float(2 / (Double.pi * Double(k)) * (0.54 - 0.46 * cos(2 * Double.pi * Double(i) / Double(T - 1)))) } }
let m = n2 - T; guard m > 1000 else { die("recording too short") }
var q = [Float](repeating: 0, count: m); vDSP_conv(x, 1, Array(h.reversed()), 1, &q, 1, vDSP_Length(m), vDSP_Length(T))
// instantaneous frequency (always >= 0 for a real signal) and amplitude
var f = [Float](repeating: 0, count: m), amp = [Float](repeating: 0, count: m)
for k in 1..<m { let i0 = x[k + mid - 1], q0 = q[k - 1], i1 = x[k + mid], q1 = q[k]
    f[k] = atan2(q1 * i0 - i1 * q0, i1 * i0 + q1 * q0) * Float(fs / (2 * Double.pi)); amp[k] = (i1 * i1 + q1 * q1).squareRoot() }
var s = amp.sorted(); let aMed = s[m / 2]; s.removeAll()
// A real recording gives |f| only. The station's own 19 kHz stereo pilot tells the sign: the pilot is part of f, so in
// |f| it appears upright while f > 0 and upside down while f < 0. Its polarity is read with a 1 ms window.
func centred(_ v: [Float], _ w: Int) -> [Float] {   // moving average over w samples, centred
    var c = [Double](repeating: 0, count: v.count + 1); for k in 0..<v.count { c[k + 1] = c[k] + Double(v[k]) }
    var o = [Float](repeating: 0, count: v.count); let h = w / 2
    for k in 0..<v.count { let a = max(0, k - h), b = min(v.count, k + h + 1); o[k] = Float((c[b] - c[a]) / Double(b - a)) }; return o }
var af = [Float](repeating: 0, count: m), pc = af, ps = af; let w19 = 2 * Double.pi * 19000 / fs
for k in 0..<m { af[k] = abs(f[k]); let ph = w19 * Double(k); pc[k] = af[k] * Float(cos(ph)); ps[k] = af[k] * Float(sin(ph)) }
let g = centred(af, max(3, Int((3 * fs / 19000).rounded())))          // |f| without the pilot and subcarriers
let wp = Int((19 * fs / 19000).rounded()); let pr = centred(pc, wp), pq = centred(ps, wp)
// pilot phase, block by block (0.1 s), from the squared pilot (so the sign of f does not matter), followed continuously:
// the recording's clock and the station's pilot differ by a few parts per million, so the phase drifts slowly
let blk = max(64, Int(fs / 10)); let nb = max(1, m / blk); var thB = [Double](repeating: 0, count: nb); var lockSum = 0.0
for bI in 0..<nb { var s2r = 0.0, s2i = 0.0; for k in stride(from: bI * blk, to: min(m, (bI + 1) * blk), by: 3) { let x = Double(pr[k]), y = Double(pq[k]); s2r += x * x - y * y; s2i += 2 * x * y }
    var e = 0.0; for k in stride(from: bI * blk, to: min(m, (bI + 1) * blk), by: 3) { e += Double(pr[k] * pr[k] + pq[k] * pq[k]) }; lockSum += (s2r * s2r + s2i * s2i).squareRoot() / max(e, 1e-12)
    var t = 0.5 * atan2(s2i, s2r); if bI > 0 { while t - thB[bI - 1] > Double.pi / 2 { t -= Double.pi }; while t - thB[bI - 1] < -Double.pi / 2 { t += Double.pi } }; thB[bI] = t }
func thAt(_ k: Int) -> Double { let x = (Double(k) - Double(blk) / 2) / Double(blk); let i0 = max(0, min(nb - 1, Int(floor(x)))), i1 = min(nb - 1, i0 + 1); let u = max(0, min(1, x - Double(i0))); return thB[i0] + (thB[i1] - thB[i0]) * u }
var dev = [Float](repeating: 0, count: m); var hold: Float = 0; var lost = 0, flips = 0; var last: Float = 0
var pilotLevel: Float = 0
for k in 0..<m { let th = thAt(k); let proj = pr[k] * Float(cos(th)) + pq[k] * Float(sin(th)); pilotLevel += abs(proj); let sg: Float = proj >= 0 ? 1 : -1
    if sg != last { flips += 1; last = sg }
    if amp[k] < 0.3 * aMed { dev[k] = hold; lost += 1 } else { hold = sg * g[k]; dev[k] = hold } }
// the overall polarity is unknown (the pilot phase is known only up to half a turn): choose the one that puts the carrier at OFFSET
var meanDev: Float = 0; vDSP_meanv(dev, 1, &meanDev, vDSP_Length(m))
let pol: Float = (meanDev >= 0) == (off >= 0) ? 1 : -1
for k in 0..<m { dev[k] = pol * dev[k] - Float(off) }
print(String(format: "pilot lock %.2f (1 = a steady 19 kHz pilot, about 0.1 = noise), pilot ripple %.0f Hz, mean frequency %.0f Hz", lockSum / Double(nb), 2 * pilotLevel / Float(m), pol * meanDev))
// audio: 15 kHz low-pass, decimate to about 44 kHz, de-emphasis
func lowpass(_ taps: Int, _ fc: Double, _ rate: Double) -> [Float] { var hh = [Float](repeating: 0, count: taps); let mm = Double(taps - 1) / 2; var sum: Float = 0
    for i in 0..<taps { let t = Double(i) - mm; let sinc = t == 0 ? 2 * fc / rate : sin(2 * Double.pi * fc / rate * t) / (Double.pi * t); hh[i] = Float(sinc * (0.54 - 0.46 * cos(2 * Double.pi * Double(i) / Double(taps - 1)))); sum += hh[i] }
    return hh.map { $0 / sum } }
let D = max(1, Int((fs / 44100).rounded())); let ars = fs / Double(D); let hA = lowpass(129, 15000, fs); let outN = (m - hA.count) / D
var au = [Float](repeating: 0, count: outN); vDSP_desamp(dev, vDSP_Stride(D), hA, &au, vDSP_Length(outN), vDSP_Length(hA.count))
let a = Float(exp(-1 / (ars * deUs * 1e-6))); var st: Float = 0; for k in 0..<outN { st = a * st + (1 - a) * au[k]; au[k] = st }
var mean: Float = 0; vDSP_meanv(au, 1, &mean, vDSP_Length(outN)); var pk: Float = 1e-9; for k in 0..<outN { au[k] -= mean; pk = max(pk, abs(au[k])) }
var wav = Data(); func le<V: FixedWidthInteger>(_ v: V) { withUnsafeBytes(of: v.littleEndian) { wav.append(contentsOf: $0) } }
wav.append("RIFF".data(using: .ascii)!); le(UInt32(36 + outN * 2)); wav.append("WAVEfmt ".data(using: .ascii)!); le(UInt32(16)); le(UInt16(1)); le(UInt16(1))
le(UInt32(ars)); le(UInt32(ars) * 2); le(UInt16(2)); le(UInt16(16)); wav.append("data".data(using: .ascii)!); le(UInt32(outN * 2))
for v in au { le(Int16(max(-32767, min(32767, v / pk * 0.8 * 32767)))) }
FileManager.default.createFile(atPath: A[4], contents: wav)
print(String(format: "auxfm: %.1f s, %.1f %% of the time outside the passband (held), %d zero crossings followed, audio %.0f Hz -> %@", Double(m) / fs, 100 * Double(lost) / Double(m), flips, ars, A[4]))
