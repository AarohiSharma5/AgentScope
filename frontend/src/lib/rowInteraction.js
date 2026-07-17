// Accessibility helpers for list tables whose rows navigate to a detail view.
//
// A clickable `<tr role="button">` discards the row/cell semantics screen
// readers rely on (WCAG 4.1.2 Name, Role, Value) and cannot legally contain
// other interactive elements (a nested <Link> or <button>). Instead we keep the
// native <table>/<tr>/<td> semantics and put a real <Link> in the row's primary
// cell as the navigation target; the row itself only carries a hover affordance.
//
// This makes rows keyboard-navigable (Tab to the link, Enter to follow),
// supports right-click / open-in-new-tab, and lets other cells hold their own
// links/buttons without nesting interactives.

// Hover / focus-within affordance for a row whose primary cell links to a detail
// view (pair with a primary-cell <Link className={ROW_LINK_CLASS}>).
export const INTERACTIVE_ROW_CLASS =
  "transition-colors hover:bg-ink-600 focus-within:bg-ink-600";

// The primary-cell <Link>: a real, keyboard-focusable link that inherits the
// cell's text styling, gains a link-colored hover, and shows the focus ring. It
// is the row's navigation target.
export const ROW_LINK_CLASS =
  "rounded-sm outline-none hover:text-accent " +
  "focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent";
