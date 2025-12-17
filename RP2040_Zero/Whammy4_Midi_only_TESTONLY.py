# Melatroid - Whammy 4 Version 1.01
from machine import Pin, ADC, UART
import time

# =========================================================
# DEBUG
# =========================================================
DEBUG = False
DEBUG_A_EVENTS = False

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
# MIDI OUT
# =========================================================
MIDI_ENABLED = True
MIDI_UART_ID = 0
MIDI_TX_PIN = 0
MIDI_CH = 3
MIDI_BAUD = 31250

MIDI_SEND_ON_START = True
MIDI_SEND_ON_STOP = False

# IMPORTANT:
# Whammy 4: bypass PC ist NICHT ein fixer Wert, sondern (active_pc + 17)
# Trotzdem behalten wir hier den Namen bei, aber wir verwenden ihn NICHT mehr als festen PC.
MIDI_PC_ON = 12
MIDI_PC_OFF = 28  # legacy/unbenutzt für echtes Bypass, siehe midi_bypass_for()

# =========================================================
# Whammy 4 Bypass Mapping
# active: 1..17, bypass: 18..34  => bypass = active + 17
# =========================================================
BYPASS_OFFSET = 17

def midi_bypass_for(active_pc: int) -> int:
    pc = int(active_pc) & 0x7F
    bp = pc + BYPASS_OFFSET
    # optional clamp (sicher, falls jemand falsche PCs sendet)
    if bp > 127:
        bp = 127
    return bp

# =========================================================
# MIDI ACCESS MODE / PRESET LOGIC
# =========================================================
PIN_MIDI_ACCESS = 14
PRESET_SCROLL_INTERVAL_MS = 350
DOUBLE_CLICK_MS = 300

ACCESS_HOLD_MS = 450
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
# 4 Preset Slots
#   A/B = single tap toggles
#   C   = (nicht mehr als eigenes Momentary im Normalbetrieb)
#   D   = double-tap persistent
# =========================================================
SLOT_A = 0
SLOT_B = 1
SLOT_C = 2
SLOT_D = 3

slot_index = [0, 0, 0, 0]
slot_name  = [PRESETS[0][0], PRESETS[0][0], PRESETS[0][0], PRESETS[0][0]]
slot_pc    = [PRESETS[0][1], PRESETS[0][1], PRESETS[0][1], PRESETS[0][1]]

# base_slot: persistenter Slot (A/B/D)
base_slot = SLOT_A
active_slot = SLOT_A
edit_slot = SLOT_A

preset_index = 0
last_preset_step_ms = 0
scroll_dir = 1

_last_sw_raw = 1
_last_press_ms_access = 0

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
PIN_FOOTSW = 4
PIN_POT = 26

DEBOUNCE_MS = 30
HOLD_TO_SWITCH_MS = 450
tap_down_ms = 0

hold_triggered = False
in_momentary_hold = False

# --- track current effect state and momentary snapshot ---
effect_is_on = False                # unser interner Stand (ON/OFF)
momentary_saved_on = False          # Zustand vor Hold
momentary_slot = SLOT_A             # welches Preset wurde momentary benutzt
momentary_pc = PRESETS[0][1]        # PC zum Momentary-Slot (für korrektes Bypass)

# Normal-mode single/double tap state
pending_single_tap = False
pending_single_tap_ms = 0

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

def midi_pc_send(program: int, channel=MIDI_CH):
    status = 0xC0 | (channel & 0x0F)
    midi_write(bytes([status, program & 0x7F]))

def midi_send_active(pc: int):
    midi_pc_send(pc)

def midi_send_bypass_for(pc_active: int):
    midi_pc_send(midi_bypass_for(pc_active))

def midi_confirm_preset(pc: int):
    # bestätigt Preset, ohne auf "falsches" fixed OFF zu springen:
    # OFF = bypass zu genau diesem pc
    for _ in range(CONFIRM_TOGGLES):
        midi_send_bypass_for(pc)
        time.sleep_ms(CONFIRM_DELAY_MS)
        midi_send_active(pc)
        time.sleep_ms(CONFIRM_DELAY_MS)

def set_base_slot(new_slot: int):
    global base_slot, active_slot
    if new_slot == SLOT_C:
        return
    base_slot = new_slot
    active_slot = new_slot

def toggle_ab_slot():
    # Single tap toggles A <-> B, egal ob man vorher in D war
    if base_slot == SLOT_A:
        set_base_slot(SLOT_B)
    else:
        set_base_slot(SLOT_A)

# =========================================================
# ACCESS PIN (GPIO14)
# =========================================================
access_down_ms = 0
access_hold_armed = False

stable_acc = midi_access.value()
last_acc = stable_acc
last_acc_change = time.ticks_ms()

def update_access_logic(now_ms: int) -> bool:
    global stable_acc, last_acc, last_acc_change
    global access_down_ms, access_hold_armed

    raw = midi_access.value()

    if raw != last_acc:
        last_acc = raw
        last_acc_change = now_ms

    if time.ticks_diff(now_ms, last_acc_change) >= DEBOUNCE_MS and stable_acc != last_acc:
        stable_acc = last_acc

        if stable_acc == 0:
            access_down_ms = now_ms
            access_hold_armed = True
        else:
            if access_hold_armed:
                dur = time.ticks_diff(now_ms, access_down_ms)
                if dur < ACCESS_HOLD_MS:
                    toggle_ab_slot()
                    midi_send_active(slot_pc[active_slot])
                    dbg(f"SLOT SWITCH (GPIO14) -> {active_slot} {slot_name[active_slot]} PC {slot_pc[active_slot]}")
            access_hold_armed = False

    if stable_acc == 0 and access_hold_armed:
        if time.ticks_diff(now_ms, access_down_ms) >= ACCESS_HOLD_MS:
            return True

    return False

def midi_access_active(now_ms: int) -> bool:
    if DEV_MIDI_ACCESS:
        return True
    return update_access_logic(now_ms)

# =========================================================
# Effect ON/OFF (unused here, but kept)
# =========================================================
active = False

def set_effect(on: bool, suppress_midi: bool = False):
    global active
    active = True if on else False
    if on:
        if (not suppress_midi) and MIDI_SEND_ON_START:
            midi_send_active(slot_pc[active_slot])
    else:
        if (not suppress_midi) and MIDI_SEND_ON_STOP:
            midi_send_bypass_for(slot_pc[active_slot])

set_effect(False)

# =========================================================
# Debounce (footswitch)
# =========================================================
stable_sw = sw.value()
last_sw = stable_sw
last_change = time.ticks_ms()

try:
    while True:
        now = time.ticks_ms()
        access = midi_access_active(now)

        # =========================================================
        # ACCESS enter/exit behavior
        # =========================================================
        if last_access is None or access != last_access:
            raw_access_pin = midi_access.value()
            print("GPIO14 raw =", raw_access_pin, "=> MIDI_ACCESS =", access)

            last_access = access
            last_access_print_ms = now

            _last_sw_raw = 1
            _last_press_ms_access = 0
            stable_sw = sw.value()
            last_sw = stable_sw
            last_change = now

            # reset
            tap_down_ms = 0
            hold_triggered = False
            in_momentary_hold = False
            pending_single_tap = False

            if access:
                edit_slot = active_slot
                active_slot = edit_slot
                midi_send_active(slot_pc[edit_slot])
                effect_is_on = True
                preset_index = slot_index[edit_slot]
                pending_active = False

        elif time.ticks_diff(now, last_access_print_ms) >= ACCESS_PRINT_INTERVAL_MS:
            last_access_print_ms = now
            raw_access_pin = midi_access.value()
            print("GPIO14 raw =", raw_access_pin, "=> MIDI_ACCESS =", access)

        # =========================================================
        # MIDI ACCESS MODE
        # =========================================================
        if access:
            raw = sw.value()
            foot_pressed = (raw == 0)
            press_edge = (_last_sw_raw == 1 and raw == 0)

            if press_edge:
                dt = time.ticks_diff(now, _last_press_ms_access)
                if 0 < dt <= DOUBLE_CLICK_MS:
                    edit_slot = (edit_slot + 1) % 4
                    active_slot = edit_slot
                    midi_send_active(slot_pc[edit_slot])
                    effect_is_on = True
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
                effect_is_on = True

                pending_active = True
                pending_index, pending_name, pending_pc = preset_index, name, pc
                pending_last_change_ms = now

                last_preset_step_ms = now
                stepped = True

            if foot_pressed and (not stepped):
                if time.ticks_diff(now, last_preset_step_ms) >= PRESET_SCROLL_INTERVAL_MS:
                    last_preset_step_ms = now
                    preset_index = (preset_index + scroll_dir) % len(PRESETS)
                    name, pc = PRESETS[preset_index]
                    midi_send_active(pc)
                    effect_is_on = True

                    pending_active = True
                    pending_index, pending_name, pending_pc = preset_index, name, pc
                    pending_last_change_ms = now

            if not foot_pressed:
                last_preset_step_ms = now

            if pending_active and (time.ticks_diff(now, pending_last_change_ms) >= PENDING_SAVE_MS):
                slot_index[edit_slot] = pending_index
                slot_name[edit_slot] = pending_name
                slot_pc[edit_slot] = pending_pc
                pending_active = False

                midi_confirm_preset(slot_pc[edit_slot])

                active_slot = edit_slot
                midi_send_active(slot_pc[edit_slot])
                effect_is_on = True
                preset_index = slot_index[edit_slot]

                pending_active = False
                _last_press_ms_access = 0
                last_preset_step_ms = now

            time.sleep_ms(1)
            continue

        # =========================================================
        # NORMAL MODE
        # - single tap: A/B toggle (confirmed after window)
        # - double tap: Slot D persistent
        # - hold: MOMENTARY ON while held:
        #         when hold triggers -> ON immediately (if it was OFF)
        #         on release -> BYPASS (korrekt zu diesem preset!)
        # =========================================================
        if not DEV_BYPASS_MOMENTARY:
            raw_sw = sw.value()
            if raw_sw != last_sw:
                last_sw = raw_sw
                last_change = now

            if time.ticks_diff(now, last_change) >= DEBOUNCE_MS and stable_sw != last_sw:
                stable_sw = last_sw

                # PRESS
                if stable_sw == 0:
                    tap_down_ms = now
                    hold_triggered = False
                    in_momentary_hold = False

                # RELEASE
                else:
                    dur = time.ticks_diff(now, tap_down_ms)

                    if hold_triggered and in_momentary_hold:
                        # Momentary ends: BYPASS on release (dynamic)
                        in_momentary_hold = False
                        midi_send_bypass_for(momentary_pc)
                        effect_is_on = False
                        if DEBUG:
                            print("HOLD RELEASE -> MOMENTARY BYPASS", midi_bypass_for(momentary_pc), "(from pc", momentary_pc, ")")

                    elif dur < HOLD_TO_SWITCH_MS:
                        # Tap (single/double)
                        if pending_single_tap and (time.ticks_diff(now, pending_single_tap_ms) <= DOUBLE_CLICK_MS):
                            # DOUBLE TAP
                            pending_single_tap = False
                            set_base_slot(SLOT_D)
                            midi_send_active(slot_pc[active_slot])
                            effect_is_on = True
                            if DEBUG:
                                print("DOUBLE TAP -> SLOT_D", slot_name[active_slot], "PC", slot_pc[active_slot])
                        else:
                            # Start single-tap window
                            pending_single_tap = True
                            pending_single_tap_ms = now

        else:
            if not active:
                set_effect(True)

        # Confirm pending single tap ONLY when window is over AND switch is not pressed
        if (not access) and pending_single_tap and stable_sw == 1:
            if time.ticks_diff(now, pending_single_tap_ms) > DOUBLE_CLICK_MS:
                pending_single_tap = False
                toggle_ab_slot()
                midi_send_active(slot_pc[active_slot])
                effect_is_on = True
                if DEBUG:
                    print("SINGLE TAP (confirmed) ->", active_slot, slot_name[active_slot], "PC", slot_pc[active_slot])

        # HOLD detection while pressed (momentary ON while held)
        if (not access) and (not DEV_BYPASS_MOMENTARY):
            if stable_sw == 0 and (not hold_triggered):
                if time.ticks_diff(now, tap_down_ms) >= HOLD_TO_SWITCH_MS:
                    # hold cancels pending single tap
                    pending_single_tap = False

                    # snapshot current state
                    momentary_slot = active_slot
                    momentary_pc = slot_pc[momentary_slot]
                    momentary_saved_on = effect_is_on

                    in_momentary_hold = True
                    hold_triggered = True

                    # ON immediately if it was OFF
                    if not momentary_saved_on:
                        midi_send_active(momentary_pc)
                        effect_is_on = True
                        if DEBUG:
                            print("HOLD -> MOMENTARY ON", momentary_slot, slot_name[momentary_slot], "PC", momentary_pc)

        time.sleep_ms(1)

except KeyboardInterrupt:
    set_effect(False)


