import { describe, expect, it, vi } from "vitest";
import { interactiveRowProps } from "./rowInteraction.js";

describe("interactiveRowProps", () => {
  it("exposes button semantics and is focusable", () => {
    const props = interactiveRowProps(() => {}, "Open thing 1");
    expect(props.role).toBe("button");
    expect(props.tabIndex).toBe(0);
    expect(props["aria-label"]).toBe("Open thing 1");
  });

  it("activates on click", () => {
    const onActivate = vi.fn();
    interactiveRowProps(onActivate).onClick();
    expect(onActivate).toHaveBeenCalledTimes(1);
  });

  it("activates on Enter and Space, and prevents Space scrolling", () => {
    const onActivate = vi.fn();
    const { onKeyDown } = interactiveRowProps(onActivate);
    const preventDefault = vi.fn();

    onKeyDown({ key: "Enter", preventDefault });
    onKeyDown({ key: " ", preventDefault });

    expect(onActivate).toHaveBeenCalledTimes(2);
    expect(preventDefault).toHaveBeenCalledTimes(2);
  });

  it("ignores other keys", () => {
    const onActivate = vi.fn();
    const { onKeyDown } = interactiveRowProps(onActivate);
    onKeyDown({ key: "Tab", preventDefault: vi.fn() });
    expect(onActivate).not.toHaveBeenCalled();
  });
});
