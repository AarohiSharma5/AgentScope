import { useEffect, useState } from "react";

// Returns a debounced copy of `value` that only updates after `delay` ms of
// quiet. Used for server-side search boxes so we issue one request after the
// user stops typing instead of one per keystroke.
export function useDebouncedValue(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
