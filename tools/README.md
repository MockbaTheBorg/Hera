# heractl.py

CLI for Hera's scripting API. Talks to Hera itself (not Hercules) at
`http://127.0.0.1:8765` by default.

```
heractl.py [-h HOST] [-p PORT] [-t TOKEN] [--raw] <command> [args...]
```

Global flags go **before** the command. `-h`/`--host`, `-p`/`--port` default
to `$HERA_API_URL`; `-t`/`--token` defaults to `$HERA_API_TOKEN`. `--raw`
prints compact JSON instead of pretty.

`DEVICE` args accept an index (`3`), an exact label (`"DSP 3270 at 0701"`),
a devnum (`0701`), or any label substring that matches only one device
(`printer`).

## Discovery

```sh
heractl.py status                  # is Hera connected to Hercules
heractl.py devices                 # list devices + their indices/labels
heractl.py capabilities            # full route table (what the API supports)
heractl.py select 0701             # bring a device to the front in the GUI
```

## Console / 3270 terminals — typing text vs. pressing keys

`console type` and `dsp type` **send exactly the text given, nothing more**.
No text has an implicit Enter added — if you want the line submitted, put a
literal `\n` at the end yourself; leave it off to just fill the field (e.g.
typing a userid before separately handling the password field).

```sh
heractl.py console type Console 'qcpuid'          # Hercules command, entered
heractl.py dsp type 0701 'IBMUSER\n'               # fills+submits userid
heractl.py dsp type 0701 'SYS1'                    # fills password, no Enter
```

Keys (Enter, PF keys, Clear, etc.) are a separate action — `dsp aid` — not
text:

```sh
heractl.py dsp aid 0701 enter
heractl.py dsp aid 0701 pf3          # PF3 = Exit, in most ISPF panels
heractl.py dsp aid 0701 clear
heractl.py dsp screen 0701           # read back what's on the glass
```

## CPU

```sh
heractl.py cpu state CPU                    # registers, PSW, status
heractl.py cpu command CPU stopall
heractl.py cpu command CPU startall
heractl.py cpu ipl-address CPU 1D0
heractl.py cpu ipl CPU                      # IPL at the address already set
heractl.py cpu ipl CPU 1D0                  # set address then IPL
```

## Printer — same as clicking the panel's buttons

```sh
heractl.py printer output '000E'                        # read buffered lines
heractl.py printer test '000E'                           # test page
heractl.py printer save '000E' --path out.pdf            # eject to PDF
heractl.py printer discard '000E'                        # empty the buffer
heractl.py printer paper-color '000E' GREEN
heractl.py printer connect '000E'
heractl.py printer disconnect '000E'
```

`printer save` without `--path` picks an auto-named file under `spool/`,
exactly like the panel's own Save button.

## Card reader / punch

```sh
heractl.py reader load 000C --line '//SCRATCH JOB' --line '//STEP1 EXEC PGM=IEFBR14' --line '/*'
heractl.py reader load 000C --file job.jcl        # or load lines from a file
heractl.py reader submit 000C                      # feed the deck to Hercules
heractl.py reader deck 000C                        # read back the deck
heractl.py reader new 000C                         # clear it
heractl.py reader setup 000C --lang JCL --auto-number true
heractl.py reader toggle-view 000C                 # editor <-> card image view

heractl.py punch deck 000D
heractl.py punch save 000D out.txt
heractl.py punch discard 000D
```

### `reader editor` — TSO/ISPF-EDIT-style line commands

Edits the reader deck one line-command at a time instead of replacing it
whole with `reader load`. Hera keeps a line pointer per reader device,
reset by `reader new` / `reader load`.

| Command | Effect |
|---|---|
| `TOP` / `BOTTOM` / `END` | Pointer to first line / last line / one past the last (append position) |
| `UP [n]` / bare `-n` | Pointer up n lines (default 1), clamped at the first line |
| `DOWN [n]` / bare `+n` | Pointer down n lines (default 1), clamped at END |
| `FIND '...'` | Next line (from current, inclusive) containing the string |
| `CHANGE '...' '...'` | Replace the first occurrence in the current line |
| `INSERT ['...']` | Insert a line (blank if omitted) at the pointer, pushing the rest down, pointer moves past it |
| `REPLACE ['...']` | Overwrite the current line's text (blank if omitted); pointer doesn't move |
| `LIST [[+\|-]n]` | Return the current line, or n lines from it (signed for direction) |

Quoted strings use `'...'`, with `''` as an escaped literal quote (classic
TSO/ISPF EDIT quoting). Only the 72-column data area is ever searched,
matched or written — the 8-column sequence-number zone (populated when
`reader setup --auto-number true`) is locked and always regenerated fresh,
regardless of language; text that overflows 72 columns is truncated and the
response carries `"truncated": true`.

```sh
heractl.py reader new 000C
heractl.py reader editor 000C "INSERT '//SCRATCH JOB (ACCT),CLASS=A'"
heractl.py reader editor 000C "INSERT '//STEP1 EXEC PGM=IEFBR14'"
heractl.py reader editor 000C 'TOP'
heractl.py reader editor 000C "FIND 'EXEC PGM'"
heractl.py reader editor 000C "CHANGE 'IEFBR14' 'IEBGENER'"
heractl.py reader editor 000C 'LIST +5'
```

## Tape

```sh
heractl.py tape files 0560                          # what's mountable
heractl.py tape mount 0560 myvol.aws --readonly
heractl.py tape status 0560
heractl.py tape unmount 0560
heractl.py tape new 0560 newtape.aws SCR001 --owner me
```

## Preferences

```sh
heractl.py preferences get
heractl.py preferences set room_background=#3355aa poll_interval=0.25
```

## Shutdown

Closes every device and quits Hera itself (same as closing the window).
Requires `--yes`:

```sh
heractl.py shutdown --yes
```
