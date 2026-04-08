## Testing Hera with a minimal z/OS 2.2 environment

This document describes a simple, reproducible way to test `Hera` using a local
Hercules instance and a small z/OS 2.2 dataset. It assumes a Linux host with
`git`, `python3`, `pip`, `wget`, and `ckd2cckd64` available.

Prerequisites

- Git
- Python 3.8+ and `venv`
- Build tools for Hercules (see https://github.com/wrljet/hercules-helper)
- `ckd2cckd64` utility

Overview

1. Build and install Hercules using `hercules-helper`.
2. Clone and install `Hera` into a Python virtual environment.
3. Create a minimal Hercules config and required DASD file(s).
4. Start Hercules, then start `hera.py`, and IPL z/OS.

Steps

1. Create a workspace and build Hercules

```sh
mkdir -p ~/IBM && cd ~/IBM
git clone https://github.com/wrljet/hercules-helper
cd hercules-helper
./hercules-buildall.sh --flavor=sdl-hyperion
# Follow any build instructions printed by the script (may require sudo).
source ~/.bashrc || true
cd ~/IBM
```

2. Clone Hera and install Python deps

```sh
git clone https://github.com/MockbaTheBorg/Hera
cd Hera
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Create a test directory and a Hercules config

```sh
mkdir -p ~/IBM/test && cd ~/IBM/test
cat > test.cnf <<'EOF'
# Minimal Hercules configuration for z/OS 2.2
CPUSERIAL 000111
CPUMODEL 8562
MAINSIZE 8192
XPNDSIZE 0
CNSLPORT 3270
HTTP PORT 8081 noauth
HTTP START
NUMCPU 4
TZOFFSET +0000
OSTAILOR Z/OS
PGMPRDOS LICENSED
LPARNAME ADCD
DIAG8CMD ENABLE
DEVTMAX 8
TIMERINT 400
CCKD ra=9,raq=16,rat=16,wr=8,gcparm=4
LOADPARM 0A80SA..
000E 1403 127.0.0.1:11403 sockdev
0700 3270 *
0701 3270 *
0580 3420
0A80 3390 sares1.cckd cu=3990-6 sf=sf/sares1_*.sf
EOF
```

4. Download DASD image(s)

Replace the example URL below with your DASD source if different.

```sh
wget https://archive.org/download/zos-2.2/Dasds/sares1
chmod 444 sares1
ckd2cckd64 sares1 sares1.cckd
chmod 444 sares1.cckd
mkdir -p sf
```

5. Start Hercules

Run Hercules from the `~/IBM/test` folder using the config created earlier:

```sh
hercules -f test.cnf
```

6. Start Hera

In a separate terminal, activate the `Hera` virtualenv and start the GUI:

```sh
cd ~/IBM/Hera
source venv/bin/activate
python hera.py
```

7. IPL z/OS

- In the Hera GUI: open the CPU tab and set the IPL dials to `A80`, then press
   the IPL button. (Or use the Hercules console and enter `IPL A80`.)
- Monitor the operator console (terminal 0700). If the system stops waiting
   for an operator reply, enter `R 0,CONTINUE` on that console.
- Wait until the IPL completes (look for messages such as
   `ISF442I Server SDSF XCF communications ready`).

8. Log in to TSO

- On terminal 0701 (TSO), enter `LOGON IBMUSER` and when prompted use the
   password `SYS1` (this example credential is for testing only).
- Press Enter to start ISPF. Common keys:
   - F3: Save and go back
   - F12: Cancel and go back

9. Shutdown z/OS cleanly

- From the MVS Operator console (0700):
   - `S SHUTSA` and wait for `IEF352I ADDRESS SPACE UNAVAILABLE`
   - `$P JES2` and wait for `IEF404I JES2 - ENDED`
   - `Z EOD` and wait for `IEE334I HALT EOD SUCCESSFUL`
   - `QUIESCE` to stop the CPUs

After shutdown you can re-IPL or power off Hercules using the GUI CPU tab.

Notes and troubleshooting

- If `hercules` is not found after building, ensure the build output bin
   directory is in your `PATH` (or run with the absolute path).
- Replace DASD images with ones appropriate for your setup — the archive
   example above is provided as a convenience and may not suit all tests.
- For automation, consider scripting the steps above and validating console
   output for key messages during IPL.
 - If you need to perform a `Factory Reset` of the z/OS environment: close
   Hercules and delete the shadow file located in the `sf` subfolder (this
   removes any saved disk shadow state).
