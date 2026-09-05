# Hera Scripting API — Examples

Requires the scripting API enabled: Preferences > API tab (or `[scripting_api]`
in `~/.config/hera/hera.conf`), restart Hera. Default `http://127.0.0.1:8765`.

Env vars used by every example:

| Var | Default | Purpose |
|---|---|---|
| `HERA_API_URL` | `http://127.0.0.1:8765` | Base URL of the scripting API |
| `HERA_API_TOKEN` | (empty) | Bearer token, only if one is set in Preferences > API |

Shell examples need `bash`, `curl`, `jq`. Python examples need `python3` and `requests`
(already a Hera dependency). Both `source common.sh` / `import hera_client` for
shared request + device-lookup helpers — run examples from anywhere, paths are
resolved relative to the script.

`hera/` — operate Hera's own GUI/state (dials, preferences, decks, printer, tape) without
touching the guest OS. `hercules/` — use that same API to drive commands into the running
Hercules/z/OS guest (console, CPU, 3270 terminal, JCL).

## hera/

| File | What it does |
|---|---|
| `01_discover_devices.sh` / `.py` | List `/devices` and `/capabilities` (paired — same calls, shell vs Python) |
| `02_select_device_cycle.sh` | Bring each room device to the front in turn, then return to the first |
| `03_set_ipl_address.py` | Set the CPU IPL address dial to a scratch value, then restore it — no IPL |
| `04_change_room_theme.sh` | Change the room background via `/preferences`, then restore it |
| `05_printer_paper_and_test.py` | Connect printer, set paper color, run test print, save PDF, discard buffer |
| `06_tape_mount_cycle.sh` | List mountable tape files, mount read-only, check status, unmount |
| `07_reader_deck_edit.sh` | Load lines into the card reader deck, read back, toggle view, clear |
| `08_dsp3270_font_and_connect.py` | Resize 3270 font, disconnect/reconnect the terminal socket |
| `09_backup_and_restore_preferences.sh` | Back up all preferences, change poll interval, restore exactly |
| `10_reader_line_editor.sh` | Build/edit a card reader deck one TSO/ISPF-EDIT-style line command at a time (`reader/editor`) instead of replacing it whole |

## hercules/

| File | What it does |
|---|---|
| `01_console_command.sh` / `.py` | Type an operator command into CONSOLE, read the response from the log (paired — shell vs Python) |
| `02_cpu_operator_commands.sh` | Press CPU operator buttons: `stopall`, `startall` |
| `03_cpu_ipl_and_wait.py` | IPL the CPU at a given address, poll status until it settles (⚠ reboots the guest) |
| `04_tso_login_and_time.sh` | Log into TSO on a 3270 terminal, run `TIME` |
| `05_ispf_navigate_with_protected_map.py` | Tab through an ISPF panel using cursor + protected-field data instead of guessing |
| `06_submit_jcl_and_read_output.py` | Submit a harmless JCL job via the reader, stream printer output as it runs |
| `07_exit_stuck_panel_pf3.sh` | Send PF3 to back out of a stuck ISPF panel |
| `08_shutdown_zos.sh` | Scripted `S SHUTSA` + emulator `quit` (⚠ shuts down the guest and Hercules) |
