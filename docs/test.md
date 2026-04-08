# Steps to test Hera.
# These steps will:
# Download, build and install Hercules
# Download and install Hera
# Download and install a minimum z/OS 2.2 environment (maintenance environment)
#

mkdir IBM
cd IBM

# Install Hercules
git clone https://github.com/wrljet/hercules-helper
cd hercules-helper
./hercules-buildall.sh --flavor=sdl-hyperion
source ~/.bashrc
cd ..

# Install Hera
git clone https://github.com/MockbaTheBorg/Hera
python -m venv venv
source venv/bin/activate
pip install -r Hera/requirements.txt 

# Create test env (z/OS 2.2)
mkdir test
cd test
cat > hercules.cnf
``` from here
CPUSERIAL 000111 # CPU serial number
CPUMODEL 8562 # CPU model number (8562=z15)
MAINSIZE 8192 # Main storage size in megabytes 768
XPNDSIZE 0 # Expanded storage size in megabytes
CNSLPORT 3270 # TCP port number to which consoles connect
HTTP PORT 8081 noauth # HTTP server
HTTP START
NUMCPU 4 # Number of CPUs
TZOFFSET +0000
OSTAILOR Z/OS # OS tailoring
PGMPRDOS LICENSED # Allow OS/390 and Z/OS systems to run
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
``` to here
wget https://archive.org/download/zos-2.2/Dasds/sares1
chmod 444 sares1
ckd2cckd64 sares1 sares1.cckd
chmod 444 sares1.cckd
mkdir sf

# Start hercules (inside test folder)
hercules -f test.cnf

# Start Hera (inside Hera folder)
source venv/bin/activate (if not already)
python hera.py

# IPL z/OS
Go to the CPU Tab and set the IPL dials to A80
Press the IPL button
(or type `IPL A80` in the Console)
Go to the terminal at 0700
If waiting for 'DENY' or 'CONTINUE', type `R 0,CONTINUE` and enter
Wait for the IPL to complete (`ISF442I Server SDSF XCF communications ready`)

# Log in to TSO
Go to the terminal at 0701
Type `LOGON IBMUSER` enter
Blindly type the password `SYS1` enter
enter
At ISPF menu:
- F3 = Save and go back
- F12 = Cancel and go back
From TSO 'Ready' Prompt:
- `ISPF` - Return to ISPF menu
- `LOGOFF` - End session

# Shutdown z/OS
Log off from TSO
Go to the terminal at 0700
Type `S SHUTSA`
Wait for `IEF352I ADDRESS SPACE UNAVAILABLE`
Type `$P JES2`
Wait for `IEF404I JES2 - ENDED`
Type `Z EOD`
Wait for `IEE334I HALT EOD SUCCESSFUL`
Type `QUIESCE`
The CPUs will stop

From this point you can either:
   IPL again
   Close Hercules (press `Power Off` in the CPU Tab)

