# ubuntu under z/VM 7.3 — unit-record devices (RDR/PCH/PRT) via vmur

Goal: run the `ubuntu` Linux guest **under z/VM** (instead of LPAR-native) so it
gets a real `vmur` driver, giving it working card reader / punch / printer.
Native/LPAR-IPL'd Linux has NO driver for 1403/3505/3525 — see the "why"
section at the bottom.

All steps below use Hera's scripting API (`http://127.0.0.1:8765`) to drive
the 3270 sessions. Helper script: `tools/hera.sh`.

```
tools/hera.sh <device-index> text "<string>"   # type text into 3270 screen
tools/hera.sh <device-index> key <name>        # send AID key: enter, clear, tab, pa1, reset, pf1..pf24, ...
tools/hera.sh <device-index> screen            # dump current screen text
```

Device indices (from `GET /devices`, fixed for this config):
- `2` = DSP 3270 at 0700 (we use this as the **z/VM console**, logged on as MAINT730)
- `3` = DSP 3270 at 0701 (we use this as the **ubuntu terminal**)

## Cookbook: tape / printer / punch / reader, step by step

Assumes `ubuntu` is already booted under z/VM and you're logged into its
Linux shell (userid/password: `ubuntu`/`ubuntu`) — see steps 0-6 below if
you're starting from a cold Hercules boot. Sudo is required for every device
here; always run `sudo <cmd>` interactively and type the password at the
`[sudo] password for ubuntu:` prompt when asked — **do not** pipe it
(`echo ubuntu | sudo -S ...` reliably fails over this console for reasons
covered under "Using the devices" below). Sudo caches the credential for a
few minutes, so you usually only type it once per burst of commands.

All 5 recipes below were run start-to-finish and byte-verified while writing
this doc.

### 1. Copy a file to tape

```
sudo chccwdev -e 0.0.0560          # only needed once per boot — brings the
                                    # tape drive online, creates /dev/ntibm0
                                    # (no-rewind) and /dev/rtibm0 (rewind)
```
A tape must be **mounted** first — from the Hercules/Hera side (not
Linux), either via Hera's TAPE panel ("New" or "Mount"), or via the
scripting API:
```
curl -s -X POST http://127.0.0.1:8765/devices/9/tape/new \
  -H "Content-Type: application/json" \
  -d '{"filename":"mytape.aws","volser":"MYTAP1","overwrite":true}'
```
(`devices/9` = tape drive at 0560 in this config; `/devices` lists indices.)

Now write the file:
```
sudo dd if=/path/to/yourfile of=/dev/rtibm0 bs=65536
```
Expect: `1+0 records in / 1+0 records out / <N> bytes copied`. Using the
**rewind** device (`rtibm0`) means it auto-rewinds to the start before
writing — good for "one file = one tape", the usual case here.

**Gotcha**: use a `bs=` at or above your file's actual size, so `dd` reads
and writes it as a single tape block — matches how you'll read it back (see
below). Piping through `tee`/`cat` also works but is less predictable about
block boundaries; `dd if=file of=/dev/rtibm0 bs=<size>` is the reliable form.

### 2. Restore a file from tape

```
sudo mt -f /dev/ntibm0 rewind
sudo mt -f /dev/ntibm0 status        # sanity check: file number = 0, block number = 0
sudo dd if=/dev/ntibm0 of=/path/to/restored bs=16384
```
Expect: `0+1 records in / 0+1 records out / <N> bytes copied`.

**Gotcha — the one that actually bit us**: the read `bs=` must be *close to*
the real block size, not just "big enough". `bs=1M` on a ~10KB block fails
outright with `dd: error reading '/dev/ntibm0': Invalid argument` (EINVAL) —
this Linux tape driver rejects a read buffer that's wildly oversized versus
the actual block, it doesn't just short-read. `bs=16384`-`65536` worked fine
for anything up to tens of KB in testing. If you get `Invalid argument`,
first check position with `mt status` (should read block/file 0 after a
rewind), then retry with a smaller `bs`.

Verify: `diff /path/to/original /path/to/restored` should show nothing.

To reuse the drive for another file, unmount/remount via Hera between tapes
(`tape/unmount` then `tape/new` or `tape/mount`), or use `mt fsf`/multi-file
conventions if you deliberately want multiple files on one tape — not
covered here, single-file-per-tape is what's tested.

### 3. Print a file to a printer

```
sudo vmur print -t -N myjob /path/to/file.txt
```
- `-t` — **required**: converts ASCII→EBCDIC (IBM037) and pads each line to
  132 chars. Without it you get raw untranslated bytes.
- `-N myjob` — optional, just sets the banner page's job name; omit and it
  uses the filename.
- Max line length is **132 characters** — longer lines error out
  (`vmur: ... exceeds 132`); pre-wrap/cut long output first
  (e.g. `cut -c1-132`).

This creates a self-addressed spool file (owned by `UBUNTU`, sitting until
routed to a real device). Confirm it's there:
```
sudo vmur list -q prt
```
To actually see it appear on a **real** printer (Hera's PRT panel / a
Hercules-attached device, not just CP's internal spool queue), from the
z/VM console (logged on as an operator-class user, e.g. `MAINT730`) make
sure the target real device is started with automatic separators — this is
a one-time-per-boot setup, not per-file:
```
cp query 000e 000f          # check which real printers exist and their state
cp start 000e class a auto  # AUTO, not the default MANUAL, sep — MANUAL blocks
cp start 000f class a auto  # every file waiting for an operator ack you can't
                             # give without being logged on as OPERATOR
```
Once started, any subsequent `vmur print` from `ubuntu` shows up automatically
— no per-file action needed. Watch it land:
```
curl -s http://127.0.0.1:8765/devices/6/printer/output   # index 6 = PRT 000F here
```
Export what printed as a real PDF:
```
curl -s -X POST http://127.0.0.1:8765/devices/6/printer/discard   # clear old content first if reusing
curl -s -X POST http://127.0.0.1:8765/devices/6/printer/save
```
returns `{"path": ".../Hera_Dev/spool/PRT_000F_<timestamp>.pdf"}`.

**If a job seems stuck** (queued forever, never prints): see the
troubleshooting notes in section 10 below — `cp query printer all`,
`cp change <userid> printer <spoolid> nohold`, and the device
detach/reattach reset trick.

### 4. Punch a file onto a card deck

```
sudo vmur punch -t -N mydeck /path/to/file.txt
```
- Same `-t` requirement as print.
- Max line length is **80 characters** (real card width) — longer lines
  error with `vmur: Input line N too long. Unit record length must not
  exceed 80`. Pre-trim: `cut -c1-80 < input > trimmed`.

Confirm:
```
sudo vmur list -q pun
```
Same self-addressed/needs-routing situation as print. To route to a
**real** punch device it's the identical dance as printing (`cp start 000d
class a auto` from the operator console), with one caveat: `000D` on this
particular system got wedged at the Hercules OS-socket level during this
session's troubleshooting and currently needs a full Hercules restart to
recover — see section 10. Reading your own punch output back into a file
(recipe 5, below) doesn't need the real device at all — that part is fully
working right now regardless.

### 5. Read a card deck into a file

Two real scenarios, same underlying mechanism (CP routing a spool file into
a userid's virtual reader, then `vmur receive` pulling it into Linux):

**(a) Reading a deck someone else punched to you** — e.g. from the z/VM
console logged on as another user (`MAINT730`), create/punch a file
addressed to `ubuntu`:
```
cp spool pun to ubuntu       # (CP command, sets punch target for this session)
punch somefile data a        # (CMS command — punches a CMS file to the target set above)
```
Expect: `PUN FILE nnnn SENT TO UBUNTU RDR AS mmmm RECS ...` — `mmmm` is the
spoolid that lands in `ubuntu`'s reader.

**(b) Reading back your own punch output** (e.g. right after recipe 3) —
self-transfer it from your punch queue into your own reader queue first,
using `vmcp` (the Linux-side bridge to CP commands, part of s390-tools;
plain `cp` inside Linux is the coreutils file-copy command, *not* z/VM CP —
easy mixup):
```
sudo vmcp transfer punch <spoolid> to \* reader
```
Expect: `RDR FILE nnnn SENT FROM UBUNTU PUN WAS <spoolid> ... / 0000001 FILE
TRANSFERRED`. `nnnn` is the new reader spoolid (usually the same number).

Either way, once the file is in your reader:
```
sudo vmur list                              # confirms it's there, shows the spoolid
sudo vmur receive --text <spoolid> /tmp/out.txt
sudo cat /tmp/out.txt                       # sudo needed — vmur receive writes as root
```
**`--text` is required** — without it you get raw untranslated card-image
bytes. `receive` also **consumes** the spool file — you can't re-receive the
same spoolid; if something goes wrong, re-punch/re-transfer and use the new
spoolid.

## 0. Prereqs

- Hercules IPL'd into z/VM 7.3 using `zOS/config/ubuntu.rc` (same rc file
  attaches both the `ubuntu` Linux disks and the `vm73` z/VM system disks —
  just IPL device `0123` instead of `0120`).
- Hera running with scripting API enabled (`GET /status` returns
  `{"connected": true, ...}`).
- If Hera's GUI process dies, hercules keeps running — just restart Hera;
  existing CP sessions on 0700/0701 survive and reconnect.

## 1. Logon to z/VM as MAINT730 (index 2 / devnum 0700)

```
tools/hera.sh 2 text "MAINT730"
tools/hera.sh 2 key tab
tools/hera.sh 2 text "ZVM730"
tools/hera.sh 2 key enter
```
If it says "Already logged on GRAF nnnn" (session alive on the other
terminal), steal it instead:
```
tools/hera.sh 2 key clear
tools/hera.sh 2 text "LOGON MAINT730 HERE"
tools/hera.sh 2 key enter
tools/hera.sh 2 text "ZVM730"
tools/hera.sh 2 key enter
```
Expect: `RECONNECTED AT ...` or a fresh CMS logon banner.

Get to CMS ready:
```
tools/hera.sh 2 text "IPL CMS"
tools/hera.sh 2 key enter
tools/hera.sh 2 key enter      # clear "VM READ", reach "Ready;"
```

## 2. CMS full-screen output pacing (important, easy to get stuck on)

CMS/CP paces long output two ways, both shown in the bottom-right status:
- `MORE...` → press **Enter** to get the next screen.
- `HOLDING` → press **Clear** to get the next screen (Enter does nothing here).

If you flood too many AIDs too fast you get `NOT ACCEPTED` (keyboard locked)
— send `key reset` to unlock, then resume paging slowly (~0.3-0.5s apart).

If you need to abort a long-running command output entirely: `key pa1` (goes
to `CP READ`), then `text "BEGIN"` + `key enter` resumes it — it does **not**
cancel/discard the output, just pauses/resumes. There is no clean "cancel"
via the exposed AID keys; either page through it or avoid triggering it
(prefer XEDIT navigation over `TYPE` for big files, see below).

## 3. Editing the z/VM directory (XEDIT) — add the UBUNTU guest

The compiled system directory source lives as `USER DIRECT` on PMAINT's
`2CC` disk (already accessed as filemode `C` for MAINT730 by default —
confirm with `Q DISK`).

Open it:
```
tools/hera.sh 2 text "xedit user direct c"
tools/hera.sh 2 key enter
```

**XEDIT quick reference** (command line is the `====>` line at the bottom —
just `text` + `enter` to it):
- `:NNNN` — jump straight to line number NNNN (fast, no paging needed).
- `top` / `bottom` — jump to start/end of file.
- `input` — enter input (append) mode at the current line; each `text`+`enter`
  after this adds one new line below the cursor; send a **blank** `enter` to
  leave input mode.
- `delete` — delete the current line.
- `change /old/new/` — substitute on the current line.
- `file` — save and quit (equivalent of `:wq`).
- `quit` — quit without saving (only if no unsaved changes; `qquit`/`ss q` to
  force-discard).
- The `Size=`, `Line=`, `Alt=` counters in the top status line are your
  sanity check: `Alt=N` = N lines changed so far in this session.

Go to bottom and append the new guest entry:
```
tools/hera.sh 2 text "bottom"
tools/hera.sh 2 key enter
tools/hera.sh 2 text "input"
tools/hera.sh 2 key enter
```
Then type these lines one at a time (`text` + `enter` each), **in this exact
order** — DIRECTXA enforces statement ordering: `IPL` must come right after
`USER`, before device statements (`CONSOLE`/`SPOOL`/`DEDICATE`/`MDISK`/`LINK`),
or you get `HCPDIR752E STATEMENT SEQUENCE ERROR`:
```
USER UBUNTU UBUNTU 512M 1G G
 IPL 120
 CONSOLE 009 3215 T
 SPOOL 00C 2540 READER *
 SPOOL 00D 2540 PUNCH A
 SPOOL 00E 1403 A
 DEDICATE 120 0120
 DEDICATE 121 0121
 DEDICATE 122 0122
 DEDICATE 560 0560
 DEDICATE 580 0580
 DEDICATE 590 0590
```
(The three tape `DEDICATE`s were added in a later pass, after the unit-record
work below, so this guest has tape access too — see the cookbook above.)
Send a blank line (`key enter` with no text) to leave input mode, then save:
```
tools/hera.sh 2 text "file"
tools/hera.sh 2 key enter
```

Notes on the entry:
- `USER UBUNTU UBUNTU 512M 1G G` — userid UBUNTU, password UBUNTU (matches
  the Linux OS's own ubuntu/ubuntu login, easy to remember), 512M initial /
  1G max virtual storage, privilege class G (ordinary user — same class as
  everything else in the shipped directory that isn't a system service).
- `SPOOL 00C/00D/00E ...` — these are **virtual** device numbers private to
  this guest, backed by CP's spool subsystem (not the real Hercules-attached
  000C/000D/000E hardware). This is what makes `vmur` work — it talks to CP
  via `diag14`/`diag210`, not real channel I/O. No clash with the real
  devices of the same number; virtual addresses are per-guest.
- `DEDICATE 120/121/122` — hands the 3 real DASD (lnroot/lnuser/lnhome,
  already containing this exact Ubuntu install) straight through to this
  guest, unconverted. Same filesystems as when IPL'd natively.

## 4. Compile the directory

```
tools/hera.sh 2 key clear
tools/hera.sh 2 text "directxa user"
tools/hera.sh 2 key enter
```
Expect: `EOJ DIRECTORY UPDATED AND ON LINE`. If you get
`HCPDIR752E STATEMENT SEQUENCE ERROR FOLLOWING USER UBUNTU`, fix statement
order (see above) and recompile — the directory is **not** updated on error.

## 5. Start the guest and connect a terminal to it

```
tools/hera.sh 2 text "xautolog ubuntu"
tools/hera.sh 2 key enter
```
Expect: `AUTO LOGON *** UBUNTU USERS = N`. This starts it disconnected.

Connect on index 3 (0701):
```
tools/hera.sh 3 text "UBUNTU"
tools/hera.sh 3 key tab
tools/hera.sh 3 text "UBUNTU"
tools/hera.sh 3 key enter
```
If it just reconnects to `CP READ` without booting, IPL didn't auto-fire —
run it manually:
```
tools/hera.sh 3 text "IPL 120"
tools/hera.sh 3 key enter
```
Expect `Booting default (ubuntu)`, then kernel boot messages (page through
with the MORE/HOLDING loop from step 2), eventually reaching
`ubuntu login:`. Boot takes ~60-90s emulated.

Log in: `ubuntu` / `ubuntu` (same as native).

**Gotcha if you edit the directory (add/remove `DEDICATE`/`SPOOL`
statements) after the guest is already logged on**: `DEDICATE` and friends
are evaluated at **LOGON time only** — re-IPLing Linux inside the same,
already-running CP session does *not* pick up directory changes, even
though the guest OS reboots fully. You must fully tear down the virtual
machine and log back on for CP to rebuild it from the updated directory:
```
tools/hera.sh 3 text "sudo shutdown -h now"   # from inside Linux, get to CP READ
tools/hera.sh 3 key enter
# (page through shutdown messages, MORE/HOLDING loop from step 2, until you see:
#  "HCPGSP2629I The virtual machine is placed in CP mode..." / "CP READ")
tools/hera.sh 3 text "logoff"                 # from CP READ — fully terminates the VM
tools/hera.sh 3 key enter
```
Then from the z/VM console: `tools/hera.sh 2 text "xautolog ubuntu"` +
`key enter` again (step 5), reconnect on index 3, `IPL 120` again. Confirm
new devices actually attached *before* IPLing Linux, while still at
`CP READ`: `query virtual dasd` / `query virtual tape` (as the `ubuntu`
session itself, not from MAINT730).

## 6. Confirm the vmur devices exist

```
ls -l /dev/ | grep vm
```
Expect:
```
crw------- 1 root root 248, 12 ... vmrdr-0.0.000c
crw------- 1 root root 248, 13 ... vmpun-0.0.000d
crw------- 1 root root 248, 14 ... vmprt-0.0.000e
```
(`/etc/rc.local` already runs `chccwdev -e 0.0.000c/000d/000e` at boot when
`/dev/vmcp` exists — i.e. automatically, whenever booted under z/VM. Nothing
manual needed here, unlike the tape case under native Linux.)

## 7. Using the devices — `vmur` (part of s390-tools, already installed)

```
vmur receive [OPTIONS] [SPOOLID] [FILE]   # pull a file in from your reader
vmur punch   [OPTIONS] [FILE]             # punch a file out
vmur print   [OPTIONS] [FILE]             # print a file out
vmur list    [-q rdr|pun|prt]             # list your own queue (rdr is default)
vmur purge / vmur order                   # manage spool files
```
Use `sudo` for all of these (device nodes are root-owned).

**IMPORTANT: sudo over this 3270 session — use interactive form, not `-S`
piped passwords.** `echo ubuntu | sudo -S cmd` reliably fails here
(`sudo: N incorrect password attempts`) even with the right password —
something about how Hera's `type_text` feeds the pipe garbles it. Just run
`sudo cmd`, wait for the `[sudo] password for ubuntu:` prompt, then send
`ubuntu` as a separate `text`+`enter`. Sudo caches the credential for a few
minutes afterward, so subsequent `sudo` calls in the same session usually
don't re-prompt.

### Punch out (tested, works)
```
echo HELLO > /tmp/t.txt
sudo vmur punch /tmp/t.txt
sudo vmur list -q pun
```
Expect a line like:
```
ORIGINID FILE CLASS RECORDS  CPY HOLD DATE  TIME     NAME      TYPE     DIST
UBUNTU   0001 A PUN 00000001 001 NONE ...            t         txt      UBUNTU
```
This defaults to a **self-addressed** spool file — it doesn't go anywhere
until you or another user routes it. To see it land somewhere else, direct
it at logon/PUNCH time (see reader section below for the CP-side of this).

### Print out (tested, works)
```
sudo vmur print /tmp/t.txt
sudo vmur list -q prt
```
Same self-addressed-until-routed behavior as punch.

### Reader in (tested, works — full round trip)
From the **z/VM console** (MAINT730, index 2), create a small CMS file and
send it to UBUNTU's reader:
```
tools/hera.sh 2 text "xedit testcard data a"
tools/hera.sh 2 key enter
tools/hera.sh 2 text "input"
tools/hera.sh 2 key enter
tools/hera.sh 2 text "HELLO FROM MAINT730"
tools/hera.sh 2 key enter
tools/hera.sh 2 key enter      # blank line, exit input mode
tools/hera.sh 2 text "file"
tools/hera.sh 2 key enter
```
Point subsequent PUNCH output at UBUNTU, then punch the file (CP command,
**not** CMS `PUNCH ... (TO ...` — that option isn't valid on this CMS):
```
tools/hera.sh 2 text "cp spool pun to ubuntu"
tools/hera.sh 2 key enter
tools/hera.sh 2 text "punch testcard data a"
tools/hera.sh 2 key enter
```
Expect: `PUN FILE nnnn SENT TO UBUNTU RDR AS mmmm RECS ...`. `mmmm` is the
spoolid on UBUNTU's side.

On the ubuntu side, list and receive it:
```
sudo vmur list                              # shows it, origin MAINT730
sudo vmur receive --text mmmm /tmp/out.txt  # USE --text OR YOU GET GARBAGE
sudo cat /tmp/out.txt
```
**`--text` is required** — without it you get raw untranslated card-image
bytes (looked like garbage EBCDIC-ish noise in testing). `receive` also
**consumes** the spool file — you can't re-receive the same spoolid, so if
you mess up the flags, re-punch from the source side and use the new spoolid.

## 8. Fix applied: `/etc/rc.local` printer setup was native-mode-only, ran (and warned) even under z/VM

Boot log showed a scary-looking but harmless warning under z/VM:
```
rc.local[763]: Warning - lp: cannot open lp device '/dev/printer' - No such device or address
```
Root cause: `/etc/rc.local` unconditionally sets up a `mkfifo /dev/printer` +
`socat /dev/printer tcp-listen:1234` + `lprng` bridge. This is a leftover
setup for **native/LPAR** Linux, where the printer devices are raw TCP
sockets exposed by Hercules (`0009`→:3215, `000E`→:10014, `000F`→:10015 per
`zOS/config/ubuntu.rc`) — note even there, port 1234 doesn't match any of
those, so this bridge looks vestigial/broken in native mode too. Under z/VM
it's actively pointless: real printing goes through `vmur`/CP spool, nothing
is listening on tcp:1234, and `lprng`'s own startup races ahead of the fifo
being created, hence the warning every boot.

**Fix**: wrapped that block in `if [ ! -e /dev/vmcp ]; then ... fi` so it
only runs in native mode (mirrors the existing `/dev/vmcp` check already at
the top of the same file for the device-enabling section). Under z/VM the
printer/lprng/socat setup is now skipped entirely — no more warning, no
useless `socat` process. `vmur print`/`punch`/`receive` remain the confirmed
way to talk to the unit-record devices under z/VM; wiring plain `lp`/`lpr`
through to `vmur` automatically was not done (out of scope) — direct `vmur`
calls are what's tested and working.

Applied as:
```
sudo cp /etc/rc.local /etc/rc.local.orig
sudo sed -i '21i if [ ! -e /dev/vmcp ]; then' /etc/rc.local
echo fi | sudo tee -a /etc/rc.local
sudo sh -n /etc/rc.local && echo SYNTAX_OK   # verify before rebooting on it
```
Original backed up at `/etc/rc.local.orig` on the guest's own disk.

## 9. Bug fixed: Hera's PCH panel never connected headlessly

`app/devices/pch3525.py` created its `SocketReader` (the thing that actually
connects to Hercules' `sockdev` and receives punched card data) lazily inside
`create_workspace()` — which only runs when the device's GUI panel is
physically opened. `app/devices/prt1403.py` creates its reader eagerly in
`__init__` instead. Since the scripting API's `punch_connect` route
(`app/scripting/routes.py`) calls `device._do_connect()` directly without
ever triggering `create_workspace()`, `self._reader` was still `None` and the
call silently no-op'd — `POST /devices/{i}/punch/connect` always returned
`{"connected": false}`, with no error.

**Fix**: moved the `SocketReader(...)` construction from `create_workspace()`
into `Pch3525Device.__init__()`, matching `prt1403.py`'s pattern exactly.
`create_workspace()` now just builds the deck-view widget, same shape as
`Prt1403Device.create_workspace()`. Verified after a Hera restart:
`POST /devices/8/punch/connect` → `{"connected": true}`, and the real
Hercules device status flips from blank to `open`.
(`rdr3505.py` doesn't have this problem — the reader/card-submit device
writes synchronously on `_do_submit`, no persistent listening socket needed.)

## 10. RESOLVED — real-device print now works (was: hangs on actual payload data)

Section 10 originally documented this as an unresolved Hercules/CP interaction
bug. It's now root-caused and fixed. Keeping the original investigation
below for the repro steps (the "stuck device" mechanics are still useful to
know), followed by the actual fix.

### The real root cause (h/t https://github.com/SDL-Hercules-390/hyperion/issues/550 —
the exact same problem, reported by the same person who set up this system, resolved 2 years ago)

Two independent bugs stack here:

1. **`vmur`'s Linux kernel driver always issues CCW opcode `0x01`** (Write
   Without Spacing) for every printer write, when it should issue `0x09`
   (Write and Space 1 Line). Punch devices don't care about line-spacing
   semantics so this never mattered for punch — only print. Hercules
   receiving CCW 01 for every line means "don't advance", which it renders
   as a `[CR]` instead of `[LF]`. This is a genuine bug in the upstream
   Linux `vmur.ko` driver (confirmed via CCW trace in the linked issue),
   not fixable from here. **Already worked around** in `zOS/config/ubuntu.rc`
   — every real PRT attach already carries the `nocr` flag
   (`ATTACH 000E 1403 0.0.0.0:10014 sockdev nocr`), which is the custom
   Hercules patch (`printer.c` `SpaceLines`) from that issue thread: it
   forces a `[LF]` even when told "don't space". This config already had the
   fix — no action needed there.

2. **`CODEPAGE default` in `zOS/config/cpu.cnf` corrupts the EBCDIC↔ASCII
   translation** of the guest's actual payload data (separator/banner text
   is generated by CP itself and renders fine either way; the *user's*
   spooled file content does not, hence "banners render, payload is blank
   or garbled"). This is exactly what was flagged (but not yet fixed) at
   the end of that same GitHub issue. Fix: use an explicit codepage.
   ```
   cp.cnf:  CODEPAGE  819/037
   ```
   Can be changed live without a restart via the Hercules system console
   (not the z/VM 3270 one — that's `devices/1` in this config,
   `POST /devices/1/console/type {"command":"codepage 819/037"}`):
   ```
   HHC01474I Using internal codepage conversion table 819/037
   ```
   **This was the actual fix that made real content print correctly** —
   confirmed with `ls -l /etc` content rendering perfectly between banner
   pages, no clumping, no garbage.

   Persisted properly in `zOS/config/ubuntu.rc` (not `cpu.cnf`, which is
   shared across every other Hercules config on this box — z22/z24/z25/z31 —
   and each `hercules -f config/cpu.cnf -r config/<x>.rc` invocation is its
   own process reading `cpu.cnf` fresh, so a change there would apply to all
   of them). `.rc` files are just Hercules console commands replayed at
   startup, and `CODEPAGE` is a valid one, so it now lives right at the top
   of `ubuntu.rc` — takes effect automatically on every future IPL of this
   system (native or z/VM) without touching any other config.

   `vmur`'s own `-t`/`--text` flag does *not* offer an alternative that
   avoids this: it performs its own ASCII↔EBCDIC conversion on the Linux
   side, hardcoded to ISO-8859-1↔IBM037 (per `man vmur`) — no flag to pick a
   different table. Hercules' `CODEPAGE` is simply the matching setting for
   the *other end* of that same conversion (decoding the EBCDIC vmur sends
   back to ASCII for display). `819/037` is exactly vmur's own pair — that's
   why it's the fix, not a workaround alongside a different one. Skipping
   `-t` and hand-converting with `dd conv=ebcdic` instead uses the generic
   ebcdic table, not IBM037, and was already tried unsuccessfully in the
   original issue thread (gave mixed LF/CR garbage after ~132 chars).

### The "stuck device" mechanics (why it looked unfixable at first)

Once a file gets corrupted by the codepage bug mid-transfer, the spool file
wedges permanently: `cp drain` reports success but the file still shows
active; `cp purge ... ALL` refuses (`NO FILES PURGED`); `cp vary off` refuses
(`not drained`). **Fix for an already-wedged file**: reset the device at the
Hercules hardware level (not just the CP/z-VM level), via the Hercules
system console (`devices/1`, `console/type`) — z/VM's CP will then let go of
it:
```
POST /devices/1/console/type {"command":"detach 000e"}
POST /devices/1/console/type {"command":"attach 000e 1403 0.0.0.0:10014 sockdev nocr"}
```
This forces `HCPHOT2260A ... HAS BEEN REMOVED FROM THE ACTIVE CONFIGURATION
(BOXED)` then re-adds it fresh. After that, purge the specific wedged
spoolid directly (not `ALL` — that still refuses):
```
cp purge <owner> prt <spoolid>      # e.g. cp purge ubuntu prt 0005
```
Also useful regardless of the codepage bug: `MANUAL SEP` (the default) makes
CP wait for an operator ack between every file that you can't give without
logging on as `OPERATOR` — always `cp start <rdev> class a auto` instead.
And if a file looks queued-but-not-printing despite `HOLD NONE`, force it:
`cp change <userid> printer|punch <spoolid> nohold`.

**Caution — the detach/reattach trick can itself wedge the device at the OS
socket level** if Hera still has a client connected/reconnecting to that
port when you detach (`punch/disconnect` it first). Even doing that,
`000D` (punch) got stuck this way during this session — Hercules kept
reporting `device already bound to socket 0.0.0.0:3525` on every reattach
attempt, and the device dropped out of `GET /cgi-bin/api/v1/devices`
entirely. That needs a full Hercules restart to recover (not done — low
priority since punch's data path was never the broken one; print was the
actual target and is now confirmed working via `000F`).

### Original investigation notes (kept for the repro details)

Tried wiring `vmur print`/`vmur punch` output (from `ubuntu`, the z/VM guest)
through to the **real** Hercules-attached devices (`0009`/`000E`/`000F` PRT,
`000D` PCH — the ones Hera's own room panels show), using standard z/VM
operator mechanics:

```
tools/hera.sh 2 text "cp start 000e class a auto"   # AUTO, not MANUAL, sep —
tools/hera.sh 2 key enter                            # MANUAL SEP blocks between
                                                       # every file waiting for
                                                       # an operator ack you can't
                                                       # give without logging on
                                                       # as OPERATOR
```
If a file appears held despite `HOLD NONE` in `cp query printer/punch all`,
force it: `CP CHANGE <userid> PRINTER|PUNCH <spoolid> NOHOLD` (`0000001 FILE
CHANGED`).

**Result**: CP's own auto-generated job separator/banner pages transmit and
render correctly in Hera's `printer/output` buffer (confirmed: full banner
art, `FILE NAME/TYPE=`, `ORIGINID=`, `SPID=` header block, twice — header and
trailer). But the actual **spooled file's data records never arrive** — the
single-line payload between the two banner pages is blank. Reproduced
identically on all three real devices tried (`000D` punch, `000E` and `000F`
print), with every combination of `AUTO`/`MANUAL SEP`, `NOHOLD`, and fresh
vs. reused spool files.

Once this happens the file wedges the device **permanently**:
- `cp drain <rdev>` reports `DRAINED` but the file still shows
  `PRT-`/`PUN- (nnnn)` (active) in `cp query printer/punch all` forever after.
- `cp purge [force] system prt/pun all` → `NO FILES PURGED` (CP refuses to
  purge a file it thinks is still attached to a device transfer).
- `cp vary off <rdev>` → `HCPCPF142E ... not drained` (refuses, contradicting
  the drain report above).
- The only way to get a *new* file moving again was to drain the wedged
  device for good and route to a different, never-used real device number.

This looks like a genuine interaction bug between Hercules' `sockdev`
PRT/PCH emulation and z/VM's real-device spool print/punch driver — CP's own
internally-generated separator CCWs succeed, but relaying the actual
spool-file data CCWs through the same channel doesn't. Not something fixable
from the Linux or z/VM config side; would need Hercules-level investigation
(out of scope for this session).

**What to use instead** — all confirmed reliable, with real content:
- `vmur punch`/`vmur print`/`vmur receive` between z/VM guests (section 7) —
  full round trip proven with real file content, including `ls -l` output
  actually sitting in CP's spool as real records (`vmur list -q pun`/`-q prt`
  shows it).
- Hera's `printer/test` → `printer/output` → `printer/save` — Hera's own
  built-in diagnostic printout, exports a real PDF
  (`Hera_Dev/spool/PRT_000E_<timestamp>.pdf`). Confirmed working.
- Hera's `reader/load` + `reader/submit` with arbitrary real content,
  confirmed byte-exact via `vmur receive --text` on the far end (this is the
  one full loop — Hera panel → real device → vmur — that works end to end).

## Why native/LPAR-IPL'd Linux can't do this (background, from earlier session)

`vmur` (`drivers/s390/char/vmur.c`) is the *only* Linux driver for
3505/3525/1403-class devices, and it only binds to z/VM's virtual spool
device types — it talks to CP via `diag14`/`diag210` hypercalls, not real
channel I/O. Its match table doesn't even list the real hardware cu_types
(`2821`/`3505`), so under native/LPAR IPL (`IPL 0120` directly, no z/VM
underneath) there is **no driver at all** for these devices —
confirmed by `chccwdev -e` failing with `No driver is attached to this
device`. This is a real Linux-on-Z limitation, not a Hercules quirk — same
would happen on a real z15 LPAR. Tape (`tape_34xx`/`tape_3590`) and DASD
(`dasd-eckd`) both have real, non-VM-dependent drivers and work fine either
way.
