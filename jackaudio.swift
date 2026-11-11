// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Kristijonas Adomaitis. Part of jacktx - https://github.com/adswill/jacktx
// Tiny CoreAudio helper for jacktx.py. It always uses the built-in headphone jack (UID BuiltInHeadphoneOutputDevice),
// whatever the system output is, so the speakers (or a recorder) can stay the default output.
//   jackaudio info        -> prints: name<TAB>present(1/0)<TAB>rate<TAB>volume(0..1)
//   jackaudio set RATE    -> sets the jack's nominal sample rate, prints: status<TAB>rate now
//   jackaudio play FILE   -> plays a WAV once on the jack, returns when it has finished
//   jackaudio rates       -> the nominal sample rates the jack offers, space separated (e.g. 44100 48000 88200 96000)
import AVFoundation
import CoreAudio
import Foundation

func addr(_ sel: AudioObjectPropertySelector, _ scope: AudioObjectPropertyScope = kAudioObjectPropertyScopeGlobal) -> AudioObjectPropertyAddress {
    AudioObjectPropertyAddress(mSelector: sel, mScope: scope, mElement: kAudioObjectPropertyElementMain)
}

func jackDevice() -> AudioDeviceID? {
    var a = addr(kAudioHardwarePropertyDevices); var sz: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &sz)
    var ids = [AudioObjectID](repeating: 0, count: Int(sz) / MemoryLayout<AudioObjectID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &a, 0, nil, &sz, &ids)
    for id in ids {
        var ua = addr(kAudioDevicePropertyDeviceUID); var uid: Unmanaged<CFString>? = nil; var s = UInt32(MemoryLayout<CFString?>.size)
        if AudioObjectGetPropertyData(id, &ua, 0, nil, &s, &uid) == 0, let u = uid?.takeRetainedValue() as String?, u == "BuiltInHeadphoneOutputDevice" { return id }
    }
    return nil
}

func rate(_ dev: AudioDeviceID) -> Double {
    var r = 0.0; var s = UInt32(MemoryLayout<Double>.size); var p = addr(kAudioDevicePropertyNominalSampleRate)
    AudioObjectGetPropertyData(dev, &p, 0, nil, &s, &r); return r
}

let args = CommandLine.arguments
guard let dev = jackDevice() else {
    if args.count >= 2 && args[1] == "info" { print("none\t0\t0\t0"); exit(0) }
    if args.count >= 2 && args[1] == "rates" { print(""); exit(0) }
    FileHandle.standardError.write("the headphone jack is not available: is the cable plugged in?\n".data(using: .utf8)!); exit(3)
}

if args.count >= 2 && args[1] == "rates" {
    var a = addr(kAudioDevicePropertyAvailableNominalSampleRates); var sz: UInt32 = 0
    AudioObjectGetPropertyDataSize(dev, &a, 0, nil, &sz)
    var ranges = [AudioValueRange](repeating: AudioValueRange(), count: Int(sz) / MemoryLayout<AudioValueRange>.size)
    AudioObjectGetPropertyData(dev, &a, 0, nil, &sz, &ranges)
    var out: [Int] = []
    for r in ranges {                                  // discrete rates come as min == max; a continuous range offers the standard ones in it
        for s in [44100.0, 48000, 88200, 96000, 176400, 192000] where s >= r.mMinimum && s <= r.mMaximum && !out.contains(Int(s)) { out.append(Int(s)) }
    }
    print(out.sorted().map(String.init).joined(separator: " "))
} else if args.count >= 3 && args[1] == "set" {
    var r = Double(args[2]) ?? 96000; var p = addr(kAudioDevicePropertyNominalSampleRate)
    let st = AudioObjectSetPropertyData(dev, &p, 0, nil, UInt32(MemoryLayout<Double>.size), &r)
    usleep(200000)
    print("\(st)\t\(Int(rate(dev)))")
} else if args.count >= 3 && args[1] == "play" {
    let engine = AVAudioEngine()
    var d = dev
    guard let au = engine.outputNode.audioUnit,
          AudioUnitSetProperty(au, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &d, UInt32(MemoryLayout<AudioDeviceID>.size)) == 0 else {
        FileHandle.standardError.write("could not route the player to the headphone jack\n".data(using: .utf8)!); exit(4)
    }
    do {
        let file = try AVAudioFile(forReading: URL(fileURLWithPath: args[2]))
        let player = AVAudioPlayerNode()
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: file.processingFormat)
        engine.mainMixerNode.outputVolume = 1.0
        try engine.start()
        var done = false
        player.scheduleFile(file, at: nil, completionCallbackType: .dataPlayedBack) { _ in done = true }
        player.play()
        signal(SIGTERM) { _ in exit(0) }
        while !done { usleep(20000) }
        engine.stop()
    } catch {
        FileHandle.standardError.write("play failed: \(error)\n".data(using: .utf8)!); exit(5)
    }
} else {
    var vol: Float32 = 1; var s = UInt32(MemoryLayout<Float32>.size)
    var p = addr(kAudioHardwareServiceDeviceProperty_VirtualMainVolume, kAudioDevicePropertyScopeOutput)
    AudioObjectGetPropertyData(dev, &p, 0, nil, &s, &vol)
    print("External Headphones\t1\t\(Int(rate(dev)))\t\(vol)")
}
