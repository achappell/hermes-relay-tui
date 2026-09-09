import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BrowserHandsFreeController,
  BrowserVoiceController,
  PcmAudioPlayer,
  type AudioBufferLike,
  type SpeechRecognitionLike,
} from "./voice";
import type { DisplayAudioStart } from "./protocol";

class FakeRecognition implements SpeechRecognitionLike {
  continuous = false;
  interimResults = false;
  lang = "";
  onresult: SpeechRecognitionLike["onresult"] = null;
  onerror: SpeechRecognitionLike["onerror"] = null;
  onend: SpeechRecognitionLike["onend"] = null;
  starts = 0;
  stops = 0;

  start(): void {
    this.starts += 1;
  }

  stop(): void {
    this.stops += 1;
  }

  result(...results: Array<{ isFinal: boolean; transcript: string }>): void {
    this.onresult?.({
      resultIndex: 0,
      results: results.map((result) => ({
        isFinal: result.isFinal,
        0: { transcript: result.transcript },
      })),
    });
  }
}

describe("BrowserVoiceController", () => {
  it("starts push-to-talk and sends only final recognized text", async () => {
    const recognition = new FakeRecognition();
    const sendText = vi.fn(() => true);
    const states: string[] = [];
    const controller = new BrowserVoiceController({
      recognitionFactory: () => recognition,
      sendText,
      onState: (state) => states.push(state),
    });

    await expect(controller.start()).resolves.toBe(true);
    expect(recognition.starts).toBe(1);
    expect(recognition.continuous).toBe(false);
    expect(recognition.interimResults).toBe(true);

    recognition.result(
      { isFinal: false, transcript: "ignore this" },
      { isFinal: true, transcript: "  send this  " },
    );

    expect(sendText).toHaveBeenCalledWith("send this");
    expect(recognition.stops).toBe(1);
    expect(states).toEqual(["listening", "submitting"]);
  });

  it("turns microphone permission failures into an actionable error", async () => {
    const states: string[] = [];
    const controller = new BrowserVoiceController({
      recognitionFactory: () => {
        throw new Error("permission denied");
      },
      sendText: () => true,
      onState: (state) => states.push(state),
      onError: (message) => states.push(message),
    });

    await expect(controller.start()).resolves.toBe(false);
    expect(states).toEqual(["error", "Microphone or speech recognition is unavailable"]);
  });

  it("stops an active recognition session when reset clears the controller", async () => {
    const recognition = new FakeRecognition();
    const controller = new BrowserVoiceController({
      recognitionFactory: () => recognition,
      sendText: () => true,
    });

    await expect(controller.start()).resolves.toBe(true);
    controller.reset();

    expect(recognition.stops).toBe(1);
    expect(recognition.onresult).toBeNull();
  });
});

describe("BrowserHandsFreeController", () => {
  afterEach(() => vi.useRealTimers());

  it("discards the wake phrase and sends one initial turn plus one follow-up", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const states: string[] = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["Hey Hermes"],
      sendText,
      onState: (state) => states.push(state),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "background words" });
    expect(sendText).not.toHaveBeenCalled();

    recognitions[0].result({ isFinal: true, transcript: "Hey Hermes" });
    expect(states).toContain("heard");
    vi.advanceTimersByTime(150);
    expect(states).toContain("listening");
    recognitions[0].result({ isFinal: true, transcript: "what is the weather?" });
    expect(sendText).toHaveBeenCalledTimes(1);
    expect(sendText).toHaveBeenCalledWith("what is the weather?");

    controller.turnFinished();
    expect(states).toContain("follow_up");
    expect(recognitions).toHaveLength(2);
    recognitions[1].result({ isFinal: true, transcript: "and tomorrow?" });
    expect(sendText).toHaveBeenCalledTimes(2);
    controller.turnFinished();
    expect(states.at(-1)).toBe("wake_ready");
    recognitions.at(-1)?.result({ isFinal: true, transcript: "another question" });
    expect(sendText).toHaveBeenCalledTimes(2);
    controller.disarm();
  });

  it("handles wake-plus-text and exact stop locally", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "hey hermes, stop." });
    expect(sendText).not.toHaveBeenCalled();
    expect(controller.state).toBe("wake_ready");
    vi.advanceTimersByTime(50);

    recognitions.at(-1)?.result({ isFinal: true, transcript: "hey hermes what time is it" });
    expect(sendText).toHaveBeenCalledWith("what time is it");
    controller.disarm();
  });

  it("uses only changed final results from a cumulative recognition event", async () => {
    const recognition = new FakeRecognition();
    const sendText = vi.fn(() => true);
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => recognition,
      wakePhrases: ["hey hermes"],
      sendText,
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognition.onresult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "hey hermes" } }],
    });
    recognition.onresult?.({
      resultIndex: 1,
      results: [
        { isFinal: true, 0: { transcript: "hey hermes" } },
        { isFinal: true, 0: { transcript: "what is the weather" } },
      ],
    });

    expect(sendText).toHaveBeenCalledWith("what is the weather");
    expect(sendText).toHaveBeenCalledTimes(1);
    controller.disarm();
  });

  it("cancels initial and follow-up capture on an exact spoken stop", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "hey hermes" });
    recognitions[0].result({ isFinal: true, transcript: "stop!" });
    expect(sendText).not.toHaveBeenCalled();
    expect(controller.state).toBe("wake_ready");
    vi.advanceTimersByTime(50);

    recognitions.at(-1)?.result({ isFinal: true, transcript: "hey hermes what is the weather" });
    expect(sendText).toHaveBeenCalledTimes(1);
    controller.turnFinished();
    recognitions.at(-1)?.result({ isFinal: true, transcript: "STOP." });
    expect(sendText).toHaveBeenCalledTimes(1);
    expect(controller.state).toBe("wake_ready");
    controller.disarm();
  });

  it("returns to wake detection after a silent bounded capture", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      wakeListenSeconds: 1,
      sendText: () => true,
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "hey hermes" });
    vi.advanceTimersByTime(1000);
    expect(controller.state).toBe("wake_ready");
    controller.disarm();
  });

  it("disarms on a recognition permission failure", async () => {
    const recognition = new FakeRecognition();
    const errors: string[] = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => recognition,
      wakePhrases: ["hey hermes"],
      sendText: () => true,
      onError: (message) => errors.push(message),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognition.onerror?.({ error: "not-allowed" });
    expect(controller.isArmed).toBe(false);
    expect(controller.state).toBe("off");
    expect(errors).toEqual(["Microphone or speech recognition is unavailable"]);
  });

  it("ignores a late result or error from a previous armed generation", async () => {
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
    });

    await expect(controller.arm()).resolves.toBe(true);
    const oldResult = recognitions[0].onresult;
    const oldError = recognitions[0].onerror;
    controller.disarm();
    await expect(controller.arm()).resolves.toBe(true);

    oldResult?.({
      resultIndex: 0,
      results: [{ isFinal: true, 0: { transcript: "hey hermes ask something" } }],
    });
    oldError?.({ error: "not-allowed" });
    expect(sendText).not.toHaveBeenCalled();
    expect(controller.isArmed).toBe(true);
    controller.disarm();
  });
});

describe("PcmAudioPlayer", () => {
  it("converts signed 16-bit little-endian chunks into scheduled browser audio", async () => {
    const source = {
      buffer: null as AudioBufferLike | null,
      onended: null as (() => void) | null,
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    };
    const buffer = {
      duration: 1,
      copyToChannel: vi.fn(),
    };
    const context = {
      state: "suspended" as const,
      currentTime: 2,
      destination: {},
      resume: vi.fn(async () => {}),
      createBuffer: vi.fn(() => buffer),
      createBufferSource: vi.fn(() => source),
    };
    const start: DisplayAudioStart = {
      type: "audio_start",
      schema: 1,
      turn_id: "turn-1",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    };
    const player = new PcmAudioPlayer({ audioContextFactory: () => context });

    await expect(player.resume()).resolves.toBe(true);
    player.start(start);
    player.append(new Uint8Array([0x00, 0x80, 0xff, 0x7f]).buffer);

    expect(context.resume).toHaveBeenCalledOnce();
    expect(context.createBuffer).toHaveBeenCalledWith(1, 2, 24000);
    expect(buffer.copyToChannel).toHaveBeenCalledWith(
      new Float32Array([-1, 32767 / 32768]),
      0,
    );
    expect(source.connect).toHaveBeenCalledWith(context.destination);
    expect(source.start).toHaveBeenCalledWith(2);

    player.abort("turn-1");
    expect(source.stop).toHaveBeenCalledOnce();
  });

  it("reports playback completion only after scheduled sources end", () => {
    const source = {
      buffer: null as AudioBufferLike | null,
      onended: null as (() => void) | null,
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    };
    const buffer = { duration: 1, copyToChannel: vi.fn() };
    const context = {
      state: "running" as const,
      currentTime: 0,
      destination: {},
      resume: vi.fn(async () => {}),
      createBuffer: vi.fn(() => buffer),
      createBufferSource: vi.fn(() => source),
    };
    const finished = vi.fn();
    const player = new PcmAudioPlayer({
      audioContextFactory: () => context,
      onPlaybackFinished: finished,
    });

    player.start({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-2",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    });
    player.append(new Uint8Array([1, 2]).buffer);
    player.end("turn-2");
    expect(finished).not.toHaveBeenCalled();
    source.onended?.();
    expect(finished).toHaveBeenCalledWith("turn-2");
  });

  it("waits for every scheduled source before reporting playback completion", () => {
    const sources = [0, 1].map(() => ({
      buffer: null as AudioBufferLike | null,
      onended: null as (() => void) | null,
      connect: vi.fn(),
      start: vi.fn(),
      stop: vi.fn(),
    }));
    const createdSources: typeof sources = [];
    const buffer = { duration: 1, copyToChannel: vi.fn() };
    const context = {
      state: "running" as const,
      currentTime: 0,
      destination: {},
      resume: vi.fn(async () => {}),
      createBuffer: vi.fn(() => buffer),
      createBufferSource: vi.fn(() => {
        const source = sources.shift() as typeof sources[number];
        createdSources.push(source);
        return source;
      }),
    };
    const finished = vi.fn();
    const player = new PcmAudioPlayer({
      audioContextFactory: () => context,
      onPlaybackFinished: finished,
    });

    player.start({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-3",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    });
    player.append(new Uint8Array([1, 2]).buffer);
    player.append(new Uint8Array([3, 4]).buffer);
    player.end("turn-3");

    expect(finished).not.toHaveBeenCalled();
    createdSources[0].onended?.();
    expect(finished).not.toHaveBeenCalled();
    createdSources[1].onended?.();
    expect(finished).toHaveBeenCalledWith("turn-3");
  });
});
