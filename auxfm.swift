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
// analytic signal: Hilbert FIR (odd taps, Hamming), delay (T-1)/2
let T = 129, mid = (T - 1) / 2; var h = [Float](repeating: 0, count: T)
for i in 0..<T { let k = i - mid; if k % 2 != 0 { h[i] = Float(2 / (Double.pi * Double(k)) * (0.54 - 0.46 * cos(2 * Double.pi * Double(i) / Double(T - 1)))) } }
let m = n - T; guard m > 1000 else { die("recording too short") }
var q = [Float](repeating: 0, count: m); vDSP_conv(x, 1, Array(h.reversed()), 1, &q, 1, vDSP_Length(m), vDSP_Length(T))
// instantaneous frequency (always >= 0 for a real signal) and amplitude
var f = [Float](repeating: 0, count: m), amp = [Float](repeating: 0, count: m)
for k in 1..<m { let i0 = x[k + mid - 1], q0 = q[k - 1], i1 = x[k + mid], q1 = q[k]
    f[k] = atan2(q1 * i0 - i1 * q0, i1 * i0 + q1 * q0) * Float(fs / (2 * Double.pi)); amp[k] = (i1 * i1 + q1 * q1).squareRoot() }
var s = amp.sorted(); let aMed = s[m / 2]; s.removeAll()
// sign tracking: the true frequency is sgn x |f|; the sign flips each time |f| dips to (about) zero
var sign: Float = off >= 0 ? 1 : -1; var dev = [Float](repeating: 0, count: m); var hold: Float = 0; var lost = 0; var armed = true
let zeroBand = Float(1500), rearm = Float(4000)
for k in 1..<m {
    let af = abs(f[k])
    if amp[k] < 0.3 * aMed { dev[k] = hold; lost += 1; continue }          // outside the input's passband
    if armed && af < zeroBand && k + 1 < m && abs(f[k + 1]) > af && abs(f[k - 1]) > af { sign = -sign; armed = false }
    if af > rearm { armed = true }
    hold = sign * af - Float(off); dev[k] = hold
}
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
print(String(format: "auxfm: %.1f s, %.1f %% of the time outside the passband (held), audio %.0f Hz -> %@", Double(m) / fs, 100 * Double(lost) / Double(m), ars, A[4]))
