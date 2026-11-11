# jacktx

Turn a Mac's headphone jack into a low-power radio transmitter. No extra hardware.

The audio chip's internal clock leaks out of the jack at **6.144 MHz**. Any audio you play is mixed onto that clock, so a tone at *f* Hz appears as a radio signal at 6.144 MHz + *f*. jacktx builds the audio for 16 radio modes so they come out as real signals that an SDR can receive and decode.

At 96 kHz output the usable window is **6.146–6.190 MHz** (about 44 kHz wide). The signal is weak and reaches a few metres at most. The headphone cable acts as the antenna.

## Requirements

- macOS with a built-in headphone jack, or Windows (see [Windows](#windows-and-linux))
- Python 3 (standard library only; numpy is used when installed and makes the receive side much faster)
- ffmpeg (`brew install ffmpeg` on macOS; `ffmpeg.exe` on PATH on Windows)
- macOS: Xcode command line tools (`xcode-select --install`), to build the small audio helper on first run
- A receiver: any SDR that covers 6 MHz (RTL-SDR V4, HackRF, Airspy HF+ ...) with an antenna near the cable
- For `-rx` and `-calibrate`: `rtl_sdr` (rtl-sdr) or `hackrf_transfer` (hackrf) on PATH

## Usage

```bash
python3 -I jacktx.py                     # list the modes
python3 -I jacktx.py -sstv               # transmit a mode until Ctrl+C
python3 -I jacktx.py -am --audio song.mp3
python3 -I jacktx.py -rtty --freq 12.3   # the same mode moved to 12.3 MHz (see the planner below)
python3 -I jacktx.py --selftest          # check every encoder, the planner and the receiver, no sound
```

jacktx always plays on the headphone jack, whatever the system output is, so the speakers can stay selected. It sets the jack to 96 kHz and puts the old rate back when it stops. Keep the jack's volume at 100 %.

| Mode | What it sends | Receive |
|---|---|---|
| `-tone` | Beacon: a carrier keyed in a 3 s pattern | CW/USB, 6.156000 MHz |
| `-am` | Audio file, AM (the clock is the carrier) | AM, 6.144000 MHz, 14 kHz |
| `-nfm` | Audio file, narrow FM | NFM, 6.168000 MHz, 25 kHz |
| `-wfm` | Audio file, wide FM (often too weak) | WFM, 6.168000 MHz, 50 kHz |
| `-usb` | Audio file, single sideband | USB, dial 6.156000 MHz |
| `-rtty` | RTTY text, 45.45 baud, 170 Hz | USB, dial 6.153875 MHz |
| `-sstv` | SSTV colour picture, Martin M1 | USB, dial 6.154000 MHz |
| `-wefax` | Weather fax chart, 120 LPM, IOC 576 | USB, dial 6.154000 MHz |
| `-specart` | A logo painted on the waterfall | Waterfall, 6.163–6.173 MHz |
| `-aprs` | APRS position report | NFM, 6.164000 MHz |
| `-pocsag` | POCSAG pager message, 512 baud | 6.162500 MHz |
| `-ft8` | FT8 CQ, every 15 s slot | USB, dial 6.154500 MHz |
| `-wspr` | WSPR beacon, even minutes | USB, dial 6.154500 MHz |
| `-multi` | AM + RTTY + APRS at once | 6.180 / 6.152 / 6.164 MHz |
| `-noaa` | NOAA APT weather-satellite image | 6.168000 MHz |
| `-sonde` | RS41 radiosonde | 6.159000 MHz |
| `-dvbs2` | DVB-S2 video, QPSK 1/4, 32 ksym/s | 6.168000 MHz (the receiver must accept 32 ksym/s) |

Each mode prints its exact frequency and settings when it starts. The callsigns and positions in the data modes are placeholders (`N0CALL`, `K1ABC`, Greenwich).

All modes decode in [OnAir](https://on-air.dev). Most also work with fldigi, WSJT-X, QSSTV and other standard decoders.

Options:

- `--audio FILE`: the file for the audio modes (anything ffmpeg reads).
- `--level DB`: peak level in dBFS (default -1).
- `--render-only`: write the WAV to `cache/` without playing it.
- `--freq MHZ`: put the mode on another frequency (below). The frequency is the one the table shows: the carrier or centre, or the USB dial for the SSB-style modes.
- `--tol KHZ`: how far from `--freq` it may land (default 10).
- `--wav FILE`: a WAV for `-am`/`-nfm`/`-wfm`/`-usb`, or alone to send the file as it is.
- `--iq FILE`: send a complex baseband recording (below).
- `--clock MHZ`: the clock frequency to print in the tune lines (default 6.144).
- `--device NAME`: play to a named device (Windows/Linux; needs `sounddevice` on Windows, or an ALSA device name for `aplay`). `--device list` shows the devices.
- `-find`: a sweep to locate the clock line (see below).

## Frequency planner: `--freq`

The jack only radiates next to its clock lines, so not every frequency can be reached. jacktx models where it can:

- **Two clocks.** The 48 kHz family (48 / 96 / 192 kHz output) runs the DAC from 6.144 MHz. The 44.1 kHz family (44.1 / 88.2 / 176.4 kHz) very likely runs from 5.6448 MHz. jacktx switches the jack to the rate it needs (macOS, through the CoreAudio helper) and puts the old rate back afterwards.
- **Windows.** Audio at *f* appears at line ± *f*, for *f* from 2 kHz up to about 0.479 x the output rate: 2-46 kHz at 96 kHz (measured), up to 92 kHz at 192 kHz (modelled).
- **Both images.** For the lower image the audio is spectrum-inverted, so the wanted signal is upright on the air (USB stays USB, FSK mark stays on top). The other image is the inverted mirror, so ignore it.
- **Harmonics.** 12.288, 18.432 and 24.576 MHz (and 11.29, 16.93 and 22.58 MHz) may carry the signal too, more weakly. They are modelled as line ± *f* until `-calibrate` has measured them.

For a requested frequency the planner picks the rate, line, image and audio offset (fundamental first, then 96 kHz first), and prints the expected accuracy. It also checks the mode's bandwidth: NFM needs 28 kHz, so a 96 kHz window that fits a tone may be too small for it. If nothing reaches the frequency within `--tol`, it says so, prints the nearest reachable frequencies on both sides, and does not transmit.

```bash
python3 -I jacktx.py --coverage                 # every reachable window from 1 to 25 MHz
python3 -I jacktx.py -ft8 --freq 12.3 --plan    # show the plan only
python3 -I jacktx.py -ft8 --freq 12.3           # FT8, USB dial 12.300 MHz (2nd harmonic, 12 kHz audio)
python3 -I jacktx.py -tone --freq 6.135         # lower image of 6.144 MHz
python3 -I jacktx.py -am --freq 12.288 --audio song.mp3   # on a line: that line is the carrier
```

Honest limits:

- About 1.4 MHz of the 1-25 MHz range can be reached, in 16 windows of 80-90 kHz each, from 5.56 to 24.67 MHz. **Nothing below about 5.56 MHz can be reached**, and neither can the gaps between the windows (for example 6.24-11.20 MHz).
- Rates other than 96 kHz, the 44.1 kHz clock and all harmonics are a model until you measure them. A harmonic can be too weak to use, or missing.
- Uncalibrated, the planner assumes the crystal is within 50 ppm: +-0.3 kHz at 6 MHz and +-1.2 kHz at 24.6 MHz, well inside 10 kHz. `--ppm X` applies a known correction, and `-calibrate` measures it.
- The wide modes leave little room: WFM (44 kHz) fits the 96 kHz window at one point only (6.168 MHz and the same spot at the other lines), and gets more room at 192 kHz. DVB-S2 and `-multi` are similar.

## Calibration and receiving with an SDR

Receiving uses an SDR only: `rtl_sdr` (RTL-SDR; a V4 tunes HF directly, older dongles need direct sampling, e.g. `--sdr-args "-D 2"`) or `hackrf_transfer`. Put the antenna near the headphone cable.

```bash
python3 -I jacktx.py -calibrate                       # transmits a tone pattern at each rate, measures every line
python3 -I jacktx.py -calibrate --rates 96000 --harmonics 1,2
python3 -I jacktx.py -rx tone                         # run -tone on the Mac, check it here
python3 -I jacktx.py -rx rtty --freq 12.3             # decode -rtty --freq 12.3 (text to the terminal)
python3 -I jacktx.py -rx nfm --out nfm.wav            # demodulate -nfm to a WAV (also: -rx am)
```

- `-calibrate` plays a pattern of 4-8 tones spread over the window and records each line with the SDR. It finds the pattern by its symmetric pairs (line ± *f*) and measures the line to a fraction of a hertz, the ppm, whether offsets scale with the harmonic, and how high the window reaches. It saves the results per device, rate and harmonic to `~/.jacktx/calibration.json`, or to `jacktx-calibration.json` next to the script if that file exists, or to `--cal FILE`. A line the SDR could not find is stored as absent, and the planner then never uses it. The result is only as accurate as the SDR's own clock: `--sdr-tol PPM` (default 3 for an RTL-SDR V4 TCXO, 20 for a HackRF) is added to the stated accuracy, and `--sdr-ppm X` corrects a known SDR error.
- `-rx tone` reports the strongest line near the expected frequency, its offset and SNR, and whether it carries the `-tone` beacon pattern. `-rx rtty` finds the tone pair itself (it copes with an uncalibrated clock), tries both polarities, and prints the text. `-rx am` and `-rx nfm` write 48 kHz WAVs.
- `--freq` means the same as on the transmit side, so give `-rx` the same value you gave the transmitter. Options: `--sdr rtl|hackrf`, `--gain DB` (HackRF `LNA,VGA`, default `24,20`, `--amp` for the amplifier), `--seconds S`, `--rx-rate HZ`, `--sdr-args "..."`.
- Every receive and calibration step also works on a recording: `--from-file FILE` with `--rx-rate HZ --rx-center MHZ` (or a SigMF file that carries both), for example `python3 -I jacktx.py -rx rtty --freq 12.3 --from-file cap.cu8 --rx-rate 2400000 --rx-center 12.05`. `-calibrate --from-file ... --cal-rate 96000 --harmonic 2 --save` stores the result of a recording.
- Without numpy the receiver uses plain Python and records at a lower rate (0.96 Msps RTL-SDR, 2 Msps HackRF). It works, but slowly: about 0.4 s of processing per second recorded.

## Custom signals: `--iq` and `--wav`

- `--iq FILE` sends a complex baseband recording: `.cu8`, `.cs8`, `.cs16`, `.cf32` (`.iq` and `.raw` are taken as cf32; `--iq-format` overrides), `.sigmf-data` with its `.sigmf-meta`, or a 2-channel WAV (I left, Q right). Raw files need `--iq-rate HZ`. jacktx measures the occupied bandwidth (99 % of the power), or takes `--iq-band LO,HI` in kHz. It resamples the band to the output rate, filters it, and moves it so the recording's 0 Hz comes out at `--freq`, upright on either image. A recording wider than the widest window is cut to it, with a warning.
- `--wav FILE` alone sends the audio unchanged: *f* Hz appears at line ± *f*. With `--freq` it is moved like SSB, so its 0 Hz lands at that frequency. With `-am`, `-nfm`, `-wfm` or `-usb` the WAV is the programme audio.
- Bad input fails with a clear message: unknown format, odd file size, missing sample rate, a 1-channel WAV given as IQ, unsupported WAV encodings.

## Windows and Linux

Requirements: Python 3 and ffmpeg on PATH. Playback uses `winsound` from the standard library on the default output device, or `aplay` on Linux.

- Python cannot set the sample rate here. Set the output device to **96000 Hz** (Settings, Sound, the device, Advanced, Default Format) and make the headphone jack the default output while transmitting. jacktx prints this reminder.
- Optional: `pip install sounddevice`, then `--device NAME` plays to that device and the speakers can stay the default.
- Whether a PC leaks its clock, and at which frequency, depends on the audio chip. 6.144 MHz is the Apple silicon value. Run `python3 -I jacktx.py -find`: it plays a slow 2-40 kHz sweep with a beep at the start of each sweep, and prints candidate clocks. Scan 1-30 MHz with an SDR for a line that moves in step, then pass its centre with `--clock MHZ`, for example `--clock 12.288`.
- Every printed tune line then uses that clock. The frequencies in the mode table above are for 6.144 MHz.
- `--freq` works the same way: the planner tells you which rate to set (Python cannot set it here). `-calibrate` needs `--cal-rate HZ` set to the device's rate, and plays the pattern on the default output.

## Notes

6.144 MHz is in the 49 m shortwave broadcast band. The signal is very weak, but you are responsible for what you transmit where you live.

## Licence

GPL-3.0-or-later ([LICENSE](LICENSE)) with one attribution term ([ADDITIONAL-TERMS.md](ADDITIONAL-TERMS.md)): keep the notices and credit jacktx in anything you build from it.

Algorithms and tables used, with credit: WSJT-X by K1JT et al. (FT8, WSPR; GPL-3), ft8_lib by Kārlis Goba (MIT), RS41 framing after rs1729 by Zilog80 (GPL-3), DVB-S2 tables from ETSI EN 302 307.
