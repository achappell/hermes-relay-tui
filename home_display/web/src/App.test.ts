// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  instances: [] as Array<{
    start: ReturnType<typeof vi.fn>;
    stop: ReturnType<typeof vi.fn>;
    dispatchAction: ReturnType<typeof vi.fn>;
    sendVoiceTurn: ReturnType<typeof vi.fn>;
  }>,
  options: [] as BridgeOptions[],
}));

vi.mock("./state/bridge", () => ({
  DisplayBridge: class {
    start = vi.fn();
    stop = vi.fn();
    dispatchAction = vi.fn(async (_action: DisplayAction) => true);
    sendVoiceTurn = vi.fn(async (_text: string) => true);

    constructor(...args: unknown[]) {
      bridges.instances.push(this);
      bridges.options.push(args[0] as BridgeOptions);
    }

  },
}));

import App from "./App.svelte";

describe("App", () => {
  afterEach(() => {
    vi.useRealTimers();
    bridges.instances.length = 0;
    bridges.options.length = 0;
  });

  it("starts and stops the same-origin state channel with the DOM reducer", async () => {
    const { container, unmount } = render(App);
    await tick();
    const bridge = bridges.instances.at(-1);

    expect(bridges.options.at(-1)?.reducer).toBeUndefined();
    expect(bridges.options.at(-1)?.onValidSnapshot).toBeUndefined();
    expect(bridge?.start).toHaveBeenCalledOnce();
    expect(container.querySelector(".state-surface")).not.toBeNull();
    expect(container.querySelector(".wasm-bootstrap-shell")).toBeNull();
    unmount();
    expect(bridge?.stop).toHaveBeenCalledOnce();
  });

  it("gates browser voice until a connected, hydrated idle snapshot is ready", async () => {
    const recognitions: FakeRecognition[] = [];
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
    const voiceSnapshot = {
      type: "snapshot" as const,
      schema: 1 as const,
      sequence: 1,
      state: "idle" as const,
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: { actions: [], features: ["browser_voice"] },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    };
    options?.onView(voiceSnapshot);
    await tick();

    const voiceButton = container.querySelector<HTMLButtonElement>("[data-voice-button]");
    expect(voiceButton).not.toBeNull();
    expect(voiceButton).toBeDisabled();
    await fireEvent.click(voiceButton as HTMLButtonElement);
    expect(recognitions).toHaveLength(0);

    options?.onConnectionState("connected");
    await tick();
    expect(voiceButton).not.toBeDisabled();
    await fireEvent.click(voiceButton as HTMLButtonElement);
    await tick();
    expect(recognitions).toHaveLength(1);
    expect(recognitions[0].start).toHaveBeenCalledOnce();

    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "  what is the weather?  " } }],
    });
    await tick();
    expect(bridges.instances.at(-1)?.sendVoiceTurn).toHaveBeenCalledWith("what is the weather?");

    options?.onView({ ...voiceSnapshot, sequence: 2 });
    await tick();
    expect(container.querySelector("[data-voice-status]")).toBeNull();

    await fireEvent.click(voiceButton as HTMLButtonElement);
    await tick();
    expect(recognitions).toHaveLength(2);
    options?.onView({
      ...voiceSnapshot,
      sequence: 3,
      state: "thinking",
      status_text: "Thinking",
      is_busy: true,
    });
    await tick();
    expect(recognitions[1].stop).toHaveBeenCalledOnce();
    expect(bridges.instances.at(-1)?.sendVoiceTurn).toHaveBeenCalledOnce();

    options?.onView({ ...voiceSnapshot, sequence: 4 });
    await tick();
    await fireEvent.click(voiceButton as HTMLButtonElement);
    await tick();
    expect(recognitions).toHaveLength(3);
    options?.onView({
      ...voiceSnapshot,
      sequence: 5,
      state: "disconnected",
      status_text: "Display disconnected",
    });
    await tick();
    expect(recognitions[2].stop).toHaveBeenCalledOnce();

    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("renders browser interim/final transcription and bounds completed response retention", async () => {
    vi.useFakeTimers();
    const recognitions: Array<{
      onresult: ((event: unknown) => void) | null;
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
    const voiceSnapshot = {
      type: "snapshot" as const,
      schema: 1 as const,
      sequence: 1,
      state: "idle" as const,
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: { actions: [], features: ["browser_voice"] },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    };
    options?.onConnectionState("connected");
    options?.onView(voiceSnapshot);
    await tick();

    await fireEvent.click(container.querySelector("[data-voice-button]") as HTMLElement);
    await tick();
    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: false, 0: { transcript: "what is the weather" } }],
    });
    await tick();
    expect(container.querySelector("[data-user-transcription-text]")).toHaveTextContent(
      "what is the weather",
    );

    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "what is the weather?" } }],
    });
    await tick();
    expect(container.querySelector("[data-user-transcription-text]")).toHaveTextContent(
      "what is the weather?",
    );

    options?.onView({
      ...voiceSnapshot,
      sequence: 2,
      state: "thinking",
      status_text: "Thinking",
      is_busy: true,
    });
    await tick();
    expect(container.querySelector("[data-user-transcription-text]")).toHaveTextContent(
      "what is the weather?",
    );

    options?.onView({
      ...voiceSnapshot,
      sequence: 3,
      state: "speaking",
      response_text: "It is sunny.",
      status_text: "Speaking",
      is_busy: true,
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("It is sunny.");
    expect(container.querySelector("[data-response-phase]")).toHaveAttribute(
      "data-response-phase",
      "streaming",
    );

    options?.onView({
      ...voiceSnapshot,
      sequence: 4,
      state: "idle",
      response_text: "It is sunny.",
      is_busy: false,
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("It is sunny.");
    expect(container.querySelector("[data-response-phase]")).toHaveAttribute(
      "data-response-phase",
      "complete",
    );

    vi.advanceTimersByTime(30_000);
    await tick();
    await fireEvent.click(container.querySelector("[data-voice-button]") as HTMLElement);
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");
    expect(container.querySelector("[data-user-transcription]")).toBeNull();
    await fireEvent.click(container.querySelector("[data-voice-button]") as HTMLElement);
    await tick();

    options?.onView({
      ...voiceSnapshot,
      sequence: 5,
      state: "thinking",
      status_text: "Thinking",
      is_busy: true,
    });
    options?.onView({
      ...voiceSnapshot,
      sequence: 6,
      state: "speaking",
      response_text: "The second answer.",
      status_text: "Speaking",
      is_busy: true,
    });
    options?.onView({
      ...voiceSnapshot,
      sequence: 7,
      state: "idle",
      response_text: "The second answer.",
      is_busy: false,
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The second answer.",
    );

    vi.advanceTimersByTime(29_999);
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The second answer.",
    );

    vi.advanceTimersByTime(1);
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The second answer.",
    );

    vi.advanceTimersByTime(30_000);
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");
    expect(container.querySelector("[data-user-transcription]")).toBeNull();

    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("clears the completed response when a hands-free capture starts or fails", async () => {
    const recognitions: Array<{
      onresult: ((event: unknown) => void) | null;
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
    const capabilities = {
      actions: [],
      features: ["browser_voice", "browser_hands_free"],
      wake_phrases: ["hey hermes"],
      wake_listen_seconds: 8,
      wake_followup_seconds: 8,
    };
    const idleSnapshot = {
      type: "snapshot" as const,
      schema: 1 as const,
      sequence: 1,
      state: "idle" as const,
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities,
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    };
    options?.onConnectionState("connected");
    options?.onView(idleSnapshot);
    options?.onView({
      ...idleSnapshot,
      sequence: 2,
      state: "thinking",
      status_text: "Thinking",
      is_busy: true,
    });
    options?.onView({
      ...idleSnapshot,
      sequence: 3,
      state: "idle",
      response_text: "The previous answer.",
      is_busy: false,
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The previous answer.",
    );

    await fireEvent.click(container.querySelector("[data-handsfree-button]") as HTMLElement);
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The previous answer.",
    );
    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "hey hermes" } }],
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");

    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: false, 0: { transcript: "what should I cook" } }],
    });
    await tick();
    expect(container.querySelector("[data-user-transcription-text]")).toHaveTextContent(
      "what should I cook",
    );

    options?.onProtocolError("display data unavailable");
    await tick();
    expect(container.querySelector("[data-user-transcription]")).toBeNull();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");

    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("clears stale conversation presentation when browser audio is unavailable", async () => {
    class ThrowingAudioContext {
      constructor() {
        throw new Error("audio unavailable");
      }
    }
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: ThrowingAudioContext,
    });

    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);
    const idleSnapshot = {
      type: "snapshot" as const,
      schema: 1 as const,
      sequence: 1,
      state: "idle" as const,
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities: { actions: [], features: [] },
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    };
    options?.onConnectionState("connected");
    options?.onView(idleSnapshot);
    options?.onView({
      ...idleSnapshot,
      sequence: 2,
      state: "thinking",
      status_text: "Thinking",
      is_busy: true,
    });
    options?.onView({
      ...idleSnapshot,
      sequence: 3,
      state: "idle",
      response_text: "A stale answer.",
      is_busy: false,
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("A stale answer.");

    options?.onAudioEvent?.({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-unavailable",
      sample_rate: 24_000,
      channels: 1,
      sample_width: 2,
    });
    await tick();

    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");
    expect(container.querySelector("[data-state=idle]")).not.toHaveTextContent("A stale answer.");

    options?.onView({
      ...idleSnapshot,
      sequence: 4,
      state: "speaking",
      response_text: "The current answer.",
      status_text: "Speaking",
      is_busy: true,
    });
    await tick();
    expect(container.querySelector('[data-state="buffering"]')).not.toBeNull();
    expect(container.querySelector('[data-state="speaking"]')).toBeNull();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The current answer.",
    );
    expect(container.querySelector("[data-response-viewport]")).toHaveAttribute(
      "data-response-phase",
      "buffering",
    );

    unmount();
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("disarms hands-free and keeps text visible as buffering when playback fails", async () => {
    const recognitions: Array<{
      onresult: ((event: unknown) => void) | null;
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
    class FailingAudioContext {
      state = "running";
      currentTime = 0;
      destination = {};
      resume = vi.fn(async () => {});
      createBuffer = vi.fn(() => {
        throw new Error("audio buffer unavailable");
      });
      createBufferSource = vi.fn();
    }
    Object.defineProperty(window, "SpeechRecognition", {
      configurable: true,
      value: FakeRecognition,
    });
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: FailingAudioContext,
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
    const idleSnapshot = {
      type: "snapshot" as const,
      schema: 1 as const,
      sequence: 1,
      state: "idle" as const,
      response_text: "",
      status_text: null,
      media: null,
      prompt: null,
      capabilities,
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    };
    options?.onConnectionState("connected");
    options?.onView(idleSnapshot);
    await tick();

    await fireEvent.click(container.querySelector("[data-handsfree-button]") as HTMLElement);
    await tick();
    expect(recognitions).toHaveLength(1);
    recognitions[0].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "hey hermes what is the weather" } }],
    });
    await tick();
    expect(container.querySelector("[data-handsfree-status]")).toHaveTextContent("Sending");

    options?.onView({
      ...idleSnapshot,
      sequence: 2,
      state: "thinking",
      response_text: "The current answer.",
      status_text: "Thinking",
      is_busy: true,
    });
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The current answer.",
    );

    options?.onAudioEvent?.({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-failed",
      sample_rate: 24_000,
      channels: 1,
      sample_width: 2,
    });
    options?.onAudioChunk?.(new Uint8Array([1, 2]).buffer);
    await tick();

    expect(container.querySelector("[data-handsfree-button]")).toHaveTextContent(
      "Enable hands-free",
    );
    expect(container.querySelector("[data-handsfree-error]")).toHaveTextContent(
      "Audio playback is unavailable — hands-free is off",
    );

    options?.onView({
      ...idleSnapshot,
      sequence: 3,
      state: "speaking",
      response_text: "The current answer.",
      status_text: "Speaking",
      is_busy: true,
    });
    await tick();
    expect(container.querySelector('[data-state="buffering"]')).not.toBeNull();
    expect(container.querySelector('[data-state="speaking"]')).toBeNull();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent(
      "The current answer.",
    );

    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
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

  it("gates hands-free on a connected idle display with the visible DOM state surface", async () => {
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
    expect(container.querySelector(".state-surface.accessible-only")).toBeNull();

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
    expect(container.querySelector(".prompt-overlay")).toBeNull();
    expect(container.querySelector(".prompt-btn")).toBeNull();

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

  it("waits for all streamed audio to finish before opening the first follow-up", async () => {
    vi.useFakeTimers();
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
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("Sunny.");
    vi.advanceTimersByTime(60_000);
    await tick();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("Sunny.");
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
    expect(container.querySelector('[data-state="listening"]')).not.toBeNull();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");
    expect(container.querySelector("[data-user-transcription]")).toBeNull();

    recognitions[1].onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "and tomorrow?" } }],
    });
    await tick();
    expect(bridges.instances.at(-1)?.sendVoiceTurn).toHaveBeenCalledTimes(2);
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 4,
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
      turn_id: "turn-2",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    });
    options?.onAudioChunk?.(new Uint8Array([5, 6]).buffer);
    options?.onAudioChunk?.(new Uint8Array([7, 8]).buffer);
    options?.onAudioEvent?.({ type: "audio_end", schema: 1, turn_id: "turn-2" });
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 5,
      state: "idle",
      response_text: "Later.",
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

    expect(audioSources).toHaveLength(4);
    expect(container.querySelector("[data-handsfree-status]")).not.toHaveTextContent(
      "Listening for a follow-up",
    );
    audioSources[2].onended?.();
    await tick();
    expect(container.querySelector("[data-handsfree-status]")).not.toHaveTextContent(
      "Listening for a follow-up",
    );
    audioSources[3].onended?.();
    await tick();
    expect(container.querySelector("[data-handsfree-status]")).toHaveTextContent(
      "Listening for a follow-up",
    );
    unmount();
    delete (window as Window & { SpeechRecognition?: unknown }).SpeechRecognition;
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("stops streamed audio when a direct-use prompt arrives", async () => {
    const audioSources: Array<{
      onended: (() => void) | null;
      connect: ReturnType<typeof vi.fn>;
      start: ReturnType<typeof vi.fn>;
      stop: ReturnType<typeof vi.fn>;
    }> = [];

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
    Object.defineProperty(window, "AudioContext", {
      configurable: true,
      value: FakeAudioContext,
    });

    const { unmount } = render(App);
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
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
    await tick();

    options?.onAudioEvent?.({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-1",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    });
    options?.onAudioChunk?.(new Uint8Array([1, 2]).buffer);
    await tick();
    expect(audioSources).toHaveLength(1);

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
      capabilities: { actions: ["prompt.choose"], features: ["prompt_overlay"] },
      is_busy: false,
      connection_healthy: true,
      can_choose: true,
      can_dismiss: false,
    });
    await tick();

    expect(audioSources[0].stop).toHaveBeenCalledOnce();
    unmount();
    delete (window as Window & { AudioContext?: unknown }).AudioContext;
  });

  it("renders the semantic DOM surface with the streamed response", async () => {
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
    expect(mirror).not.toHaveClass("accessible-only");
    expect(container.querySelector("[data-display-canvas]")).toBeNull();
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
    expect(container.querySelector('[data-state="error"]')).toHaveTextContent(
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
    expect(container.querySelector('[data-state="error"]')).not.toBeNull();

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
    expect(container.querySelector('[data-state="speaking"]')).not.toBeNull();
    expect(container.querySelector("[data-canvas-error]")).toBeNull();
    unmount();
  });

  it("renders a direct-use prompt and sends one validated bridge action", async () => {
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
      capabilities: {
        actions: ["prompt.choose"],
        features: ["prompt_overlay"],
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: true,
      can_dismiss: false,
    });
    await tick();

    const bridge = bridges.instances.at(-1);
    expect(container.querySelector(".state-surface")).not.toHaveClass("accessible-only");
    expect(container.querySelector('[aria-hidden="true"] > .state-surface')).not.toBeNull();
    expect(container.querySelector(".prompt-overlay")).not.toBeNull();
    await fireEvent.click(container.querySelector(".prompt-btn") as HTMLElement);
    await tick();

    expect(bridge?.dispatchAction).toHaveBeenCalledWith({
      type: "action",
      schema: 1,
      action_id: "sethome",
      choice: "yes",
    });
    expect(bridge?.dispatchAction).toHaveBeenCalledOnce();
    expect(container.querySelector(".prompt-overlay")).toBeNull();
    unmount();
  });

  it("keeps a direct-use prompt available after a failed action", async () => {
    const { container, unmount } = render(App);
    await tick();
    const options = bridges.options.at(-1);
    const bridge = bridges.instances.at(-1);
    bridge?.dispatchAction.mockResolvedValue(false);

    options?.onConnectionState("connected");
    options?.onView({
      type: "snapshot",
      schema: 1,
      sequence: 1,
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
      capabilities: {
        actions: ["prompt.choose"],
        features: ["prompt_overlay"],
      },
      is_busy: false,
      connection_healthy: true,
      can_choose: true,
      can_dismiss: false,
    });
    await tick();

    await fireEvent.click(container.querySelector(".prompt-btn") as HTMLElement);
    await tick();

    expect(container.querySelector(".prompt-overlay")).not.toBeNull();
    expect(container.querySelector("[data-action-error]")).toHaveTextContent(
      "Display action could not be sent",
    );
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
    expect(container.querySelector(".prompt-overlay")).not.toBeNull();

    options?.onConnectionState("disconnected");
    await tick();
    expect(container.querySelector(".prompt-overlay")).toBeNull();
    expect(container.querySelector('[data-state="disconnected"]')).not.toBeNull();
    unmount();
  });

  it("does not require generated WASM artifacts to start the DOM display", async () => {
    const { container, unmount } = render(App);
    await tick();

    expect(container.querySelector(".state-surface")).not.toBeNull();
    expect(container.querySelector(".wasm-bootstrap-shell")).toBeNull();
    expect(bridges.instances).toHaveLength(1);
    unmount();
  });
});
