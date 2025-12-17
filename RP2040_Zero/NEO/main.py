# Melatroid - Whammy 4 NEO - Version 2.20


from machine import UART, Pin, ADC
import time
import urandom

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

# Momentary/Holding/Shutter/Harmony/StepSeq trigger (must be higher than tap)
MOMENTARY_HOLD_MS = 500

# re-enter preset programming from Layer 2 via long-hold
LAYER2_REPROGRAM_HOLD_MS = 2000
# Prevent effect "blip" during preset switching:
SWITCH_MUTE_MS = 250

sw = Pin(PIN_FOOTSW, Pin.IN, Pin.PULL_UP)
layer_sw = Pin(PIN_LAYER_SWITCH, Pin.IN, Pin.PULL_UP)

# =========================================================
# POTENTIOMETER (Holding-time / Shutter interval / Runner step control)
#   FIX: non-linear mapping + separate ranges per mode
#   + StepSeq uses pot_time_ms for step time AND pot_shape for live random intensity
# =========================================================
POT_ADC_PIN = 26

# Holding mode range (long times)
HOLD_MIN_MS = 200
HOLD_MAX_MS = 5000

# Shutter mode range (fast musically useful chop speed)
# (this is per PHASE: ON->OFF or OFF->ON)
SHUTTER_MIN_MS = 30
SHUTTER_MAX_MS = 400

# Runner (Harmony/StepSeq) step time range (ms)
HARMONY_STEP_MIN_MS = 50
HARMONY_STEP_MAX_MS = 800

POT_READ_INTERVAL_MS = 40
POT_SHAPE_READ_INTERVAL_MS = 60

pot = ADC(POT_ADC_PIN)
pot_time_ms = 1000
_last_pot_read_ms = 0

pot_shape = 0
_last_pot_shape_read_ms = 0


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
MODE_HARMONY = 4
MODE_STEPSEQ = 5   # NEW
MODE_LEGACY = 6    # moved down (fixes settings mapping)
mode = MODE_LATCH


def update_pot_time_ms(now_ms: int):
    """
    - MODE_HOLDING => 200..5000ms (expo-ish)
    - MODE_SHUTTER => 30..400ms   (expo-ish, more resolution at fast end)
    - MODE_HARMONY => 50..800ms   (expo-ish, more resolution at fast end)
    - MODE_STEPSEQ => 50..800ms   (expo-ish, more resolution at fast end)
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

    elif mode == MODE_HARMONY or mode == MODE_STEPSEQ:
        pot_time_ms = map_u16_expo(raw, HARMONY_STEP_MIN_MS, HARMONY_STEP_MAX_MS, k_percent=600)
        pot_time_ms = clamp(pot_time_ms, HARMONY_STEP_MIN_MS, HARMONY_STEP_MAX_MS)

    else:
        pot_time_ms = 1000


def update_pot_shape(now_ms: int):
    """
    Separate pot-derived parameter used by StepSeq for LIVE random mutation intensity.
    Read it at a slightly slower rate; it can share the same ADC.
    """
    global pot_shape, _last_pot_shape_read_ms
    if time.ticks_diff(now_ms, _last_pot_shape_read_ms) < POT_SHAPE_READ_INTERVAL_MS:
        return
    _last_pot_shape_read_ms = now_ms
    pot_shape = pot.read_u16()  # 0..65535


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
    ("Mode: Latch (default ON)", 0),              # idx 0
    ("Mode: Momentary (default OFF)", 1),         # idx 1
    ("Mode: Holding (pot timeout)", 16),          # idx 2
    ("Mode: Shutter (pot timeout)", 15),          # idx 3
    ("Mode: Harmony (pot timeout)", 14),          # idx 4
    ("Mode: Step Sequenzer       ", 13),          # idx 5
    ("Mode: Legacy  No Presets   ", 7),           # idx 6
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

# =========================================================
# RUNTIME LAYERS (GPIO14 controls this)
# =========================================================
LAYER_PRESET = 0   # Layer 1: performance
LAYER_EFFECT = 1   # Layer 2: SETTINGS menu

runtime_layer = LAYER_PRESET

# Boot/Programming state (needed for PC gating)
STAGES = 3
stage = 0
programming_done = False


def midi_pc(pc: int):
    # Legacy blocks ONLY in Layer 1 (performance) after programming is done.
    # Layer 2 stays unchanged and may send PC for scrolling feedback.
    if programming_done and (runtime_layer == LAYER_PRESET) and (mode == MODE_LEGACY):
        return
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
    blink_selected_channel(times=10, on_ms=80, off_ms=40)
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
# HARMONY RUNNER (3 MODES) with pot-controlled step time
#   - Short tap in Layer 1 cycles mode: DOWN -> UP -> PINGPONG
#   - Hold starts runner (unchanged)
# =========================================================
HARMONY_MODE_DOWN = 0     # 15 -> 8
HARMONY_MODE_UP = 1       # 8 -> 15
HARMONY_MODE_PINGPONG = 2 # 15 -> 8 -> 15 -> ...

harmony_mode = HARMONY_MODE_DOWN  # default (top->down)

def build_harmony_seq(hmode: int):
    down = list(range(15, 7, -1))   # 15..8
    up = list(range(8, 16, 1))      # 8..15
    if hmode == HARMONY_MODE_DOWN:
        return down
    elif hmode == HARMONY_MODE_UP:
        return up
    else:
        # pingpong without double-hitting endpoints:
        # 15..8 then 9..14 then repeat via modulo
        return down + list(range(9, 15, 1))  # 9..14

harmony_seq = build_harmony_seq(harmony_mode)

harmony_active = False
harmony_i = 0
harmony_next_step_at = 0
harmony_last_pc = 15

def harmony_rebuild_seq():
    global harmony_seq
    harmony_seq = build_harmony_seq(harmony_mode)

def cycle_harmony_mode():
    global harmony_mode
    harmony_mode = (harmony_mode + 1) % 3
    # feedback: 1x/2x/3x blink depending on mode
    blink_selected_channel(times=harmony_mode + 1, on_ms=60, off_ms=60)

def harmony_start(now_ms: int):
    global harmony_active, harmony_i, harmony_next_step_at, harmony_last_pc
    harmony_rebuild_seq()
    harmony_active = True
    harmony_i = 0
    harmony_last_pc = harmony_seq[harmony_i]
    midi_cc(0, 127)               # arm once
    midi_pc(harmony_last_pc)      # initial PC
    harmony_next_step_at = time.ticks_add(now_ms, pot_time_ms)

def harmony_step(now_ms: int):
    global harmony_i, harmony_next_step_at, harmony_last_pc
    harmony_i = (harmony_i + 1) % len(harmony_seq)
    harmony_last_pc = harmony_seq[harmony_i]
    midi_pc(harmony_last_pc)      # PC only
    harmony_next_step_at = time.ticks_add(now_ms, pot_time_ms)

def harmony_stop():
    global harmony_active
    if not harmony_active:
        return
    harmony_active = False
    midi_cc(0, 0)                 # disarm once
    midi_pc(pc_bypass(harmony_last_pc))

# =========================================================
# STEP SEQUENCER (like Harmony runner, but random pattern)
#   - Pattern generated ONCE when mode selected
#   - POT controls LIVE mutation intensity (swaps per step)
#   - Short tap cycles DOWN/UP/PINGPONG (pattern stays)
# =========================================================
STEPSEQ_MODE_DOWN = 0
STEPSEQ_MODE_UP = 1
STEPSEQ_MODE_PINGPONG = 2

stepseq_mode = STEPSEQ_MODE_DOWN

STEPSEQ_POOL = list(range(8, 16))     # Harmony preset PCs 8..15
stepseq_base = STEPSEQ_POOL[:]        # stored random permutation
stepseq_seq = []                      # derived playback seq

stepseq_active = False
stepseq_i = 0
stepseq_next_step_at = 0
stepseq_last_pc = 15

def stepseq_generate_base():
    """Generate a unique random permutation once, keep until mode is chosen again."""
    global stepseq_base
    arr = STEPSEQ_POOL[:]  # copy
    # Fisher-Yates shuffle
    for i in range(len(arr) - 1, 0, -1):
        j = urandom.getrandbits(16) % (i + 1)
        arr[i], arr[j] = arr[j], arr[i]
    stepseq_base = arr

def stepseq_build_seq():
    """Build playback sequence from the stored base + mode."""
    global stepseq_seq
    base = stepseq_base
    if stepseq_mode == STEPSEQ_MODE_UP:
        stepseq_seq = base[:]
    elif stepseq_mode == STEPSEQ_MODE_DOWN:
        stepseq_seq = base[::-1]
    else:
        # pingpong without double-hitting endpoints
        if len(base) >= 2:
            stepseq_seq = base + base[-2:0:-1]
        else:
            stepseq_seq = base[:]

def stepseq_cycle_mode():
    global stepseq_mode
    stepseq_mode = (stepseq_mode + 1) % 3
    blink_selected_channel(times=stepseq_mode + 1, on_ms=60, off_ms=60)

def stepseq_mutate_live():
    """
    Live randomization controlled by pot_shape:
    - low pot => no change
    - higher pot => more swaps per step
    """
    global stepseq_base

    # map 0..65535 to 0..6 swaps/step
    max_swaps = 6
    swaps = (pot_shape * max_swaps) >> 16  # 0..6
    if swaps == 0:
        return

    n = len(stepseq_base)
    for _ in range(swaps):
        i = urandom.getrandbits(16) % n
        j = urandom.getrandbits(16) % n
        if i != j:
            stepseq_base[i], stepseq_base[j] = stepseq_base[j], stepseq_base[i]

def stepseq_start(now_ms: int):
    global stepseq_active, stepseq_i, stepseq_next_step_at, stepseq_last_pc
    stepseq_build_seq()
    if not stepseq_seq:
        return
    stepseq_active = True
    stepseq_i = 0
    stepseq_last_pc = stepseq_seq[stepseq_i]
    midi_cc(0, 127)               # arm once
    midi_pc(stepseq_last_pc)      # initial PC
    stepseq_next_step_at = time.ticks_add(now_ms, pot_time_ms)

def stepseq_step(now_ms: int):
    global stepseq_i, stepseq_next_step_at, stepseq_last_pc

    # live influence each step:
    stepseq_mutate_live()
    stepseq_build_seq()

    stepseq_i = (stepseq_i + 1) % len(stepseq_seq)
    stepseq_last_pc = stepseq_seq[stepseq_i]
    midi_pc(stepseq_last_pc)      # PC only
    stepseq_next_step_at = time.ticks_add(now_ms, pot_time_ms)

def stepseq_stop():
    global stepseq_active
    if not stepseq_active:
        return
    stepseq_active = False
    midi_cc(0, 0)                 # disarm once
    midi_pc(pc_bypass(stepseq_last_pc))

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

stored_preset_index = [-1, -1]   # preset A, preset B

# --- Reprogram staging ---
reprog_active = False
reprog_temp = [-1, -1]

# Performance state
active_slot = 0
effect_enabled = True

# Legacy momentary runtime (Layer 1 only)
legacy_momentary_engaged = False

# Momentary/Holding runtime
momentary_engaged = False
holding_armed = False
holding_off_at = 0
holding_wait_release = False

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
    global harmony_active, harmony_next_step_at
    global legacy_momentary_engaged

    # stop transient engines cleanly
    harmony_stop()
    stepseq_stop()

    pc = current_active_pc()

    # Legacy behavior:
    # In Legacy we want ONLY CC0, and in Layer 1 it must act as true momentary:
    # - if footswitch is held (legacy_momentary_engaged) => CC ON
    # - otherwise => CC OFF
    if mode == MODE_LEGACY:
        midi_cc(0, 127 if legacy_momentary_engaged else 0)

        # reset transient states
        momentary_engaged = False
        holding_armed = False
        holding_off_at = 0
        shutter_active = False
        shutter_phase_on = False
        shutter_next_toggle_at = 0
        harmony_active = False
        harmony_next_step_at = 0
        return

    if mode == MODE_LATCH:
        if effect_enabled:
            send_effect_on(pc)
        else:
            send_effect_off(pc)
    else:
        # Momentary/Holding/Shutter/Harmony/StepSeq start only by press logic
        send_effect_off(pc)

    # reset transient states when applying a sound baseline
    momentary_engaged = False
    holding_armed = False
    holding_off_at = 0

    shutter_active = False
    shutter_phase_on = False
    shutter_next_toggle_at = 0

    harmony_active = False
    harmony_next_step_at = 0

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
    (Layer 2 stays unchanged, even in Legacy mode)
    """
    global selection_index
    _, pc = SETTINGS[selection_index]
    send_effect_off(pc)

def start_preset_switch_with_mute():
    global active_slot, switch_mute_until, switch_apply_pending
    global momentary_engaged, holding_armed, holding_off_at
    global shutter_active, shutter_phase_on, shutter_next_toggle_at
    global harmony_active, harmony_next_step_at

    # No preset switching in Legacy
    if mode == MODE_LEGACY:
        return

    if stored_preset_index[0] < 0 or stored_preset_index[1] < 0:
        return

    # stop transient engines cleanly before switching
    harmony_stop()
    stepseq_stop()

    pc_now = current_active_pc()
    if mode == MODE_LATCH and effect_enabled:
        active_slot = 1 - active_slot
        pc_new = current_active_pc()
        midi_pc(pc_new)
        return
    
    send_bypass_pc_only(pc_now)
    
    active_slot = 1 - active_slot

    momentary_engaged = False
    holding_armed = False
    holding_off_at = 0
    holding_wait_release = False

    shutter_active = False
    shutter_phase_on = False
    shutter_next_toggle_at = 0

    harmony_active = False
    harmony_next_step_at = 0

    switch_mute_until = time.ticks_add(time.ticks_ms(), SWITCH_MUTE_MS)
    switch_apply_pending = True

def on_single_tap_layer1():
    global effect_enabled
    # Legacy: no tap-toggle; Legacy is true momentary (press/release)
    if mode == MODE_LEGACY:
        return

    if mode != MODE_LATCH:
        return
    effect_enabled = not effect_enabled
    apply_current_sound()

def on_double_tap_layer1():
    # In Legacy: no preset slot switching
    if mode == MODE_LEGACY:
        return
    start_preset_switch_with_mute()

def apply_scanned_setting_and_exit():
    """
    Layer 2 single-tap:
    apply selected mode (frozen at press time), then return to Layer 1.
    AND: blink selected MIDI channel 3x (NOTE ON/OFF) as confirmation.
    """
    global mode, runtime_layer, scan_paused
    global legacy_momentary_engaged

    idx = selected_setting_index

    if idx == 0:
        mode = MODE_LATCH
    elif idx == 1:
        mode = MODE_MOMENTARY
    elif idx == 2:
        mode = MODE_HOLDING
    elif idx == 3:
        mode = MODE_SHUTTER
    elif idx == 4:
        mode = MODE_HARMONY
    elif idx == 5:
        mode = MODE_STEPSEQ       # ✅ StepSeq
    elif idx == 6:
        mode = MODE_LEGACY        # ✅ Legacy moved
    else:
        mode = MODE_LATCH

    # switching modes: start clean
    legacy_momentary_engaged = False

    # ✅ generate random pattern ONCE when StepSeq is selected
    if mode == MODE_STEPSEQ:
        stepseq_generate_base()

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
    global harmony_active, harmony_next_step_at
    global legacy_momentary_engaged

    # clear any pending taps
    pending_single_tap = False
    legacy_momentary_engaged = False

    # stop transient engines
    harmony_stop()
    stepseq_stop()

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
    harmony_active = False
    harmony_next_step_at = 0

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
        update_pot_shape(now)

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

        # Holding auto-OFF (Layer 1 only) - disabled in Legacy (no PC-based hold)
        if (programming_done and runtime_layer == LAYER_PRESET and mode == MODE_HOLDING
            and momentary_engaged and mode != MODE_LEGACY):
            if time.ticks_diff(now, holding_off_at) >= 0:
                pc = current_active_pc()
                send_effect_off(pc)
                momentary_engaged = False

        # Momentary/Holding/Shutter/Harmony/StepSeq trigger (Layer 1 only, disabled during preset-switch mute)
        if programming_done and runtime_layer == LAYER_PRESET and stable_sw == 0 and (not switch_apply_pending):
            # Legacy: do NOT start any PC-based engines. Legacy is handled on PRESS/RELEASE only.
            if mode == MODE_LEGACY:
                pass

            elif mode == MODE_MOMENTARY:
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
                    holding_off_at = 0
                    holding_wait_release = True

            elif mode == MODE_SHUTTER:
                # Start shutter after hold threshold; start phase = ON
                if (not shutter_active) and time.ticks_diff(now, press_start_ms) >= MOMENTARY_HOLD_MS:
                    shutter_active = True
                    shutter_phase_on = True
                    pc = current_active_pc()
                    shutter_start(pc)  # CC0 once + PC ON (no CC spam later)
                    shutter_next_toggle_at = time.ticks_add(now, pot_time_ms)

            elif mode == MODE_HARMONY:
                # Start harmony runner after hold threshold
                if (not harmony_active) and time.ticks_diff(now, press_start_ms) >= MOMENTARY_HOLD_MS:
                    harmony_start(now)

            elif mode == MODE_STEPSEQ:
                # Start step sequencer after hold threshold
                if (not stepseq_active) and time.ticks_diff(now, press_start_ms) >= MOMENTARY_HOLD_MS:
                    stepseq_start(now)

        # Shutter toggling (PC-only Active <-> Bypass), while pressed (Layer 1 only)
        if programming_done and runtime_layer == LAYER_PRESET and mode == MODE_SHUTTER and stable_sw == 0 and shutter_active:
            if time.ticks_diff(now, shutter_next_toggle_at) >= 0:
                pc = current_active_pc()
                if shutter_phase_on:
                    shutter_off_phase(pc)   # PC only
                    shutter_phase_on = False
                else:
                    shutter_on_phase(pc)    # PC only
                    shutter_phase_on = True

                shutter_next_toggle_at = time.ticks_add(now, pot_time_ms)

        # Harmony runner stepping, while pressed (Layer 1 only)
        if programming_done and runtime_layer == LAYER_PRESET and mode == MODE_HARMONY and stable_sw == 0 and harmony_active:
            if time.ticks_diff(now, harmony_next_step_at) >= 0:
                harmony_step(now)

        # StepSeq runner stepping, while pressed (Layer 1 only)
        if programming_done and runtime_layer == LAYER_PRESET and mode == MODE_STEPSEQ and stable_sw == 0 and stepseq_active:
            if time.ticks_diff(now, stepseq_next_step_at) >= 0:
                stepseq_step(now)

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

                    # Legacy: immediate CC ON in Layer 1 (no delay)
                    if runtime_layer == LAYER_PRESET and mode == MODE_LEGACY:
                        legacy_momentary_engaged = True
                        midi_cc(0, 127)
                        pending_single_tap = False  # no tap logic in legacy

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
                        elif selection_index == 3:
                            mode = MODE_SHUTTER
                        elif selection_index == 4:
                            mode = MODE_HARMONY
                        elif selection_index == 5:
                            mode = MODE_STEPSEQ
                            stepseq_generate_base()   # ✅ generate once on selection
                        elif selection_index == 6:
                            mode = MODE_LEGACY
                        else:
                            mode = MODE_LATCH

                        # mode feedback during boot stage
                        if mode == MODE_LATCH:
                            send_effect_on(0)
                        elif mode == MODE_LEGACY:
                            legacy_momentary_engaged = False
                            midi_cc(0, 0)
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

                        # Legacy: immediate CC OFF on release, skip tap/doubletap/engines
                        if mode == MODE_LEGACY:
                            legacy_momentary_engaged = False
                            midi_cc(0, 0)
                            pending_single_tap = False
                        else:
                            # Momentary/Holding/Shutter/Harmony/StepSeq off on release
                            if mode == MODE_MOMENTARY:
                                pc = current_active_pc()
                                send_effect_off(pc)
                                momentary_engaged = False

                            elif mode == MODE_HOLDING:
                                holding_armed = False

                                # Timer erst nach Release starten
                                if momentary_engaged and holding_wait_release:
                                    holding_off_at = time.ticks_add(now, pot_time_ms)
                                    holding_wait_release = False
                                    
                            elif mode == MODE_SHUTTER:
                                pc = current_active_pc()
                                shutter_stop(pc)  # end in bypass (CC0 once)
                                shutter_active = False
                                shutter_phase_on = False
                                shutter_next_toggle_at = 0

                            elif mode == MODE_HARMONY:
                                harmony_stop()

                            elif mode == MODE_STEPSEQ:
                                stepseq_stop()

                            # ✅ Harmony: short tap cycles harmony runner mode (DOWN/UP/PINGPONG)
                            if mode == MODE_HARMONY and press_dur < MOMENTARY_HOLD_MS:
                                cycle_harmony_mode()
                                pending_single_tap = False

                            # ✅ StepSeq: short tap cycles runner mode (DOWN/UP/PINGPONG)
                            elif mode == MODE_STEPSEQ and press_dur < MOMENTARY_HOLD_MS:
                                stepseq_cycle_mode()
                                pending_single_tap = False

                            else:
                                # tap / double tap (Layer 1)
                                if press_dur <= LAYER2_TAP_MAX_MS:
                                    if pending_single_tap and time.ticks_diff(now, last_release_ms) <= DOUBLE_TAP_WINDOW_MS:
                                        pending_single_tap = False
                                        on_double_tap_layer1()   # Preset/Slot wechseln
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
                        legacy_momentary_engaged = False
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

