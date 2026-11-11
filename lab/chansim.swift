// chansim IN.cs8 NOISE.f32 GAIN OUT.f32 [DELAY_S]: square-law detect a 2 Msps cs8 file, bring it to 96 kHz, add it to a real aux noise recording
import Foundation
let a = CommandLine.arguments
let d = try! Data(contentsOf: URL(fileURLWithPath: a[1])); let nz = (try! Data(contentsOf: URL(fileURLWithPath: a[2]))).withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
let g = Float(a[3])!; let delay = a.count > 5 ? Double(a[5])! : 0.7
let n = d.count / 2; let ratio = 2_000_000.0 / 96000.0; let nout = Int(Double(n) / ratio)
var sig = [Float](repeating: 0, count: nout)
d.withUnsafeBytes { p in let b = p.bindMemory(to: Int8.self)
    for o in 0..<nout { let s = Int(Double(o) * ratio), e = min(n, Int(Double(o + 1) * ratio)); var acc: Float = 0
        for i in s..<e { let x = Float(b[2 * i]), y = Float(b[2 * i + 1]); acc += x * x + y * y }
        sig[o] = acc / Float(max(1, e - s)) / (126 * 126) } }
let off = Int(delay * 96000); var out = [Float](repeating: 0, count: nout + off + 96000)
for i in 0..<out.count { out[i] = nz[i % nz.count] + (i >= off && i - off < nout ? g * (sig[i - off] - 0.375) : 0) }
out.withUnsafeBytes { try! Data($0).write(to: URL(fileURLWithPath: a[4])) }
