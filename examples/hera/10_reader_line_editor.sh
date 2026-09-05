#!/usr/bin/env bash
# Build and edit a card reader deck one TSO/ISPF-EDIT-style line command at a
# time via reader/editor, instead of replacing the whole deck with
# reader/load (see 07_reader_deck_edit.sh for that bulk approach).
set -euo pipefail
cd "$(dirname "$0")/.."
source common.sh

index=$(find_device_index RDR)
echo "Card reader is device index $index"

api_post "/devices/$index/reader/new" > /dev/null

edit() {
    api_post "/devices/$index/reader/editor" "{\"command\": \"$1\"}"
}

echo "Building a 3-line deck with INSERT (each insert lands at the pointer,
then advances past it):"
edit "INSERT '//SCRATCH JOB (ACCT),CLASS=A'" | jq -c .
edit "INSERT '//STEP1 EXEC PGM=IEFBR14'"     | jq -c .
edit "INSERT '/*'"                            | jq -c .

echo "TOP, then FIND the EXEC statement:"
edit "TOP" | jq -c .
edit "FIND 'EXEC PGM'" | jq -c .

echo "CHANGE the program name on the current line:"
edit "CHANGE 'IEFBR14' 'IEBGENER'" | jq -c .

echo "LIST the whole deck from the current pointer:"
edit "TOP" > /dev/null
edit "LIST +5" | jq .

echo "Full deck (raw, including the padded/locked sequence zone):"
api_get "/devices/$index/reader/deck" | jq .
