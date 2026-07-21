// Whether this is a public read-only demo build. Set at build time with
// VITE_DEMO_MODE=true (pairs with the backend's DEMO_MODE, which enforces
// read-only server-side). The UI uses this to show a banner and to disable
// write actions so the demo feels intentional rather than broken.
export const IS_DEMO =
  (typeof import.meta !== "undefined" && import.meta.env?.VITE_DEMO_MODE) === "true";

// A shared, friendly message for any place a write is blocked in the demo.
export const DEMO_READONLY_MESSAGE =
  "This is a read-only demo — creating, deleting and running actions are disabled.";
