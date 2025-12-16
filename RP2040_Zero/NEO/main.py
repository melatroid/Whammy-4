# Melatroid - Whammy 4 NEO - Version 2.00

from machine import UART, Pin, ADC
import time

# =========================================================
# MIDI CONFIG
# =========================================================
MIDI_UART_ID = 0
MIDI_TX_PIN = 0
MIDI_BAUD = 31250
TARGET_CH = 3   # 0-based => CH04

# --- channel-blink (no CC0, no PC/BYPASS) ---
BLINK_NOTE = 60       # C-1
BLINK_VEL = 100
BLINK_ON_MS = 90
BLINK_OFF_MS = 90
BLINK_TIMES = 3

# =========================================================
# FOOTSWITCH + LAYER SWITCH
# =========================================================
PIN_FOOTSW = 4
PIN_LAYER_SWITCH = 14
DEBOUNCE_MS = 30

# Tap / Double-Tap
TAP_MAX_MS = 900
LAYER2_TAP_MAX_MS = 900
DOUBLE_TAP_WINDOW_MS = 320

# Momentary/Holding/Shutter trigger (must be higher than tap)
MOMENTARY_HOLD_MS = 500

# re-enter preset programming from Layer 2 via long-hold
LAYER2_REPROGRAM_HOLD_MS = 2000
# Prevent effect "blip" during preset switching:
SWITCH_MUTE_MS = 250

sw = Pin(PIN_FOOTSW, Pin.IN, Pin.PULL_UP)
layer_sw = Pin(PIN_LAYER_SWITCH, Pin.IN, Pin.PULL_UP)

# =========================================================
# POTENTIOMETER (Holding-time / Shutter interval control)
#   FIX: non-linear mapping + separate ranges per mode
# =========================================================
POT_ADC_PIN = 26

# Holding mode range (long times)
HOLD_MIN_MS = 200
HOLD_MAX_MS = 5000

# Shutter mode range (fast musically useful chop speed)
# (this is per PHASE: ON->OFF or OFF->ON)
SHUTTER_MIN_MS = 30
SHUTTER_MAX_MS = 400

POT_READ_INTERVAL_MS = 40

pot = ADC(POT_ADC_PIN)
pot_time_ms = 1000
_last_pot_read_ms = 0

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def map_u16_expo(raw_u16: int, lo: int, hi: int, k_percent: int = 450) -> int:
    """
    Exponential-ish curve without floats.
    raw_u16: 0..65535
    k_percent: 100..800 typical
      higher => more resolution at short times (more "log-like")
    """
    x = raw_u16  # 0..65535
    y_quad = (x * x) >> 16        # 0..65535 (quadratic curve)
    y = (y_quad * k_percent + x * (1000 - k_percent)) // 1000
    span = hi - lo
    return lo + (y * span) // 65535

# Forward declaration for mode constants (used in update_pot_time_ms)
MODE_LATCH = 0
MODE_MOMENTARY = 1
MODE_HOLDING = 2
MODE_SHUTTER = 3
mode = MODE_LATCH

def update_pot_time_ms(now_ms: int):
    """
    FIX:
    - MODE_HOLDING => 200..5000ms (expo-ish)
    - MODE_SHUTTER => 30..400ms   (expo-ish, more resolution at fast end)
    - others: keep 1000ms
    """
    global pot_time_ms, _last_pot_read_ms, mode
    if time.ticks_diff(now_ms, _last_pot_read_ms) < POT_READ_INTERVAL_MS:
        return
    _last_pot_read_ms = now_ms

    raw = pot.read_u16()  # 0..65535

    if mode == MODE_SHUTTER:
        pot_time_ms = map_u16_expo(raw, SHUTTER_MIN_MS, SHUTTER_MAX_MS, k_percent=550)
        pot_time_ms = clamp(pot_time_ms, SHUTTER_MIN_MS, SHUTTER_MAX_MS)
    elif mode == MODE_HOLDING:
        pot_time_ms = map_u16_expo(raw, HOLD_MIN_MS, HOLD_MAX_MS, k_percent=350)
        pot_time_ms = clamp(pot_time_ms, HOLD_MIN_MS, HOLD_MAX_MS)
    else:
        pot_time_ms = 1000

# =========================================================
# PRESETS (Whammy 4, 0..16)
# =========================================================
PRESETS = [
    ("Detune Shallow", 0),
    ("Detune Deep", 1),
    ("Whammy: Up 2 Oct", 2),
    ("Whammy: Up 1 Oct", 3),
    ("Whammy: Down 1 Oct", 4),
    ("Whammy: Down 2 Oct", 5),
    ("Whammy: Dive Bomb", 6),
    ("Whammy: Drop Tune", 7),
    ("Harmony: Oct/Oct", 8),
    ("Harmony: 5th/4th", 9),
    ("Harmony: 4th/3rd", 10),
    ("Harmony: 5th/7th", 11),
    ("Harmony: 5th/6th", 12),
    ("Harmony: 4th/5th", 13),
    ("Harmony: 3rd/4th", 14),
    ("Harmony: b3rd/3rd", 15),
    ("Harmony: 2nd/3rd", 16),
]

# SETTINGS PCs are used ONLY for display/scroll feedback
SETTINGS = [
    ("Mode: Latch (default ON)", 16),
    ("Mode: Momentary (default OFF)", 15),
    ("Mode: Holding (pot timeout)", 14),
    ("Mode: Shutter (pot timeout)", 13),
]

BYPASS_OFFSET = 17

# =========================================================
# STARTUP ANIMATION CONFIG
# =========================================================
STARTUP_PASSES = 2
STARTUP_STEP_MS = 50
STARTUP_FIXED_PC_ORDER = [
    0, 8,  1, 9,  2,
    10, 3, 11, 4,
    12, 5, 13, 6,
    14, 7, 15, 16
]
STARTUP_FIXED_PC_ORDER2 = [
    16, 0, 15, 1, 14,
    2, 13, 3, 12,
    4, 11, 5, 10,
    6, 9, 7, 8
]

# =========================================================
# MIDI
# =========================================================
uart = UART(MIDI_UART_ID, baudrate=MIDI_BAUD, tx=Pin(MIDI_TX_PIN))

def midi_pc(pc: int):
    uart.write(bytes([0xC0 | TARGET_CH, pc & 0x7F]))

def midi_cc(cc: int, val: int):
    uart.write(bytes([0xB0 | TARGET_CH, cc & 0x7F, val & 0x7F]))

def midi_note_on(note: int, vel: int):
    uart.write(bytes([0x90 | TARGET_CH, note & 0x7F, vel & 0x7F]))

def midi_note_off(note: int):
    # robust: Note-Off as Note-On with velocity 0
    uart.write(bytes([0x90 | TARGET_CH, note & 0x7F, 0]))
    # optional extra "true note off" for compatibility
    uart.write(bytes([0x80 | TARGET_CH, note & 0x7F, 0]))

def pc_bypass(pc: int):
    return pc + BYPASS_OFFSET

def send_effect_on(pc: int):
    midi_cc(0, 127)
    midi_pc(pc)

def send_effect_off(pc: int):
    midi_cc(0, 0)
    midi_pc(pc_bypass(pc))

def send_bypass_pc_only(pc: int):
    midi_pc(pc_bypass(pc))

def confirm_saved_preset_pc_only(pc: int):
    midi_pc(pc)                 # ON
    time.sleep_ms(70)
    midi_pc(pc_bypass(pc))      # OFF (bypass)
    time.sleep_ms(40)
    midi_pc(pc)                 # tiny extra flash (optional)
    time.sleep_ms(50)
    midi_pc(pc_bypass(pc))      # end in bypass

def blink_selected_channel(times=BLINK_TIMES, on_ms=BLINK_ON_MS, off_ms=BLINK_OFF_MS):
    """
    Blink the MIDI CHANNEL by sending NOTE ON/OFF pulses.
    No CC0, no ProgramChange, no bypass tricks.
    """
    midi_note_off(BLINK_NOTE)
    time.sleep_ms(80)
    for _ in range(times):
        midi_note_on(BLINK_NOTE, BLINK_VEL)
        time.sleep_ms(on_ms)
        midi_note_off(BLINK_NOTE)
        time.sleep_ms(off_ms)

# =========================================================
# SHUTTER MIDI (FIX: PC-only toggling, CC0 only at start/stop)
# =========================================================
def shutter_start(pc: int):
    # one-time "arm"
    midi_cc(0, 127)
    midi_pc(pc)

def shutter_on_phase(pc: int):
    # PC only (no CC spam)
    midi_pc(pc)

def shutter_off_phase(pc: int):
    # PC only (no CC spam)
    midi_pc(pc_bypass(pc))

def shutter_stop(pc: int):
    # one-time "disarm" and end in bypass
    midi_cc(0, 0)
    midi_pc(pc_bypass(pc))

# =========================================================
# STARTUP SEQUENCE (BOOT ONLY!)
# =========================================================
def startup_sequence():
    midi_cc(0, 0)
    direction = 1

    # Phase 1 disabled
    # Phase 2
    for _ in range(STARTUP_PASSES):
        order = STARTUP_FIXED_PC_ORDER if direction > 0 else reversed(STARTUP_FIXED_PC_ORDER)
        for pc in order:
            midi_pc(pc_bypass(pc))
            time.sleep_ms(STARTUP_STEP_MS)
        direction = -direction

    # Phase 3
    for _ in range(STARTUP_PASSES):
        order = STARTUP_FIXED_PC_ORDER2 if direction > 0 else reversed(STARTUP_FIXED_PC_ORDER2)
        for pc in order:
            midi_pc(pc_bypass(pc))
            time.sleep_ms(STARTUP_STEP_MS)
        direction = -direction

    midi_cc(0, 0)
    midi_pc(pc_bypass(0))

# =========================================================
# BOOT PROGRAMMING (3 stages)
# =========================================================
SCAN_INTERVAL_MS_BOOT = 1000
scan_direction = 1
scan_paused = False
last_scan_step_ms = 0
selection_index = 0

STAGES = 3
stage = 0
programming_done = False

stored_preset_index = [-1, -1]   # preset A, preset B

# --- Reprogram staging (NICHT sofort überschreiben!) ---
reprog_active = False
reprog_temp = [-1, -1]

# (mode constants already defined above)
# mode = MODE_LATCH

# =========================================================
# RUNTIME LAYERS (GPIO14 controls this)
# =========================================================
LAYER_PRESET = 0   # Layer 1: performance
LAYER_EFFECT = 1   # Layer 2: SETTINGS menu

runtime_layer = LAYER_PRESET

# Performance state
active_slot = 0
effect_enabled = True

# Momentary/Holding runtime
momentary_engaged = False
holding_armed = False
holding_off_at = 0

# Shutter runtime (MIDI: Active <-> Bypass)
shutter_active = False
shutter_phase_on = False
shutter_next_toggle_at = 0

# Layer 2 selection freeze (fixes "can't select reliably")
selected_setting_index = 0

# Switch-mute state (blip free)
switch_mute_until = 0
switch_apply_pending = False

# =========================================================
# SWITCH STATE / TAP STATE (debounce)
# =========================================================
stable_sw = sw.value()
last_sw = stable_sw
last_change = time.ticks_ms()
press_start_ms = 0

stable_layer = layer_sw.value()
last_layer = stable_layer
last_layer_change = time.ticks_ms()

pending_single_tap = False
pending_single_tap_deadline = 0
last_release_ms = 0

# long-hold guard so it triggers once per hold
layer2_long_hold_fired = False

# ✅ Merkt, in welchem Layer der aktuelle Press begonnen hat (verhindert "unabsichtliches" Reprogramming)
press_layer = LAYER_PRESET

# =========================================================
# HELPERS
# =========================================================
def current_active_pc():
    idx = stored_preset_index[active_slot]
    if idx < 0:
        return 0
    return PRESETS[idx][1]

def apply_current_sound():
    global momentary_engaged, holding_armed, holding_off_at
    global shutter_active, shutter_phase_on, shutter_next_toggle_at

    pc = current_active_pc()
    if mode == MODE_LATCH:
        if effect_enabled:
            send_effect_on(pc)
        else:
            send_effect_off(pc)
    else:
        # Momentary/Holding/Shutter start only by press logic
        send_effect_off(pc)

    # reset transient states when applying a sound baseline
    momentary_engaged = False
    holding_armed = False
    holding_off_at = 0
    shutter_active = False
    shutter_phase_on = False
    shutter_next_toggle_at = 0

def show_boot_scan_item():
    global selection_index
    if stage <= 1:
        _, pc = PRESETS[selection_index]
        send_effect_off(pc)
    else:
        _, pc = SETTINGS[selection_index]
        send_effect_off(pc)

def show_settings_layer_scan_item():
    """
    Layer 2 feedback (Settings):
    reliable display feedback -> CC0 OFF + bypass PC
    (This remains for scrolling feedback)
    """
    global selection_index
    _, pc = SETTINGS[selection_index]
    send_effect_off(pc)

def start_preset_switch_with_mute():
    global active_slot, switch_mute_until, switch_apply_pending
    global momentary_engaged, holding_armed, holding_off_at
    global shutter_active, shutter_phase_on, shutter_next_toggle_at

    if stored_preset_index[0] < 0 or stored_preset_index[1] < 0:
        return

    pc_now = current_active_pc()
    send_effect_off(pc_now)

    active_slot = 1 - active_slot

    momentary_engaged = False
    holding_armed = False
    holding_off_at = 0

    shutter_active = False
    shutter_phase_on = False
    shutter_next_toggle_at = 0

    switch_mute_until = time.ticks_add(time.ticks_ms(), SWITCH_MUTE_MS)
    switch_apply_pending = True

def on_single_tap_layer1():
    global effect_enabled
    if mode != MODE_LATCH:
        return
    effect_enabled = not effect_enabled
    apply_current_sound()

def on_double_tap_layer1():
    start_preset_switch_with_mute()

def apply_scanned_setting_and_exit():
    """
    Layer 2 single-tap:
    apply selected mode (frozen at press time), then return to Layer 1.
    AND: blink selected MIDI channel 3x (NOTE ON/OFF) as confirmation.
    """
    global mode, runtime_layer, scan_paused

    idx = selected_setting_index

    if idx == 0:
        mode = MODE_LATCH
    elif idx == 1:
        mode = MODE_MOMENTARY
    elif idx == 2:
        mode = MODE_HOLDING
    else:
        mode = MODE_SHUTTER

    blink_selected_channel()

    runtime_layer = LAYER_PRESET
    scan_paused = False
    apply_current_sound()

def restart_preset_programming():
    """
    Re-enter boot programming for preset A + preset B (stages 0 and 1),
    without reboot. Triggered by long-hold in Layer 2.

    WICHTIG:
    - Alte Presets NICHT sofort löschen.
    - Erst wenn A+B wirklich neu gespeichert wurden, werden sie übernommen.
    """
    global programming_done, stage, selection_index, scan_direction
    global scan_paused, last_scan_step_ms
    global pending_single_tap, layer2_long_hold_fired
    global momentary_engaged, holding_armed, holding_off_at
    global shutter_active, shutter_phase_on, shutter_next_toggle_at
    global reprog_active, reprog_temp, stored_preset_index

    # clear any pending taps
    pending_single_tap = False

    # ✅ staging aktivieren: alte Presets bleiben gültig, bis commit passiert
    reprog_active = True
    reprog_temp = stored_preset_index[:]  # copy

    # go back to boot programming stage 0
    stage = 0
    # optional: starte beim aktuellen Preset A, wenn vorhanden
    selection_index = reprog_temp[0] if reprog_temp[0] >= 0 else 0
    scan_direction = 1
    scan_paused = False
    last_scan_step_ms = time.ticks_ms()

    # enter programming mode
    programming_done = False

    # allow next long-hold only after release
    layer2_long_hold_fired = True

    # reset transient runtime states
    momentary_engaged = False
    holding_armed = False
    holding_off_at = 0
    shutter_active = False
    shutter_phase_on = False
    shutter_next_toggle_at = 0

    # feedback + show first boot item
    blink_selected_channel()
    show_boot_scan_item()

def enter_effect_layer():
    global runtime_layer, selection_index, last_scan_step_ms, scan_paused
    runtime_layer = LAYER_EFFECT
    selection_index = 0
    last_scan_step_ms = time.ticks_ms()
    scan_paused = False
    show_settings_layer_scan_item()

def exit_effect_layer():
    global runtime_layer
    runtime_layer = LAYER_PRESET
    apply_current_sound()

# =========================================================
# BOOT
# =========================================================
startup_sequence()
midi_cc(0, 0)
show_boot_scan_item()

# =========================================================
# MAIN LOOP
# =========================================================
try:
    while True:
        now = time.ticks_ms()
        update_pot_time_ms(now)

        # Apply after preset switch mute (Layer 1 only)
        if switch_apply_pending and time.ticks_diff(now, switch_mute_until) >= 0:
            switch_apply_pending = False
            apply_current_sound()

        # ----- Read layer switch with debounce (GPIO14 toggles layer) -----
        rawL = layer_sw.value()
        if rawL != last_layer:
            last_layer = rawL
            last_layer_change = now

        if time.ticks_diff(now, last_layer_change) >= DEBOUNCE_MS and stable_layer != last_layer:
            stable_layer = last_layer

            # Cancel any pending tap when changing layer
            pending_single_tap = False

            # Pull-up: 0 = switch ON (Layer2), 1 = switch OFF (Layer1)
            if stable_layer == 0:
                enter_effect_layer()
            else:
                exit_effect_layer()

        # Resolve delayed single-tap (nur Single-Tap ausführen!)
        if pending_single_tap and time.ticks_diff(now, pending_single_tap_deadline) >= 0:
            pending_single_tap = False
            if programming_done:
                if runtime_layer == LAYER_PRESET:
                    on_single_tap_layer1()
                else:
                    apply_scanned_setting_and_exit()

        # Holding auto-OFF (Layer 1 only)
        if programming_done and runtime_layer == LAYER_PRESET and mode == MODE_HOLDING and momentary_engaged:
            if time.ticks_diff(now, holding_off_at) >= 0:
                pc = current_active_pc()
                send_effect_off(pc)
                momentary_engaged = False

        # Momentary/Holding/Shutter trigger (Layer 1 only, disabled during preset-switch mute)
        if programming_done and runtime_layer == LAYER_PRESET and stable_sw == 0 and (not switch_apply_pending):
            if mode == MODE_MOMENTARY:
                if (not momentary_engaged) and time.ticks_diff(now, press_start_ms) >= MOMENTARY_HOLD_MS:
                    momentary_engaged = True
                    pc = current_active_pc()
                    send_effect_on(pc)

            elif mode == MODE_HOLDING:
                if (not holding_armed) and (not momentary_engaged) and time.ticks_diff(now, press_start_ms) >= MOMENTARY_HOLD_MS:
                    holding_armed = True
                    momentary_engaged = True
                    pc = current_active_pc()
                    send_effect_on(pc)
                    holding_off_at = time.ticks_add(now, pot_time_ms)

            elif mode == MODE_SHUTTER:
                # Start shutter after hold threshold; start phase = ON
                if (not shutter_active) and time.ticks_diff(now, press_start_ms) >= MOMENTARY_HOLD_MS:
                    shutter_active = True
                    shutter_phase_on = True
                    pc = current_active_pc()
                    shutter_start(pc)  # FIX: CC0 once + PC ON (no CC spam later)
                    shutter_next_toggle_at = time.ticks_add(now, pot_time_ms)

        # Shutter toggling (PC-only Active <-> Bypass), while pressed (Layer 1 only)
        if programming_done and runtime_layer == LAYER_PRESET and mode == MODE_SHUTTER and stable_sw == 0 and shutter_active:
            if time.ticks_diff(now, shutter_next_toggle_at) >= 0:
                pc = current_active_pc()
                if shutter_phase_on:
                    shutter_off_phase(pc)   # FIX: PC only
                    shutter_phase_on = False
                else:
                    shutter_on_phase(pc)    # FIX: PC only
                    shutter_phase_on = True

                shutter_next_toggle_at = time.ticks_add(now, pot_time_ms)

        # Layer 2 long-hold => restart preset programming (stages 0+1)
        # ✅ Nur wenn der Press in Layer 2 gestartet wurde!
        if programming_done and runtime_layer == LAYER_EFFECT and stable_sw == 0:
            if (press_layer == LAYER_EFFECT) and (not layer2_long_hold_fired) and time.ticks_diff(now, press_start_ms) >= LAYER2_REPROGRAM_HOLD_MS:
                restart_preset_programming()

        # ----- Read footswitch with debounce -----
        raw = sw.value()
        if raw != last_sw:
            last_sw = raw
            last_change = now

        if time.ticks_diff(now, last_change) >= DEBOUNCE_MS and stable_sw != last_sw:
            stable_sw = last_sw

            # =========================
            # PRESS
            # =========================
            if stable_sw == 0:
                press_start_ms = now
                press_layer = runtime_layer  # ✅ Press-Layer merken

                if programming_done:
                    momentary_engaged = False
                    holding_armed = False
                    holding_off_at = 0

                    shutter_active = False
                    shutter_phase_on = False
                    shutter_next_toggle_at = 0

                    # allow long-hold again (fires only once per hold)
                    layer2_long_hold_fired = False

                    # freeze Layer 2 selection while pressing
                    if runtime_layer == LAYER_EFFECT:
                        scan_paused = True
                        selected_setting_index = selection_index

                else:
                    scan_paused = True

                    if stage <= 1:
                        # ✅ während Reprogramming in TEMP schreiben, nicht direkt überschreiben
                        if reprog_active:
                            reprog_temp[stage] = selection_index
                        else:
                            stored_preset_index[stage] = selection_index

                        _, pc = PRESETS[selection_index]
                        confirm_saved_preset_pc_only(pc)

                    else:
                        # Boot stage 3: select mode by index
                        if selection_index == 0:
                            mode = MODE_LATCH
                        elif selection_index == 1:
                            mode = MODE_MOMENTARY
                        elif selection_index == 2:
                            mode = MODE_HOLDING
                        else:
                            mode = MODE_SHUTTER

                        if mode == MODE_LATCH:
                            send_effect_on(0)
                        else:
                            send_effect_off(0)

            # =========================
            # RELEASE
            # =========================
            else:
                press_dur = time.ticks_diff(now, press_start_ms)

                if programming_done:
                    # NOTE: Layer switching is now ONLY via GPIO14.
                    if runtime_layer == LAYER_PRESET:
                        # Momentary/Holding/Shutter off on release
                        if mode == MODE_MOMENTARY:
                            pc = current_active_pc()
                            send_effect_off(pc)
                            momentary_engaged = False

                        elif mode == MODE_HOLDING:
                            holding_armed = False

                        elif mode == MODE_SHUTTER:
                            pc = current_active_pc()
                            shutter_stop(pc)  # FIX: end in bypass (CC0 once)
                            shutter_active = False
                            shutter_phase_on = False
                            shutter_next_toggle_at = 0

                        # tap / double tap (Layer 1)
                        if press_dur <= LAYER2_TAP_MAX_MS:
                            if pending_single_tap and time.ticks_diff(now, last_release_ms) <= DOUBLE_TAP_WINDOW_MS:
                                pending_single_tap = False
                                on_double_tap_layer1()   # ✅ Preset/Slot wechseln
                            else:
                                pending_single_tap = True
                                last_release_ms = now
                                pending_single_tap_deadline = time.ticks_add(now, DOUBLE_TAP_WINDOW_MS)

                    else:
                        # Layer 2 (Settings):
                        # long-hold already handled while pressed -> do NOT apply setting then
                        if layer2_long_hold_fired:
                            pending_single_tap = False
                        else:
                            # single tap (delayed): apply mode + exit
                            if press_dur <= TAP_MAX_MS:
                                if pending_single_tap and time.ticks_diff(now, last_release_ms) <= DOUBLE_TAP_WINDOW_MS:
                                    pending_single_tap = False
                                else:
                                    pending_single_tap = True
                                    last_release_ms = now
                                    pending_single_tap_deadline = time.ticks_add(now, DOUBLE_TAP_WINDOW_MS)

                        # allow scanning again after release
                        scan_paused = False

                else:
                    # Boot programming stage advance
                    if stage < (STAGES - 1):

                        # ✅ COMMIT: erst wenn Stage 1 abgeschlossen ist (A+B gesetzt)
                        if stage == 1 and reprog_active:
                            stored_preset_index = reprog_temp[:]  # jetzt erst überschreiben
                            reprog_active = False

                        stage += 1

                        # sinnvolle Startposition pro Stage
                        if stage <= 1:
                            # bei Stage 1 evtl. auf altes B springen
                            if reprog_active:
                                selection_index = reprog_temp[stage] if reprog_temp[stage] >= 0 else 0
                            else:
                                selection_index = stored_preset_index[stage] if stored_preset_index[stage] >= 0 else 0
                        else:
                            selection_index = 0

                        scan_direction = 1
                        last_scan_step_ms = now
                        scan_paused = False
                        show_boot_scan_item()
                    else:
                        programming_done = True
                        scan_paused = True
                        reprog_active = False  # safety

                        runtime_layer = LAYER_PRESET
                        active_slot = 0
                        effect_enabled = True
                        apply_current_sound()

        # =========================
        # Layer 2 scanning (settings layer)
        # =========================
        if programming_done and runtime_layer == LAYER_EFFECT:
            if (not scan_paused) and time.ticks_diff(now, last_scan_step_ms) >= SCAN_INTERVAL_MS_BOOT:
                last_scan_step_ms = now
                selection_index = (selection_index + 1) % len(SETTINGS)
                show_settings_layer_scan_item()

        # =========================
        # Boot scan stepping (programming)
        # =========================
        if (not programming_done) and (not scan_paused) and time.ticks_diff(now, last_scan_step_ms) >= SCAN_INTERVAL_MS_BOOT:
            last_scan_step_ms = now
            if stage <= 1:
                selection_index = (selection_index + scan_direction) % len(PRESETS)
            else:
                selection_index = (selection_index + scan_direction) % len(SETTINGS)
            show_boot_scan_item()

        time.sleep_ms(1)

except KeyboardInterrupt:
    pass

