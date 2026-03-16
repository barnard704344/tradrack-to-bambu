# Orca Slicer Configuration for TradRack-to-Bambu Bridge

This guide configures Orca Slicer to automatically insert M600 filament-change
commands at every tool change, so the G-code is ready for the bridge when sent
directly to the P1S. **No manual G-code processing required.**

## How It Works

1. Orca Slicer uses custom "Tool change G-code" to insert M600 + a comment
   with the target tool number at each filament swap
2. You send the G-code directly to the P1S from Orca Slicer (LAN/SD/FTP)
3. The bridge auto-fetches the G-code from the P1S when a print starts
4. The bridge scans it for the tool-change sequence
5. When the P1S hits M600 and pauses, the bridge triggers Happy Hare

## Printer Profile Setup

In Orca Slicer, create a new printer profile for the P1S + TradRack:

1. **Printer Settings → Basic Information**
   - Printer: BambuLab P1S
   - Set number of extruders to match your TradRack gates (e.g., 8)

2. **Printer Settings → Custom G-code → Tool change G-code**

   Replace the default tool change G-code with:

   ```gcode
   ; TRADRACK_TOOL_CHANGE T=[next_extruder]
   M600
   ```

   This inserts a comment (so the bridge knows which tool to load) followed
   by M600 (which makes the P1S pause for filament change).

   **Important:** Remove any existing tool-change commands (like `T[next_extruder]`)
   from this section. The P1S has no MMU, so Tx commands would cause errors.

3. **Printer Settings → Custom G-code → Start G-code**

   Add at the very beginning (before any other commands):

   ```gcode
   ; TRADRACK_INITIAL_TOOL T=[initial_extruder]
   M600
   ```

   This handles loading the first filament before the print starts.

4. **Printer Settings → Custom G-code → End G-code**

   Optionally add at the end:

   ```gcode
   ; TRADRACK_PRINT_END
   ```

   This helps the bridge know the print is finishing (it also detects this via MQTT).

## Filament Purge Settings

Since the TradRack handles filament changes externally, you may want to adjust:

- **Printer Settings → Extruder → Retraction when tool is disabled**: Set to 0
  (Happy Hare manages retraction)
- **Filament Settings → Multimaterial → Purging volumes**: Keep these as normal —
  the P1S still needs to purge the old color from the nozzle after filament swap

## Sending to P1S

Once sliced, send the G-code to the P1S as you normally would:
- **Send to printer** via LAN (Orca Slicer's built-in send feature)
- **Export G-code** to SD card
- The bridge will auto-detect the print starting and fetch the G-code

## Verifying the G-code

Before your first print, export the G-code and search for `TRADRACK_TOOL_CHANGE`
to verify the M600 commands are in the right places:

```
; TRADRACK_TOOL_CHANGE T=1
M600
...printing layer...
; TRADRACK_TOOL_CHANGE T=0
M600
...printing layer...
```

Each `TRADRACK_TOOL_CHANGE` comment tells the bridge which TradRack gate to load.
The M600 makes the P1S pause so the bridge has time to perform the swap.
