// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DisplaySnapshot } from "./state/protocol";

type ChannelCallbacks = {
  onSnapshot: (snapshot: DisplaySnapshot) => void;
  onConnectionState: (state: "connecting" | "connected" | "disconnected") => void;
  onProtocolError: (message: string) => void;
  onValidSnapshot?: () => void;
};

const channels = vi.hoisted(() => ({
  instances: [] as Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }>,
  callbacks: [] as ChannelCallbacks[],
}));

vi.mock("./state/channel", () => ({
  StateChannel: class {
    start = vi.fn();
    stop = vi.fn();

    constructor(...args: unknown[]) {
      channels.instances.push(this);
      channels.callbacks.push({
        onSnapshot: args[1] as ChannelCallbacks["onSnapshot"],
        onConnectionState: args[2] as ChannelCallbacks["onConnectionState"],
        onProtocolError: args[3] as ChannelCallbacks["onProtocolError"],
        onValidSnapshot: args[5] as ChannelCallbacks["onValidSnapshot"],
      });
    }
  },
}));

import App from "./App.svelte";

describe("App", () => {
  afterEach(() => {
    channels.instances.length = 0;
    channels.callbacks.length = 0;
  });

  it("starts and stops a same-origin state channel", () => {
    const { unmount } = render(App);
    const channel = channels.instances.at(-1);

    expect(channel?.start).toHaveBeenCalledOnce();
    unmount();
    expect(channel?.stop).toHaveBeenCalledOnce();
  });

  it("clears a protocol error when a valid snapshot arrives", async () => {
    const { container, unmount } = render(App);
    const callbacks = channels.callbacks.at(-1);

    callbacks?.onConnectionState("connected");
    callbacks?.onProtocolError("display data unavailable");
    await tick();
    expect(container.querySelector('[data-state="error"]')).not.toBeNull();

    callbacks?.onValidSnapshot?.();
    await tick();
    expect(container.querySelector('[data-state="idle"]')).not.toBeNull();

    callbacks?.onSnapshot({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "speaking",
      response_text: "fresh response",
      status_text: null,
      media: null,
    });
    await tick();
    expect(container.querySelector('[data-state="speaking"]')).not.toBeNull();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("fresh response");
    unmount();
  });
});
