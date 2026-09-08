# Trading desk UI conventions

Use the existing application design system when adding or expanding a technique.
Team2Page.tsx is the reference for a compact desk: underline navigation,
one-line summaries, saved-run links and progressive detail. A technique can have
different controls and trading rules while retaining the same interaction model.

- Reuse `tips-page`, `tips-head`, `tabs`, `panel`, `panel-head`, `tbl`, `scroll-x`,
  `status-pill`, `primary-btn`, `ghost-btn` and `link-btn`. Reuse shared Spinner,
  ErrorState, EmptyState, SymIcon and the Armed hub where appropriate.
- Start with the trader's current task. Keep plans, active execution, history
  and validation separate. Put configuration in a clearly named Settings tab;
  put long explanations and source material under Method or expandable detail.
- Use the spacing, typography, radius, surface and semantic-color tokens in
  styles.css. Avoid a separate hero, button system or fixed desktop type scale
  for one technique. Keep technique CSS limited to its own composition.
- Show state with text as well as color. Missing data, failed requests and
  pending execution need distinct messages. Loading must not masquerade as an
  empty result; failed reads should offer retry when possible.
- Use real buttons for actions and links for navigation. Give tabs selected
  states and keyboard navigation. Keep focus visible and move it to opened
  detail so keyboard users can follow the same flow.
- Preserve the workspace/account boundary and the meaning of existing trading
  controls. A presentation change must not silently alter execution policy.
- Register tabs in lib/routing.ts; preserve prior URLs when reorganizing a page.
- Put phone and touch overrides only in mobile.css. Touch inputs need 16px text
  on tablets as well as phones; retain the shared minimum target sizes. Wide
  data tables belong in scroll-x containers, not an overflowing document.

For a user-visible release, follow CLAUDE.md's Versioning section, update the
curated changelog and run the version check/build. Verify representative populated,
empty and error states, light/dark themes and keyboard navigation, then run the
mobile audit for every changed tab and any affected detail view.
