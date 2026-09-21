#!/usr/bin/env bash
# Reproduce every v2 replay file. usage: run_all.sh DATA OUTDIR WORKTREE [base|grid|arms]
# DATA = cache folder (SPY_1m.json QQQ_1m.json IWM_1m.json vix1d.csv opt/); WORKTREE = the checkout whose backend is measured.
DATA=$1; OUT=$2; WT=$3; WHAT=${4:-all}
H="$(cd "$(dirname "$0")" && pwd)"
PY=/c/Cursor/zargar/backend/.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
export PYTHONPATH="$(cygpath -w "$WT/backend")"
mkdir -p "$OUT"
cd "$WT/backend" || exit 1
run() { # name start end args...
  local name=$1; shift
  [ -f "$OUT/$name.json" ] && { echo "have $name"; return; }
  echo -n "$name: "; $PY "$H/replay.py" "$DATA" "$OUT/$name.json" "$@" 2>"$OUT/$name.err" | tail -1
}
FULL="2026-05-07 2026-09-18"; TRAIN="2026-05-07 2026-08-14"
if [ "$WHAT" = base ] || [ "$WHAT" = all ]; then
  run all_base_s0_proxy $FULL slippage_ticks=0
  run all_base_s0_conservative $FULL slippage_ticks=0 @touch=conservative
  run all_base_s0_optimistic $FULL slippage_ticks=0 @touch=optimistic
fi
if [ "$WHAT" = grid ] || [ "$WHAT" = all ]; then
  for s in 0 1 2; do for f in 0 0.65 1.04; do
    [ "$s$f" = "01.04" ] && continue
    run all_base_s${s}_f${f}_proxy $FULL slippage_ticks=$s fee_per_contract=$f
  done; done
  run all_base_s1_conservative $FULL slippage_ticks=1 @touch=conservative
fi
if [ "$WHAT" = arms ] || [ "$WHAT" = all ]; then
  declare -A ARMS=( [H1]="stop_candles=2" [H2]="min_target_atr=1.5" [H3]="trim_cue=new_extreme" [H4]="no_trade_zone=conjunction" [H5]="target_premium=1.2" [E1]="target_collision=replan" [E2]="target_exit=false" )
  for a in H1 H2 H3 H4 H5 E1 E2; do for s in 0 1; do
    run train_${a}_s${s}_proxy $TRAIN slippage_ticks=$s ${ARMS[$a]}
  done; done
fi
