# Hera — A GUI for SDL Hercules (Hyperion)

Hera is a modern graphical front end for the SDL Hercules (Hyperion) IBM mainframe emulator. It provides a PySide6-based workspace that makes common operator tasks faster and more visual: managing CPUs, DASD, tape volumes, card readers and punches, printers, 3270 terminals and the operator console — all from a single application.

**Platform note:** Hera is developed and exercised on Linux. The code is platform-agnostic where possible and may run on macOS or Windows, but those platforms are not tested.

![Hera screenshot](app/bitmaps/screenshot.png)

---

## Features

- **Interactive device panels:** View and control CPUs, DASD, tape drives, card readers/punches, printers and consoles.
- **Printer export:** Printer output can be saved/exported as PDF files for easy archival and sharing.
- **Punched-card file support:** Save and load card decks as punched-card file images so card-based input/output can be preserved and re-used.
- **Tape image support:** Create, read and write tape image files for storing datasets; compatible with Hercules tape handling so datasets can be transferred between Hera and the emulator.
- **3270 terminal integration:** Full 3270 sessions with convenient screens and input handling.

---

## Requirements

- Python 3.8 or newer
- A running SDL Hyperion Hercules instance with its REST API enabled (port 8081 by default)

---

## Installation

```bash
# 1. Clone the repository
git clone https://github.com/MockbaTheBorg/Hera
cd Hera

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## Running Hera

```bash
# Connect to the local Hercules instance (default: 127.0.0.1:8081)
python hera.py

# Connect to a remote host or non-default port
python hera.py --host 192.168.1.10 --port 8081
```

| Option | Default | Description |
|--------|---------|------------- |
| `--host` | `127.0.0.1` | Hostname or IP of the Hercules REST API |
| `--port` | `8081` | Port of the Hercules REST API |

---

## Notes

- Hera stores user preferences in `~/.config/hera/hera.conf`.
- Use `File -> Preferences` in the UI to edit saved connections, appearance and window settings.
- Command-line options override values stored in the config file.
- The Hercules REST API should be reachable before starting Hera; device panels will indicate if the connection is not available.

---

## Credits

- **Jason** (original inspiration) — by Oleh Yuschuk
- **SDL Hercules** — by Roger Bowler, Jay Maynard, Jan Jaeger, and the [SDL Hercules community](https://github.com/SDL-Hercules-390/hyperion)