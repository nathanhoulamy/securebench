#!/bin/sh
# Public assertion-free compile-and-run adapter for one bounded GPT-2 prompt.

set -eu

IFS= read -r request
prompt_base64=$(
    printf '%s\n' "$request" |
        sed -n 's@^{"challenge":{"prompt_base64":"\([A-Za-z0-9+/=]*\)"},"challenge_id":"[^"]*","evaluation_id":"[^"]*","format":"securebench.adapter-request/v2","trusted_helpers":{}}$@\1@p'
)
if [ -z "$prompt_base64" ]; then
    exit 2
fi
prompt=$(printf '%s' "$prompt_base64" | base64 -d)

compile_stdout=/tmp/securebench-gpt2-compile.stdout
compile_stderr=/tmp/securebench-gpt2-compile.stderr
run_stdout=/tmp/securebench-gpt2-run.stdout
run_stderr=/tmp/securebench-gpt2-run.stderr
binary=/app/a.out

run_bounded() {
    output_prefix=$1
    shift
    stdout_pipe="$output_prefix.stdout.pipe"
    stderr_pipe="$output_prefix.stderr.pipe"
    rm -f "$stdout_pipe" "$stderr_pipe"
    mkfifo "$stdout_pipe" "$stderr_pipe"
    head -c 65536 <"$stdout_pipe" >"$output_prefix.stdout" &
    stdout_reader=$!
    head -c 65536 <"$stderr_pipe" >"$output_prefix.stderr" &
    stderr_reader=$!
    "$@" >"$stdout_pipe" 2>"$stderr_pipe"
    command_exit=$?
    # A hostile program may fork and leave a descendant holding a pipe open
    # after the monitored process exits. Give normal readers time to observe
    # EOF, then stop them so Adapter completion stays bounded.
    reader_waits=0
    while { kill -0 "$stdout_reader" 2>/dev/null || kill -0 "$stderr_reader" 2>/dev/null; } &&
        [ "$reader_waits" -lt 20 ]; do
        sleep 0.01
        reader_waits=$((reader_waits + 1))
    done
    kill "$stdout_reader" "$stderr_reader" 2>/dev/null || true
    wait "$stdout_reader" || true
    wait "$stderr_reader" || true
    rm -f "$stdout_pipe" "$stderr_pipe"
    return "$command_exit"
}

set +e
run_bounded /tmp/securebench-gpt2-compile \
    timeout --kill-after=2s 15s gcc -O3 /app/gpt2.c -lm -o "$binary"
compile_exit=$?
set -e

run_exit=-1
: >"$run_stdout"
: >"$run_stderr"
if [ "$compile_exit" -eq 0 ]; then
    set +e
    (
        cd /app
        run_bounded /tmp/securebench-gpt2-run \
            timeout --kill-after=2s 90s "$binary" \
                gpt2-124M.ckpt vocab.bpe "$prompt"
    )
    run_exit=$?
    set -e
fi

printf '{"format":"securebench.adapter-response/v2","status":"observed","observation":{'
printf '"compile_exit":%s,' "$compile_exit"
printf '"compile_stdout_base64":"'
base64 -w0 "$compile_stdout"
printf '","compile_stderr_base64":"'
base64 -w0 "$compile_stderr"
printf '","run_exit":%s,' "$run_exit"
printf '"stdout_base64":"'
base64 -w0 "$run_stdout"
printf '","stderr_base64":"'
base64 -w0 "$run_stderr"
printf '"}}\n'
