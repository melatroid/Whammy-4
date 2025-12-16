from machine import Pin, ADC, UART
import time

SHOWVALUES = True
TEST_CHANNELS = True

PIN_FOOTSW = 4
PIN_LAYER_SWITCH = 14
PIN_POT = 26

DEBOUNCE_MS = 30
POLL_MS = 5
PRINT_EVERY_MS = 1000

POT_SMOOTH_ALPHA_NUM = 1
POT_SMOOTH_ALPHA_DEN = 8
POT_PRINT_THRESHOLD_8BIT = 3

MIDI_ENABLED = True
MIDI_UART_ID = 0
MIDI_TX_PIN = 0
MIDI_BAUD = 31250

CHANNEL_TEST_SEND_CC0 = True
CHANNEL_TEST_SEND_PC = True
CHANNEL_TEST_CC_NUM = 0
CHANNEL_TEST_CC_ON = 127
CHANNEL_TEST_CC_OFF = 0
CHANNEL_TEST_PULSE_MS = 60

PRESETS = [
    ("Detune Shallow", 0),
    ("Detune Deep", 1),
    ("Whammy: Up 2 Oct", 2),
    ("Whammy: Up 1 Oct", 3),
    ("Whammy: Down 1 Oct", 4),
    ("Whammy: Down 2 Oct", 5),
    ("Whammy: Dive Bomb", 6),
    ("Whammy: Drop Tune", 7),
    ("Harmony: 2nd/3rd", 8),
    ("Harmony: b3rd/3rd", 9),
    ("Harmony: 3rd/4th", 10),
    ("Harmony: 4th/5th", 11),
    ("Harmony: 5th/6th", 12),
    ("Harmony: 5th/7th", 13),
    ("Harmony: 4th/3rd", 14),
    ("Harmony: 5th/4th", 15),
    ("Harmony: Oct/Oct", 16),
]

footsw = Pin(PIN_FOOTSW, Pin.IN, Pin.PULL_UP)
layer_sw = Pin(PIN_LAYER_SWITCH, Pin.IN, Pin.PULL_UP)
pot = ADC(Pin(PIN_POT))

midi = None
if MIDI_ENABLED:
    midi = UART(MIDI_UART_ID, baudrate=MIDI_BAUD, tx=Pin(MIDI_TX_PIN))

def midi_write(data):
    if MIDI_ENABLED and midi is not None:
        midi.write(data)

def midi_cc(cc, val, ch0):
    midi_write(bytes([0xB0 | (ch0 & 0x0F), cc & 0x7F, val & 0x7F]))

def midi_pc(pc, ch0):
    midi_write(bytes([0xC0 | (ch0 & 0x0F), pc & 0x7F]))

def debounce_init(pin):
    v = pin.value()
    now = time.ticks_ms()
    return {"stable": v, "last_raw": v, "last_change_ms": now}

def debounce_update(pin, state, now_ms):
    raw = pin.value()
    if raw != state["last_raw"]:
        state["last_raw"] = raw
        state["last_change_ms"] = now_ms
    if time.ticks_diff(now_ms, state["last_change_ms"]) >= DEBOUNCE_MS:
        if state["stable"] != state["last_raw"]:
            state["stable"] = state["last_raw"]

def pressed_from_pullup(stable_raw):
    return stable_raw == 0

def adc_to_8bit(v_u16):
    return (v_u16 * 255 + 32767) // 65535

fs_state = debounce_init(footsw)
ly_state = debounce_init(layer_sw)

raw8 = adc_to_8bit(pot.read_u16())
filt8 = raw8

last_pot_8_reported = filt8
pending_pot_8 = last_pot_8_reported
pending_pot_changed = False

last_tick_ms = time.ticks_ms()
ch_test_0 = 0
preset_index = 0

print("=== INPUT + CHANNEL TEST (1Hz) ===")
print("Ctrl+C to stop\n")

try:
    while True:
        now = time.ticks_ms()

        debounce_update(footsw, fs_state, now)
        debounce_update(layer_sw, ly_state, now)

        raw8 = adc_to_8bit(pot.read_u16())
        filt8 = filt8 + (POT_SMOOTH_ALPHA_NUM * (raw8 - filt8)) // POT_SMOOTH_ALPHA_DEN

        if abs(filt8 - last_pot_8_reported) >= POT_PRINT_THRESHOLD_8BIT:
            pending_pot_8 = filt8
            pending_pot_changed = True

        if (SHOWVALUES or TEST_CHANNELS) and time.ticks_diff(now, last_tick_ms) >= PRINT_EVERY_MS:
            fs_pressed = pressed_from_pullup(fs_state["stable"])
            ly_on = pressed_from_pullup(ly_state["stable"])
            layer = "LAYER_2" if ly_on else "LAYER_1"

            if pending_pot_changed:
                last_pot_8_reported = pending_pot_8
                pending_pot_changed = False

            ch_1based = ch_test_0 + 1

            if TEST_CHANNELS:
                if CHANNEL_TEST_SEND_PC:
                    _, pc = PRESETS[preset_index]
                    midi_pc(pc, ch_test_0)
                if CHANNEL_TEST_SEND_CC0:
                    midi_cc(CHANNEL_TEST_CC_NUM, CHANNEL_TEST_CC_ON, ch_test_0)
                    time.sleep_ms(CHANNEL_TEST_PULSE_MS)
                    midi_cc(CHANNEL_TEST_CC_NUM, CHANNEL_TEST_CC_OFF, ch_test_0)

            if SHOWVALUES:
                preset_name, preset_pc = PRESETS[preset_index]
                print(
                    f"CH={ch_1based:02d} | "
                    f"FOOTSW={fs_pressed} | "
                    f"LAYER_SW={ly_on} ({layer}) | "
                    f"POT_8bit={last_pot_8_reported:3d} | "
                    f"PC={preset_pc:02d} {preset_name}"
                )
            else:
                print(f"CH={ch_1based:02d}")

            ch_test_0 = (ch_test_0 + 1) % 16
            preset_index = (preset_index + 1) % len(PRESETS)
            last_tick_ms = now

        time.sleep_ms(POLL_MS)

except KeyboardInterrupt:
    print("\nTest stopped.")

