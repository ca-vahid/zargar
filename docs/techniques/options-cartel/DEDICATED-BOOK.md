# Dedicated Practice book integration — 0.7.7

The 2026-09-08 Practice reset assigns Cartel through
`techniques.options_cartel.default_portfolio`. Cartel previously retained a
separate preparation account selection and queried every sim portfolio directly;
the new platform setting alone was therefore insufficient for this desk.

The configured technique book is now authoritative for Practice preparation.
Legacy saved account selections are resolved to it without rewriting historical
runs, moving orders or changing risk settings. Missing/archived configured books
fail closed; there is no fallback to the old shared book or another technique.
Live preparation retains its separate explicit broker-account selection.

New arming and entry checks reject archived books and another technique's Practice
book. Runtime restoration skips archived-book arms when the platform reports the
archive flag. Preparation, manual Cartel arming and risk-account selectors filter
archived accounts and use the configured Practice book. The latest preparation
panel is scoped to the resolved account, so an old shared-book run is not labeled
as work for the newly assigned account. Old records remain readable by ID.

Archive detection accepts both the platform's Portfolio.archived field and its
portfolio-cache flag. This supports integration with the pending platform archive
change without copying it or adding a competing archive implementation. The
existing settings override resolver already recognizes the technique default key.
Claude's archive/list/position/order-reset code still needs to be deployed and
restarted separately; this change does not merge or deploy that work.

Risk is calculated from the selected Cartel book's equity, not the combined
Practice balance. This update does not change the risk percentage, premium budget,
cash check, gross-exposure limit or any live-trading permissions.
