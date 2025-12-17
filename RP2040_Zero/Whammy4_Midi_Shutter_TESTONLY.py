# Melatroid - Whammy 4 Version 1.00
from machine import Pin, ADC, UART
import time

# =========================================================
# DEBUG
# =========================================================
DEBUG = False
DEBUG_A_EVENTS = False
DEBUG_A_SCOPE = True
SCOPE_EVERY_MS = 5
SCOPE_WIDTH = 80

def dbg(msg):
    if DEBUG:
        print(msg)

def a_dbg(msg):
    if DEBUG_A_EVENTS:
        print(msg)

# =========================================================
# DEVELOPMENT BYPASS
# =========================================================
DEV_BYPASS_MOMENTARY = False
DEV_MIDI_ACCESS = False

# =========================================================
# BYPASS / GATE LOGIC
# =========================================================
BYPASS_B_INVERT = True
BBM_DELAY_US = 20

# =========================================================
# MIDI OUT
# =========================================================
MIDI_ENABLED = True
MIDI_UART_ID = 0
MIDI_TX_PIN = 0
MIDI_CH = 3
MIDI_BAUD = 31250

MIDI_SEND_ON_START = True
MIDI_SEND_ON_STOP = False  # wenn True: sendet BYPASS beim Stop

MIDI_PC_ON = 12
MIDI_PC_OFF = 28  # legacy/fallback wenn BYPASS_MODE="fixed"

# =========================================================
# SHUTTER MODE
#   "midi"  = Shutter via MIDI PC (Active <-> Bypass)
#   "relay" = Shutter via Relais (dein altes Verhalten)
# =========================================================
SHUTTER_MODE = "midi"

# Optional: harte Untergrenze, damit das Pedal bei sehr schnellen PC-Wechseln nicht "verschluckt"
MIDI_MIN_HALF_MS = 60  # z.B. 60ms = ~8.3Hz (ON/OFF)
# Setze auf MIN_HALF_MS, wenn du keine extra Begrenzung willst:
# MIDI_MIN_HALF_MS = MIN_HALF_MS   (geht hier noch nicht, weil MIN_HALF_MS weiter unten definiert ist)

# =========================================================
# BYPASS MAP (Whammy 4)
# =========================================================
# "offset" = bypass = active + 17  (wie auf deinem Bild: 1..17 -> 18..34)
# "fixed"  = bypass = MIDI_PC_OFF (altes Verhalten, falls Firmware anders ist)
BYPASS_MODE = "offset"
BYPASS_OFFSET = 17

def pc_bypass_for(active_pc: int) -> int:
    if BYPASS_MODE == "fixed":
        return MIDI_PC_OFF & 0x7F
    pc = int(active_pc) & 0x7F
    bp = pc + BYPASS_OFFSET
    if bp > 127:
        bp = 127
    return bp

# =========================================================
# MIDI ACCESS MODE / PRESET LOGIC
# =========================================================
PIN_MIDI_ACCESS = 14
PRESET_SCROLL_INTERVAL_MS = 350
DOUBLE_CLICK_MS = 300

PENDING_SAVE_MS = 2000

CONFIRM_TOGGLES = 3
CONFIRM_DELAY_MS = 120

PRESETS = [
    ("Detune Shallow", 1),
    ("Detune Deep", 2),
    ("Whammy: Up 2 Oct", 3),
    ("Whammy: Up 1 Oct", 4),
    ("Whammy: Down 1 Oct", 5),
    ("Whammy: Down 2 Oct", 6),
    ("Whammy: Dive Bomb", 7),
    ("Whammy: Drop Tune", 8),
    ("Harmony: Oct/Oct", 9),
    ("Harmony: 5th/4th", 10),
    ("Harmony: 4th/3rd", 11),
    ("Harmony: 5th/7th", 12),
    ("Harmony: 5th/6th", 13),
    ("Harmony: 4th/5th", 14),
    ("Harmony: 3rd/4th", 15),
    ("Harmony: b3rd/3rd", 16),
    ("Harmony: 2nd/3rd", 17),
]

# =========================================================
# 2 Preset Slots
# =========================================================
SLOT_A = 0
SLOT_B = 1

slot_index = [0, 0]
slot_name  = [PRESETS[0][0], PRESETS[0][0]]
slot_pc    = [PRESETS[0][1], PRESETS[0][1]]

active_slot = SLOT_A
edit_slot = SLOT_A

preset_index = 0
last_preset_step_ms = 0
scroll_dir = 1

_last_sw_raw = 1
_last_press_ms_access = 0

# Normal mode tap/hold
tap_down_ms = 0
last_tap_up_ms = 0
tap_armed = False
pending_shutter = False

TAP_MAX_MS = 170
DTAP_GAP_MS = 260

# Pending selection (Access mode)
pending_active = False
pending_index = 0
pending_name = PRESETS[0][0]
pending_pc = PRESETS[0][1]
pending_last_change_ms = 0

last_access = None
last_access_print_ms = 0
ACCESS_PRINT_INTERVAL_MS = 200

# =========================================================
# PINS
# =========================================================
PIN_A = 2
PIN_B = 3
PIN_FOOTSW = 4
PIN_POT = 26

DRY = 0
WET = 1

POT_EVERY_MS = 10
MIN_HALF_MS = 30
MAX_HALF_MS = 1000
DEBOUNCE_MS = 30

# jetzt, wo MIN_HALF_MS existiert:
if MIDI_MIN_HALF_MS < MIN_HALF_MS:
    MIDI_MIN_HALF_MS = MIN_HALF_MS

# =========================================================
# Poti-Filter
# =========================================================
POT_WINDOW = 10
POT_MAX_DEV = 200
POT_FORCE_AFTER = 4

# =========================================================
# Setup IO
# =========================================================
a = Pin(PIN_A, Pin.OUT, value=DRY)
b = Pin(PIN_B, Pin.OUT, value=1)
sw = Pin(PIN_FOOTSW, Pin.IN, Pin.PULL_UP)
midi_access = Pin(PIN_MIDI_ACCESS, Pin.IN, Pin.PULL_UP)
pot = ADC(Pin(PIN_POT))

# =========================================================
# MIDI Setup
# =========================================================
midi = None
if MIDI_ENABLED:
    midi = UART(MIDI_UART_ID, baudrate=MIDI_BAUD, tx=Pin(MIDI_TX_PIN))

def midi_write(data: bytes):
    if MIDI_ENABLED and midi is not None:
        midi.write(data)

def midi_pc(program: int, channel=MIDI_CH):
    status = 0xC0 | (channel & 0x0F)
    midi_write(bytes([status, program & 0x7F]))

def midi_send_active(pc: int):
    midi_pc(pc)

def midi_send_bypass_for(pc_active: int):
    midi_pc(pc_bypass_for(pc_active))

def midi_confirm_preset(pc: int):
    for _ in range(CONFIRM_TOGGLES):
        midi_send_bypass_for(pc)
        time.sleep_ms(CONFIRM_DELAY_MS)
        midi_send_active(pc)
        time.sleep_ms(CONFIRM_DELAY_MS)

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def map_pot_to_half_ms(v):
    span = MAX_HALF_MS - MIN_HALF_MS
    return MAX_HALF_MS - (v * span // 65535)

def b_write_raw(v01: int):
    if BYPASS_B_INVERT:
        b.value(0 if v01 else 1)
    else:
        b.value(v01)

# a_state ist jetzt zusätzlich unser "Phase"-Marker für MIDI-Shutter
a_state = DRY

def set_A_and_B(a_val: int):
    """Make-before-make relay handling: WET=1, DRY=0"""
    global a_state
    new_a = 1 if a_val else 0
    old_a = a_state
    if new_a == old_a:
        return

    if new_a == 1:
        b_write_raw(0)
        if BBM_DELAY_US:
            time.sleep_us(BBM_DELAY_US)
        a_state = 1
        a.value(1)
    else:
        a_state = 0
        a.value(0)
        if BBM_DELAY_US:
            time.sleep_us(BBM_DELAY_US)
        b_write_raw(1)

# =========================================================
# Pot Filter
# =========================================================
pot_u16_raw = 0
pot_u16_mean = 0
pot_hist = []
pot_outlier_streak = 0
pot_outlier_dir = 0

def pot_reset_and_prime():
    global pot_u16_raw, pot_u16_mean, pot_hist, pot_outlier_streak, pot_outlier_dir
    pot_u16_raw = pot.read_u16()
    pot_hist = [pot_u16_raw]
    pot_u16_mean = pot_u16_raw
    pot_outlier_streak = 0
    pot_outlier_dir = 0

def pot_update_filtered():
    global pot_u16_raw, pot_u16_mean, pot_hist, pot_outlier_streak, pot_outlier_dir
    pot_u16_raw = pot.read_u16()

    if not pot_hist:
        pot_hist = [pot_u16_raw]
        pot_u16_mean = pot_u16_raw
        pot_outlier_streak = 0
        pot_outlier_dir = 0
        return True

    diff = pot_u16_raw - pot_u16_mean
    if abs(diff) > POT_MAX_DEV:
        d = 1 if diff > 0 else -1
        if d == pot_outlier_dir:
            pot_outlier_streak += 1
        else:
            pot_outlier_dir = d
            pot_outlier_streak = 1

        if pot_outlier_streak >= POT_FORCE_AFTER:
            pot_hist = [pot_u16_raw]
            pot_u16_mean = pot_u16_raw
            pot_outlier_streak = 0
            pot_outlier_dir = 0
            return True

        return False

    pot_outlier_streak = 0
    pot_outlier_dir = 0

    pot_hist.append(pot_u16_raw)
    if len(pot_hist) > POT_WINDOW:
        pot_hist.pop(0)
    pot_u16_mean = sum(pot_hist) // len(pot_hist)
    return True

def midi_access_active() -> bool:
    if DEV_MIDI_ACCESS:
        return True
    return midi_access.value() == 0

# =========================================================
# Effect ON/OFF (Shutter gate logic)
# =========================================================
active = False
last_toggle = time.ticks_ms()
last_pot_ms = time.ticks_ms()
half_ms = MAX_HALF_MS
last_scope_ms = time.ticks_ms()
scope_count = 0

def set_effect(on: bool, suppress_midi: bool = False):
    """Start/stop shutter. In MIDI mode: toggling is done via PC Active/Bypass."""
    global active, last_toggle, last_pot_ms, half_ms, scope_count, a_state

    if on:
        active = True
        now0 = time.ticks_ms()

        pot_reset_and_prime()
        half_ms = clamp(map_pot_to_half_ms(pot_u16_mean), MIN_HALF_MS, MAX_HALF_MS)

        # extra limit only for MIDI shutter (optional)
        if SHUTTER_MODE == "midi":
            half_ms = clamp(half_ms, MIDI_MIN_HALF_MS, MAX_HALF_MS)

        last_pot_ms = now0
        last_toggle = now0

        # Startphase = ON
        a_state = WET

        # Relais wie vorher initial auf WET (Audio-Pfad aktiv)
        set_A_and_B(WET)

        if DEBUG_A_SCOPE:
            print("\n[SCOPE START]")
            scope_count = 0

        if (not suppress_midi) and MIDI_SEND_ON_START:
            midi_send_active(slot_pc[active_slot])
            if DEBUG:
                print("EFFECT START -> SLOT", active_slot, slot_name[active_slot], "PC", slot_pc[active_slot])

    else:
        active = False
        set_A_and_B(DRY)
        a_state = DRY

        if (not suppress_midi) and MIDI_SEND_ON_STOP:
            midi_send_bypass_for(slot_pc[active_slot])
            if DEBUG:
                print("EFFECT STOP -> BYPASS PC", pc_bypass_for(slot_pc[active_slot]),
                      "(from", slot_pc[active_slot], ")")

        if DEBUG_A_SCOPE:
            print("\n[SCOPE STOP]\n")

# Boot-safe
set_effect(False)

# =========================================================
# Debounce (normal mode)
# =========================================================
stable_sw = sw.value()
last_sw = stable_sw
last_change = time.ticks_ms()

try:
    while True:
        now = time.ticks_ms()
        access = midi_access_active()

        # =========================================================
        # ACCESS DEBUG + enter/exit behavior
        # =========================================================
        raw_access_pin = midi_access.value()
        if last_access is None or access != last_access:
            print("GPIO14 raw =", raw_access_pin, "=> MIDI_ACCESS =", access)
            last_access = access
            last_access_print_ms = now

            _last_sw_raw = 1
            _last_press_ms_access = 0
            stable_sw = sw.value()
            last_sw = stable_sw
            last_change = now

            tap_down_ms = 0
            last_tap_up_ms = 0
            tap_armed = False
            pending_shutter = False

            if access:
                set_A_and_B(WET)

                edit_slot = active_slot
                midi_send_active(slot_pc[edit_slot])
                preset_index = slot_index[edit_slot]
                pending_active = False
            else:
                if not active:
                    set_A_and_B(DRY)

        elif time.ticks_diff(now, last_access_print_ms) >= ACCESS_PRINT_INTERVAL_MS:
            last_access_print_ms = now
            print("GPIO14 raw =", raw_access_pin, "=> MIDI_ACCESS =", access)

        # =========================================================
        # MIDI ACCESS MODE
        # =========================================================
        if access:
            if a_state != WET:
                set_A_and_B(WET)

            raw = sw.value()
            foot_pressed = (raw == 0)
            press_edge = (_last_sw_raw == 1 and raw == 0)

            if press_edge:
                dt = time.ticks_diff(now, _last_press_ms_access)
                if 0 < dt <= DOUBLE_CLICK_MS:
                    edit_slot = SLOT_B if edit_slot == SLOT_A else SLOT_A
                    midi_send_active(slot_pc[edit_slot])
                    preset_index = slot_index[edit_slot]
                    pending_active = False

                    _last_press_ms_access = 0
                    if DEBUG:
                        print("EDIT SLOT ->", edit_slot, "PREVIEW", slot_name[edit_slot], "PC", slot_pc[edit_slot])

                    _last_sw_raw = raw
                    time.sleep_ms(1)
                    continue
                else:
                    _last_press_ms_access = now

            _last_sw_raw = raw
            stepped = False

            if press_edge:
                preset_index = (preset_index + scroll_dir) % len(PRESETS)
                name, pc = PRESETS[preset_index]
                midi_send_active(pc)

                pending_active = True
                pending_index, pending_name, pending_pc = preset_index, name, pc
                pending_last_change_ms = now

                last_preset_step_ms = now
                stepped = True

                if DEBUG:
                    print("PREVIEW (tap):", preset_index, name, "PC", pc, "-> pending write to SLOT", edit_slot)

            if foot_pressed and (not stepped):
                if time.ticks_diff(now, last_preset_step_ms) >= PRESET_SCROLL_INTERVAL_MS:
                    last_preset_step_ms = now
                    preset_index = (preset_index + scroll_dir) % len(PRESETS)
                    name, pc = PRESETS[preset_index]
                    midi_send_active(pc)

                    pending_active = True
                    pending_index, pending_name, pending_pc = preset_index, name, pc
                    pending_last_change_ms = now

                    if DEBUG:
                        print("PREVIEW (hold):", preset_index, name, "PC", pc, "-> pending write to SLOT", edit_slot)

            if not foot_pressed:
                last_preset_step_ms = now

            if pending_active and (time.ticks_diff(now, pending_last_change_ms) >= PENDING_SAVE_MS):
                slot_index[edit_slot] = pending_index
                slot_name[edit_slot] = pending_name
                slot_pc[edit_slot] = pending_pc
                pending_active = False

                midi_confirm_preset(slot_pc[edit_slot])

                if DEBUG:
                    print("COMMIT SLOT", edit_slot, "->", slot_index[edit_slot], slot_name[edit_slot], "PC", slot_pc[edit_slot])

            time.sleep_ms(1)
            continue

        # =========================================================
        # NORMAL MODE
        # =========================================================
        if not DEV_BYPASS_MOMENTARY:
            raw_sw = sw.value()
            if raw_sw != last_sw:
                last_sw = raw_sw
                last_change = now

            if time.ticks_diff(now, last_change) >= DEBOUNCE_MS and stable_sw != last_sw:
                stable_sw = last_sw

                if stable_sw == 0:
                    tap_down_ms = now
                    pending_shutter = True

                else:
                    if active:
                        set_effect(False)

                    dur = time.ticks_diff(now, tap_down_ms)

                    if pending_shutter and 0 <= dur <= TAP_MAX_MS:
                        gap = time.ticks_diff(now, last_tap_up_ms)

                        if tap_armed and 0 <= gap <= DTAP_GAP_MS:
                            active_slot = SLOT_B if active_slot == SLOT_A else SLOT_A
                            tap_armed = False
                            last_tap_up_ms = 0

                            midi_send_active(slot_pc[active_slot])

                            if DEBUG:
                                print("ACTIVE SLOT ->", active_slot, slot_name[active_slot], "PC", slot_pc[active_slot])
                        else:
                            tap_armed = True
                            last_tap_up_ms = now
                    else:
                        tap_armed = False
                        last_tap_up_ms = 0

                    pending_shutter = False

            if pending_shutter and (sw.value() == 0) and (not active):
                if time.ticks_diff(now, tap_down_ms) > TAP_MAX_MS:
                    pending_shutter = False
                    set_effect(True)

            if tap_armed and time.ticks_diff(now, last_tap_up_ms) > DTAP_GAP_MS:
                tap_armed = False

        else:
            if not active:
                set_effect(True)

        # Poti only while shutter active
        if active and time.ticks_diff(now, last_pot_ms) >= POT_EVERY_MS:
            last_pot_ms = now
            pot_update_filtered()
            half_ms = clamp(map_pot_to_half_ms(pot_u16_mean), MIN_HALF_MS, MAX_HALF_MS)

            if SHUTTER_MODE == "midi":
                half_ms = clamp(half_ms, MIDI_MIN_HALF_MS, MAX_HALF_MS)

        # Shutter toggling
        if active and time.ticks_diff(now, last_toggle) >= half_ms:
            last_toggle = now

            if SHUTTER_MODE == "relay":
                set_A_and_B(DRY if a_state else WET)

            else:
                # MIDI shutter: toggle Active <-> Bypass
                if a_state == WET:
                    midi_send_bypass_for(slot_pc[active_slot])  # OFF phase
                    a_state = DRY
                else:
                    midi_send_active(slot_pc[active_slot])      # ON phase
                    a_state = WET

        # optional scope
        if DEBUG_A_SCOPE and active and time.ticks_diff(now, last_scope_ms) >= SCOPE_EVERY_MS:
            last_scope_ms = now
            # in MIDI mode show phase marker, not GPIO
            print("█" if a_state == WET else "·", end="")
            scope_count += 1
            if scope_count >= SCOPE_WIDTH:
                print(f"  half={half_ms}ms  SLOT={active_slot}  PHASE={a_state}  B(GPIO)={b.value()}")
                scope_count = 0

        time.sleep_ms(1)

except KeyboardInterrupt:
    set_effect(False)

