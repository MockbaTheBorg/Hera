# Hercules z/VM Cheat Sheet

*A practical reference guide for Hercules-based z/VM systems. Commands, utilities, and techniques validated through hands-on testing (z/VM 7.3, MAINT730/CMS session, `config/ubuntu.rc`).*

**Last Updated: September 4, 2026**

## Contents

- [Hercules & Logon](#hercules--logon)
- [3270 Terminal Keys](#3270-terminal-keys)
- [CP Command Basics](#cp-command-basics)
- [Console Output Paging (MORE.../HOLDING)](#console-output-paging-morehholding)
- [Devices: Query & Status](#devices-query--status)
- [Dynamic Device Activation](#dynamic-device-activation)
- [Printer & Punch](#printer--punch)
- [Card Reader](#card-reader)
- [Tape](#tape)
- [Second Terminal (0701) / Multi-User](#second-terminal-0701--multi-user)
- [CMS Basics](#cms-basics)
- [Known Quirks & Gotchas](#known-quirks--gotchas)

---

## Hercules & Logon

This system IPLs z/VM from device `0123` (see the Hercules banner printed at startup: `Use IPL XXXX to start the system` / `z/VM : 0123`).

### Logging on

Once IPL completes, the master terminal (device `0700`) shows the z/VM ONLINE logo with USERID/PASSWORD fields. Standard flow:

```
USERID   ===> MAINT730
PASSWORD ===> ZVM730
```

Tab moves between fields; Enter transmits. On successful logon you land directly in CMS (`Ready;` prompt), not a menu.

---

## 3270 Terminal Keys

| Key | Purpose (verified against this z/VM's CP, not assumed from 3270 spec) |
|-----|------|
| **ENTER** | Transmit current input to CP/CMS |
| **CLEAR** | Advances to the *next* screenful when status shows `MORE...`; also clears a locked/held screen |
| **PA1** | **Discards all remaining pending output** and returns straight to `Ready;` — this is NOT "page forward" (see caveat below) |
| **PA2** | Not exercised this session |
| **PA3** | **Undefined on this CP profile** — pressing it produces `* PF06 UNDEFINED` (CP's PA/PF key table quirk: an unassigned PA key's AID byte gets echoed back through the same message CP uses for an unassigned PF key, so the message text says "PF06" even though a real PA3 was pressed). Not a Hera bug — reproduced identically twice. |
| **PF1–PF24** | Program function keys, same as any 3270 session; `HELP`'s XEDIT-style browser uses `PF3` = Quit, `PF7`/`PF8` = page back/forward |

**Caveat on paging**: it's tempting to assume PA1 is "page forward" like PF8 is elsewhere — it isn't. If you have a long `Q V ALL`-style listing showing `MORE...`, press **CLEAR** repeatedly to see it all; pressing **PA1** at any point abandons everything still queued and drops you back to `Ready;`.

---

## CP Command Basics

Two figured out this session:

- From **CMS**, prefix any CP (not CMS) command with `#CP` to send it straight to the Control Program, e.g. `#CP Q V ALL`. Without the prefix, CMS tries to interpret it as a CMS command first.
- `HCPCMD001E Unknown CP command: xxxx` is CP's response both for a genuinely nonexistent command **and** for a real command your userid's privilege class isn't authorized to use — CP doesn't distinguish the two in the error text (security by obscurity). If a documented command comes back "unknown," privilege class is worth suspecting before assuming a typo.

| Command | Description |
|---------|-------------|
| `#CP Q V ALL` | Full virtual device list for your own virtual machine (paginates on `MORE...`) |
| `#CP Q V <dev>` | Status of a single device |
| `#CP Q NAMES` | Every logged-on/disconnected (`DSC`) userid and the real console device (if any) each is tied to |
| `#CP Q <dev>` | Status of a specific real/logical device (e.g. `Q 0701` → `GRAF 0701 DISABLED`) |
| `Q DISK` | (CMS command, no `#CP` needed) minidisks currently linked/accessed |
| `INDICATE LOAD` | System-wide load: CPU%, paging rate, MDC hit ratio, per-processor utilization |

---

## Console Output Paging (MORE.../HOLDING)

Long CP output (e.g. `Q V ALL` against a system with 60+ devices) doesn't scroll — it pages:

1. Status line shows `MORE...` — more output is queued.
2. Press **CLEAR** to advance one screenful. Repeat until status returns to `RUNNING`.
3. If status instead shows `HOLDING`, the *next* input you send (even Enter) releases the next page.
4. To bail out of a long listing without reading the rest, press **PA1** (see the terminal-key table above) — instant return to `Ready;`, no more pages shown.

---

## Devices: Query & Status

Real (Hercules-defined) hardware for this configuration, discovered via `Q V ALL` and the Hercules console log:

| Devnum | Type | Notes |
|--------|------|-------|
| `0009` | 3215 console printer | Bound to MAINT730's own console (hardcopy log) |
| `000C` | 3505 card reader | `STARTED SYSTEM` at boot, always available for spool intake |
| `000D` | 3525 card punch | `STARTED SYSTEM CLASS *` at boot |
| `000E` | 1403 printer | System default spooled printer |
| `000F` | 1403 printer | Second printer — **not** attached to any VM by default |
| `0560` | 3480 tape | Not attached by default |
| `0580` | 3490 tape | Not attached by default |
| `0590` | 3590 tape | Not attached by default |
| `0700` | 3270 GRAF | Master console terminal (must be connected before/at logon) |
| `0701` | 3270 GRAF | Second terminal — **disabled** by default (see below) |
| `0120`–`0127` | 3390 DASD | Real packs; MAINT730's minidisks (`Q DISK`) are extents carved from these |

---

## Dynamic Device Activation

Real devices not already attached to your virtual machine can be attached live, without a re-IPL — this is the core "z/VM does dynamic device activation" capability:

```
#CP ATTACH <realdev> * <vdev>
```

`*` means "to my own virtual machine." Examples validated this session:

```
#CP ATTACH 000F * 000F      → PRT  000F ATTACHED TO MAINT730 000F
#CP ATTACH 0560 * 0560      → TAPE 0560 ATTACHED TO MAINT730 0560
```

To release a device: `#CP DETACH <vdev>` (for a tape drive, this also unmounts/ejects whatever's loaded — Hera's tape status went from `loaded: true` back to `loaded: false` after a `DETACH`/re-`ATTACH` cycle in testing).

**Gotcha**: CMS's own `TAPE` utility hardcodes virtual device address `181` (referred to internally as `TAP1`) and won't recognize a tape attached at any other virtual address. If you want to use the plain `TAPE DUMP`/`TAPE LOAD` commands, attach the drive as `181`, not its real device number:

```
#CP DETACH 0560
#CP ATTACH 0560 * 181
```

---

## Printer & Punch

Attaching a real printer/punch (above) makes it visible to CP, but the **default spooled** printer/punch (`000E`/`000D`) won't actually print/punch a queued job until:

1. The device is started: `#CP START 000E` (note: `START PRT 000E` is invalid syntax — just `START 000E`)
2. **CP then asks the operator to "mount a form"** — real spooling hardware behavior, not a Hera bug:
   ```
   HCPRSS405A Mount form STANDARD on printer 000E
   HCPRSS405A Mount form STANDARD on punch 000D
   ```
   This is answered with `REPLY <msgid> <text>` — **but `REPLY` requires class-A (operator) privilege**, which MAINT730 does not have on this system (`#CP REPLY 1 STANDARD` → `HCPCMD001E Unknown CP command: REPLY`). The real `OPERATOR` userid is auto-logged at boot (see `Q NAMES` → `OPERATOR - SYSC`) and would need to answer this from its own console. Until then, jobs sit queued (`Q PRT ALL` shows status `PRT- (nnnn)`, stuck).

Commands exercised:

| Command | Description |
|---------|-------------|
| `PRINT fn ft fm` | Spool a CMS file to the default virtual printer (000E) |
| `PUNCH fn ft fm` | Spool a CMS file to the default virtual punch (000D) |
| `#CP Q PRT ALL` | List all printer spool files system-wide, with status |
| `#CP Q RDR ALL` | List all reader spool files (files sent *to* a reader, not raw device intake) |
| `#CP START <dev>` | Start a spooled UR device so it begins processing its queue |
| `#CP PURGE PRT ALL` | Purge your own queued printer spool files (use to clear a stuck "mount form" job) |
| `#CP PURGE PUN ALL` | Same, for punch |

**Practical takeaway**: `ATTACH`+`Q V`+`START` fully demonstrates dynamic printer/punch activation at the CP level. Getting an actual sheet/card physically "printed" through the default spooled devices needs an operator-class reply that MAINT730 can't issue — a real access-control boundary, worth remembering before assuming a print job "isn't working."

---

## Card Reader

The real reader (`000C`) is always `STARTED SYSTEM` and Hera's simulated hardware can feed it an arbitrary card deck (`reader/load` + `reader/submit` in the scripting API, or the Reader device's GUI deck editor).

Fed a 2-line deck of raw text this session and confirmed the reader genuinely activates and CP attempts to read it:

```
HCPRSR431E Reader 000C id card missing or invalid
```

This confirms the reader path is live end-to-end (Hercules → CP intake), but real VM reader-based job/file submission requires the deck's **first card to be a proper VM identification card** (the `$$ IDENT` job header used by RSCS/PVM-style file transfer, or a real CP-format spool header) — a plain text/command deck isn't sufficient.

**Do not just hand-craft an "almost right" ID card to get past this.** [SDL-Hercules-390/hyperion#554](https://github.com/SDL-Hercules-390/hyperion/issues/554) (filed against this exact scenario) documents that an ID card which is *subtly malformed but still parseable* doesn't get cleanly rejected like ours did — it **crashes the z/VM guest** (`HCPDMP908I SYSTEM FAILURE ON CPU 0000, CODE - LAL008`). Confirmed by the Hercules maintainer as a genuine z/VM bug (reproduces identically on real IBM zPDT hardware with an EBCDIC deck), closed `WON'T FIX` — nothing to patch on the Hercules side. The clean `HCPRSR431E ... missing or invalid` we got is the *safe* failure mode, because our header was unambiguously wrong-shaped rather than close-but-wrong.

### The correct ID card format — confirmed working

Per [IBM's z/VM 7.4 docs, "Using Real Cards"](https://www.ibm.com/docs/en/zvm/7.4.0?topic=cms-using-real-cards), the real syntax is **keyword-based**, not positional:

```
ID|USERID userid CLASS class NAME name TAG tagtext
```

- `ID` or `USERID` must start in **column 1**, fields separated by ≥1 blank
- `userid` = recipient of the resulting spool file (required)
- `CLASS`, `NAME` optional; `TAG tagtext` optional and must be last if present

This is exactly why the crashing card in issue #554 was dangerous: `USERID MAINT620 TEST TEXT C` is *positional* (`userid name type class`), not this keyword syntax — close enough to parse partway, wrong enough to crash.

Tested live, end to end, with no incident:

```
# Deck (2 cards):
ID MAINT730 CLASS A NAME TESTCARD
THIS IS A TEST DATA CARD

# Submitted via reader/load + reader/submit, then on the CP side:
#CP START 000C          → RDR 000C STARTED SYSTEM / RDR FILE 0007 HAS BEEN READ
#CP Q RDR                → MAINT730 0007 A RDR 00000001 ...
RECEIVE 0007 TESTCARD DATA A
TYPE TESTCARD DATA A     → THIS IS A TEST DATA CARD
```

Content survived intact, no crash, no error. **Gotcha**: after Hera (re)connects to the reader socket, CP does not automatically consume the deck just because a client connected — you still need `#CP START 000C` to make it actually read. A connected-but-not-started reader just sits there silently (no error, no read, nothing happens) until started.

**Gotcha**: this reader's socket is one-shot per submit (a fresh TCP connection each time, not a persistent one), and Hercules' `sockdev` will refuse a second connection attempt while it still considers a prior one "connected" (`connection ... rejected: client ... still connected`) — this can linger after a bad deck (like the #554-style crash-adjacent case) leaves the device in a stuck state. **Do not fix this with a bare `devinit <dev>`** — it unbinds the socket entirely and fails to rebind without the full original attach spec, breaking the device until you `detach`/`attach` it again with the complete `sockdev ascii trunc eof` parameters. If Hera's own reader socket errors out afterward, restart Hera.

---

## Tape

Full write/read round trip validated:

```
# 1. Create + mount a blank scratch tape (via Hera's tape/new + tape/mount, or
#    equivalently `hetinit` + a real AWS tape file on the host side)
# 2. Attach it as virtual 181 (see the CMS TAPE gotcha above)
#CP ATTACH 0560 * 181

# 3. Write a file to tape
TAPE DUMP PROFILE EXEC A

# 4. Rewind
TAPE REW

# 5. Read it back (use * * to accept the file's own name/type from the tape label)
TAPE LOAD * * A
```

Verified with `LISTFILE PROFILE EXEC A (DATE` before and after — the reloaded file's original date/time survived the round trip unchanged.

| Command | Description |
|---------|-------------|
| `TAPE DUMP fn ft fm` | Write one CMS file to the currently-mounted tape at `181` |
| `TAPE LOAD fn ft fm` | Read the next file off tape into a CMS file (`* * fm` keeps the tape's own name/type) |
| `TAPE REW` | Rewind |
| `#CP Q V 0560` (or whatever vdev) | Confirm attach + device type |

**Gotcha**: the very first `TAPE DUMP` after attaching can fail with `HCPERP2233I TAPE 0560 NOT READY, CP-OPERATOR NOTIFIED` if the drive was detached/reattached without re-mounting the volume first (a `DETACH` ejects it). Re-mount, then retry — no reboot needed.

---

## Second Terminal (0701) / Multi-User

By default the second 3270 line is **disabled**, even though it's already defined as a real device and Hercules will happily complete telnet negotiation with a client connected to it (you'll just see Hercules's own idle banner, never a z/VM logon screen):

```
#CP Q 0701          →  GRAF  0701 DISABLED
#CP ENABLE 0701      →  Command complete
```

After `ENABLE`, the terminal immediately shows CP's pre-logon menu:

```
Enter one of the following commands:
   LOGON userid
   DIAL userid
   MSG userid message
   LOGOFF
```

From here, `LOGON <userid>` starts a fresh session (prompts for password) or reconnects to that userid's already-running *disconnected* session if one exists — `Q NAMES` shows `DSC` next to any disconnected user (e.g. `OPERATOR`, all the auto-logged service machines). `DIAL <userid>` is for connecting to a virtual machine's own dial-enabled virtual console pool (VTAM/VSCS-style) and returned `HCPDIA055E Line(s) not available` when tried against a regular disconnected user — that's not what `DIAL` is for.

Once enabled, `Q NAMES` shows the pre-logon placeholder for that line: `LOGN0701 - 0701`.

**Note**: reconnecting to a disconnected userid via `LOGON` still requires that userid's real password — there's no privileged shortcut demonstrated this session, and guessing/brute-forcing another userid's password was deliberately not attempted.

---

## CMS Basics

| Command | Description |
|---------|-------------|
| `LISTFILE * * A` | List all files on your A-disk |
| `LISTFILE fn ft fm (DATE` | List one file with size/date/time detail |
| `HELP <topic>` | Full-screen XEDIT-style help browser (`PF3`=Quit, `PF7`/`PF8`=page) — note `HELP <verb> <subverb>` (e.g. `HELP TAPE LOAD`) is usually NOT a valid combined topic; use `HELP TAPE` and page to the subsection instead |
| `Q DISK` | List currently accessed minidisks |

---

## Known Quirks & Gotchas

Consolidated from above, for quick scanning:

1. **PA1 discards pending output**, it does not page forward — CLEAR does that.
2. **PA3 is undefined** on this CP profile and reports itself (misleadingly) as `PF06 UNDEFINED`.
3. **`HCPCMD001E Unknown CP command`** can mean "doesn't exist" OR "you're not authorized" — CP doesn't tell you which.
4. **CMS's `TAPE` utility only ever looks at vdev `181`** — attach your tape drive there, not at its real address, if you want to use plain `TAPE DUMP`/`TAPE LOAD`.
5. **Detaching a tape drive unmounts/ejects the volume** — remount before the next `TAPE DUMP`/`LOAD`.
6. **Spooled printer/punch output needs an operator-class `REPLY`** to a "mount form" prompt before it actually prints/punches — `ATTACH`+`START` alone queues the job but doesn't complete it if your userid lacks class A.
7. **A raw text "card deck" isn't valid reader input** for CP job/file intake — a real ID card is required as the first card, in `ID|USERID userid CLASS class NAME name` keyword syntax (col 1, space-separated) — see the Card Reader section for a confirmed-working example. **Do not iterate toward a "close enough" ID card by guessing at positional syntax** — [hyperion#554](https://github.com/SDL-Hercules-390/hyperion/issues/554) shows a subtly-malformed positional one crashes z/VM outright (confirmed z/VM bug, `WON'T FIX` on the Hercules side); use the real documented keyword syntax instead, which round-tripped cleanly with no incident.
8. **`0701` (and presumably any additional real GRAF line) starts `DISABLED`** — `ENABLE <dev>` before expecting a logon screen; connecting a client alone isn't enough.
9. **A connected reader doesn't auto-read** — `#CP START 000C` is required even when a client is already connected; otherwise the deck just sits there with no error and no read.
10. **Never run a bare `devinit <dev>` on a `sockdev`** (reader/printer/punch) to try to clear a stuck connection — it unbinds the socket and fails to rebind without the full original attach spec. Recover with `detach <dev>` then `attach <dev> ... sockdev ...` (exact original parameters), and restart Hera if its own client then errors out.
11. **The reader has no `connect`/`disconnect` control** (unlike punch/printer/tape) — by design, since it opens a fresh one-shot socket per submit rather than holding a persistent connection. This means there's no way to proactively clear a stuck "still connected" state from the reader side alone; see #10.

---

*Built through collaborative, live testing against a real running Hercules z/VM 7.3 instance. Each entry validated before inclusion; commands that failed are documented with their exact error text rather than omitted.*
