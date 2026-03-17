# Hardware Reference

> **Work in Progress** — Components listed but not yet tested together.

## Components

| Component | Details | Purpose |
|-----------|---------|---------|
| Raspberry Pi 4 | 4GB/8GB | Runs Klipper, Happy Hare, Moonraker, bridge |
| Fly-ECRF-V2 | RP2040, TMC2209 UART | TradRack stepper drivers (selector + gear) |
| MeanWell 24V PSU | 24V 3.5A (84W) | Powers Fly-ECRF-V2 and TradRack motors |
| 5V Step-Down Converter | 24V → 5V buck converter | Powers Raspberry Pi from 24V rail |
| 5-inch Touchscreen | Pi-compatible DSI/HDMI | KlipperScreen or status display |
| TradRack | 8-slot filament changer | Open-source MMU |
| Binky Encoder | 12-tooth disc encoder PCB | Filament motion sensing (clog detection, homing, flow monitoring) |

## Fly-ECRF-V2 Board

- **MCU**: RP2040 (Raspberry Pi silicon)
- **Stepper drivers**: 2× TMC2209 (UART mode)
- **Communication**: USB
- **Firmware**: Klipper MCU with Katapult bootloader (16KiB offset)

**Wiring and DIP switch documentation:**
https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring

### Pin Mapping

From the official Fly-ECRF-V2 pinout diagram:

| Function | GPIO Pin |
|----------|----------|
| Selector Step | gpio4 |
| Selector Dir | gpio3 |
| Selector Enable | gpio5 |
| Selector UART | gpio2 |
| Selector Diag/Endstop | gpio20 |
| Gear Step | gpio7 |
| Gear Dir | gpio8 |
| Gear Enable | gpio6 |
| Gear UART | gpio9 |
| Gear Diag/Encoder (Binky) | gpio15 |
| Servo | gpio21 |
| Neopixel | gpio14 |

Pins are referenced as RP2040 GPIO numbers (`gpio0`–`gpio29`).

### Binky Encoder Wiring

The Binky encoder PCB connects to the **Gear DIAG header** on the Fly-ECRF-V2 (gpio15). This is a shared pin — both `MMU_GEAR_DIAG` and `MMU_ENCODER` map to gpio15.

- **Signal**: Binky encoder output → gpio15 (Gear DIAG header)
- **Power**: 3.3V and GND from the ECRF-V2 header
- **Resolution**: 1.0 mm/pulse (12-tooth disc with BMG gear circumference)

Happy Hare uses the encoder for gate homing, clog detection, flow rate monitoring, and filament runout detection.

## Wiring Overview

```
                                    ┌─────────────────────┐
  Mains Power ──► Switch ──►       │  MeanWell 24V PSU   │
                                    │  24V 3.5A           │
                                    └────────┬────────────┘
                                             │ 24V
                              ┌──────────────┼──────────────┐
                              │              │              │
                              ▼              ▼              │
                     ┌────────────┐  ┌──────────────────┐  │
                     │ 5V Step-   │  │ Fly-ECRF-V2      │  │
                     │ Down Conv. │  │ XT30 power input  │  │
                     └──────┬─────┘  │ (via custom       │  │
                            │ 5V     │  XT60→XT30 cable) │  │
                            ▼        │                   │  │
                     ┌────────────┐  │  Selector motor  │──► TradRack
                     │ Raspberry  │  │  Gear motor      │──► TradRack
                     │ Pi 4       │  │  Servo           │──► TradRack
                     │            │  └────────┬─────────┘
                     │  5" Screen │           │ USB-C
                     │            │◄──────────┘
                     └────────────┘
```

### Fly-ECRF-V2 to TradRack Connections

```
Fly-ECRF-V2                          TradRack
├── Selector stepper (gpio4/3/5) ─────► Selector NEMA17
├── Gear stepper (gpio7/8/6) ───────► Gear NEMA14
├── Servo (gpio21) ────────────────► Filament grip servo
├── Gear DIAG header (gpio15) ◄─────── Binky encoder PCB
└── Neopixel (gpio14) ─────────────► LED strip (optional)
```

## Power

### Mains Input
- Mains power cable with inline power switch
- Feeds MeanWell 24V PSU

### MeanWell 24V 3.5A PSU
- Input: Mains AC (110/220V)
- Output: 24V DC, 3.5A (84W)
- Powers: Fly-ECRF-V2 (which in turn powers TradRack motors/servo), 5V step-down converter

### 5V Step-Down Converter
- Input: 24V from PSU
- Output: 5V for Raspberry Pi
- Connect to Pi via GPIO header pins or USB-C (check converter output rating — Pi 4 needs 3A at 5V)

## Connections

### Custom XT60 to XT30 Cable
- **XT60 side**: connects to 24V PSU output
- **XT30 side**: plugs into Fly-ECRF-V2 power input
- Use appropriate gauge wire for 3.5A (20AWG minimum recommended)

### USB: Pi → Fly-ECRF-V2
- USB-A (Pi) to USB-C (Fly-ECRF-V2)
- Provides Klipper MCU serial communication
- DIP switches on ECRF-V2 must be set to USB mode (see [Mellow wiring docs](https://mellow.klipper.cn/en/docs/ProductDoc/ToolBoard/fly-ercf/ercfv2/wiring))
- Device shows as `/dev/serial/by-id/usb-Klipper_rp2040_XXXXX-if00`

### Pi 5-inch Screen
- DSI ribbon cable or HDMI (depending on screen model)
- For KlipperScreen UI or bridge status display

## Enclosure

- 3D-printed case housing:
  - Raspberry Pi 4
  - Fly-ECRF-V2
  - 5V step-down converter
  - 5-inch screen (front-mounted)
- MeanWell PSU and mains switch mounted separately or in a larger enclosure
- Ensure ventilation for PSU, Pi, and ECRF-V2 stepper drivers

## TODO

- [ ] Confirm 5V step-down converter model and rated output current
- [ ] Confirm 5-inch screen model (DSI vs HDMI)
- [ ] Design 3D-printed case (dimensions TBD once all parts in hand)
- [ ] Verify XT60→XT30 cable pinout and wire gauge
- [ ] Test full power-up sequence
- [ ] Measure actual current draw under load (motors moving)
- [ ] Add fuse/protection between PSU and components
