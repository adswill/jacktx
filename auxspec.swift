// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// auxspec: live spectrum frames from the headphone jack's input, for the viewer of `jackrx.py auxview`.
//   auxspec UID RATE NFFT FPS     writes NFFT/2 float32 values (dB, 0 dB = full scale sine) per frame to stdout, FPS frames a second
// It never opens the built-in microphone: that device is refused by UID.
import Accelerate
import CoreAudio
import Foundation

func A(_ s: AudioObjectPropertySelector, _ sc: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress { AudioObjectPropertyAddress(mSelector: s, mScope: sc, mElement: kAudioObjectPropertyElementMain) }
func ids(_ o: AudioObjectID, _ s: AudioObjectPropertySelector, _ sc: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> [AudioObjectID] {
    var a = A(s, sc); var sz: UInt32 = 0; guard AudioObjectGetPropertyDataSize(o, &a, 0, nil, &sz) == 0, sz > 0 else { return [] }
    var v = [AudioObjectID](repeating: 0, count: Int(sz) / 4); AudioObjectGetPropertyData(o, &a, 0, nil, &sz, &v); return v }
func str(_ o: AudioObjectID, _ s: AudioObjectPropertySelector) -> String { var a = A(s); var u: Unmanaged<CFString>? = nil; var sz = UInt32(8)
    return AudioObjectGetPropertyData(o, &a, 0, nil, &sz, &u) == 0 ? (u?.takeRetainedValue() as String? ?? "") : "" }
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }

let args = CommandLine.arguments
guard args.count >= 5, let rate = Double(args[2]), let nfft = Int(args[3]), let fps = Double(args[4]), nfft >= 256, nfft & (nfft - 1) == 0 else { die("usage: auxspec UID RATE NFFT FPS") }
if args[1] == "BuiltInMicrophoneDevice" { die("auxspec does not open the built-in microphone") }
let sys = AudioObjectID(kAudioObjectSystemObject)
let inputs = ids(sys, kAudioHardwarePropertyDevices).filter { !ids($0, kAudioDevicePropertyStreams, kAudioObjectPropertyScopeInput).isEmpty }
guard let dev = inputs.first(where: { str($0, kAudioDevicePropertyDeviceUID) == args[1] }) else { die("no input device with UID \(args[1])") }
var r = rate; var ra = A(kAudioDevicePropertyNominalSampleRate)
if AudioObjectSetPropertyData(dev, &ra, 0, nil, UInt32(8), &r) != 0 { die("the device refused \(Int(rate)) Hz") }
usleep(400_000)

final class Ring { var buf = [Float](); let lock = NSLock() }
let ring = Ring()
var procID: AudioDeviceIOProcID? = nil
let st = AudioDeviceCreateIOProcIDWithBlock(&procID, dev, nil) { _, inData, _, _, _ in
    let abl = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inData))
    guard let b = abl.first, let p = b.mData else { return }
    let ch = max(1, Int(b.mNumberChannels)); let n = Int(b.mDataByteSize) / 4 / ch; let f = p.bindMemory(to: Float.self, capacity: n * ch)
    ring.lock.lock(); for i in 0..<n { ring.buf.append(f[i * ch]) }; ring.lock.unlock()
}
guard st == 0, let pid = procID else { die("cannot open the device (\(st))") }
AudioDeviceStart(dev, pid)
signal(SIGPIPE, SIG_IGN)

let setup = vDSP_DFT_zop_CreateSetup(nil, vDSP_Length(nfft), .FORWARD)!
let win = (0..<nfft).map { Float(0.5 - 0.5 * cos(2 * Double.pi * Double($0) / Double(nfft))) }
let hop = nfft / 2, half = nfft / 2
var pending = [Float]()
let zero = [Float](repeating: 0, count: nfft)
let out = FileHandle.standardOutput
while true {
    usleep(useconds_t(1_000_000 / fps))
    ring.lock.lock(); pending += ring.buf; ring.buf.removeAll(keepingCapacity: true); ring.lock.unlock()
    var acc = [Float](repeating: 0, count: half); var n = 0
    while pending.count >= nfft {
        var seg = [Float](repeating: 0, count: nfft); vDSP_vmul(pending, 1, win, 1, &seg, 1, vDSP_Length(nfft))
        var re = [Float](repeating: 0, count: nfft), im = re; vDSP_DFT_Execute(setup, seg, zero, &re, &im)
        for k in 0..<half { acc[k] += re[k] * re[k] + im[k] * im[k] }
        n += 1; pending.removeFirst(hop)
    }
    if n == 0 { continue }
    let scale = Float(n) * Float(nfft) * Float(nfft) / 16          // Hann window, full-scale sine = 0 dB
    var db = [Float](repeating: 0, count: half); for k in 0..<half { db[k] = 10 * log10(acc[k] / scale + 1e-20) }
    let data = db.withUnsafeBytes { Data($0) }
    do { try out.write(contentsOf: data) } catch { exit(0) }
}
