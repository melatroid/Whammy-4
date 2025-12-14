from machine import UART, Pin
import time

# ============================
# MIDI OUT CONFIG
# ============================
MIDI_UART_ID = 0
MIDI_TX_PIN = 0           # GPIO0 -> MIDI DIN Pin 5 (via 220Ω)
MIDI_BAUD = 31250

# ============================
# TARGET CHANNEL
# ============================
TARGET_CH = 3  # 0-based: 3 = MIDI Channel 4

# ============================
# WHAMMY 4 (Manual) Mappings
# ============================
# Program Changes laut Manual:
# PC  1..17  = ACTIVE (Effect on)
# PC 18..34  = BYPASS (Effect off)
WHAMMY_PRESETS = [
    ("Detune Shallow", 1),
    ("Detune Deep", 2),
    ("Whammy +2 Oct", 3),
    ("Whammy +1 Oct", 4),
    ("Whammy -1 Oct", 5),
    ("Whammy -2 Oct", 6),
    ("Whammy Dive Bomb", 7),
    ("Whammy Drop Tune", 8),
    ("Harmony Oct/Oct", 9),
    ("Harmony 5th/4th", 10),
    ("Harmony 4th/3rd", 11),
    ("Harmony 5th/7th", 12),
    ("Harmony 5th/6th", 13),
    ("Harmony 4th/5th", 14),
    ("Harmony 3rd/4th", 15),
    ("Harmony b3rd/3rd", 16),
    ("Harmony 2nd/3rd", 17),
]

def pc_bypass(pc_active: int) -> int:
    return pc_active + 17  # Manual: bypass = active + 17

# ============================
# TEST SETTINGS
# ============================
PAUSE_BETWEEN_MSG = 1000    

TEST_PROGRAM_CHANGE = True
TEST_CC0_ON_OFF = True
TEST_CC11_SWEEP = False   

# CC11 Sweep Settings
CC11_STEP_DELAY_MS = 20
CC11_STEP = 8              

# ============================
# SETUP
# ============================
uart = UART(MIDI_UART_ID, baudrate=MIDI_BAUD, tx=Pin(MIDI_TX_PIN))

def midi_pc(program: int, channel: int):
    """Program Change: 0xC0..0xCF + program"""
    status = 0xC0 | (channel & 0x0F)
    uart.write(bytes([status, program & 0x7F]))

def midi_cc(cc: int, val: int, channel: int):
    """Control Change: 0xB0..0xBF + cc + val"""
    status = 0xB0 | (channel & 0x0F)
    uart.write(bytes([status, cc & 0x7F, val & 0x7F]))

def log(msg):
    print(msg)

def test_cc0(channel: int):
    # CC0: 0..64 OFF, 65..127 ON
    log(f"CH {channel+1:02d} -> CC0 OFF")
    midi_cc(0, 0, channel)
    time.sleep_ms(PAUSE_BETWEEN_MSG)

    log(f"CH {channel+1:02d} -> CC0 ON")
    midi_cc(0, 127, channel)
    time.sleep_ms(PAUSE_BETWEEN_MSG)

def test_cc11_sweep(channel: int):
    log(f"CH {channel+1:02d} -> CC11 sweep 0..127")
    for v in range(0, 128, CC11_STEP):
        midi_cc(11, v, channel)
        time.sleep_ms(CC11_STEP_DELAY_MS)
    for v in range(127, -1, -CC11_STEP):
        midi_cc(11, v, channel)
        time.sleep_ms(CC11_STEP_DELAY_MS)
    time.sleep_ms(PAUSE_BETWEEN_MSG)

def test_program_changes(channel: int):
    for name, pc_on in WHAMMY_PRESETS:
        pc_off = pc_bypass(pc_on)

        log(f"CH {channel+1:02d} -> PC {pc_on:02d} ACTIVE  ({name})")
        midi_pc(pc_on, channel)
        time.sleep_ms(PAUSE_BETWEEN_MSG)

        log(f"CH {channel+1:02d} -> PC {pc_off:02d} BYPASS  ({name})")
        midi_pc(pc_off, channel)
        time.sleep_ms(PAUSE_BETWEEN_MSG)

print("=== Whammy 4 MIDI ANALYSE (FIXED CHANNEL) ===")
print("Testet NUR Channel 4 (0-based = 3).")
print("- Program Change ACTIVE/BYPASS (Manual: 1..17 / 18..34)")
print("- CC0 ON/OFF (Manual: CC0 <65 OFF, >=65 ON)")
print("- optional CC11 sweep (Manual: CC11 = treadle 0..127)")
print("Abbruch: Ctrl+C\n")

try:
    while True:
        ch = TARGET_CH
        log(f"\n--- TESTING CHANNEL {ch+1} ---")

        if TEST_CC0_ON_OFF:
            test_cc0(ch)

        if TEST_PROGRAM_CHANGE:
            test_program_changes(ch)

        if TEST_CC11_SWEEP:
            test_cc11_sweep(ch)

        # Wiederholen
        log("\n--- LOOP RESTART (same channel) ---\n")
        time.sleep_ms(800)

except KeyboardInterrupt:
    print("\nTest gestoppt.")
