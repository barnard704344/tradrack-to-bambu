# Hardware Reference

> **Work in Progress** — Components listed but not yet tested together.

## Components

| Component | Details | Purpose |
|-----------|---------|---------|
| Raspberry Pi 4 | 4GB/8GB | Runs Klipper, Happy Hare, Moonraker, bridge |
| Fly-ECRF-V2 | STM32F072, TMC2209 UART | TradRack stepper drivers (selector + gear) |
| MeanWell 24V PSU | 24V 3.5A (84W) | Powers Fly-ECRF-V2 and TradRack motors |
| 5V Step-Down Converter | 24V → 5V buck converter | Powers Raspberry Pi from 24V rail |
| 5-inch Touchscreen | Pi-compatible DSI/HDMI | KlipperScreen or status display |
| TradRack | 8-slot filament changer | Open-source MMU |

## Wiring Overview

```
                                    ┌─────────────────────┐
  Mains Power ──► Switch ──►       │  MeanWell 24V PSU   │
                                    │  24V 3.5A           │
                                    └────────┬────────────┘
                                             │ 24V
                              ┌──────────────┼──────────────┐
                              │              │
                              ▼              ▼
                     ┌────────────┐  ┌──────────────────┐
                     │ 5V Step-   │  │ Fly-ECRF-V2      │
                     │ Down Conv. │  │ XT30 power input  │
                     └──────┬─────┘  │ (via custom       │
                            │ 5V     │  XT60→XT30 cable) │
                            ▼        │                  │
                     ┌────────────┐  │  Selector motor  │──► TradRack
                     │ Raspberry  │  │  Gear motor      │──► TradRack
                     │ Pi 4       │  │  Servo           │──► TradRack
                     │            │  └────────┬─────────┘
                     │  5" Screen │           │ USB
                     │            │◄──────────┘
                     └────────────┘
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
- USB-A (Pi) to USB-C/Micro (Fly-ECRF-V2)
- Provides Klipper MCU serial communication
- Device shows as `/dev/serial/by-id/usb-Klipper_stm32f072_XXXXX-if00`

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
