# Hercules z/OS ADCD Cheat Sheet

*A practical reference guide for Hercules-based z/OS ADCD systems. Commands, utilities, and techniques validated through hands-on testing.*

**Last Updated: April 8, 2026**

## Contents

- [Hercules](#hercules)
- [General MVS](#general-mvs)
- [General TSO/ISPF](#general-tsoispf)
- [JCL & Job Control](#jcl--job-control)
- [SDSF / JES](#sdsf--jes)
- [Useful One-liners / Scripts](#useful-one-liners--scripts)

---

## Hercules

Hercules emulator configuration, startup, and operational commands.

### Starting the Emulator

Launch Hercules with a configuration file:

```
./start <config_file>
```

Common configuration files for ADCD:
- `z24` — Full z/OS system with all optional products
- `z24min` — Minimal maintenance system for quick IPL

### IPL (Initial Program Load)

Once Hercules is running, IPL the z/OS system from the Hercules console. A80 is the standard IPL device address for ADCD:

```
IPL A80
```

The system will take considerable time to boot. Monitor the 3270 console for progress messages. First boot may take 30-90 minutes depending on host performance.

### Enable Integrated Console

Once z/OS is running, activate the Hercules integrated 3270 console from the Hercules command console:

```
.VARY CN(*),ACTIVATE
```

### Console Terminology and Setup

z/OS provides two distinct types of 3270 terminals:

- **Master/Operator Console (device 0700)** — Used for operator commands that control the system
- **TSO Logon Terminal** — Used for user logon to TSO/ISPF and interactive commands

#### Important Setup Requirements

- The Master/Operator Console terminal (device 0700) must be connected to Hercules BEFORE the IPL. If you connect after IPL, the console will not function properly.
- TSO logon terminals can be connected at any time after z/OS is booted.

### Command Types: MVS vs TSO

Throughout this document you will see two types of commands:

- **MVS System Commands (or Operator Commands)** — Issued from the Master/Operator Console to control the z/OS system (e.g., `D C,L`, `VARY 0700,CONSOLE`)
- **TSO Commands** — Issued by users logged into TSO/ISPF for interactive tasks (e.g., `LOGON IBMUSER`, `DSLIST`)

### Operator Command Syntax

Operator commands are prefixed differently depending on where they are issued:

- **In Hercules Integrated Console:** Commands must be prepended with a dot (.). For example: `.D A,L`
- **In the Master/Operator Console (3270 terminal):** No dot is needed. Command is entered directly. For example: `D A,L`

### Late Console Connection Recovery

If you connect a terminal emulator to device 0700 AFTER z/OS has already booted, the terminal will display the Hercules logo but z/OS will not route console messages to it. Follow these steps to recover:

1. From the Hercules integrated console, issue the command: `.VARY 0700,CONSOLE`
2. On the 0700 terminal still showing the Hercules logo, press the **CLEAR** key
3. The console screen will now display properly and z/OS messages will begin appearing

### Verifying Console Status

To display all consoles and their status, issue the command from the Master/Operator Console:

```
D C,L
```

This displays all defined consoles and their status (ACTIVE or INACTIVE). Look for device L700 or C908 — these should show STATUS=ACT once properly activated.

---

## 3270 Terminal Keys

These key definitions apply across both console and TSO/ISPF sessions.

### Essential 3270 Terminal Keys

The 3270 terminal keyboard has special keys beyond a standard PC keyboard. Here are the most useful ones:

| Key | Keyboard Mapping* | Purpose |
|-----|-------------------|---------|
| **PA1** | Escape, Ctrl+P | **Attention/Interrupt** — Cancel current command and return to READY prompt |
| **PA2** | Ctrl+Home | **Refresh/Redisplay** — Restore last screen sent from mainframe (useful if you made mistakes) |
| **PA3** | Ctrl+PageUp | **Cancel pending output** — Stop receiving output from a command |
| **CLEAR** | Ctrl+Z | **Clear screen** — Clears the display (may need PA1 after for full reset) |
| **RESET** | Ctrl+T | **Unlock keyboard** — Unlocks keyboard if locked after invalid input |
| **ENTER** | Return/Enter | **Send data** — Transmit current screen input to mainframe |
| **PF1-PF12** | F1-F12 | **Program Function keys** — Customizable keys (default functions vary by installation) |
| **PF13-PF24** | Shift+F1-F12 | **Extended Function keys** — Additional customizable keys |
| **TAB** | Tab | **Move cursor to next field** — Navigate between input fields |

**Finding keys on your keyboard:** The 3270 keys listed above are emulated on PC keyboards. The exact mapping depends on your tn3270 emulator (Vista, x3270, etc.). Check your emulator settings or help menu for the exact mappings. Most modern emulators allow customization.

## Console Display & Panel Control

When you issue commands like `D A,L`, the 3270 console splits the screen and displays results in a scrollable panel area. Here's how to manage these panels:

### Managing Console Display Panels

| Command | Description |
|---------|-------------|
| `K E,D` | Erase and close the bottom display area (removes the scrollable panel) |
| `K A,NONE` | Undefine the display area completely |
| `K E,1` | Delete the top line of the display area |
| `K S,REF` | Open console configuration menu to customize display behavior |
| `K D` | Restore/redefine the display area (brings the panel back after closing with `K E,D`) |

**Most common workflow:** After running a command that creates a panel (like `D A,L`), press **K E,D** to clear and close it when you're done reviewing the output. To bring the panel back later, press **K D**.

---

## General MVS

General MVS System commands for querying system status, managing devices, and controlling the operating system.

### System Status & Display Commands

| Command | Description |
|---------|-------------|
| `D A,L` | List active jobs and users |
| `D T` | Display current time and date |
| `D IPLINFO` | Display IPL information and z/OS version |
| `D M` | Display device matrix configuration |
| `D R,L` | Display unanswered messages or action items |
| `D C,SS` | Display console subsystems |

### DASD/Disk Devices

| Command | Description |
|---------|-------------|
| `D U,DASD,ONLINE` | Display all online DASD volumes |
| `D U,,,0A80,1` | Display a specific device (example: device 0A80) |
| `D U,,,0000,100` | Display device range (devices 0000-0100) |
| `D U,,,0500,50` | Display device range (devices 0500-0550) |

### Printer Devices (1403 Printers)

| Command | Description |
|---------|-------------|
| `D U,,,000E,1` | Display printer device 000E (1403 printer) |
| `D U,,,000F,1` | Display printer device 000F (1403 printer) |

### Card Reader/Punch Devices

| Command | Description |
|---------|-------------|
| `D U,,,000C,1` | Display card reader device 000C (3505 reader) |
| `D U,,,000D,1` | Display card punch device 000D (3525 punch) |

### Console Printer Device

| Command | Description |
|---------|-------------|
| `D U,,,0009,1` | Display console printer device 0009 (3215 console) |

### Tape Devices

| Command | Description |
|---------|-------------|
| `D U,,,0560,1` | Display tape device 0560 |
| `D U,,,0580,1` | Display tape device 0580 |
| `D U,,,0590,1` | Display tape device 0590 |
| `D U,TAPE` | Display all tape devices and status |
| `V 0560,ONLINE` | Vary tape device 0560 online |
| `V 0560,OFFLINE` | Vary tape device 0560 offline |

### Device Display & Querying Tips

The `D U` command is powerful but can generate large outputs that are paginated on the 3270 console. Here are practical ways to work with device displays:

**Handling Pagination:**
- Large `D U` queries are paged automatically on the console
- Press **Page Down (PF8)** to scroll forward through results
- Press **Page Up (PF7)** to scroll backward
- Press **End** to jump to the last page

**Query by Device Type (avoids pagination):**
| Command | Description |
|---------|-------------|
| `D U,DASD` | Display all DASD devices |
| `D U,PRINTER` | Display all printer devices (if recognized) |
| `D U,READER` | Display all reader devices (if recognized) |

**Query by Address Range (limits output):**
| Command | Description |
|---------|-------------|
| `D U,,,0A00,50` | Display 50 devices starting at address 0A00 |

Replace the start address and range count as needed. The same syntax can be used with other starting addresses, such as the examples listed above. This is useful for systematic inventory of large device configurations.

### Job/Task Control Commands

| Command | Description |
|---------|-------------|
| `S VTAM` | Start VTAM (Virtual Telecommunications Access Method, required for terminal access) |
| `S TSO` | Start TSO/ISPF environment for user access |
| `P TCPIP` | Stop TCP/IP stack |
| `C jobname` | Cancel a job by name |

---

## General TSO/ISPF

TSO (Time Sharing Option) commands for interactive session management, dataset operations, and system information.

### Help & Information Commands

| Command | Description |
|---------|-------------|
| `HELP` | Display TSO help menu system |
| `HELP LISTDS` | Get detailed help on a specific command (e.g., LISTDS) |
| `TIME` | Display current date and time |

### Dataset Management Commands

| Command | Description |
|---------|-------------|
| `LISTDS 'SYS1.PARMLIB'` | List attributes of a dataset (record format, record length, block size, etc.) |
| `LISTDS 'SYS1.PARMLIB' MEMBERS` | List all members of a Partitioned Dataset (PDS) |
| `LISTALC` | List all datasets currently allocated in your TSO session |
| `LISTBC` | List broadcast messages sent by system administrator (if any) |

### Dataset Operations & Allocation

| Command | Description |
|---------|-------------|
| `ALLOCATE DA(userid.newds) NEW SPACE(100,50) TRACKS LRECL(80) BLKSIZE(800) DSORG(PO)` | Create new Partitioned Dataset (PDS) with specific space and DCB attributes |
| `ALLOCATE DA(userid.newds) NEW SPACE(10,5) TRACKS DSORG(PS) LRECL(80)` | Create new sequential dataset (PS) with specified attributes |
| `ALLOCATE DA(userid.existingds) SHR` | Allocate existing dataset for shared (read) access |
| `FREE DA(userid.newds)` | Free/deallocate a dataset allocation |
| `DELETE 'userid.testdata'` | Delete a dataset (use caution!) |
| `RENAME 'userid.oldname' 'userid.newname'` | Rename a dataset or PDS member |

### Text Editing Commands

| Command | Description |
|---------|-------------|
| `EDIT 'userid.dataset(member)'` | Create or edit a member in a Partitioned Dataset (PDS) |
| `EDIT 'userid.sequential.data'` | Create or edit a sequential dataset |

### ISPF & Profile Commands

| Command | Description |
|---------|-------------|
| `ISPF` | Start ISPF/PDF full-screen editor and utilities system (opens primary option menu) |
| `PROFILE` | Display or modify your TSO user profile settings |

### Job & Session Commands

| Command | Description |
|---------|-------------|
| `STATUS` | Display status of batch jobs you have submitted |
| `LOGOFF` | End your TSO session and disconnect |
| `SEND 'message'` | Send a message to another TSO user |

---

## JCL & Job Control

Job Control Language syntax, common patterns, and job submission techniques.

*[No entries yet]*

---

## SDSF / JES

Spool Display and Search Facility for job management and output viewing.

### Job Management

| Command | Description |
|---------|-------------|
| `$DA` | Display all jobs in the system |
| `$D J'userid'` | Display jobs for a specific user |
| `$C J'jobname'` | Cancel a specific job |
| `$H J'jobname'` | Hold a specific job |
| `$A J'jobname'` | Release a held job |

### Output Management

| Command | Description |
|---------|-------------|
| `$H O'jobname'` | Hold output for a specific job |
| `$A O'jobname'` | Release held output for a specific job |
| `$P O'jobname'` | Purge output for a specific job |

### Spool Management

| Command | Description |
|---------|-------------|
| `$D SPOOL` | Display spool usage |
| `$P J,ALL` | Purge all jobs from the spool |
| `$D SPOOL,VOL` | Display spool volumes |

### Printer Management

| Command | Description |
|---------|-------------|
| `$D PR` | Display printer status |
| `$S PRn` | Start a specific printer |
| `$P PRn` | Stop a specific printer |

### JES2 System Commands

| Command | Description |
|---------|-------------|
| `$S JES2` | Restart JES2 |
| `$P JES2` | Stop JES2 |

### Miscellaneous

| Command | Description |
|---------|-------------|
| `$D I` | Display active initiators |
| `$S I'n'` | Start an initiator |
| `$P I'n'` | Stop an initiator |

---

## Useful One-liners / Scripts

Quick scripts, shell one-liners, and automation snippets for common tasks.

*[No entries yet]*

---

*Built through collaborative testing on live Hercules z/OS ADCD systems. Each entry validated before inclusion.*
