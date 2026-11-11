// auxlink: a data link over an AM carrier into the aux input (square-law detector, very low signal-to-noise).
//   auxlink tx IN.bin OUT.cs8 T_MS     2 Msps cs8 for hackrf_transfer; carrier at +100 kHz; the envelope is a 16-tone FSK subcarrier
//   auxlink rx IN.f32 OUT.bin T_MS     decode a 96 kHz mono float32 recording of the aux input
// Frame: 1.5 s pilot tone, 64-symbol preamble, length header (16 bits, each sent 5 times), payload + CRC32 through a K=7 rate-1/2
// convolutional code and an interleaver, 64-symbol postamble. 4 coded bits per symbol; T_MS is the symbol length (5, 10 or 20).
import Foundation
import Accelerate

let args = CommandLine.arguments
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }
guard args.count >= 5, let tms = Double(args[4]) else { die("usage: auxlink tx IN.bin OUT.cs8 T_MS | auxlink rx IN.f32 OUT.bin T_MS") }
let M = 16, PRE = 64, HDRREP = 5
let spacing = 2000.0 / tms            // 2/T
let tones = (0..<M).map { 9300.0 + Double($0) * spacing }
// pseudo-random preamble and postamble symbols (fixed)
func pn(_ seed: UInt32, _ n: Int) -> [Int] { var s = seed; return (0..<n).map { _ in s = s &* 1664525 &+ 1013904223; return Int((s >> 24) & 15) } }
let preSym = pn(0x1234567, PRE), postSym = pn(0x7654321, PRE)
func crc32(_ d: [UInt8]) -> UInt32 { var c: UInt32 = 0xFFFFFFFF
    for b in d { c ^= UInt32(b); for _ in 0..<8 { c = (c & 1) != 0 ? (c >> 1) ^ 0xEDB88320 : c >> 1 } }
    return ~c }
func parity(_ v: Int) -> Int { v.nonzeroBitCount & 1 }
let G1 = 0o133, G2 = 0o171
func convEncode(_ bits: [Int]) -> [Int] { var sr = 0; var out = [Int](); out.reserveCapacity(bits.count * 2)
    for b in bits { sr = ((sr << 1) | b) & 0x7F; out.append(parity(sr & G1)); out.append(parity(sr & G2)) }
    return out }
func interleaveStride(_ n: Int) -> Int { var p = 10007; func gcd(_ a: Int, _ b: Int) -> Int { b == 0 ? a : gcd(b, a % b) }
    while gcd(p, n) != 1 { p += 2 }; return p }
func frameBits(_ payload: [UInt8]) -> [Int] {      // info bits: payload, CRC32, 6 tail zeros
    let c = crc32(payload); let all = payload + [UInt8(c & 255), UInt8((c >> 8) & 255), UInt8((c >> 16) & 255), UInt8(c >> 24)]
    var bits = [Int](); for b in all { for i in 0..<8 { bits.append(Int((b >> (7 - i)) & 1)) } }
    return bits + [0, 0, 0, 0, 0, 0] }
func codedSymbols(_ payload: [UInt8]) -> [Int] {
    var c = convEncode(frameBits(payload)); while c.count % 4 != 0 { c.append(0) }
    let n = c.count, p = interleaveStride(n); var il = [Int](repeating: 0, count: n)
    for i in 0..<n { il[(i * p) % n] = c[i] }
    return stride(from: 0, to: n, by: 4).map { il[$0] << 3 | il[$0 + 1] << 2 | il[$0 + 2] << 1 | il[$0 + 3] } }
func headerSymbols(_ len: Int) -> [Int] {          // 16 bits, each 5 times, 4 bits per symbol
    var bits = [Int](); for i in 0..<16 { let b = (len >> (15 - i)) & 1; for _ in 0..<HDRREP { bits.append(b) } }
    return stride(from: 0, to: bits.count, by: 4).map { bits[$0] << 3 | bits[$0 + 1] << 2 | bits[$0 + 2] << 1 | bits[$0 + 3] } }
let HDRSYM = 16 * HDRREP / 4

if args[1] == "tx" {
    let payload = [UInt8](try! Data(contentsOf: URL(fileURLWithPath: args[2])))
    guard payload.count < 65536 else { die("payload too long") }
    let syms = preSym + headerSymbols(payload.count) + codedSymbols(payload) + postSym
    let fs = 2_000_000.0, spb = Int(fs * tms / 1000)
    FileManager.default.createFile(atPath: args[3], contents: nil); let fh = FileHandle(forWritingAtPath: args[3])!
    var ph = 0.0, cph = 0
    let cc = (0..<20).map { cos(2 * Double.pi * Double($0) / 20) }, cs = (0..<20).map { sin(2 * Double.pi * Double($0) / 20) }
    func emit(_ f: Double, _ n: Int, _ amp: Double) { var buf = [Int8](repeating: 0, count: n * 2); let dp = 2 * Double.pi * f / fs
        for i in 0..<n { let e = (0.5 + 0.5 * cos(ph)) * amp * 126; ph += dp; if ph > 2 * Double.pi { ph -= 2 * Double.pi }
            buf[2 * i] = Int8(e * cc[cph]); buf[2 * i + 1] = Int8(e * cs[cph]); cph = (cph + 1) % 20 }
        buf.withUnsafeBytes { fh.write(Data($0)) } }
    emit(tones[0], Int(fs * 1.5), 1)                               // pilot: lets the receiver settle and measures the link
    for s in syms { emit(tones[s], spb, 1) }
    emit(tones[0], Int(fs * 0.5), 1)
    fh.closeFile()
    let secs = 2.0 + Double(syms.count) * tms / 1000
    print(String(format: "tx file: %d payload bytes, %d symbols, %.1f s on air, net %.0f bit/s", payload.count, syms.count, secs, 2000 / tms))
    exit(0)
}
guard args[1] == "rx" else { die("tx or rx") }
let rate = 96000.0
let d = try! Data(contentsOf: URL(fileURLWithPath: args[2])); let x = d.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
let L = Int(rate * tms / 1000)
// tone tables for one symbol window
var tc = [[Float]](), ts = [[Float]]()
for f in tones { tc.append((0..<L).map { Float(cos(2 * Double.pi * f * Double($0) / rate)) }); ts.append((0..<L).map { Float(sin(2 * Double.pi * f * Double($0) / rate)) }) }
func energies(_ start: Int) -> [Float] {
    var e = [Float](repeating: 0, count: M); if start < 0 || start + L > x.count { return e }
    x.withUnsafeBufferPointer { xp in for k in 0..<M { var re: Float = 0, im: Float = 0
        vDSP_dotpr(xp.baseAddress! + start, 1, tc[k], 1, &re, vDSP_Length(L)); vDSP_dotpr(xp.baseAddress! + start, 1, ts[k], 1, &im, vDSP_Length(L)); e[k] = re * re + im * im } }
    return e }
func seqMetric(_ seq: [Int], _ s0: Double, _ step: Double) -> Float {   // share of the energy that sits on the expected tones
    var hit: Float = 0, tot: Float = 0
    for (i, p) in seq.enumerated() { let e = energies(Int((s0 + Double(i) * step).rounded())); hit += e[p]; tot += e.reduce(0, +) }
    return tot > 0 ? hit / tot : 0 }
// 1. preamble: coarse then fine
var best: Float = 0, s0 = 0.0
let searchEnd = min(x.count - (PRE + 4) * L, Int(rate * 6))
var s = 0; while s < searchEnd { let m = seqMetric(preSym, Double(s), Double(L)); if m > best { best = m; s0 = Double(s) }; s += L / 4 }
var fine = s0; for ds in stride(from: -L / 4, through: L / 4, by: max(1, L / 32)) { let m = seqMetric(preSym, s0 + Double(ds), Double(L)); if m > best { best = m; fine = s0 + Double(ds) } }
s0 = fine
print(String(format: "preamble at %.3f s, %.0f %% of the energy on the expected tones (chance: 6 %%)", s0 / rate, best * 100))
if best < 0.12 { print("RESULT no preamble found"); exit(1) }
// 2. header
var Ld = Double(L)
var hb = [Float](repeating: 0, count: 16)
for i in 0..<HDRSYM { let e = energies(Int((s0 + Double(PRE + i) * Ld).rounded()))
    for b in 0..<4 { var m1: Float = 0, m0: Float = 0; for k in 0..<M { if (k >> (3 - b)) & 1 == 1 { m1 = max(m1, e[k]) } else { m0 = max(m0, e[k]) } }
        hb[(i * 4 + b) / HDRREP] += (m1 - m0) / (m1 + m0 + 1e-20) } }
var plen = 0; for i in 0..<16 { plen = plen << 1 | (hb[i] > 0 ? 1 : 0) }
let infoBits = (plen + 4) * 8 + 6; var ncoded = infoBits * 2; while ncoded % 4 != 0 { ncoded += 1 }
let nsym = ncoded / 4
print("header: \(plen) payload bytes, \(nsym) symbols")
if s0 + Double(PRE + HDRSYM + nsym + PRE) * Ld > Double(x.count) { print("RESULT the recording is too short for that length (bad header or cut recording)"); exit(1) }
// 3. postamble: exact symbol length (clock difference between the transmitter and the Mac)
let postIdx = Double(PRE + HDRSYM + nsym)
var pbest: Float = 0, pshift = 0.0
for ds in stride(from: -Double(L), through: Double(L), by: Double(max(1, L / 32))) { let m = seqMetric(postSym, s0 + postIdx * Ld + ds, Ld); if m > pbest { pbest = m; pshift = ds } }
if pbest > 0.12 { Ld += pshift / postIdx }
print(String(format: "postamble: %.0f %% on the expected tones, clock difference %+.1f ppm", pbest * 100, (Ld / Double(L) - 1) * 1e6))
// 4. payload energies, per-tone noise, soft bits
var E = [[Float]](); E.reserveCapacity(nsym)
for i in 0..<nsym { E.append(energies(Int((s0 + Double(PRE + HDRSYM + i) * Ld).rounded()))) }
var noise = [Float](repeating: 1, count: M)
for k in 0..<M { let v = E.map { $0[k] }.sorted(); noise[k] = max(v[v.count / 2] / 0.693, 1e-20) }
var soft = [Float](repeating: 0, count: ncoded); var esn: Float = 0
for i in 0..<nsym { let m = (0..<M).map { E[i][$0] / noise[$0] }; esn += m.max()!
    for b in 0..<4 { var m1: Float = 0, m0: Float = 0; for k in 0..<M { if (k >> (3 - b)) & 1 == 1 { m1 = max(m1, m[k]) } else { m0 = max(m0, m[k]) } }
        soft[i * 4 + b] = m1 - m0 } }
let p = interleaveStride(ncoded); var dil = [Float](repeating: 0, count: ncoded); for i in 0..<ncoded { dil[i] = soft[(i * p) % ncoded] }
// 5. Viterbi, 64 states, soft decision
let NS = 64; var metric = [Float](repeating: -1e30, count: NS); metric[0] = 0
var prev = [[UInt8]](repeating: [UInt8](repeating: 0, count: NS), count: infoBits)
var outA = [[Int]](repeating: [0, 0], count: NS * 2)          // outputs for (state, input bit)
for st in 0..<NS { for b in 0..<2 { let sr = ((st << 1) | b) & 0x7F; outA[st * 2 + b] = [parity(sr & G1), parity(sr & G2)] } }
for t in 0..<infoBits { var nm = [Float](repeating: -1e30, count: NS); let a = dil[2 * t], b2 = dil[2 * t + 1]
    for st in 0..<NS where metric[st] > -1e29 { for b in 0..<2 { let o = outA[st * 2 + b]; let ns = ((st << 1) | b) & 0x3F
        let v = metric[st] + (o[0] == 1 ? a : -a) + (o[1] == 1 ? b2 : -b2)
        if v > nm[ns] { nm[ns] = v; prev[t][ns] = UInt8(st) } } }
    metric = nm }
var st = 0; var bits = [Int](repeating: 0, count: infoBits)       // the tail forces state 0
for t in stride(from: infoBits - 1, through: 0, by: -1) { bits[t] = st & 1; st = Int(prev[t][st]) }
var bytes = [UInt8](); for i in 0..<(plen + 4) { var v = 0; for j in 0..<8 { v = v << 1 | bits[i * 8 + j] }; bytes.append(UInt8(v)) }
let payload = Array(bytes[0..<plen]); let got = UInt32(bytes[plen]) | UInt32(bytes[plen + 1]) << 8 | UInt32(bytes[plen + 2]) << 16 | UInt32(bytes[plen + 3]) << 24
// statistics: compare the raw symbol decisions with what the corrected data says was sent
let sent = codedSymbols(payload); var wrong = 0
for i in 0..<min(nsym, sent.count) { let m = (0..<M).map { E[i][$0] / noise[$0] }; if m.firstIndex(of: m.max()!)! != sent[i] { wrong += 1 } }
let esn0 = 10 * log10(max(esn / Float(nsym) - 1, 0.01))
print(String(format: "link: symbol energy %.1f dB over the noise, signal strength %.1f dB-Hz, %d of %d symbols wrong before correction (%.1f %%)", esn0, esn0 + 10 * log10(Float(1000 / tms)), wrong, nsym, 100 * Double(wrong) / Double(nsym)))
try! Data(payload).write(to: URL(fileURLWithPath: args[3]))
print(crc32(payload) == got ? "RESULT ok: \(plen) bytes received, checksum correct (every bit right)" : "RESULT checksum wrong: the data has errors")
