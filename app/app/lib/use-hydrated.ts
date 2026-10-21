import { useSyncExternalStore } from "react";

const subscribe = () => () => {};

/**
 * `false` in the server render and during hydration, `true` once React owns
 * the page. Hydration resets an uncontrolled field to its `defaultValue`, so
 * a field the tutor types into stays read-only until this is `true`.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  );
}
