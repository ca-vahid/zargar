#!/usr/bin/env bash
# usage: run_arms.sh TAG START END SLIP arm1 arm2 ...
S="$(dirname "$0")"; TAG=$1; START=$2; END=$3; SLIP=$4; shift 4
PY=/c/Cursor/zargar/backend/.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(cygpath -w "$TEMP/t2prof/backend")"
declare -A ARMS=( [base]="" [H1]="stop_candles=2" [H2]="min_target_atr=1.5" [H3]="trim_cue=new_extreme" [H4]="no_trade_zone=conjunction" [H5]="target_premium=1.2" [E1]="target_collision=replan" [E2]="target_exit=false" )
mkdir -p "$S/runs"
for a in "$@"; do
  out="$S/runs/${TAG}_${a}_s${SLIP}.json"
  if [ ! -f "$out" ]; then $PY "$S/replay.py" "$S/data" "$out" "$START" "$END" --real slippage_ticks=$SLIP ${ARMS[$a]} > /dev/null 2>"$S/runs/${TAG}_${a}_s${SLIP}.err" || { echo "FAILED $a"; tail -3 "$S/runs/${TAG}_${a}_s${SLIP}.err"; continue; }; fi
  $PY "$S/book.py" "$out" "$START" "$END" 2 "${TAG}_${a}_s${SLIP}"
done
