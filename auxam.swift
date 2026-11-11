// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// auxam IN.f32 RATE OUT.wav [LO HI]: clean an aux recording for listening: band LO..HI Hz (default 300..3400), narrow lines (hum, USB tones) removed, 16 kHz 16-bit wav
import Foundation
import Accelerate
let a = CommandLine.arguments
guard a.count >= 4, let rate = Double(a[2]) else { print("usage: auxam IN.f32 RATE OUT.wav [LO HI]"); exit(2) }
let lo = a.count > 4 ? Double(a[4])! : 300, hi = a.count > 5 ? Double(a[5])! : 3400
let d = try! Data(contentsOf: URL(fileURLWithPath: a[1])); let x = d.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
var N = 1; while N < x.count { N *= 2 }
let fwd = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(N), .FORWARD)!, inv = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(N), .INVERSE)!
var re = [Float](repeating: 0, count: N), im = re; let xi = x + [Float](repeating: 0, count: N - x.count), zi = [Float](repeating: 0, count: N)
vDSP_DFT_Execute(fwd, xi, zi, &re, &im)
let k1 = Int(lo / rate * Double(N)), k2 = Int(hi / rate * Double(N))
var mag = [Float](repeating: 0, count: k2 + 1); for k in 0...k2 { mag[k] = (re[k] * re[k] + im[k] * im[k]).squareRoot() }
// local median over +-W bins; a bin more than 4x above it is a narrow line: pull it down to the median
let W = max(50, Int(40.0 / rate * Double(N)))
var cut = 0
for k in 0..<N / 2 + 1 {
    if k < k1 || k > k2 { re[k] = 0; im[k] = 0; if k > 0 && k < N / 2 { re[N - k] = 0; im[N - k] = 0 }; continue }
    let s = Array(mag[max(k1, k - W)...min(k2, k + W)]).sorted(); let med = s[s.count / 2]
    if mag[k] > 4 * med { let g = med / mag[k] * 0.5; re[k] *= g; im[k] *= g; cut += 1 }
    re[N - k] = re[k]; im[N - k] = -im[k]
}
var or = [Float](repeating: 0, count: N), oi = or; vDSP_DFT_Execute(inv, re, im, &or, &oi)
let step = rate / 16000; let n = Int(Double(x.count) / step) - 1; var y = (0..<n).map { or[Int(Double($0) * step)] }
var pk: Float = 0; let srt = y.map { abs($0) }.sorted(); pk = srt[Int(Double(srt.count) * 0.999)]
var out = Data(); func u32(_ v: UInt32) { var v = v; out.append(Data(bytes: &v, count: 4)) }; func u16(_ v: UInt16) { var v = v; out.append(Data(bytes: &v, count: 2)) }
out.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + n * 2)); out.append("WAVEfmt ".data(using: .ascii)!); u32(16); u16(1); u16(1); u32(16000); u32(32000); u16(2); u16(16)
out.append("data".data(using: .ascii)!); u32(UInt32(n * 2))
for v in y { u16(UInt16(bitPattern: Int16(max(-1, min(1, v / pk * 0.8)) * 32000))) }
try! out.write(to: URL(fileURLWithPath: a[3]))
print("cleaned: \(cut) narrow-line bins pulled down, \(String(format: "%.1f", Double(n) / 16000)) s written")
