# Noise Catcher — Bill of Materials

## Core Hardware

| # | Item | Model / Spec | Qty | Unit | Total | Purpose |
|---|------|-------------|-----|------|-------|---------|
| 1 | Single-board computer | **Raspberry Pi 4B 1 GB** | 1 | ~$35 | $35 | Runs capture daemon 24/7. Quad-core Cortex-A72 @ 1.5 GHz, 1 GB RAM, WiFi 5, Bluetooth 5.0, Gigabit Ethernet. ~3.5W idle. Full-size USB-A ports — no dongles needed. |
| 2 | MicroSD card | **SanDisk Extreme 32 GB** (U3/V30/A1) | 1 | ~$12 | $12 | OS + SQLite storage. 32 GB = ~6 months of raw 1s data. A1 rating for random write performance. |
| 3 | USB power supply | **5V 2.5A** (official Pi PSU or Anker PowerPort) | 1 | ~$10 | $10 | Stable power for 24/7 operation. Avoid cheap chargers — voltage sag causes SD corruption. |
| 4 | Calibrated measurement mic | **miniDSP UMIK-1** | 1 | ~$79 | $79 | USB condenser mic with individual calibration file. ±1 dB accuracy from 20 Hz–20 kHz. Ships with unique serial-matched frequency response data. Industry standard for hobbyist acoustic measurement. |
| 5 | USB OTG adapter | **Micro-USB male → USB-A female** | — | — | — | Not needed with Pi 4B (full-size USB-A ports). Only required if using Pi Zero 2 W alternative. |
| 6 | Active USB extension cable | **USB 3.0 active repeater, 5–10 m** | 1 | ~$15 | $15 | Lets you place the mic at the window while keeping the Pi indoors. Active (powered) cable avoids signal degradation over distance. Passive cables >3m are unreliable for USB audio. |

**Core total: ~$151**

---

## Enclosure & Weather Protection

| # | Item | Model / Spec | Qty | Unit | Total | Purpose |
|---|------|-------------|-----|------|-------|---------|
| 7 | Pi case | **Official Pi 4 case** or **Argon ONE** | 1 | ~$10 | $10 | Basic physical protection. Argon ONE acts as a passive heatsink — recommended for 24/7 operation in warm rooms. |
| 8 | Mic outdoor enclosure | **Small IP65 junction box** (~100×100×70 mm) | 1 | ~$8 | $8 | Protects the UMIK-1 body from rain/condensation. Drill a hole for the mic capsule to protrude, seal with silicone. |
| 9 | Foam windscreen | **Generic lavalier mic foam**, or cut from **open-cell acoustic foam** | 1 | ~$5 | $5 | Reduces wind noise on the mic capsule. Critical — even a light breeze across an unprotected mic reads as 40–60 dB of false noise. |
| 10 | Silicone sealant | **Clear RTV silicone**, small tube | 1 | ~$5 | $5 | Seals enclosure joints and cable entry against moisture. |
| 11 | Cable clips / adhesive mounts | **3M Command outdoor cable clips** | 1 pack | ~$6 | $6 | Route the USB extension neatly along the window frame. |

**Enclosure total: ~$34**

---

## Optional / Nice-to-Have

| # | Item | Model / Spec | Qty | Unit | Total | Purpose |
|---|------|-------------|-----|------|-------|---------|
| 12 | Spare microSD | Same as #2 | 1 | ~$12 | $12 | Rotate cards for backups. SD cards in continuous-write scenarios have limited lifespan. |
| — | GPIO header | Already on Pi 4B | — | — | — | Pi 4B ships with GPIO headers pre-soldered. |

---

## Grand Total

| Tier | Cost |
|------|------|
| Core hardware | $151 |
| Enclosure & weather | $34 |
| Optional | $12 |
| **All-in** | **~$197** |
| **Minimum viable** (skip optional) | **~$185** |

---

## Availability Notes

- **Raspberry Pi 4B 1 GB** is the recommended board — generally in stock, full-size USB-A, Gigabit Ethernet fallback. Retailers: PiShop.us, Adafruit, SparkFun, Amazon. Alternatives in priority order:
  1. **Raspberry Pi 3A+** (~$25) — cheaper, fanless, full-size USB-A, no Ethernet. Works if WiFi is reliable.
  2. **Raspberry Pi Zero 2 W** (~$25) — smallest and lowest power, but needs a micro-USB OTG adapter for the UMIK-1. Stock is spotty.
  3. **Radxa Zero 3W** (~$25) — similar to Zero 2 W, competitive stock.

- **UMIK-1** ships from miniDSP directly (Hong Kong) or via Amazon/Deer Creek Audio (US). Lead time: 1–2 weeks. Each unit includes a unique `.cal` text file — **do not lose this**. Download it from miniDSP's site by serial number as a backup.

- **Active USB extension**: the "Cable Matters Active USB 3.0 Extension 10m" is reliable. Cheaper "active" cables sometimes drop the USB 1.1 audio stream. Test before mounting permanently.

---

## Assembly Checklist

1. Flash Raspberry Pi OS Lite (64-bit) to microSD — use Raspberry Pi Imager, enable SSH + WiFi in settings.
2. Boot Pi, `ssh pi@noisecatcher.local`, run `apt update && apt full-upgrade`.
3. Plug UMIK-1 directly into a USB-A port, verify: `arecord -l` should list "UMIK-1".
4. Record a test clip: `arecord -D plughw:1 -f S24_3LE -r 48000 -d 10 test.wav`.
5. Drill enclosure: hole for mic capsule, cable gland for USB, small drain hole at bottom.
6. Mount mic in enclosure with foam windscreen, seal with silicone.
7. Route USB extension from Pi (indoors) to mic enclosure (window).
8. Secure cables with clips.
