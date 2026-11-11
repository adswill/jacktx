// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// auxin: the headphone jack as an input, when the Mac offers one (a plug with a microphone contact).
//   auxin list                       every input device: uid<TAB>name<TAB>rates<TAB>jack(1/0)
//   auxin rec UID RATE SECONDS OUT   record raw float32 mono (first channel) from that device at RATE
// It never opens the built-in microphone: that device is refused by UID.
import CoreAudio
import Foundation

func A(_ s: AudioObjectPropertySelector, _ sc: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress { AudioObjectPropertyAddress(mSelector: s, mScope: sc, mElement: kAudioObjectPropertyElementMain) }
func ids(_ o: AudioObjectID, _ s: AudioObjectPropertySelector, _ sc: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> [AudioObjectID] {
    var a = A(s, sc); var sz: UInt32 = 0; guard AudioObjectGetPropertyDataSize(o, &a, 0, nil, &sz) == 0, sz > 0 else { return [] }
    var v = [AudioObjectID](repeating: 0, count: Int(sz) / 4); AudioObjectGetPropertyData(o, &a, 0, nil, &sz, &v); return v }
func str(_ o: AudioObjectID, _ s: AudioObjectPropertySelector) -> String { var a = A(s); var u: Unmanaged<CFString>? = nil; var sz = UInt32(8)
    return AudioObjectGetPropertyData(o, &a, 0, nil, &sz, &u) == 0 ? (u?.takeRetainedValue() as String? ?? "") : "" }
func die(_ s: String) -> Never { FileHandle.standardError.write((s + "\n").data(using: .utf8)!); exit(2) }
func rates(_ d: AudioObjectID) -> [Double] { var a = A(kAudioDevicePropertyAvailableNominalSampleRates); var sz: UInt32 = 0
    guard AudioObjectGetPropertyDataSize(d, &a, 0, nil, &sz) == 0 else { return [] }
    var r = [AudioValueRange](repeating: AudioValueRange(), count: Int(sz) / MemoryLayout<AudioValueRange>.size); AudioObjectGetPropertyData(d, &a, 0, nil, &sz, &r)
    return r.map { $0.mMaximum } }
let sys = AudioObjectID(kAudioObjectSystemObject)
let inputs = ids(sys, kAudioHardwarePropertyDevices).filter { !ids($0, kAudioDevicePropertyStreams, kAudioObjectPropertyScopeInput).isEmpty }
let args = CommandLine.arguments
func isJack(_ d: AudioObjectID) -> Bool { let u = str(d, kAudioDevicePropertyDeviceUID); return u.hasPrefix("BuiltIn") && u != "BuiltInMicrophoneDevice" }
if args.count >= 2 && args[1] == "list" {
    for d in inputs { print("\(str(d, kAudioDevicePropertyDeviceUID))\t\(str(d, kAudioObjectPropertyName))\t\(rates(d).map { String(Int($0)) }.joined(separator: " "))\t\(isJack(d) ? 1 : 0)") }
    exit(0)
}
guard args.count >= 6, args[1] == "rec", let rate = Double(args[3]), let secs = Double(args[4]) else { die("usage: auxin list | auxin rec UID RATE SECONDS OUT.f32") }
if args[2] == "BuiltInMicrophoneDevice" { die("auxin does not record the built-in microphone") }
guard let dev = inputs.first(where: { str($0, kAudioDevicePropertyDeviceUID) == args[2] }) else { die("no input device with UID \(args[2])") }
var r = rate; var ra = A(kAudioDevicePropertyNominalSampleRate)
if AudioObjectSetPropertyData(dev, &ra, 0, nil, UInt32(8), &r) != 0 { die("the device refused \(Int(rate)) Hz") }
usleep(400_000)
final class Rec { var data = [Float](); var want = 0 }
let rec = Rec(); rec.want = Int(rate * secs); rec.data.reserveCapacity(rec.want)
var procID: AudioDeviceIOProcID? = nil
let st = AudioDeviceCreateIOProcIDWithBlock(&procID, dev, nil) { _, inData, _, _, _ in
    let abl = UnsafeMutableAudioBufferListPointer(UnsafeMutablePointer(mutating: inData))
    guard let b = abl.first, let p = b.mData else { return }
    let ch = max(1, Int(b.mNumberChannels)); let n = Int(b.mDataByteSize) / 4 / ch; let f = p.bindMemory(to: Float.self, capacity: n * ch)
    for i in 0..<n where rec.data.count < rec.want { rec.data.append(f[i * ch]) }
}
guard st == 0, let pid = procID else { die("cannot open the device (\(st))") }
AudioDeviceStart(dev, pid)
let t0 = Date(); while rec.data.count < rec.want && Date().timeIntervalSince(t0) < secs + 5 { usleep(50_000) }
AudioDeviceStop(dev, pid); AudioDeviceDestroyIOProcID(dev, pid)
rec.data.withUnsafeBytes { try? Data($0).write(to: URL(fileURLWithPath: args[5])) }
print("recorded \(rec.data.count) samples at \(Int(rate)) Hz")
