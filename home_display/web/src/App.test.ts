// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DisplayAction } from "./state/protocol";
import type { DisplayView } from "./state/reducer";

type BridgeOptions = {
  reducer?: unknown;
  onView: (view: DisplayView) => void;
  onConnectionState: (state: "connecting" | "connected" | "disconnected") => void;
  onProtocolError: (message: string) => void;
  onValidSnapshot?: () => void;
  onActionError?: (message: string) => void;
};

const bridges = vi.hoisted(() => ({
  instances: [] as Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }>,
  options: [] as BridgeOptions[],
}));

const wasm = vi.hoisted(() => ({
  loadDisplayWasm: vi.fn(),
}));

const canvasHosts = vi.hoisted(() => ({
  instances: [] as Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }>,
}));

vi.mock("./state/bridge", () => ({
  DisplayBridge: class {
    start = vi.fn();
    stop = vi.fn();

    constructor(...args: unknown[]) {
      bridges.instances.push(this);
      bridges.options.push(args[0] as BridgeOptions);
    }

    dispatchAction(_action: DisplayAction): Promise<boolean> {
      return Promise.resolve(true);
    }
  },
}));

vi.mock("./state/wasm", () => wasm);

vi.mock("./state/canvas", () => ({
  CanvasDisplayHost: class {
    start = vi.fn();
    stop = vi.fn();

    constructor() {
      canvasHosts.instances.push(this);
    }
  },
}));

import App from "./App.svelte";

describe("App", () => {
  beforeEach(() => {
    wasm.loadDisplayWasm.mockReset();
    wasm.loadDisplayWasm.mockResolvedValue({});
  });

  afterEach(() => {
    bridges.instances.length = 0;
    bridges.options.length = 0;
    canvasHosts.instances.length = 0;
  });

  it("starts and stops a same-origin state channel after the WASM reducer loads", async () => {
    const { unmount } = render(App);
    await tick();
    const bridge = bridges.instances.at(-1);

    expect(bridge?.start).toHaveBeenCalledOnce();
    unmount();
    expect(bridge?.stop).toHaveBeenCalledOnce();
  });

  it("shows a browser voice control when the display advertises browser voice", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);

    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "idle",
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: { actions: [], features: ["browser_voice"] },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    expect(container.querySelector("[data-voice-button]")).toHaveTextContent("Tap to talk");
    unmount();
  });

  it("clears a protocol error when a valid snapshot arrives", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);

    options?.onConnectionState("connected");
    options?.onProtocolError("display data unavailable");
    await tick();
    expect(container.querySelector("[data-canvas-error]")).not.toBeNull();

    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "speaking",
      response_text: "fresh response",
      status_text: null,
      media: null,
      prompt: null,
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();
    expect(container.querySelector("[data-display-canvas]")).not.toBeNull();
    expect(container.querySelector("[data-canvas-error]")).toBeNull();
    unmount();
  });

  it("keeps the shared canvas visible when state is prompt", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);

    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 2,
      state: "prompt",
      response_text: "",
      status_text: null,
      media: null,
      prompt: {
        kind: "notice",
        title: "Setup Needed",
        body: "Configure home channel?",
        options: [{ id: "yes", label: "Set home" }, { id: "no", label: "Skip" }],
        action_id: "sethome",
        timeout_seconds: null,
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: true,
      can_dismiss: false,
    });
    await tick();
    expect(container.querySelector("[data-display-canvas]")).not.toBeNull();
    expect(container.querySelector(".prompt-overlay")).toBeNull();
    unmount();
  });

  it("hides a stale prompt while the bridge is disconnected", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);

    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 2,
      state: "prompt",
      response_text: "",
      status_text: null,
      media: null,
      prompt: {
        kind: "notice",
        title: "Setup Needed",
        body: "Configure home channel?",
        options: [{ id: "yes", label: "Set home" }],
        action_id: "sethome",
        timeout_seconds: null,
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: true,
      can_dismiss: false,
    });
    await tick();
    expect(container.querySelector("[data-display-canvas]")).not.toBeNull();

    options?.onConnectionState("disconnected");
    await tick();
    expect(container.querySelector("[data-display-canvas]")).not.toBeNull();
    unmount();
  });

  it("shows an actionable setup error when the WASM artifact is unavailable", async () => {
    wasm.loadDisplayWasm.mockRejectedValueOnce(
      new Error("Display WebAssembly is unavailable. Run scripts/build_display_wasm.sh"),
    );
    const { container, unmount } = render(App);
    await tick();
    await tick();

    expect(container.querySelector('[data-state="error"]')).not.toBeNull();
    expect(container).toHaveTextContent("scripts/build_display_wasm.sh");
    expect(bridges.instances).toHaveLength(0);
    unmount();
  });
});
