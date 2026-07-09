// Accessibility helpers for table rows that behave like links.
//
// Clickable `<tr>` elements are invisible to keyboard and screen-reader users
// unless they expose a role, are focusable, and respond to Enter/Space. This
// helper returns those props so every list table stays keyboard-navigable with
// consistent behavior.

// Tailwind classes for a focus ring on an interactive row (pair with the row's
// existing hover styles).
export const INTERACTIVE_ROW_CLASS =
  "cursor-pointer transition-colors hover:bg-ink-600 focus:outline-none " +
  "focus-visible:bg-ink-600 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent";

export function interactiveRowProps(onActivate, ariaLabel) {
  return {
    role: "button",
    tabIndex: 0,
    "aria-label": ariaLabel,
    onClick: onActivate,
    onKeyDown: (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onActivate(event);
      }
    },
  };
}
