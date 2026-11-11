// jacksim IN.wav OUT.cs8 LINE_HZ NOISE: put a 96 kHz stereo WAV beside a radio line as the jack does (carrier + both sidebands), 2 Msps cs8, with noise
import Foundation
let a = CommandLine.arguments
let wd = try! Data(contentsOf: URL(fileURLWithPath: a[1])); let line = Double(a[3])!, nz = Double(a[4])!
let s: [Double] = wd.withUnsafeBytes { p in let q = p.baseAddress!.advanced(by: 44).assumingMemoryBound(to: Int16.self); return stride(from: 0, to: (wd.count - 44) / 2, by: 2).map { Double(q[$0]) / 32768 } }
let fs = 2_000_000.0; let lead = Int(fs * 0.8); let n = Int(Double(s.count - 1) * fs / 96000) + lead
FileManager.default.createFile(atPath: a[2], contents: nil); let fh = FileHandle(forWritingAtPath: a[2])!
var g = SystemRandomNumberGenerator(); func gauss() -> Double { let u = Double.random(in: 1e-12..<1, using: &g), v = Double.random(in: 0..<1, using: &g); return (-2 * log(u)).squareRoot() * cos(2 * Double.pi * v) }
var i = 0; let w = 2 * Double.pi * line / fs
while i < n { let m = min(1 << 20, n - i); var buf = [Int8](repeating: 0, count: m * 2)
    for j in 0..<m { let t = i + j; var au = 0.0; if t >= lead { let p = Double(t - lead) * 96000 / fs; let k = Int(p); au = s[k] + (s[k + 1] - s[k]) * (p - Double(k)) }
        let amp = 6.0 * (0.4 + au); let ph = w * Double(t)
        buf[2 * j] = Int8(max(-127, min(127, amp * cos(ph) + nz * gauss()))); buf[2 * j + 1] = Int8(max(-127, min(127, amp * sin(ph) + nz * gauss()))) }
    buf.withUnsafeBytes { fh.write(Data($0)) }; i += m }
fh.closeFile()
