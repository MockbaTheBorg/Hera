# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
"""
Shared TN3270 protocol constants and helpers.
"""

import codecs

from ..widgets.terminal_screen import CELLS

TERMINAL_TYPE = "IBM-3279-2-E"

IAC = 0xFF
WILL = 0xFB
WONT = 0xFC
DO = 0xFD
DONT = 0xFE
SB = 0xFA
SE = 0xF0
IP = 0xF4
EOR = 0xEF

OPT_BINARY = 0x00
OPT_EOR = 0x19
OPT_TTYPE = 0x18

CMD_W = frozenset({0x01, 0xF1})
CMD_RB = frozenset({0x02, 0xF2})
CMD_NOP = frozenset({0x03})
CMD_EW = frozenset({0x05, 0xF5})
CMD_RM = frozenset({0x06, 0xF6})
CMD_EWA = frozenset({0x0D, 0x7E})
CMD_RMA = frozenset({0x0E, 0x63})
CMD_EAU = frozenset({0x0F, 0x6F})
CMD_WSF = frozenset({0x11, 0xF3})

ORD_PT = 0x05
ORD_GE = 0x08
ORD_SBA = 0x11
ORD_EUA = 0x12
ORD_IC = 0x13
ORD_SF = 0x1D
ORD_SA = 0x28
ORD_SFE = 0x29
ORD_MF = 0x2C
ORD_RA = 0x3C
ORDERS = frozenset({ORD_PT, ORD_GE, ORD_SBA, ORD_EUA, ORD_IC, ORD_SF, ORD_SA, ORD_SFE, ORD_MF, ORD_RA})

EAT_ALL = 0x00
EAT_HIGHLIGHT = 0x41
EAT_COLOR = 0x42

HL_NORMAL = 0xF0
HL_BLINK = 0xF1
HL_REVERSE = 0xF2
HL_UNDERSCORE = 0xF4
HL_INTENSIFY = 0xF8

AID_NONE = 0x60
AID_SF = 0x88
AID_CLEAR = 0x6D
AID_ENTER = 0x7D
AID_PA1 = 0x6C
AID_PA2 = 0x6E
AID_PA3 = 0x6B

SHORT_READ_AIDS = frozenset({AID_CLEAR, AID_PA1, AID_PA2, AID_PA3})

SF_READ_PARTITION = 0x01
SF_ERASE_RESET = 0x03
SF_OUTBOUND_DS = 0x40
SF_QUERY_REPLY = 0x81

QC_SUMMARY = 0x80
QC_USABLE = 0x81
QC_ALPHA = 0x84
QC_CHARSETS = 0x85
QC_COLOR = 0x86
QC_HIGHLIGHT = 0x87
QC_REPLY_MODES = 0x88
QC_DDM = 0x95
QC_AUX_DEVICE = 0xA1
QC_IMPL_PARTS = 0xA6
QC_NULL = 0xFF

QUERY_PROFILE_ORDER = [
    QC_USABLE,
    QC_ALPHA,
    QC_CHARSETS,
    QC_COLOR,
    QC_HIGHLIGHT,
    QC_REPLY_MODES,
    QC_DDM,
    QC_AUX_DEVICE,
    QC_IMPL_PARTS,
]

QUERY_PROFILE_BODIES = {
    QC_USABLE: bytes.fromhex(
        "01 00 00 50 00 18 01 00 0a 02 e5 00 02 00 6f 09 0c 07 80"
    ),
    QC_ALPHA: bytes.fromhex("00 07 80 00"),
    QC_CHARSETS: bytes.fromhex(
        "82 00 09 0c 00 00 00 00 07 00 10 00 02 b9 00 25 01 10 f1 03 c3 01 36"
    ),
    QC_COLOR: bytes.fromhex(
        "00 10 00 f4 f1 f1 f2 f2 f3 f3 f4 f4 f5 f5 f6 f6 f7 f7 "
        "f8 f8 f9 f9 fa fa fb fb fc fc fd fd fe fe ff ff"
    ),
    QC_HIGHLIGHT: bytes.fromhex("05 00 f0 f1 f1 f2 f2 f4 f4 f8 f8"),
    QC_REPLY_MODES: bytes.fromhex("00 01 02"),
    QC_DDM: bytes.fromhex("00 00 10 00 10 00 01 01"),
    QC_AUX_DEVICE: bytes.fromhex("00 00 00 00 00 00 00 06 a7 f3 f2 f7 f0 00"),
    QC_IMPL_PARTS: bytes.fromhex("00 00 0b 01 00 00 50 00 18 00 50 00 18"),
}

_SIX_BIT = bytes([
    0x40, 0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7,
    0xC8, 0xC9, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F,
    0x50, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
    0xD8, 0xD9, 0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F,
    0x60, 0x61, 0xE2, 0xE3, 0xE4, 0xE5, 0xE6, 0xE7,
    0xE8, 0xE9, 0x6A, 0x6B, 0x6C, 0x6D, 0x6E, 0x6F,
    0xF0, 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7,
    0xF8, 0xF9, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F,
])

GE_TO_UNICODE = {
    0x85: "│",
    0xA2: "─",
    0xC3: "■",
    0xC4: "└",
    0xC5: "┌",
    0xC6: "├",
    0xC7: "┴",
    0xD3: "┼",
    0xD4: "┘",
    0xD5: "┐",
    0xD6: "┤",
    0xD7: "┬",
}


def decode_addr(b0: int, b1: int) -> int:
    """Decode a 3270 12-bit or 14-bit buffer address."""
    setting = (b0 & 0xC0) >> 6
    if setting in (0b01, 0b11):
        return ((b0 & 0x3F) << 6) | (b1 & 0x3F)
    return ((b0 & 0x3F) << 8) | b1


def encode_addr(addr: int) -> bytes:
    """Encode a 3270 buffer address using 12-bit (6+6) encoding."""
    return bytes([_SIX_BIT[(addr >> 6) & 0x3F], _SIX_BIT[addr & 0x3F]])


def wrap_addr(addr: int, size: int = CELLS) -> int:
    return addr % size


def ebcdic_to_char(byte: int) -> str:
    if byte == 0x00:
        return " "
    try:
        return codecs.decode(bytes([byte]), "cp037")
    except Exception:
        return "?"
