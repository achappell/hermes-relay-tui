// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";

const channels = vi.hoisted(() => ({
  instances: [] as Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }>,
}));

vi.mock("./state/channel", () => ({
  StateChannel: class {
    start = vi.fn();
    stop = vi.fn();

    constructor(..._args: unknown[]) {
      channels.instances.push(this);
    }
  },
}));

import App from "./App.svelte";

describe("App", () => {
  it("starts and stops a same-origin state channel", () => {
    const { unmount } = render(App);
    const channel = channels.instances.at(-1);

    expect(channel?.start).toHaveBeenCalledOnce();
    unmount();
    expect(channel?.stop).toHaveBeenCalledOnce();
  });
});
