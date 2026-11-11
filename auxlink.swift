// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// auxlink: the jack radio link. One frame format, two directions:
//   HackRF -> aux input   the frame is a 16-tone FSK subcarrier on an AM carrier; the detector on the cable turns it into audio
//   jack -> HackRF        the same tones are played as audio; they appear beside one of the jack's radio lines
//
//   auxlink tx     IN.bin OUT.cs8 T_MS            2 Msps cs8 for hackrf_transfer, carrier at +100 kHz, envelope = the tones
//   auxlink txam   IN.wav OUT.cs8                 any 16-bit mono WAV as plain AM (2 Msps cs8, carrier at +100 kHz)
//   auxlink txwav  IN.bin OUT.wav T_MS            96 kHz stereo WAV of the tones, for the headphone jack
//   auxlink rx     IN.f32 OUT.bin T_MS [RATE]     decode a mono float32 recording (default 96000 Hz)
//   auxlink iq2aud IN.cs8 RATE LINE_HZ OUT.f32 T_MS   HackRF capture -> 100 kHz audio: the band above the line at LINE_HZ from the
//                                                 capture centre, with the line's exact frequency found from the tones themselves
//   auxlink probe  IN.cs8 RATE LINE_HZ TONE_HZ    strength of a test tone beside a line, in dB-Hz
// Frame: 1.5 s pilot tone, 64-symbol preamble, length header (16 bits, each sent 5 times), payload + CRC32 through a K=7 rate-1/2
// convolutional code and an interleaver, 64-symbol postamble. 4 coded bits per symbol; T_MS is the symbol length (5, 10, 20, 40).
import Foundation
import Accelerate

let args = CommandLine.arguments
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }
guard args.count >= 2 else { die("usage: auxlink tx|txam|txwav|rx|iq2aud|probe ... (see the header of auxlink.swift)") }
let cmd = args[1]
let M = 16, PRE = 64, HDRREP = 5, HDRSYM = 16 * HDRREP / 4
func toneSet(_ tms: Double) -> [Double] { (0..<M).map { 9300.0 + Double($0) * 2000.0 / tms } }
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
func frameBits(_ payload: [UInt8]) -> [Int] {
    let c = crc32(payload); let all = payload + [UInt8(c & 255), UInt8((c >> 8) & 255), UInt8((c >> 16) & 255), UInt8(c >> 24)]
    var bits = [Int](); for b in all { for i in 0..<8 { bits.append(Int((b >> (7 - i)) & 1)) } }
    return bits + [0, 0, 0, 0, 0, 0] }
func codedSymbols(_ payload: [UInt8]) -> [Int] {
    var c = convEncode(frameBits(payload)); while c.count % 4 != 0 { c.append(0) }
    let n = c.count, p = interleaveStride(n); var il = [Int](repeating: 0, count: n)
    for i in 0..<n { il[(i * p) % n] = c[i] }
    return stride(from: 0, to: n, by: 4).map { il[$0] << 3 | il[$0 + 1] << 2 | il[$0 + 2] << 1 | il[$0 + 3] } }
func headerSymbols(_ len: Int) -> [Int] {
    var bits = [Int](); for i in 0..<16 { let b = (len >> (15 - i)) & 1; for _ in 0..<HDRREP { bits.append(b) } }
    return stride(from: 0, to: bits.count, by: 4).map { bits[$0] << 3 | bits[$0 + 1] << 2 | bits[$0 + 2] << 1 | bits[$0 + 3] } }
func frameSymbols(_ path: String) -> [Int] {
    let payload = [UInt8](try! Data(contentsOf: URL(fileURLWithPath: path)))
    guard payload.count < 65536 else { die("payload too long (65535 bytes at most)") }
    return preSym + headerSymbols(payload.count) + codedSymbols(payload) + postSym }
func readCS8(_ path: String) -> Data { guard let d = try? Data(contentsOf: URL(fileURLWithPath: path)) else { die("cannot read \(path)") }; return d }
func writeWav(_ path: String, _ samples: [Int16], rate: Int, channels: Int) {
    var out = Data(); func u32(_ v: UInt32) { var v = v; out.append(Data(bytes: &v, count: 4)) }; func u16(_ v: UInt16) { var v = v; out.append(Data(bytes: &v, count: 2)) }
    out.append("RIFF".data(using: .ascii)!); u32(UInt32(36 + samples.count * 2)); out.append("WAVEfmt ".data(using: .ascii)!); u32(16); u16(1); u16(UInt16(channels))
    u32(UInt32(rate)); u32(UInt32(rate * channels * 2)); u16(UInt16(channels * 2)); u16(16); out.append("data".data(using: .ascii)!); u32(UInt32(samples.count * 2))
    samples.withUnsafeBytes { out.append(Data($0)) }; try! out.write(to: URL(fileURLWithPath: path)) }

// ---------------------------------------------------------------- transmit files
let carC = (0..<20).map { cos(2 * Double.pi * Double($0) / 20) }, carS = (0..<20).map { sin(2 * Double.pi * Double($0) / 20) }
if cmd == "tx" {
    guard args.count >= 5, let tms = Double(args[4]) else { die("auxlink tx IN.bin OUT.cs8 T_MS") }
    let syms = frameSymbols(args[2]), tones = toneSet(tms); let fs = 2_000_000.0, spb = Int(fs * tms / 1000)
    FileManager.default.createFile(atPath: args[3], contents: nil); let fh = FileHandle(forWritingAtPath: args[3])!
    var ph = 0.0, cph = 0
    func emit(_ f: Double, _ n: Int) { var buf = [Int8](repeating: 0, count: n * 2); let dp = 2 * Double.pi * f / fs
        for i in 0..<n { let e = (0.5 + 0.5 * cos(ph)) * 126; ph += dp; if ph > 2 * Double.pi { ph -= 2 * Double.pi }
            buf[2 * i] = Int8(e * carC[cph]); buf[2 * i + 1] = Int8(e * carS[cph]); cph = (cph + 1) % 20 }
        buf.withUnsafeBytes { fh.write(Data($0)) } }
    emit(tones[0], Int(fs * 1.5)); for s in syms { emit(tones[s], spb) }; emit(tones[0], Int(fs * 0.5)); fh.closeFile()
    print(String(format: "frame: %d symbols, %.1f s on air, net %.0f bit/s", syms.count, 2.0 + Double(syms.count) * tms / 1000, 2000 / tms)); exit(0)
}
if cmd == "txwav" {
    guard args.count >= 5, let tms = Double(args[4]) else { die("auxlink txwav IN.bin OUT.wav T_MS") }
    let syms = frameSymbols(args[2]), tones = toneSet(tms); let fs = 96000.0, spb = Int(fs * tms / 1000)
    var out = [Int16](); var ph = 0.0
    func emit(_ f: Double, _ n: Int) { let dp = 2 * Double.pi * f / fs; for _ in 0..<n { let v = Int16(29000 * sin(ph)); ph += dp; if ph > 2 * Double.pi { ph -= 2 * Double.pi }; out.append(v); out.append(v) } }
    emit(tones[0], Int(fs * 1.5)); for s in syms { emit(tones[s], spb) }; emit(tones[0], Int(fs * 0.5))
    writeWav(args[3], out, rate: 96000, channels: 2)
    print(String(format: "frame: %d symbols, %.1f s of audio, net %.0f bit/s", syms.count, 2.0 + Double(syms.count) * tms / 1000, 2000 / tms)); exit(0)
}
if cmd == "txam" {
    guard args.count >= 4 else { die("auxlink txam IN.wav OUT.cs8") }
    let wd = try! Data(contentsOf: URL(fileURLWithPath: args[2]))
    let wrate = Double(wd.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 24, as: UInt32.self) }), ch = Int(wd.withUnsafeBytes { $0.loadUnaligned(fromByteOffset: 22, as: UInt16.self) })
    var a: [Double] = wd.withUnsafeBytes { p in let s = p.baseAddress!.advanced(by: 44).assumingMemoryBound(to: Int16.self); return stride(from: 0, to: (wd.count - 44) / 2, by: max(1, ch)).map { Double(s[$0]) / 32768 } }
    let pk = max(a.map { abs($0) }.max() ?? 1, 1e-6); a = a.map { tanh(2.5 * $0 / pk) / tanh(2.5) }            // light compression: more modulation
    a = [Double](repeating: 0, count: Int(wrate / 2)) + a + [Double](repeating: 0, count: Int(wrate / 2))
    let fs = 2_000_000.0, n = Int(Double(a.count - 1) * fs / wrate)
    FileManager.default.createFile(atPath: args[3], contents: nil); let fh = FileHandle(forWritingAtPath: args[3])!
    var i = 0; while i < n { let m = min(1 << 20, n - i); var buf = [Int8](repeating: 0, count: m * 2)
        for j in 0..<m { let p = Double(i + j) * wrate / fs; let k = Int(p); let v = a[k] + (a[k + 1] - a[k]) * (p - Double(k)); let e = (0.5 + 0.45 * v) * 126; let c = (i + j) % 20
            buf[2 * j] = Int8(e * carC[c]); buf[2 * j + 1] = Int8(e * carS[c]) }
        buf.withUnsafeBytes { fh.write(Data($0)) }; i += m }
    fh.closeFile(); print(String(format: "AM file: %.1f s", Double(n) / fs)); exit(0)
}

// ---------------------------------------------------------------- HackRF capture -> audio band above a line
func bandAbove(_ d: Data, _ rate: Double, _ line: Double) -> ([Float], [Float], Double) {   // complex baseband at rate/dec, the line sits at -12 kHz
    let n = d.count / 2, dec = Int((rate / 100000).rounded()); let orate = rate / Double(dec)
    var re = [Float](repeating: 0, count: n), im = re
    let w = -2 * Double.pi * (line + 12000) / rate
    d.withUnsafeBytes { p in let b = p.bindMemory(to: Int8.self); var ph = 0.0
        for i in 0..<n { let c = Float(cos(ph)), s = Float(sin(ph)); let x = Float(b[2 * i]), y = Float(b[2 * i + 1]); re[i] = x * c - y * s; im[i] = x * s + y * c; ph += w; if ph < -Double.pi { ph += 2 * Double.pi } } }
    let taps = 16 * dec + 1; let fc = 14000.0 / rate; let mid = Double(taps - 1) / 2
    let h: [Float] = (0..<taps).map { let t = Double($0) - mid; let s = t == 0 ? 2 * fc : sin(2 * Double.pi * fc * t) / (Double.pi * t); return Float(s * (0.54 - 0.46 * cos(2 * Double.pi * Double($0) / Double(taps - 1)))) }
    let m = (n - taps) / dec; var ore = [Float](repeating: 0, count: m), oim = ore
    vDSP_desamp(re, vDSP_Stride(dec), h, &ore, vDSP_Length(m), vDSP_Length(taps)); vDSP_desamp(im, vDSP_Stride(dec), h, &oim, vDSP_Length(m), vDSP_Length(taps))
    return (ore, oim, orate) }
func avgSpectrum(_ re: [Float], _ im: [Float], _ N: Int) -> [Float] {                       // power per bin, bin k = frequency k/N*rate (negative above N/2)
    let setup = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(N), .FORWARD)!; var acc = [Float](repeating: 0, count: N)
    let win = (0..<N).map { Float(0.5 - 0.5 * cos(2 * Double.pi * Double($0) / Double(N))) }; var o = 0
    while o + N <= re.count { var a = [Float](repeating: 0, count: N), b = a, fr = a, fi = a
        vDSP_vmul(Array(re[o..<o + N]), 1, win, 1, &a, 1, vDSP_Length(N)); vDSP_vmul(Array(im[o..<o + N]), 1, win, 1, &b, 1, vDSP_Length(N)); vDSP_DFT_Execute(setup, a, b, &fr, &fi)
        for k in 0..<N { acc[k] += fr[k] * fr[k] + fi[k] * fi[k] }; o += N / 2 }
    return acc }
if cmd == "probe" {
    guard args.count >= 6, let rate = Double(args[3]), let line = Double(args[4]), let tone = Double(args[5]) else { die("auxlink probe IN.cs8 RATE LINE_HZ TONE_HZ") }
    let (re, im, orate) = bandAbove(readCS8(args[2]), rate, line); let N = 32768; let sp = avgSpectrum(re, im, N); let bw = orate / Double(N)
    func bin(_ f: Double) -> Int { ((Int((f / bw).rounded()) % N) + N) % N }
    var best: Float = 0, bf = 0.0
    for df in stride(from: -4000.0, through: 4000.0, by: bw) { let v = sp[bin(tone - 12000 + df)]; if v > best { best = v; bf = df } }
    let fl = (0..<N).map { sp[$0] }.sorted()[N / 2]
    let snr: Double = 10 * log10(Double(best / fl)); let nbw: Double = bw * 1.5; let cn0: Double = snr + 10 * log10(nbw)
    print(String(format: "tone %.1f dB over the noise in %.1f Hz = %.1f dB-Hz, line offset %+.0f Hz", snr, nbw, cn0, bf)); exit(0)
}
if cmd == "iq2aud" {
    guard args.count >= 7, let rate = Double(args[3]), let line = Double(args[4]), let tms = Double(args[6]) else { die("auxlink iq2aud IN.cs8 RATE LINE_HZ OUT.f32 T_MS") }
    let (re, im, orate) = bandAbove(readCS8(args[2]), rate, line); let N = 32768; let sp = avgSpectrum(re, im, N); let bw = orate / Double(N); let tones = toneSet(tms)
    func bin(_ f: Double) -> Int { ((Int((f / bw).rounded()) % N) + N) % N }
    var best: Float = 0, d0 = 0.0                                              // the 16 tones form a comb: slide it over the spectrum
    for df in stride(from: -4000.0, through: 4000.0, by: bw) { var s: Float = 0; for f in tones { s += sp[bin(f - 12000 + df)] }; if s > best { best = s; d0 = df } }
    let fl = sp.sorted()[N / 2]
    let tsn: Double = 10 * log10(Double(best / Float(M) / fl))
    print(String(format: "tones found %+.0f Hz from the expected place, %.1f dB over the noise", d0, tsn))
    var out = [Float](repeating: 0, count: re.count); let w = 2 * Double.pi * (12000 - d0) / orate; var ph = 0.0
    for i in 0..<re.count { out[i] = re[i] * Float(cos(ph)) - im[i] * Float(sin(ph)); ph += w; if ph > Double.pi { ph -= 2 * Double.pi } }
    var pk: Float = 0; vDSP_maxmgv(out, 1, &pk, vDSP_Length(out.count)); if pk > 0 { var g = 0.5 / pk; vDSP_vsmul(out, 1, &g, &out, 1, vDSP_Length(out.count)) }
    out.withUnsafeBytes { try! Data($0).write(to: URL(fileURLWithPath: args[5])) }
    print(String(format: "audio written at %.0f Hz", orate)); exit(0)
}

// ---------------------------------------------------------------- receive
guard cmd == "rx", args.count >= 5, let tms = Double(args[4]) else { die("auxlink rx IN.f32 OUT.bin T_MS [RATE]") }
let rate = args.count > 5 ? Double(args[5])! : 96000.0
let tones = toneSet(tms)
let d = try! Data(contentsOf: URL(fileURLWithPath: args[2])); let x = d.withUnsafeBytes { Array($0.bindMemory(to: Float.self)) }
let L = Int(rate * tms / 1000)
var tc = [[Float]](), ts = [[Float]]()
for f in tones { tc.append((0..<L).map { Float(cos(2 * Double.pi * f * Double($0) / rate)) }); ts.append((0..<L).map { Float(sin(2 * Double.pi * f * Double($0) / rate)) }) }
func energies(_ start: Int) -> [Float] {
    var e = [Float](repeating: 0, count: M); if start < 0 || start + L > x.count { return e }
    x.withUnsafeBufferPointer { xp in for k in 0..<M { var re: Float = 0, im: Float = 0
        vDSP_dotpr(xp.baseAddress! + start, 1, tc[k], 1, &re, vDSP_Length(L)); vDSP_dotpr(xp.baseAddress! + start, 1, ts[k], 1, &im, vDSP_Length(L)); e[k] = re * re + im * im } }
    return e }
func seqMetric(_ seq: [Int], _ s0: Double, _ step: Double) -> Float {
    var hit: Float = 0, tot: Float = 0
    for (i, p) in seq.enumerated() { let e = energies(Int((s0 + Double(i) * step).rounded())); hit += e[p]; tot += e.reduce(0, +) }
    return tot > 0 ? hit / tot : 0 }
var best: Float = 0, s0 = 0.0
let searchEnd = min(x.count - (PRE + 4) * L, Int(rate * 8))
var s = 0; while s < searchEnd { let m = seqMetric(preSym, Double(s), Double(L)); if m > best { best = m; s0 = Double(s) }; s += L / 4 }
var fine = s0; for ds in stride(from: -L / 4, through: L / 4, by: max(1, L / 32)) { let m = seqMetric(preSym, s0 + Double(ds), Double(L)); if m > best { best = m; fine = s0 + Double(ds) } }
s0 = fine
print(String(format: "preamble at %.3f s, %.0f %% of the energy on the expected tones (chance: 6 %%)", s0 / rate, best * 100))
if best < 0.12 { print("RESULT no frame found"); exit(1) }
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
let postIdx = Double(PRE + HDRSYM + nsym)
var pbest: Float = 0, pshift = 0.0
for ds in stride(from: -Double(L), through: Double(L), by: Double(max(1, L / 32))) { let m = seqMetric(postSym, s0 + postIdx * Ld + ds, Ld); if m > pbest { pbest = m; pshift = ds } }
if pbest > 0.12 { Ld += pshift / postIdx }
print(String(format: "postamble: %.0f %% on the expected tones, clock difference %+.1f ppm", pbest * 100, (Ld / Double(L) - 1) * 1e6))
var E = [[Float]](); E.reserveCapacity(nsym)
for i in 0..<nsym { E.append(energies(Int((s0 + Double(PRE + HDRSYM + i) * Ld).rounded()))) }
var noise = [Float](repeating: 1, count: M)
for k in 0..<M { let v = E.map { $0[k] }.sorted(); noise[k] = max(v[v.count / 2] / 0.693, 1e-20) }
var soft = [Float](repeating: 0, count: ncoded); var esn: Float = 0
for i in 0..<nsym { let m = (0..<M).map { E[i][$0] / noise[$0] }; esn += m.max()!
    for b in 0..<4 { var m1: Float = 0, m0: Float = 0; for k in 0..<M { if (k >> (3 - b)) & 1 == 1 { m1 = max(m1, m[k]) } else { m0 = max(m0, m[k]) } }
        soft[i * 4 + b] = min(m1, 400) - min(m0, 400) } }
let p = interleaveStride(ncoded); var dil = [Float](repeating: 0, count: ncoded); for i in 0..<ncoded { dil[i] = soft[(i * p) % ncoded] }
let NS = 64; var metric = [Float](repeating: -1e30, count: NS); metric[0] = 0
var prev = [[UInt8]](repeating: [UInt8](repeating: 0, count: NS), count: infoBits)
var outA = [[Int]](repeating: [0, 0], count: NS * 2)
for st in 0..<NS { for b in 0..<2 { let sr = ((st << 1) | b) & 0x7F; outA[st * 2 + b] = [parity(sr & G1), parity(sr & G2)] } }
for t in 0..<infoBits { var nm = [Float](repeating: -1e30, count: NS); let a = dil[2 * t], b2 = dil[2 * t + 1]
    for st in 0..<NS where metric[st] > -1e29 { for b in 0..<2 { let o = outA[st * 2 + b]; let ns = ((st << 1) | b) & 0x3F
        let v = metric[st] + (o[0] == 1 ? a : -a) + (o[1] == 1 ? b2 : -b2)
        if v > nm[ns] { nm[ns] = v; prev[t][ns] = UInt8(st) } } }
    metric = nm }
var st = 0; var bits = [Int](repeating: 0, count: infoBits)
for t in stride(from: infoBits - 1, through: 0, by: -1) { bits[t] = st & 1; st = Int(prev[t][st]) }
var bytes = [UInt8](); for i in 0..<(plen + 4) { var v = 0; for j in 0..<8 { v = v << 1 | bits[i * 8 + j] }; bytes.append(UInt8(v)) }
let payload = Array(bytes[0..<plen]); let got = UInt32(bytes[plen]) | UInt32(bytes[plen + 1]) << 8 | UInt32(bytes[plen + 2]) << 16 | UInt32(bytes[plen + 3]) << 24
let sent = codedSymbols(payload); var wrong = 0
for i in 0..<min(nsym, sent.count) { let m = (0..<M).map { E[i][$0] / noise[$0] }; if m.firstIndex(of: m.max()!)! != sent[i] { wrong += 1 } }
let esn0 = 10 * log10(max(esn / Float(nsym) - 1, 0.01))
let cn0: Double = Double(esn0) + 10 * log10(1000 / tms); let wpct: Double = 100 * Double(wrong) / Double(max(nsym, 1))
print(String(format: "link: symbol energy %.1f dB over the noise, signal strength %.1f dB-Hz, %d of %d symbols wrong before correction (%.1f %%)", Double(esn0), cn0, wrong, nsym, wpct))
try! Data(payload).write(to: URL(fileURLWithPath: args[3]))
print(crc32(payload) == got ? "RESULT ok: \(plen) bytes received, checksum correct (every bit right)" : "RESULT checksum wrong: the data has errors")
