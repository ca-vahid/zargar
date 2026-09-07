# Sean ledger coverage and measurement limits

Source: [public Sean tab, gid 0](https://docs.google.com/spreadsheets/d/1yp96STZjdbA6JM06Rm-xlGiT9BzXoSO1w7ZCKnuifIs/htmlview/sheet?headers=true&gid=0),
linked by the Cartel pinned post S07. Retrieved 2026-09-07. All 1,246 rendered
rows were parsed, including the column-header row; the main trade table is A:H
and its narrative notes are J. All 111 populated main trade-note cells were read.
Side cells containing a separate small table were not treated as trade notes.
This is complete structural analysis of this retrieved tab, not verification of
the underlying trades, a complete alert archive, or analysis of Jacob's tab.

Local evidence: `.cache/options-cartel/sean-ledger.html`,
`sean-ledger-rows.json` and `ledger-audit.json` in the same directory. HTML SHA-256:
`a0f8b4650dba808f687daf7ae9a3b04dc1879ef35b6716f19b5ef735fc9d204f`.

## Findings from the retrieved snapshot

| Measure | Count |
|---|---:|
| Main-table rows with ticker-shaped symbol and positive numeric entry | 1,140 |
| Rows labeled exactly Swing | 740 |
| Rows labeled Shares | 28 |
| Rows with a numeric reported percentage | 1,127 |
| Negative reported percentages | 308 |
| Missing numeric final exit | 651 |
| Closed status, case-insensitive | 905 |
| Open status, case-insensitive | 25 |
| Blank status | 210 |

For 1,117 of the 1,127 numeric percentage rows, the displayed percentage matches
`(highest-trim field / entry - 1) * 100` within 0.02 percentage points. Of these,
811 do not also match the final-exit field. This supports the existing restriction:
the column is not a weighted realized campaign return. Quantities and partial
allocation histories are missing, and no portfolio win rate or expectancy is
computed from these counts. Missing `$ -` values were kept unknown, not set to zero.

## Data-quality and attribution boundaries

- Row 37 is a weekly heading with numeric price cells; it was excluded from the
  trade count. Ticker-shaped values in the trade-type column at rows 33/34 are
  retained as malformed labels, not silently reclassified.
- Row 432's displayed 20% differs from the approximately 18.42% calculated from
  its displayed 0.38 entry and 0.45 exit; rounding or hidden precision is possible,
  but the cause was not established.
- Date sections mix week/month headings, repeated headings and missing years.
  These do not establish exact trade-entry timestamps or contract years.
- Day trades, scalps, lottos, hedges, rolls and shares coexist with swings.
  Older notes include 1m/3m trades and other setups beyond the September method.
  They are historical evidence, not authority to add those techniques to today's
  Cartel swing policy or pool their results into its calibration.
- Negative examples include failed breakouts, weak follow-through, trading
  against the market and overnight news gaps. Row 114 even notes a stop before
  a later favorable move; that later move cannot replace the actual stopped result.

Complete weighted outcomes still require original alerts, matching contracts,
timestamped partial quantities and actual fills. The ledger supplies leads for
source-example review; it does not satisfy those missing execution inputs.
