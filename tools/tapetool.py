# Hera - Hercules Hyperion GUI - by Mockba the Borg
# Based on Jason by Oleh Yuschuk
#
#!/usr/bin/env python3
"""
Inspect and extract datasets from AWS tape images.

The tool understands:
- AWS block framing
- Standard IBM tape labels (VOL1/HDR1/HDR2/EOF1/EOF2)
- Logical records for RECFM=F and RECFM=V/VB datasets
- IEBCOPY-style unloaded partitioned datasets stored as one tape dataset
"""

from __future__ import annotations

import argparse
import codecs
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

EBCDIC_CODEC = "cp037"
LABEL_NAMES = {"VOL1", "HDR1", "HDR2", "EOF1", "EOF2", "EOV1", "EOV2"}
MEMBER_NAME_RE = re.compile(r"//([A-Z0-9#$@]{1,8})\b")


class TapeToolError(Exception):
    """Fatal parsing or usage error."""


def ebcdic_to_text(data: bytes) -> str:
    return codecs.decode(data, EBCDIC_CODEC, errors="replace")


def text_field(data: bytes) -> str:
    return ebcdic_to_text(data).rstrip()


def as_int(data: bytes) -> int | None:
    text = text_field(data).strip()
    return int(text) if text.isdigit() else None


def rdw_length(data: bytes) -> int:
    return int.from_bytes(data[:2], "big")


def bdw_length(data: bytes) -> int:
    if data[0] & 0x80:
        return int.from_bytes(data[:4], "big") & 0x7FFFFFFF
    return int.from_bytes(data[:2], "big")


@dataclass
class AwsBlock:
    index: int
    offset: int
    current_length: int
    previous_length: int
    flags1: int
    flags2: int
    data: bytes

    @property
    def is_tapemark(self) -> bool:
        return self.current_length == 0

    @property
    def label_id(self) -> str | None:
        if self.is_tapemark or len(self.data) < 4:
            return None
        label = ebcdic_to_text(self.data[:4])
        return label if label in LABEL_NAMES else None


@dataclass
class TapeLabel:
    kind: str
    raw: bytes
    text: str
    fields: dict[str, object]


@dataclass
class LogicalRecord:
    index: int
    raw: bytes
    block_index: int


@dataclass
class MemberEntry:
    number: int
    name: str
    key: int
    records: list[LogicalRecord] = field(default_factory=list)

    @property
    def payload_bytes(self) -> bytes:
        payload = bytearray()
        for record in self.records:
            payload.extend(unload_member_payload(record))
        return bytes(payload)

    @property
    def line_count(self) -> int:
        data = self.payload_bytes
        return len(data) // 80 if len(data) % 80 == 0 else 0

    @property
    def data_bytes(self) -> int:
        return len(self.payload_bytes)


@dataclass
class DatasetEntry:
    number: int
    synthetic_name: str
    header_labels: list[TapeLabel]
    trailer_labels: list[TapeLabel]
    data_blocks: list[AwsBlock]
    record_format: str
    block_size: int | None
    lrecl: int | None
    dsid: str | None
    file_sequence: int | None
    block_count: int | None
    records: list[LogicalRecord] = field(default_factory=list)
    organization: str = "SEQ"
    dataset_format: str = "sequential"
    members: list[MemberEntry] = field(default_factory=list)

    def hdr1(self) -> TapeLabel | None:
        for label in self.header_labels:
            if label.kind == "HDR1":
                return label
        return None

    def hdr2(self) -> TapeLabel | None:
        for label in self.header_labels:
            if label.kind == "HDR2":
                return label
        return None

    @property
    def display_name(self) -> str:
        if self.dsid:
            return f"{self.synthetic_name} ({self.dsid})"
        return self.synthetic_name

    @property
    def is_partitioned(self) -> bool:
        return bool(self.members)

    @property
    def data_size(self) -> int:
        return sum(len(block.data) for block in self.data_blocks)

    def summary_format(self) -> str:
        base = self.record_format or "U"
        if self.dataset_format == "iebcopy-unload":
            return f"{base} unloaded-partitioned"
        if self.is_partitioned:
            return f"{base} partitioned"
        return base


@dataclass
class TapeImage:
    path: Path
    size: int
    blocks: list[AwsBlock]
    volume_labels: list[TapeLabel]
    datasets: list[DatasetEntry]

    @property
    def tapemark_count(self) -> int:
        return sum(1 for block in self.blocks if block.is_tapemark)

    @property
    def volume_name(self) -> str | None:
        for label in self.volume_labels:
            if label.kind == "VOL1":
                value = label.fields.get("volume")
                if isinstance(value, str) and value:
                    return value
        return None


def parse_aws_blocks(path: Path) -> list[AwsBlock]:
    data = path.read_bytes()
    blocks: list[AwsBlock] = []
    offset = 0
    index = 1
    while offset + 6 <= len(data):
        current_length = int.from_bytes(data[offset:offset + 2], "little")
        previous_length = int.from_bytes(data[offset + 2:offset + 4], "little")
        flags1 = data[offset + 4]
        flags2 = data[offset + 5]
        block_offset = offset
        offset += 6
        if offset + current_length > len(data):
            raise TapeToolError(f"truncated AWS block {index}")
        payload = data[offset:offset + current_length]
        offset += current_length
        blocks.append(
            AwsBlock(
                index=index,
                offset=block_offset,
                current_length=current_length,
                previous_length=previous_length,
                flags1=flags1,
                flags2=flags2,
                data=payload,
            )
        )
        index += 1
    if offset != len(data):
        raise TapeToolError("trailing bytes found after last AWS block")
    return blocks


def parse_label(block: AwsBlock) -> TapeLabel:
    text = ebcdic_to_text(block.data[:80]).ljust(80)
    kind = text[:4]
    fields: dict[str, object] = {}
    if kind == "VOL1":
        fields["volume"] = text[4:10].strip()
        fields["owner"] = text[37:51].strip()
    elif kind in {"HDR1", "EOF1", "EOV1"}:
        fields["dsid"] = text[4:21].rstrip()
        fields["volume"] = text[21:27].strip()
        fields["file_sequence"] = as_int(block.data[27:31])
        fields["generation"] = as_int(block.data[31:35])
        fields["version"] = as_int(block.data[35:37])
        fields["creation"] = text[37:43].strip()
        fields["expiration"] = text[43:49].strip()
        fields["block_count"] = as_int(block.data[54:60])
        fields["system"] = text[60:73].rstrip()
    elif kind in {"HDR2", "EOF2", "EOV2"}:
        recfm = text[4:5].strip() or "U"
        block_size = as_int(block.data[5:10])
        lrecl = as_int(block.data[10:15])
        fields["recfm"] = recfm
        fields["block_size"] = block_size
        fields["lrecl"] = lrecl
        fields["raw_tail"] = text[15:39].rstrip()
    return TapeLabel(kind=kind, raw=block.data, text=text, fields=fields)


def parse_standard_labeled_tape(path: Path) -> TapeImage:
    blocks = parse_aws_blocks(path)
    size = path.stat().st_size
    index = 0

    volume_labels: list[TapeLabel] = []
    while index < len(blocks) and not blocks[index].is_tapemark:
        label_id = blocks[index].label_id
        if label_id and label_id.startswith("VOL"):
            volume_labels.append(parse_label(blocks[index]))
            index += 1
            continue
        break

    datasets: list[DatasetEntry] = []
    dataset_no = 1
    while index < len(blocks):
        if blocks[index].is_tapemark:
            index += 1
            continue

        header_labels: list[TapeLabel] = []
        while index < len(blocks) and not blocks[index].is_tapemark and blocks[index].label_id in {"HDR1", "HDR2", "EOV1", "EOV2"}:
            header_labels.append(parse_label(blocks[index]))
            index += 1

        if index >= len(blocks) or not blocks[index].is_tapemark:
            raise TapeToolError(f"dataset {dataset_no}: expected tapemark before data")
        index += 1

        data_blocks: list[AwsBlock] = []
        while index < len(blocks) and not blocks[index].is_tapemark:
            data_blocks.append(blocks[index])
            index += 1

        trailer_labels: list[TapeLabel] = []
        if index < len(blocks) and blocks[index].is_tapemark:
            index += 1
            while index < len(blocks) and not blocks[index].is_tapemark and blocks[index].label_id in {"EOF1", "EOF2", "EOV1", "EOV2"}:
                trailer_labels.append(parse_label(blocks[index]))
                index += 1
            if index < len(blocks) and blocks[index].is_tapemark:
                index += 1

        hdr1 = next((label for label in header_labels if label.kind == "HDR1"), None)
        hdr2 = next((label for label in header_labels if label.kind == "HDR2"), None)
        record_format = str(hdr2.fields.get("recfm", "U")) if hdr2 else "U"
        block_size = hdr2.fields.get("block_size") if hdr2 else None
        lrecl = hdr2.fields.get("lrecl") if hdr2 else None
        dsid = str(hdr1.fields["dsid"]).strip() if hdr1 and hdr1.fields.get("dsid") else None
        file_sequence = hdr1.fields.get("file_sequence") if hdr1 else None
        block_count = hdr1.fields.get("block_count") if hdr1 else None
        if not isinstance(block_size, int):
            block_size = None
        if not isinstance(lrecl, int):
            lrecl = None
        if not isinstance(file_sequence, int):
            file_sequence = None
        if not isinstance(block_count, int):
            block_count = None

        dataset = DatasetEntry(
            number=dataset_no,
            synthetic_name=f"DS{dataset_no:03d}",
            header_labels=header_labels,
            trailer_labels=trailer_labels,
            data_blocks=data_blocks,
            record_format=record_format,
            block_size=block_size,
            lrecl=lrecl,
            dsid=dsid,
            file_sequence=file_sequence,
            block_count=block_count,
        )
        dataset.records = logical_records_for_dataset(dataset)
        detect_partitioned_unload(dataset)
        datasets.append(dataset)
        dataset_no += 1

    return TapeImage(path=path, size=size, blocks=blocks, volume_labels=volume_labels, datasets=datasets)


def logical_records_for_dataset(dataset: DatasetEntry) -> list[LogicalRecord]:
    records: list[LogicalRecord] = []
    recno = 1
    recfm = dataset.record_format.upper()
    if recfm.startswith("V"):
        for block in dataset.data_blocks:
            if len(block.data) < 8:
                raise TapeToolError(f"dataset {dataset.number}: short VB block at AWS block {block.index}")
            block_len = bdw_length(block.data[:4])
            if block_len != len(block.data):
                raise TapeToolError(
                    f"dataset {dataset.number}: BDW length mismatch in AWS block {block.index}"
                )
            offset = 4
            while offset < len(block.data):
                if offset + 4 > len(block.data):
                    raise TapeToolError(f"dataset {dataset.number}: truncated RDW in block {block.index}")
                record_len = rdw_length(block.data[offset:offset + 4])
                if record_len < 4 or offset + record_len > len(block.data):
                    raise TapeToolError(
                        f"dataset {dataset.number}: invalid RDW length {record_len} in block {block.index}"
                    )
                raw = block.data[offset + 4:offset + record_len]
                records.append(LogicalRecord(index=recno, raw=raw, block_index=block.index))
                recno += 1
                offset += record_len
    elif recfm.startswith("F") and dataset.lrecl:
        for block in dataset.data_blocks:
            if len(block.data) % dataset.lrecl != 0:
                raise TapeToolError(
                    f"dataset {dataset.number}: block {block.index} length {len(block.data)} is not a multiple of LRECL {dataset.lrecl}"
                )
            for offset in range(0, len(block.data), dataset.lrecl):
                raw = block.data[offset:offset + dataset.lrecl]
                records.append(LogicalRecord(index=recno, raw=raw, block_index=block.index))
                recno += 1
    else:
        for block in dataset.data_blocks:
            records.append(LogicalRecord(index=recno, raw=block.data, block_index=block.index))
            recno += 1
    return records


def detect_partitioned_unload(dataset: DatasetEntry) -> None:
    if len(dataset.records) < 4:
        return
    control = dataset.records[2].raw
    if "FORMAT" not in ebcdic_to_text(control):
        return

    members: list[MemberEntry] = []
    for record in dataset.records[3:]:
        if len(record.raw) < 12:
            return
        payload = unload_member_payload(record)
        key = unload_member_key(record)
        ascii_text = ebcdic_to_text(payload[:80])
        match = MEMBER_NAME_RE.match(ascii_text)
        name = match.group(1) if match else f"MEM{len(members) + 1:03d}"
        if members and members[-1].key == key:
            members[-1].records.append(record)
            continue
        members.append(MemberEntry(number=len(members) + 1, name=name, key=key, records=[record]))

    if members:
        dataset.members = members
        dataset.organization = "PO"
        dataset.dataset_format = "iebcopy-unload"


def unload_member_key(record: LogicalRecord) -> int:
    return int.from_bytes(record.raw[8:10], "big")


def unload_member_payload(record: LogicalRecord) -> bytes:
    if len(record.raw) < 12:
        raise TapeToolError(f"record {record.index}: short unloaded-member header")
    payload_length = int.from_bytes(record.raw[10:12], "big")
    payload_start = 12
    payload_end = payload_start + payload_length
    if payload_end > len(record.raw):
        raise TapeToolError(
            f"record {record.index}: unloaded-member payload overruns logical record"
        )
    return record.raw[payload_start:payload_end]


def format_dataset_line(dataset: DatasetEntry) -> str:
    pieces = [
        f"{dataset.number:3d}",
        dataset.synthetic_name,
        f"format={dataset.summary_format()}",
    ]
    if dataset.dsid:
        pieces.append(f"label={dataset.dsid}")
    if dataset.block_size:
        pieces.append(f"blksize={dataset.block_size}")
    if dataset.lrecl:
        pieces.append(f"lrecl={dataset.lrecl}")
    if dataset.is_partitioned:
        pieces.append(f"members={len(dataset.members)}")
    pieces.append(f"records={len(dataset.records)}")
    return "  ".join(pieces)


def chunk_80(data: bytes) -> list[bytes]:
    if not data:
        return []
    if len(data) % 80 == 0:
        return [data[i:i + 80] for i in range(0, len(data), 80)]
    return [data]


def render_records_ascii(records: Iterable[bytes]) -> bytes:
    lines = [ebcdic_to_text(record).rstrip() for record in records]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def render_dataset_bytes(dataset: DatasetEntry, ascii_mode: bool) -> bytes:
    if dataset.dataset_format == "iebcopy-unload" and ascii_mode:
        rendered = []
        for record in dataset.records:
            rendered.append(ebcdic_to_text(record.raw).rstrip())
        return ("\n".join(rendered) + ("\n" if rendered else "")).encode("utf-8")

    if ascii_mode:
        return render_records_ascii(record.raw for record in dataset.records)
    return b"".join(record.raw for record in dataset.records)


def render_member_bytes(member: MemberEntry, ascii_mode: bool) -> bytes:
    data = member.payload_bytes
    chunks = chunk_80(data)
    if ascii_mode:
        return render_records_ascii(chunks)
    return b"".join(chunks)


def get_dataset(tape: TapeImage, number: int) -> DatasetEntry:
    if number < 1 or number > len(tape.datasets):
        raise TapeToolError(f"dataset {number} not found")
    return tape.datasets[number - 1]


def get_member(dataset: DatasetEntry, number: int) -> MemberEntry:
    if not dataset.is_partitioned:
        raise TapeToolError(f"{dataset.synthetic_name} is not partitioned")
    if number < 1 or number > len(dataset.members):
        raise TapeToolError(f"member {number} not found in dataset {dataset.number}")
    return dataset.members[number - 1]


def print_general_info(tape: TapeImage) -> None:
    print(f"image: {tape.path}")
    print(f"size: {tape.size} bytes")
    print(f"aws blocks: {len(tape.blocks)}")
    print(f"tapemarks: {tape.tapemark_count}")
    if tape.volume_name:
        print(f"volume: {tape.volume_name}")
    print(f"datasets: {len(tape.datasets)}")
    for dataset in tape.datasets:
        print(f"  {format_dataset_line(dataset)}")


def print_volume(tape: TapeImage) -> None:
    volume = tape.volume_name
    if not volume:
        raise TapeToolError("no VOL1 label found")
    print(volume)


def print_dataset_list(tape: TapeImage) -> None:
    if not tape.datasets:
        print("no datasets found")
        return
    print("No   Dataset  Details")
    for dataset in tape.datasets:
        print(format_dataset_line(dataset))


def print_member_list(dataset: DatasetEntry) -> None:
    if not dataset.is_partitioned:
        print(f"{dataset.synthetic_name} is not partitioned")
        return
    print(f"Dataset {dataset.number}: {dataset.display_name}")
    print("No   Member     Lines  Bytes")
    for member in dataset.members:
        lines = member.line_count if member.line_count else "-"
        print(f"{member.number:3d}  {member.name:<8}  {lines:>5}  {member.data_bytes:>5}")


def print_labels(tape: TapeImage) -> None:
    payload = {
        "volume": [label.text.rstrip() for label in tape.volume_labels],
        "datasets": [
            {
                "dataset": dataset.synthetic_name,
                "header": [label.text.rstrip() for label in dataset.header_labels],
                "trailer": [label.text.rstrip() for label in dataset.trailer_labels],
            }
            for dataset in tape.datasets
        ],
    }
    print(json.dumps(payload, indent=2))


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and extract datasets from AWS tape images")
    parser.add_argument("image", nargs="?", default="tape.aws", help="AWS tape image path (default: tape.aws)")
    parser.add_argument("-d", action="store_true", help="print general information about the tape")
    parser.add_argument("-v", action="store_true", help="print the tape volume name")
    parser.add_argument("-l", action="store_true", help="list datasets on the tape")
    parser.add_argument("-m", metavar="N", type=int, help="list directory of dataset N if it is partitioned")
    parser.add_argument(
        "-e",
        nargs="+",
        metavar="ARG",
        help="extract dataset N, or member X from dataset N",
    )
    parser.add_argument("-a", action="store_true", help="convert extracted output to ASCII / UTF-8 text")
    parser.add_argument("--labels", action="store_true", help="dump raw standard labels as JSON")
    parser.add_argument("--members", action="store_true", help="include member details in -d output when available")
    args = parser.parse_args(argv)

    if args.e and len(args.e) not in {2, 3}:
        parser.error("-e requires OUTFILE DATASET or OUTFILE DATASET MEMBER")

    actions = [args.d, args.v, args.l, args.m is not None, args.e is not None, args.labels]
    if sum(bool(action) for action in actions) == 0:
        parser.error("select at least one action: -d, -v, -l, -m, -e or --labels")
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    image_path = Path(args.image)
    if not image_path.exists():
        raise TapeToolError(f"image not found: {image_path}")

    tape = parse_standard_labeled_tape(image_path)

    if args.d:
        print_general_info(tape)
        if args.members:
            for dataset in tape.datasets:
                if dataset.is_partitioned:
                    print()
                    print_member_list(dataset)

    if args.v:
        if args.d:
            print()
        print_volume(tape)

    if args.l:
        if args.d or args.v:
            print()
        print_dataset_list(tape)

    if args.m is not None:
        if args.d or args.v or args.l:
            print()
        dataset = get_dataset(tape, args.m)
        print_member_list(dataset)

    if args.labels:
        if args.d or args.v or args.l or args.m is not None:
            print()
        print_labels(tape)

    if args.e:
        outfile = Path(args.e[0])
        dataset_no = int(args.e[1])
        dataset = get_dataset(tape, dataset_no)
        if len(args.e) == 2:
            payload = render_dataset_bytes(dataset, args.a)
        else:
            member_no = int(args.e[2])
            member = get_member(dataset, member_no)
            payload = render_member_bytes(member, args.a)
        outfile.write_bytes(payload)
        if args.d or args.v or args.l or args.m is not None or args.labels:
            print()
        print(f"wrote {len(payload)} bytes to {outfile}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except TapeToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
