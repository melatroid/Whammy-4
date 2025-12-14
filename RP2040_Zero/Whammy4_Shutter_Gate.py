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
MIDI_SEND_ON_STOP = False
MIDI_PC_ON = 12
MIDI_PC_OFF = 28 

# =========================================================
# MIDI ACCESS MODE / PRESET LOGIC
# =========================================================
PIN_MIDI_ACCESS = 14
PRESET_SCROLL_INTERVAL_MS = 350
DOUBLE_CLICK_MS = 300

# Auto-commit confirmation after inactivity (Access mode)
PENDING_SAVE_MS = 2000

# MIDI-only confirmation: toggle OFF/ON N times
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
#   slot 0 = Preset A
#   slot 1 = Preset B
# =========================================================
SLOT_A = 0
SLOT_B = 1

slot_index = [0, 0]
slot_name  = [PRESETS[0][0], PRESETS[0][0]]
slot_pc    = [PRESETS[0][1], PRESETS[0][1]]

# Normal shutter mode: which preset slot is used
active_slot = SLOT_A

# Access mode: which preset slot is being edited
edit_slot = SLOT_A

# Scrolling index (preview cursor)
preset_index = 0
last_preset_step_ms = 0
scroll_dir = 1  # +1 forward, -1 backward

# Click tracking (shared raw edge)
_last_sw_raw = 1

# IMPORTANT FIX: separate double-click timing for access vs normal mode
_last_press_ms_access = 0

# ---------------------------------------------------------
# NORMAL MODE: robust double-tap detection on RELEASE
# and IMPORTANT: NO relay output (GPIO2/3) while user is tapping.
# Shutter starts only after HOLD (press longer than TAP_MAX_MS)
# ---------------------------------------------------------
tap_down_ms = 0
last_tap_up_ms = 0
tap_armed = False
pending_shutter = False

TAP_MAX_MS = 170     # max duration of a tap
DTAP_GAP_MS = 260    # max allowed gap between taps (release->release)

# Pending selection (Access mode)
pending_active = False
pending_index = 0
pending_name = PRESETS[0][0]
pending_pc = PRESETS[0][1]
pending_last_change_ms = 0

# Access debug tracking
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

def midi_confirm_preset(pc: int):
    """
    MIDI-only confirmation:
    toggle OFF/ON multiple times. Does NOT touch relays.
    Ends ON at the selected preset.
    """
    for _ in range(CONFIRM_TOGGLES):
        midi_pc(MIDI_PC_OFF)
        time.sleep_ms(CONFIRM_DELAY_MS)
        midi_pc(pc)
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
    return midi_access.value() == 0  # against GND = active

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
    """Normal shutter mode start/stop. Start sends current active_slot preset."""
    global active, last_toggle, last_pot_ms, half_ms, scope_count

    if on:
        active = True
        now0 = time.ticks_ms()

        pot_reset_and_prime()
        half_ms = clamp(map_pot_to_half_ms(pot_u16_mean), MIN_HALF_MS, MAX_HALF_MS)
        last_pot_ms = now0

        set_A_and_B(WET)
        last_toggle = now0

        if DEBUG_A_SCOPE:
            print("\n[SCOPE START]")
            scope_count = 0

        if (not suppress_midi) and MIDI_SEND_ON_START:
            midi_pc(slot_pc[active_slot])
            if DEBUG:
                print("EFFECT START -> SLOT", active_slot, slot_name[active_slot], "PC", slot_pc[active_slot])

    else:
        active = False
        set_A_and_B(DRY)

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

            # reset tracking on mode switch
            _last_sw_raw = 1
            _last_press_ms_access = 0
            stable_sw = sw.value()
            last_sw = stable_sw
            last_change = now

            # reset normal-mode double tap state too
            tap_down_ms = 0
            last_tap_up_ms = 0
            tap_armed = False
            pending_shutter = False

            if access:
                set_A_and_B(WET)

                # Always edit the slot that is currently active in normal mode.
                edit_slot = active_slot

                # Preview the stored preset of that slot
                midi_pc(slot_pc[edit_slot])

                # Align scroll cursor with stored preset
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

            # --- double click => TOGGLE EDIT SLOT A/B (NO MIDI scroll dir change) ---
            if press_edge:
                dt = time.ticks_diff(now, _last_press_ms_access)
                if 0 < dt <= DOUBLE_CLICK_MS:
                    # toggle which slot we are editing
                    edit_slot = SLOT_B if edit_slot == SLOT_A else SLOT_A

                    # preview stored preset of that slot
                    midi_pc(slot_pc[edit_slot])

                    # align scroll cursor to that slot's stored preset
                    preset_index = slot_index[edit_slot]

                    # clear pending (so we don't accidentally commit old selection)
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

            # --- tap => preview next preset (pending) ---
            if press_edge:
                preset_index = (preset_index + scroll_dir) % len(PRESETS)
                name, pc = PRESETS[preset_index]
                midi_pc(pc)  # preview

                pending_active = True
                pending_index, pending_name, pending_pc = preset_index, name, pc
                pending_last_change_ms = now

                last_preset_step_ms = now
                stepped = True

                if DEBUG:
                    print("PREVIEW (tap):", preset_index, name, "PC", pc, "-> pending write to SLOT", edit_slot)

            # --- hold => scroll preview ---
            if foot_pressed and (not stepped):
                if time.ticks_diff(now, last_preset_step_ms) >= PRESET_SCROLL_INTERVAL_MS:
                    last_preset_step_ms = now
                    preset_index = (preset_index + scroll_dir) % len(PRESETS)
                    name, pc = PRESETS[preset_index]
                    midi_pc(pc)  # preview

                    pending_active = True
                    pending_index, pending_name, pending_pc = preset_index, name, pc
                    pending_last_change_ms = now

                    if DEBUG:
                        print("PREVIEW (hold):", preset_index, name, "PC", pc, "-> pending write to SLOT", edit_slot)

            if not foot_pressed:
                last_preset_step_ms = now

            # --- auto-commit after inactivity ---
            if pending_active and (time.ticks_diff(now, pending_last_change_ms) >= PENDING_SAVE_MS):
                # commit current slot
                slot_index[edit_slot] = pending_index
                slot_name[edit_slot] = pending_name
                slot_pc[edit_slot] = pending_pc
                pending_active = False

                midi_confirm_preset(slot_pc[edit_slot])

                if DEBUG:
                    print("COMMIT SLOT", edit_slot, "->", slot_index[edit_slot], slot_name[edit_slot], "PC", slot_pc[edit_slot])

                # =========================================================
                # NEW: after committing preset for slot 1, automatically start
                # selection for slot 2 (toggle edit_slot and preview it)
                # =========================================================
                edit_slot = SLOT_B if edit_slot == SLOT_A else SLOT_A

                # preview stored preset of the new edit slot
                midi_pc(slot_pc[edit_slot])

                # align scroll cursor to the stored preset of the new slot
                preset_index = slot_index[edit_slot]

                # start clean (avoid accidental commit/doubleclick carryover)
                pending_active = False
                _last_press_ms_access = 0
                last_preset_step_ms = now

            time.sleep_ms(1)
            continue

        # =========================================================
        # NORMAL MODE: Momentary = Shutter
        # + double tap toggles active_slot (Preset A/B)
        #   IMPORTANT: NO RELAY output while tapping:
        #   - PRESS starts "pending_shutter"
        #   - if HOLD > TAP_MAX_MS => start shutter (relays switch)
        #   - release before that => it's a tap (no relays touched)
        # =========================================================
        if not DEV_BYPASS_MOMENTARY:
            raw_sw = sw.value()
            if raw_sw != last_sw:
                last_sw = raw_sw
                last_change = now

            # debounced state change
            if time.ticks_diff(now, last_change) >= DEBOUNCE_MS and stable_sw != last_sw:
                stable_sw = last_sw

                # -------- PRESS (debounced) --------
                if stable_sw == 0:
                    tap_down_ms = now
                    pending_shutter = True  # decide later if it's hold

                # -------- RELEASE (debounced) --------
                else:
                    # If shutter already running -> stop
                    if active:
                        set_effect(False)

                    dur = time.ticks_diff(now, tap_down_ms)

                    # If we never started shutter, a short press counts as tap
                    if pending_shutter and 0 <= dur <= TAP_MAX_MS:
                        gap = time.ticks_diff(now, last_tap_up_ms)

                        if tap_armed and 0 <= gap <= DTAP_GAP_MS:
                            # DOUBLE TAP => toggle slot
                            active_slot = SLOT_B if active_slot == SLOT_A else SLOT_A
                            tap_armed = False
                            last_tap_up_ms = 0

                            # immediate feedback: send preset of selected slot (MIDI only)
                            midi_pc(slot_pc[active_slot])

                            if DEBUG:
                                print("ACTIVE SLOT ->", active_slot, slot_name[active_slot], "PC", slot_pc[active_slot])
                        else:
                            # first tap: arm for a second tap
                            tap_armed = True
                            last_tap_up_ms = now
                    else:
                        # not a tap (or shutter was started) -> disarm
                        tap_armed = False
                        last_tap_up_ms = 0

                    pending_shutter = False

            # Start shutter only if still pressed and held long enough
            if pending_shutter and (sw.value() == 0) and (not active):
                if time.ticks_diff(now, tap_down_ms) > TAP_MAX_MS:
                    pending_shutter = False
                    set_effect(True)

            # disarm pending double tap if timed out
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

        # Shutter toggling
        if active and time.ticks_diff(now, last_toggle) >= half_ms:
            last_toggle = now
            set_A_and_B(DRY if a_state else WET)

        # optional scope
        if DEBUG_A_SCOPE and active and time.ticks_diff(now, last_scope_ms) >= SCOPE_EVERY_MS:
            last_scope_ms = now
            print("█" if a.value() else "·", end="")
            scope_count += 1
            if scope_count >= SCOPE_WIDTH:
                print(f"  half={half_ms}ms  SLOT={active_slot}  A={a_state}  B(GPIO)={b.value()}")
                scope_count = 0

        time.sleep_ms(1)

except KeyboardInterrupt:
    set_effect(False)

