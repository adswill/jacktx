// xcorr AUX.f32 AUXRATE REF.wav [LO HI]: is the programme in REF.wav (16-bit mono) present in the aux recording?
// Both go to 16 kHz, band LO..HI Hz; the aux side is whitened so hum lines carry no weight. Prints the peak, its lag and its height over the noise.
import Foundation
import Accelerate
let a = CommandLine.arguments
guard a.count >= 4, let ar = Double(a[2]) else { print("usage"); exit(2) }
let lo = a.count > 4 ? Double(a[4])! : 300, hi = a.count > 5 ? Double(a[5])! : 7000
func lowpass(_ x: [Float], _ rate: Double, _ fc: Double) -> [Float] {
    let n = 255; var h = [Float](repeating: 0, count: n); let m = Double(n - 1) / 2
    for i in 0..<n { let t = Double(i) - m; let s = t == 0 ? 2 * fc / rate : sin(2 * .pi * fc / rate * t) / (.pi * t)
        h[i] = Float(s * (0.42 - 0.5 * cos(2 * .pi * Double(i) / Double(n - 1)) + 0.08 * cos(4 * .pi * Double(i) / Double(n - 1)))) }
    var y = [Float](repeating: 0, count: x.count); let xp = [Float](repeating: 0, count: n / 2) + x + [Float](repeating: 0, count: n)
    vDSP_conv(xp, 1, h, 1, &y, 1, vDSP_Length(x.count), vDSP_Length(n)); return y }
func to16k(_ x: [Float], _ rate: Double) -> [Float] {
    let f = lowpass(x, rate, 7500); let n = Int(Double(x.count) * 16000 / rate) - 2; var y = [Float](repeating: 0, count: max(n, 0))
    for i in 0..<y.count { let p = Double(i) * rate / 16000; let k = Int(p); let fr = Float(p - Double(k)); y[i] = f[k] * (1 - fr) + f[k + 1] * fr }
    return y }
let ad = try! Data(contentsOf: URL(fileURLWithPath: a[1])); let aux = ad.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
let wd = try! Data(contentsOf: URL(fileURLWithPath: a[3]))
let wrate = Double(wd.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 24, as: UInt32.self) })
let ref: [Float] = wd.withUnsafeBytes { p in let s = p.baseAddress!.advanced(by: 44).assumingMemoryBound(to: Int16.self); return (0..<(wd.count - 44) / 2).map { Float(s[$0]) / 32768 } }
let A = to16k(aux, ar), R = to16k(ref, wrate)
var N = 1; while N < max(A.count, R.count) * 2 { N *= 2 }
let setup = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(N), .FORWARD)!, inv = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(N), .INVERSE)!
func fft(_ x: [Float]) -> ([Float], [Float]) { let re = x + [Float](repeating: 0, count: N - x.count), im = [Float](repeating: 0, count: N); var or = [Float](repeating: 0, count: N), oi = or
    vDSP_DFT_Execute(setup, re, im, &or, &oi); return (or, oi) }
let (ar_, ai_) = fft(A), (rr, ri) = fft(R)
var cr = [Float](repeating: 0, count: N), ci = cr
let k1 = Int(lo / 16000 * Double(N)), k2 = Int(hi / 16000 * Double(N))
for k in k1..<k2 { let m = (ar_[k] * ar_[k] + ai_[k] * ai_[k]).squareRoot(); if m <= 0 { continue }
    let wr = ar_[k] / m, wi = ai_[k] / m; let xr = wr * rr[k] + wi * ri[k], xi = wi * rr[k] - wr * ri[k]
    cr[k] = xr; ci[k] = xi; cr[N - k] = xr; ci[N - k] = -xi }
var or = [Float](repeating: 0, count: N), oi = or; vDSP_DFT_Execute(inv, cr, ci, &or, &oi)
var ss: Float = 0; vDSP_measqv(or, 1, &ss, vDSP_Length(N)); let sd = ss.squareRoot()
let maxlag = 3 * 16000; var best: Float = 0; var bl = 0
for l in -maxlag...maxlag { let v = abs(or[(l + N) % N]); if v > best { best = v; bl = l } }
var second: Float = 0; for l in -maxlag...maxlag where abs(l - bl) > 400 { second = max(second, abs(or[(l + N) % N])) }
print(String(format: "peak %.1f x noise at lag %+.4f s (next best elsewhere %.1f x noise; chance alone gives about 5)", best / sd, Double(bl) / 16000, second / sd))
