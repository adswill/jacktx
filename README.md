# jacktx

Turn a Mac's headphone jack into a low-power radio transmitter. No extra hardware.

The audio chip's internal clock leaks out of the jack at **6.144 MHz**. Any audio you play is mixed onto that clock, so a tone at *f* Hz appears as a radio signal at 6.144 MHz + *f*. jacktx builds the audio for 16 radio modes so they come out as real signals that an SDR can receive and decode.

At 96 kHz output the usable window is **6.146–6.190 MHz** (about 44 kHz wide). The signal is weak and reaches a few metres at most. The headphone cable acts as the antenna.

## Requirements

- macOS with a built-in headphone jack
- Python 3 (standard library only)
- ffmpeg (`brew install ffmpeg`)
- Xcode command line tools (`xcode-select --install`), to build the small audio helper on first run
- A receiver: any SDR that covers 6 MHz (RTL-SDR V4, HackRF, Airspy HF+ ...) with an antenna near the cable

## Usage

```bash
python3 -I jacktx.py                     # list the modes
python3 -I jacktx.py -sstv               # transmit a mode until Ctrl+C
python3 -I jacktx.py -am --audio song.mp3
python3 -I jacktx.py --selftest          # check every encoder, no sound
```

jacktx always plays on the headphone jack, whatever the system output is, so the speakers can stay selected. It sets the jack to 96 kHz and puts the old rate back when it stops. Keep the jack's volume at 100 %.

| Mode | What it sends | Receive |
|---|---|---|
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

## Notes

6.144 MHz is in the 49 m shortwave broadcast band. The signal is very weak, but you are responsible for what you transmit where you live.

## Licence

GPL-3.0-or-later ([LICENSE](LICENSE)) with one attribution term ([ADDITIONAL-TERMS.md](ADDITIONAL-TERMS.md)): keep the notices and credit jacktx in anything you build from it.

Algorithms and tables used, with credit: WSJT-X by K1JT et al. (FT8, WSPR; GPL-3), ft8_lib by Kārlis Goba (MIT), RS41 framing after rs1729 by Zilog80 (GPL-3), DVB-S2 tables from ETSI EN 302 307.
