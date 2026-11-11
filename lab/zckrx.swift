// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// zckrx: coherent tone integrator for lab/zck.py.
//   zckrx IN.cs8 RATE CHUNK OUT.cf32 F1 F2 ...     (frequencies in Hz relative to the capture centre)
// For every frequency it mixes the capture down and sums CHUNK samples at a time. OUT holds, chunk after chunk, one
// complex float32 per frequency. Sums of neighbouring chunks are coherent, so the caller can choose the symbol timing.
import Foundation
let A = CommandLine.arguments
guard A.count >= 6, let rate = Double(A[2]), let chunk = Int(A[3]) else { FileHandle.standardError.write("usage: zckrx IN.cs8 RATE CHUNK OUT F1 F2 ...\n".data(using: .utf8)!); exit(2) }
let freqs = A[5...].compactMap(Double.init); let nf = freqs.count
guard let fh = FileHandle(forReadingAtPath: A[1]) else { exit(2) }
FileManager.default.createFile(atPath: A[4], contents: nil); let oh = FileHandle(forWritingAtPath: A[4])!
// one rotating phasor per frequency, renormalised every block
var pr = [Double](repeating: 1, count: nf), pi = [Double](repeating: 0, count: nf)
let cr = freqs.map { cos(-2 * Double.pi * $0 / rate) }, ci = freqs.map { sin(-2 * Double.pi * $0 / rate) }
var accR = [Double](repeating: 0, count: nf), accI = accR; var inChunk = 0, chunks = 0
var out = [Float](); out.reserveCapacity(2 * nf * 4096)
while true {
    guard let d = try? fh.read(upToCount: 1 << 21), d.count >= 2 else { break }
    d.withUnsafeBytes { raw in
        let p = raw.bindMemory(to: Int8.self); let n = d.count / 2
        for k in 0..<n {
            let x = Double(p[2 * k]), y = Double(p[2 * k + 1])
            for j in 0..<nf {
                accR[j] += x * pr[j] - y * pi[j]; accI[j] += x * pi[j] + y * pr[j]
                let t = pr[j] * cr[j] - pi[j] * ci[j]; pi[j] = pr[j] * ci[j] + pi[j] * cr[j]; pr[j] = t
            }
            inChunk += 1
            if inChunk == chunk {
                for j in 0..<nf { out.append(Float(accR[j])); out.append(Float(accI[j])); accR[j] = 0; accI[j] = 0
                    let m = (pr[j] * pr[j] + pi[j] * pi[j]).squareRoot(); pr[j] /= m; pi[j] /= m }
                inChunk = 0; chunks += 1
            }
        }
    }
    if out.count > 1 << 20 { out.withUnsafeBytes { oh.write(Data($0)) }; out.removeAll(keepingCapacity: true) }
}
out.withUnsafeBytes { oh.write(Data($0)) }; oh.closeFile()
print("chunks \(chunks) freqs \(nf)")
