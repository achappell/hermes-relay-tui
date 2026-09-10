// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DisplayAction, DisplayAudioEvent } from "./state/protocol";
import type { DisplayView } from "./state/reducer";

type BridgeOptions = {
  reducer?: unknown;
  onView: (view: DisplayView) => void;
  onConnectionState: (state: "connecting" | "connected" | "disconnected") => void;
  onProtocolError: (message: string) => void;
  onValidSnapshot?: () => void;
  onActionError?: (message: string) => void;
  sendVoiceTurn?: (text: string) => Promise<boolean>;
  onAudioEvent?: (event: DisplayAudioEvent) => void;
  onAudioChunk?: (chunk: ArrayBuffer) => void;
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
    sendVoiceTurn = vi.fn(async (_text: string) => true);

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

  it("gates hands-free on a connected idle display and keeps accessible state text off-canvas", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);

    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "idle",
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: {
        actions: [],
        features: ["browser_voice", "browser_hands_free"],
        wake_phrases: ["hey hermes"],
        wake_listen_seconds: 8,
        wake_followup_seconds: 8,
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    const handsFreeButton = container.querySelector<HTMLButtonElement>("[data-handsfree-button]");
    expect(handsFreeButton).toHaveTextContent("Enable hands-free");
    expect(handsFreeButton).not.toBeDisabled();
    expect(container.querySelector(".state-surface.accessible-only")).not.toBeNull();

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
        title: "Setup needed",
        body: "Configure home channel?",
        options: [{ id: "yes", label: "Set home" }],
        action_id: "sethome",
        timeout_seconds: null,
      },
      capabilities: {
        actions: [],
        features: ["browser_voice", "browser_hands_free"],
        wake_phrases: ["hey hermes"],
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();
    expect(container.querySelector<HTMLButtonElement>("[data-handsfree-button]")).toBeDisabled();
    unmount();
  });

  it("disarms hands-free when the state channel disconnects", async () => {
    class FakeRecognition {
      continuous = false;
      interimResults = false;
      lang = "";
      onresult: ((event: unknown) => void) | null = null;
      onerror: ((event: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      start = vi.fn();
      stop = vi.fn();
    }
    class FakeAudioContext {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = vi.fn(async () => {});
      createBuffer = vi.fn();
      createBufferSource = vi.fn();
    }
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: FakeRecognition,
    });
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: FakeAudioContext,
    });

    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);
    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "idle",
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: {
        actions: [],
        features: ["browser_voice", "browser_hands_free"],
        wake_phrases: ["hey hermes"],
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    await fireEvent.click(container.querySelector("[data-handsfree-button]") as HTMLElement);
    await tick();
    expect(container.querySelector("[data-handsfree-button]")).toHaveTextContent(
      "Disable hands-free",
    );

    options?.onConnectionState("disconnected");
    await tick();
    expect(container.querySelector("[data-handsfree-button]")).toHaveTextContent(
      "Enable hands-free",
    );
    expect(container.querySelector("[data-handsfree-error]")).toHaveTextContent(
      "Display disconnected",
    );
    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("waits for all streamed audio to finish before opening the one follow-up", async () => {
    const recognitions: Array<{
      onresult: ((event: unknown) => void) | null;
      start: ReturnType<typeof vi.fn>;
      stop: ReturnType<typeof vi.fn>;
    }> = [];
    const audioSources: Array<{
      onended: (() => void) | null;
      connect: ReturnType<typeof vi.fn>;
      start: ReturnType<typeof vi.fn>;
      stop: ReturnType<typeof vi.fn>;
    }> = [];

    class FakeRecognition {
      continuous = false;
      interimResults = false;
      lang = "";
      onresult: ((event: unknown) => void) | null = null;
      onerror: ((event: unknown) => void) | null = null;
      onend: (() => void) | null = null;
      start = vi.fn();
      stop = vi.fn();

      constructor() {
        recognitions.push(this);
      }
    }
    class FakeAudioContext {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = vi.fn(async () => {});
      createBuffer = vi.fn(() => ({ duration: 1, copyToChannel: vi.fn() }));
      createBufferSource = vi.fn(() => {
        const source = {
          onended: null as (() => void) | null,
          connect: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
        };
        audioSources.push(source);
        return source;
      });
    }
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: FakeRecognition,
    });
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: FakeAudioContext,
    });

    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);
    const capabilities = {
      actions: [],
      features: ["browser_voice", "browser_hands_free"],
      wake_phrases: ["hey hermes"],
      wake_listen_seconds: 8,
      wake_followup_seconds: 8,
    };
    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "idle",
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities,
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    await fireEvent.click(container.querySelector("[data-handsfree-button]") as HTMLElement);
    await tick();
    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "hey hermes what is the weather" } }],
    });
    await tick();
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 2,
      state: "thinking",
      response_text: "",
      status_text: "Thinking",
      media: null,
      prompt: null,
      capabilities,
      is_busy: true,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    options?.onAudioEvent?.({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-1",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    });
    options?.onAudioChunk?.(new Uint8Array([1, 2]).buffer);
    options?.onAudioChunk?.(new Uint8Array([3, 4]).buffer);
    options?.onAudioEvent?.({ type: "audio_end", schema: 1, turn_id: "turn-1" });
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 3,
      state: "idle",
      response_text: "Sunny.",
      status_text: null,
      media: null,
      prompt: null,
      capabilities,
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    expect(audioSources).toHaveLength(2);
    expect(container.querySelector("[data-handsfree-status]")).not.toHaveTextContent(
      "Listening for a follow-up",
    );
    audioSources[0].onended?.();
    await tick();
    expect(container.querySelector("[data-handsfree-status]")).not.toHaveTextContent(
      "Listening for a follow-up",
    );
    audioSources[1].onended?.();
    await tick();
    expect(container.querySelector("[data-handsfree-status]")).toHaveTextContent(
      "Listening for a follow-up",
    );
    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("keeps the semantic mirror synchronized with the rendered response", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);

    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "speaking",
      response_text: "The answer is ready.",
      status_text: "Speaking",
      media: null,
      prompt: null,
      is_busy: true,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    const mirror = container.querySelector(".state-surface");
    expect(mirror).toHaveAttribute("data-state", "speaking");
    expect(mirror).toHaveTextContent("The answer is ready.");
    expect(container.querySelector("[data-display-canvas]")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    unmount();
  });

  it("disables voice controls when a protocol error leaves only a stale idle view", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);
    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
      state: "idle",
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: {
        actions: [],
        features: ["browser_voice", "browser_hands_free"],
        wake_phrases: ["hey hermes"],
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();
    expect(container.querySelector("[data-handsfree-button]")).not.toBeDisabled();

    options?.onProtocolError("display data unavailable");
    await tick();
    expect(container.querySelector("[data-handsfree-button]")).toBeDisabled();
    expect(container.querySelector("[data-canvas-error]")).toHaveTextContent(
      "display data unavailable",
    );
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
