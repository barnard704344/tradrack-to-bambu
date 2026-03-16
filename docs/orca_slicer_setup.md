# Orca Slicer Configuration for TradRack-to-Bambu Bridge

This guide configures Orca Slicer's P1S printer profile to work with the
TradRack MMU instead of the Bambu AMS. The only change needed is in the
**"Change filament G-code"** field — everything else stays as Bambu's defaults.

**No manual G-code processing required.** Slice → send to P1S → bridge handles it.

## How It Works

1. Orca Slicer's **"Change filament G-code"** replaces the Bambu AMS command
   (`M620`) with M600 + a comment identifying the target tool
2. You send the G-code to the P1S from Orca Slicer as normal
3. The bridge auto-fetches the G-code from the P1S when a print starts
4. The bridge scans it for the tool-change sequence
5. When the P1S hits M600 and pauses, the bridge triggers Happy Hare

## Printer Profile Setup

Start from the stock **Bambu Lab P1S 0.4 nozzle** profile in Orca Slicer.
We only modify the **Change filament G-code** field.

### Machine G-code Tab

#### Machine start G-code — NO CHANGES

Keep Bambu's default P1S start G-code as-is:

```gcode
;===== machine: P1S-0.4 ==========================
;===== date: 20250822 ==========================
;===== turn on the HB fan & MC board fan ====================
M104 S75 ;set extruder temp to turn on the HB fan and prevent filament oozing from nozzle
M710 A1 S255 ;turn on MC fan by default(P1S)
;===== reset machine status =================
M290 X40 Y40 Z2.6666666
G91
```

(Your profile may have more lines below — keep them all.)

Optionally, add this comment at the very top so the bridge knows the initial tool:

```gcode
; TRADRACK_INITIAL_TOOL T=[initial_extruder]
```

#### Machine end G-code — NO CHANGES

Keep Bambu's default:

```gcode
;===== date: 20230428 =======================
M400 ; wait for buffer to clear
G92 E0 ; zero the extruder
G1 E-0.8 F1800 ; retract
G1 Z{max_layer_z + 0.5} F900 ; lower z a little
G1 X65 Y245 F12000 ; move to safe pos
G1 Y265 F3000
```

#### Layer change G-code — NO CHANGES

Keep Bambu's default:

```gcode
; layer num/total_layer_count: {layer_num+1}/[total_layer_count]
; update layer progress
M73 L{layer_num+1}
M991 S0 P{layer_num} ;notify layer change
```

#### Change filament G-code — THIS IS THE KEY CHANGE

Replace the stock Bambu AMS G-code:

```gcode
;=P1S 20250822=
M620 S[next_extruder]A
M204 S9000
G1 Z{max_layer_z + 3.0} F1200

G1 X70 F21000
G1 Y245
G1 Y265 F3000
```

With this (TradRack bridge version):

```gcode
; TRADRACK_TOOL_CHANGE T=[next_extruder]
; Lift Z and park head for filament change
G1 Z{max_layer_z + 3.0} F1200
G1 X70 F21000
G1 Y245
G1 Y265 F3000
; Pause for TradRack filament swap
M600
```

What changed:
- **Removed** `M620 S[next_extruder]A` — this is the Bambu AMS command (no AMS present)
- **Added** `; TRADRACK_TOOL_CHANGE T=[next_extruder]` — tells bridge which tool to load
- **Kept** the Z-lift and XY parking moves — gets the nozzle out of the way
- **Added** `M600` at the end — pauses the P1S for the bridge to perform the swap
- **Removed** `M204 S9000` — acceleration override not needed for the park move

`[next_extruder]` is Orca Slicer's variable that resolves to the target tool
number (0, 1, 2, etc.) at slice time.

#### Pause G-code — NO CHANGES

Keep as-is:

```gcode
M400 U1
```

### Multimaterial Tab

Keep the stock P1S settings:

- **Single Extruder Multi Material**: Enabled (checked)
- **Extruders**: 1
- **Purge in prime tower**: Disabled (unchecked)
- **Enable filament ramming**: Disabled (unchecked)
- **Cooling tube position**: 91.5 mm
- **Cooling tube length**: 5 mm
- **Filament parking position**: 92 mm
- **Extra loading distance**: -2 mm
- **Filament load time**: 29 s
- **Filament unload time**: 28 s
- **Tool change time**: 0 s

### Extruder Tab — NO CHANGES

Keep your stock P1S extruder settings as-is.

## Sending to P1S

Once sliced, send the G-code to the P1S as you normally would:
- **Send to printer** via LAN (Orca Slicer's built-in send feature)
- **Export G-code** to SD card
- The bridge will auto-detect the print starting and fetch the G-code

## Verifying the G-code

Before your first print, export the G-code and search for `TRADRACK_TOOL_CHANGE`
to verify the commands are in the right places:

```gcode
...
; TRADRACK_TOOL_CHANGE T=1
G1 Z5.2 F1200
G1 X70 F21000
G1 Y245
G1 Y265 F3000
M600
...printing with filament 1...
; TRADRACK_TOOL_CHANGE T=0
G1 Z5.2 F1200
G1 X70 F21000
G1 Y245
G1 Y265 F3000
M600
...printing with filament 0...
```

You can also verify with the bridge's scan command:

```bash
python -m src.main scan exported_file.gcode
```
