# Shared helpers for the Hera scripting API shell examples.
# Source this file: source "$(dirname "$0")/../common.sh"
#
# Configure via environment variables:
#   HERA_API_URL   base URL of Hera's scripting API (default http://127.0.0.1:8765)
#   HERA_API_TOKEN bearer token, if one is set in Preferences > API (default: none)

: "${HERA_API_URL:=http://127.0.0.1:8765}"
: "${HERA_API_TOKEN:=}"

_auth_header=()
if [ -n "$HERA_API_TOKEN" ]; then
    _auth_header=(-H "Authorization: Bearer $HERA_API_TOKEN")
fi

api_get() {
    curl -sf "${_auth_header[@]}" "$HERA_API_URL$1"
}

api_post() {
    curl -sf "${_auth_header[@]}" -H "Content-Type: application/json" -X POST -d "${2:-{\}}" "$HERA_API_URL$1"
}

# find_device_index DEVCLASS [OCCURRENCE=0]
# Prints the index of the Nth device of the given devclass (CPU, CONSOLE,
# DSP, PRT, RDR, PCH, TAPE), or nothing if none is found.
find_device_index() {
    local devclass="$1" occurrence="${2:-0}"
    api_get /devices | jq -r --arg c "$devclass" --argjson n "$occurrence" \
        '[.[] | select(.devclass==$c)] | .[$n].index'
}
