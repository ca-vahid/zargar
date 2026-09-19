#!/usr/bin/env bash
# Build every results file from the replay files. usage: assemble.sh DATA RUNDIR RESULTSDIR
DATA=$1; R=$2; OUT=$3
H="$(cd "$(dirname "$0")" && pwd)"
PY=/c/Cursor/zargar/backend/.venv/Scripts/python.exe
export PYTHONIOENCODING=utf-8
mkdir -p "$OUT"
TR="2026-05-07 2026-08-14"
# brackets on the corrected baseline entries, TRAIN only
$PY "$H/bracket.py" "$DATA" "$R/all_base_s0_proxy.json" $TR 1.5 "$R/train_X1_s0_proxy.json" 0 >  "$OUT/bracket_log.txt"
$PY "$H/bracket.py" "$DATA" "$R/all_base_s0_proxy.json" $TR 2.0 "$R/train_X2_s0_proxy.json" 0 >> "$OUT/bracket_log.txt"
$PY "$H/bracket.py" "$DATA" "$R/all_base_s0_proxy.json" $TR 1.5 "$R/train_X1_s1_proxy.json" 1 >> "$OUT/bracket_log.txt"
$PY "$H/bracket.py" "$DATA" "$R/all_base_s0_proxy.json" $TR 2.0 "$R/train_X2_s1_proxy.json" 1 >> "$OUT/bracket_log.txt"
{
  for w in "2026-05-07 2026-09-18 ALL" "2026-05-07 2026-08-14 TRAIN" "2026-08-17 2026-09-11 HOLDOUT_descriptive" "2026-09-14 2026-09-18 POST_descriptive"; do
    set -- $w; $PY "$H/analyze.py" one "$R/all_base_s0_proxy.json" $1 $2 "baseline_$3"
  done
  for f in all_base_s0_conservative all_base_s0_optimistic all_base_s0_f0_proxy all_base_s0_f0.65_proxy all_base_s1_f0_proxy all_base_s1_f0.65_proxy \
           all_base_s1_f1.04_proxy all_base_s2_f0_proxy all_base_s2_f0.65_proxy all_base_s2_f1.04_proxy all_base_s1_conservative; do
    $PY "$H/analyze.py" one "$R/$f.json" 2026-05-07 2026-09-18 "$f"
  done
} > "$OUT/baseline_stats.jsonl"
{
  for a in H1 H2 H3 H4 H5 E1 E2 X1 X2; do
    $PY "$H/analyze.py" pair "$R/all_base_s0_proxy.json" "$R/train_${a}_s0_proxy.json" $TR "${a}_slip0"
    $PY "$H/analyze.py" pair "$R/all_base_s1_f1.04_proxy.json" "$R/train_${a}_s1_proxy.json" $TR "${a}_slip1"
  done
} > "$OUT/arm_pairs.jsonl"
{
  $PY "$H/book.py" "$R/all_base_s0_proxy.json" 2026-05-07 2026-09-18 "$DATA"
  $PY "$H/book.py" "$R/all_base_s0_proxy.json" $TR "$DATA"
  $PY "$H/book.py" "$R/all_base_s1_f1.04_proxy.json" $TR "$DATA"
  for a in H1 H2 H3 H4 H5 E1 E2 X1 X2; do $PY "$H/book.py" "$R/train_${a}_s0_proxy.json" $TR "$DATA"; done
} > "$OUT/book_simplified.jsonl"
$PY "$H/manifest.py" "$DATA" "$R/all_base_s0_proxy.json" "$OUT/manifest_all_base_s0_proxy.json" > "$OUT/manifest_summary.txt"
( cd "$R" && sha256sum all_base_*.json train_*.json | sort -k2 ) > "$OUT/replay_file_identities.sha256"
echo assembled
