
# Melatroid
# Whammy 4 - Shutter Gate Effect
# 
from machine import Pin, ADC
import time

# =========================================================
# DEBUG
# =========================================================
DEBUG = False
DEBUG_A_EVENTS = False
DEBUG_A_SCOPE = True
SCOPE_EVERY_MS = 5
SCOPE_WIDTH = 80

# =========================================================
# DEVELOPMENT BYPASS
# =========================================================
DEV_BYPASS_MOMENTARY = False

# =========================================================
# PC SOUND (Serial Frequency Output)
# =========================================================
FREQ_SEND_EVERY_MS = 50

# =========================================================
# BYPASS / GATE LOGIC
# =========================================================
BYPASS_B_INVERT = True   
BBM_DELAY_US = 20    

def dbg(msg):
    if DEBUG:
        print(msg)

def a_dbg(msg):
    if DEBUG_A_EVENTS:
        print(msg)

# ---------------- Pins ----------------
PIN_A = 2
PIN_B = 3
PIN_FOOTSW = 4
PIN_POT = 26

# ---------------- Pegel ----------------
DRY = 0
WET = 1

# ---------------- Timing ----------------
POT_EVERY_MS = 10
MIN_HALF_MS = 30
MAX_HALF_MS = 1000
DEBOUNCE_MS = 30
SEQ_DELAY_MS = 5
DEBUG_EVERY_MS = 100

# ---------------- Poti-Filter ----------------
POT_WINDOW = 10
POT_MAX_DEV = 200
POT_FORCE_AFTER = 4

# ---------------- Setup ----------------
a = Pin(PIN_A, Pin.OUT, value=DRY)
b = Pin(PIN_B, Pin.OUT, value=1)

sw = Pin(PIN_FOOTSW, Pin.IN, Pin.PULL_UP)
pot = ADC(Pin(PIN_POT))

def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v

def map_pot_to_half_ms(v):
    span = MAX_HALF_MS - MIN_HALF_MS
    return MAX_HALF_MS - (v * span // 65535)

def a_name(v): return "WET" if v else "DRY"
def b_name(v): return "ON" if v else "OFF"

def b_write_raw(v01: int):
    """Schreibt 0/1 auf B, optional invertiert."""
    if BYPASS_B_INVERT:
        b.value(0 if v01 else 1)
    else:
        b.value(v01)

def set_A_and_B(a_val: int):
    """
    Wechselalgorithmus mit Reihenfolge (Break-before-make):
      - A soll 1 werden: erst B=0 (Bypass weg), dann A=1
      - A soll 0 werden: erst A=0, dann B=1 (Bypass rein)
    Dabei gilt immer: B = NOT A
    """
    global a_state
    new_a = 1 if a_val else 0
    old_a = a_state

    if new_a == old_a:
        return

    if new_a == 1:
        # erst Bypass weg, dann A an
        b_write_raw(0)  # B=0
        if BBM_DELAY_US:
            time.sleep_us(BBM_DELAY_US)
        a_state = 1
        a.value(1)
    else:
        # erst A aus, dann Bypass rein
        a_state = 0
        a.value(0)
        if BBM_DELAY_US:
            time.sleep_us(BBM_DELAY_US)
        b_write_raw(1)  # B=1

# ---------------- Debounce ----------------
stable_sw = sw.value()
last_sw = stable_sw
last_change = time.ticks_ms()

# ---------------- Runtime ----------------
active = False
a_state = DRY
last_toggle = time.ticks_ms()
last_dbg = time.ticks_ms()

# Realtime-Debug A
last_a_toggle_ms = last_toggle
last_scope_ms = time.ticks_ms()
scope_count = 0

# PC freq sender
last_freq_send = time.ticks_ms()

# Pot cache
pot_u16_raw = 0
pot_u16_mean = 0
pot_pct = 0
half_ms = MAX_HALF_MS
freq_hz = 1000 / (2 * half_ms)
last_pot_ms = time.ticks_ms()

# Filter-Zustand
pot_hist = []
pot_rejects = 0
pot_outlier_streak = 0
pot_outlier_dir = 0

def pot_reset_and_prime():
    global pot_u16_raw, pot_u16_mean, pot_hist, pot_rejects
    global pot_outlier_streak, pot_outlier_dir

    pot_rejects = 0
    pot_outlier_streak = 0
    pot_outlier_dir = 0

    pot_u16_raw = pot.read_u16()
    pot_hist = [pot_u16_raw]
    pot_u16_mean = pot_u16_raw

def pot_update_filtered():
    global pot_u16_raw, pot_u16_mean, pot_hist, pot_rejects
    global pot_outlier_streak, pot_outlier_dir

    pot_u16_raw = pot.read_u16()

    if not pot_hist:
        pot_hist = [pot_u16_raw]
        pot_u16_mean = pot_u16_raw
        pot_outlier_streak = 0
        pot_outlier_dir = 0
        return True

    prev_mean = pot_u16_mean
    diff = pot_u16_raw - prev_mean

    if abs(diff) > POT_MAX_DEV:
        pot_rejects += 1

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

def set_effect(on: bool):
    """
    Fix: Beim Einschalten SOFORT mit EIN-Phase starten (A=1).
    Beim Ausschalten: A=0 dann B=1.
    """
    global active, last_toggle, last_a_toggle_ms, last_pot_ms
    global pot_pct, half_ms, freq_hz, last_freq_send, scope_count

    if on:
        active = True

        now0 = time.ticks_ms()

        # Poti sofort initialisieren, damit half_ms passt bevor wir A setzen
        pot_reset_and_prime()
        pot_pct = (pot_u16_mean * 100) // 65535
        half_ms = clamp(map_pot_to_half_ms(pot_u16_mean), MIN_HALF_MS, MAX_HALF_MS)
        freq_hz = 1000 / (2 * half_ms)
        last_pot_ms = now0

        # Start: SOFORT A=1 (damit B=0)
        set_A_and_B(WET)

        # Timer so setzen, dass erst nach half_ms wieder getoggelt wird
        last_toggle = now0
        last_a_toggle_ms = now0
        last_freq_send = now0

        if DEBUG_A_SCOPE:
            print("\n[SCOPE START]")
            scope_count = 0

    else:
        active = False
        set_A_and_B(DRY)
        time.sleep_ms(SEQ_DELAY_MS)
        if DEBUG_A_SCOPE:
            print("\n[SCOPE STOP]\n")

dbg("RP2040 Momentary Shutter DEBUG gestartet")

# BOOT-SAFE
set_effect(False)

# DEV BYPASS
if DEV_BYPASS_MOMENTARY:
    set_effect(True)

try:
    while True:
        now = time.ticks_ms()

        # ---- Footswitch ----
        if not DEV_BYPASS_MOMENTARY:
            raw_sw = sw.value()
            if raw_sw != last_sw:
                last_sw = raw_sw
                last_change = now

            if time.ticks_diff(now, last_change) >= DEBOUNCE_MS and stable_sw != last_sw:
                stable_sw = last_sw
                new_active = (stable_sw == 0)  # pressed = LOW
                if new_active != active:
                    set_effect(new_active)
        else:
            raw_sw = 0

        # ---- Poti nur während Effekt AN ----
        if active and time.ticks_diff(now, last_pot_ms) >= POT_EVERY_MS:
            last_pot_ms = now
            pot_update_filtered()

            pot_pct = (pot_u16_mean * 100) // 65535
            half_ms = clamp(map_pot_to_half_ms(pot_u16_mean), MIN_HALF_MS, MAX_HALF_MS)
            freq_hz = 1000 / (2 * half_ms)

        # ---- Shutter: toggelt A und damit B gegenläufig ----
        if active and time.ticks_diff(now, last_toggle) >= half_ms:
            last_toggle = now
            set_A_and_B(DRY if a_state else WET)

            if DEBUG_A_EVENTS:
                dt = time.ticks_diff(now, last_a_toggle_ms)
                last_a_toggle_ms = now
                a_dbg(f"[A TOGGLE] A={a_state} dt={dt}ms half={half_ms}ms")

        # ---- Scope ----
        if DEBUG_A_SCOPE and active and time.ticks_diff(now, last_scope_ms) >= SCOPE_EVERY_MS:
            last_scope_ms = now
            a_live = a.value()
            ch = "█" if a_live else "·"
            print(ch, end="")
            scope_count += 1
            if scope_count >= SCOPE_WIDTH:
                print(f"  half={half_ms}ms  A={a_state} B={b.value()}")
                scope_count = 0

        time.sleep_ms(1)

except KeyboardInterrupt:
    set_effect(False)
    dbg("Stop -> A=DRY, B=NOT(A)")

