# Wide signals from the headphone jack: what was measured

Measured 2026-11-11 on a MacBook Pro (codec CS42L84), a plain 3-pole aux cable in the jack with its far end free, and a
HackRF Pro a short distance away (its own antenna, not touching the cable). Everything below is a measurement unless it
says otherwise. The HackRF antenna position was not changed, so absolute levels are low; only slow, narrow signals decode
at that distance.

## 1. How the jack radiates

- While audio plays, the cable carries a **comb of lines every 512 kHz** (12.288 MHz / 24), seen from 6 MHz to beyond
  80 MHz. The old "6.144 MHz clock line" is one tooth of it. With silence playing, only every second tooth (1.024 MHz)
  is present, weaker.
- Strongest teeth at this antenna (30 Hz bins, over the noise): 18.432 MHz +39 dB, 67.584 MHz +26 dB, 73.728 MHz +25 dB,
  36.864 MHz +22 dB, 61.44 MHz +22 dB. 6.144 MHz itself: +11 dB (the antenna is poor at HF).
- **Each tooth is switched by the sign of the audio**, not multiplied by it. A 1 kHz sine gives sidebands at 1, 3, 5, 7,
  9 and 11 kHz with levels 30.5, 23.0, 17.8, 15.2, 12.8 and 11.6 dB over the noise: the 1/n ladder of a square wave,
  with no even harmonics. So the RF is `tooth x (c + m x sign(audio))`.
- A switch has sharp edges, so its sidebands are not limited to the 48 kHz of the audio path.

## 2. How wide it gets

One 40 kHz sine at full scale, 12 s capture, 1.9 Hz bins, lower side of the 18.432 MHz tooth (dB over noise):

| copy k | offset | level | ideal square wave (relative to k = 1) | measured (relative) |
|---|---|---|---|---|
| 1 | 40 kHz | +39.7 | 0 | 0 |
| 3 | 120 kHz | +27.6 | -9.5 | -12.1 |
| 5 | 200 kHz | +22.2 | -14.0 | -17.5 |
| 7 | 280 kHz | +15.8 | -16.9 | -23.9 |
| 9 | 360 kHz | +12.7 | -19.1 | -27.0 |
| 11 | 440 kHz | +9.2 | -20.8 | -30.5 |
| 13 | 520 kHz | +3.2 | -22.3 | -36.5 |

- Sidebands are detected out to **440 kHz** clearly and **520 kHz** marginally: about **0.9 to 1.0 MHz of occupied
  width** around one tooth, from a single audio tone. The next tooth is 512 kHz away and does the same, so the teeth's
  sidebands meet: the emission is continuous across the spectrum, not islands of 96 kHz.
- The ladder falls faster than 1/k above about 250 kHz, so the switch edge takes on the order of 1 to 2 microseconds.
  That is the physical limit of this mechanism: roughly 1 MHz per tooth.
- The upper side of the tooth is weaker than the lower side for small k (the switch changes phase as well as
  amplitude). Use the lower side.

## 3. Information in the wide part (zero-crossing keying)

`lab/zck.py` keys the audio frequency between 37 and 44 kHz. The k-th copy is then a frequency-shift signal k times as
wide (37k / 44k kHz from the tooth). The text "JACKTX WIDE 1 MHZ" was sent at 15.3 bit/s and read back from the HackRF
capture, each copy alone:

| copy used | distance from the tooth | bit errors of 176 |
|---|---|---|
| k = 1 | 37 / 44 kHz | 0 |
| k = 3 | 111 / 132 kHz | 0 |
| k = 5 | 185 / 220 kHz | 10 (5.7 %) |
| k = 7 | 259 / 308 kHz | 45 (26 %) |
| k >= 9 | beyond 333 kHz | not readable at this distance |

So the message is recovered without error from signal energy that lies entirely more than 100 kHz from the tooth.

With coherent detection (`zck.py rxc`, one matched integration per symbol; same antenna position, a second capture):

| copies used | bit errors of 176 |
|---|---|
| k = 5 alone (185 / 220 kHz) | 3 (1.7 %) |
| k = 7 alone (259 / 308 kHz) | 7 (4.0 %) |
| only beyond 111 kHz (k >= 3) | 0 |
| only beyond 185 kHz (k >= 5) | 2 (1.1 %) |
| only beyond 259 kHz (k >= 7) | 8 (4.5 %) |
| only beyond 333 kHz (k >= 9) | 31 (18 %) |

Slower symbols reach further (same antenna position, coherent detection, bit errors of 176):

| copies used | 15.3 bit/s | 7.6 bit/s | 3.8 bit/s |
|---|---|---|---|
| only beyond 185 kHz (k >= 5) | 2 | 0 | 0 |
| only beyond 259 kHz (k >= 7) | 8 | 0 | 0 |
| only beyond 333 kHz (k >= 9) | 31 | 9 | 3 |
| k = 9 alone (333 / 396 kHz) | 41 | 14 | 0 |
| k = 11 alone (407 / 484 kHz) | 48 | 29 | 15 |

So at this antenna distance the message is read without error from energy that lies entirely beyond 259 kHz on the
lower side of the tooth, and with 98 % of bits right from energy beyond 333 kHz: a decodable signal 600 to 800 kHz wide
counting both sides. The copy at 407 to 484 kHz reads at 91 % at 3.8 bit/s. In the 3.8 bit/s run the innermost copy
(k = 1) had 5 errors while k = 9 had none: a narrow interferer near 18.39 MHz is the likely cause (not checked).
The picture `wideband-proof.png` shows the spectrum with the tone on and off.

## 3b. A sweep across 900 kHz

`lab/sweep900.py` steps one emission across 900 kHz in 10 kHz steps (91 steps of 1 s) around 73.728 MHz, where three
neighbouring teeth (73.216, 73.728, 74.240 MHz) are all strong. For each step it picks the nearest tooth and the smallest
odd k with k x f equal to the distance (f between 15 and 45 kHz, k up to 7), so the chosen copy lands on the step.
The HackRF capture (2 Msps, centre 73.95 MHz) is then checked at every step: the strongest 1.25 Hz bin within 40 Hz of
the expected frequency, against the same measurement 400 Hz to the side.

- Detected at **91 of 91 steps**. Signal +17.6 to +43 dB over the mean noise; the control stays below +8.6 dB for 95 %
  of the steps (one control point reached +16.9 dB, a spur).
- By copy: k = 1 median +41 dB, k = 3 +33 dB, k = 5 +27 dB, k = 7 +23 dB.
- Picture: `sweep900-proof.png`; numbers: `sweep900.csv`.

This shows a controlled, narrow emission can be placed anywhere in a 900 kHz span. It is a stepped tone, not a filled
block: with frequency-hopping audio (a filled block) the floor rose by less than 0.5 dB at this antenna distance, which
is within the drift between two captures.

## 4. What this is and what it is not

- It is a real, deterministic, data-bearing emission about 1 MHz wide per tooth, made with nothing but audio samples.
- It is **not** 1 MHz of independent bandwidth. The audio path still has 48 kHz, so all copies carry the same
  information: a spread (redundant) signal. The gain is robustness and reach, like any spread-spectrum signal, and the
  receiver can add the copies (and the same copies on other teeth) together.
- The edges of the switch can be placed with much finer timing than one audio sample, so pulse-position signalling with
  sub-microsecond steps is possible in principle. That would use the width for data rate. It needs a signal about
  30 dB stronger than here (antenna against the cable, or a direct connection) and was not tried.
- Not possible from the jack: an arbitrary 1 MHz-wide waveform (for example DVB-S2 at 1 Msym/s). The audio path has
  96 000 samples a second; no arrangement of them defines a million independent values a second.

## 5. Tried and ruled out

- A constant (DC) level does not move any line: no frequency-tunable emission was found.
- Full-scale noise, intersample-over patterns and square waves do not raise the broadband floor measurably.
- The noise floor between teeth does not follow the audio envelope (less than 0.15 dB at 100 Hz for a 50 Hz sine).
- The jack offers only 44.1, 48, 88.2 and 96 kHz; there is no hidden faster format.

## 6. Next steps

1. Put the receiving antenna against the cable (or clip it to the far plug's sleeve) and repeat `lab/zck.py`: every
   10 dB of signal moves the readable limit out by about two copies.
2. Add copy-combining across teeth (17.92, 18.432, 18.944 MHz carry the same signal) for another few dB.
3. Try pulse-position keying once the signal is strong enough.

## Reproduce

```bash
python3 lab/zck.py tx zck.wav "JACKTX WIDE 1 MHZ"
hackrf_transfer -r zck.cs8 -f 18700000 -s 2000000 -n 34000000 -l 32 -g 30 -a 1 &
cache/jackaudio play zck.wav
lab/bin/labdsp psd --rate 2e6 --nfft 32768 --seg 0.016384 --in zck.cs8 --out zck.sg
python3 lab/zck.py rx zck.sg "JACKTX WIDE 1 MHZ"
```
