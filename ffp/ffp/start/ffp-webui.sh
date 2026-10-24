#!/bin/sh

# Set the executable search path to known FFP and firmware locations.
PATH=/ffp/bin:/ffp/sbin:/bin:/sbin:/usr/bin:/usr/sbin
export PATH

# Define the WebUI executable, configuration, PID file, and log file.
WEBUI_BIN=/ffp/bin/ffp-webui
WEBUI_PYTHON=/ffp/bin/python3.13-static
WEBUI_CONFIG=/ffp/etc/ffp-webui/config.json
WEBUI_PID=/ffp/var/run/ffp-webui.pid
WEBUI_LOG=/ffp/var/log/ffp-webui.log
WEBUI_ENV=/ffp/etc/ffp-webui/environment

# Load only simple KEY=VALUE records without evaluating shell code.
load_webui_environment() {
    if [ -r "$WEBUI_ENV" ]; then
        while IFS='=' read -r key value; do
            case "$key" in
                FFP_*|LANG|LC_ALL|TZ ) ;;
                * ) continue ;;
            esac
            case "$key" in
                *[!A-Za-z0-9_]* ) continue ;;
            esac
            export "$key=$value"
        done < "$WEBUI_ENV"
    fi
}

# Confirm that a PID file refers to this WebUI executable before signaling it.
webui_pid_is_ours() {
    pid="$1"
    case "$pid" in
        ''|*[!0-9]*) return 1 ;;
    esac
    [ -r "/proc/$pid/cmdline" ] || return 1
    tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -F "/ffp/bin/ffp-webui" >/dev/null 2>&1
}

# Start the server once and record its process identifier.
start_webui() {
    if [ ! -x "$WEBUI_BIN" ]; then
        echo "FFP WebUI executable is missing: $WEBUI_BIN"
        return 1
    fi
    if [ ! -x "$WEBUI_PYTHON" ]; then
        echo "FFP WebUI Python runtime is missing: $WEBUI_PYTHON"
        return 1
    fi
    if ! "$WEBUI_PYTHON" -c 'import hashlib, math, ssl; math.sqrt(2); hashlib.sha256(b"webui-runtime-check").digest()' >/dev/null 2>&1; then
        echo "FFP WebUI Python runtime failed math/hashlib/ssl import checks."
        return 1
    fi
    if [ ! -r "$WEBUI_CONFIG" ]; then
        echo "FFP WebUI configuration is missing: $WEBUI_CONFIG"
        return 1
    fi
    if [ -r "$WEBUI_PID" ]; then
        old_pid=$(cat "$WEBUI_PID" 2>/dev/null)
        if webui_pid_is_ours "$old_pid"; then
            echo "FFP WebUI is already running (PID $old_pid)."
            return 0
        fi
        rm -f "$WEBUI_PID"
    fi
    mkdir -p /ffp/var/run /ffp/var/log
    load_webui_environment
    "$WEBUI_PYTHON" "$WEBUI_BIN" --config "$WEBUI_CONFIG" >> "$WEBUI_LOG" 2>&1 &
    new_pid=$!
    echo "$new_pid" > "$WEBUI_PID"
    sleep 1
    if webui_pid_is_ours "$new_pid"; then
        echo "FFP WebUI started (PID $new_pid)."
        return 0
    fi
    rm -f "$WEBUI_PID"
    echo "FFP WebUI did not remain running; inspect $WEBUI_LOG."
    return 1
}

# Stop only the process whose command line identifies the WebUI binary.
stop_webui() {
    if [ ! -r "$WEBUI_PID" ]; then
        echo "FFP WebUI PID file was not found."
        return 0
    fi
    old_pid=$(cat "$WEBUI_PID" 2>/dev/null)
    if ! webui_pid_is_ours "$old_pid"; then
        rm -f "$WEBUI_PID"
        echo "Stale WebUI PID file removed."
        return 0
    fi
    kill "$old_pid" 2>/dev/null
    attempt=0
    while [ "$attempt" -lt 5 ] && webui_pid_is_ours "$old_pid"; do
        sleep 1
        attempt=$((attempt + 1))
    done
    if webui_pid_is_ours "$old_pid"; then
        kill -9 "$old_pid" 2>/dev/null
        sleep 1
    fi
    rm -f "$WEBUI_PID"
    echo "FFP WebUI stopped."
}

# Route the FFP service-manager argument to a fixed operation.
case "$1" in
    start)
        start_webui
        ;;
    stop|kill)
        stop_webui
        ;;
    restart)
        stop_webui
        start_webui
        ;;
    status)
        if [ -r "$WEBUI_PID" ] && webui_pid_is_ours "$(cat "$WEBUI_PID" 2>/dev/null)"; then
            echo "FFP WebUI is running (PID $(cat "$WEBUI_PID" 2>/dev/null))."
        else
            echo "FFP WebUI is not running."
            exit 1
        fi
        ;;
    *)
        echo "Usage: $0 {start|stop|kill|restart|status}"
        exit 2
        ;;
esac
