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
  onstart: (() => void) | null = null;
  starts = 0;
  stops = 0;

  constructor(private readonly announcesStart = true) {}

  start(): void {
    this.starts += 1;
    if (this.announcesStart) this.onstart?.();
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
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserVoiceController({
      recognitionFactory: () => recognition,
      sendText,
      onState: (state) => states.push(state),
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.start()).resolves.toBe(true);
    expect(recognition.starts).toBe(1);
    expect(recognition.continuous).toBe(false);
    expect(recognition.interimResults).toBe(true);

    recognition.result({ isFinal: false, transcript: "send this" });
    expect(sendText).not.toHaveBeenCalled();
    expect(transcripts).toEqual([{ text: "send this", isFinal: false }]);

    recognition.result({ isFinal: true, transcript: "  send this  " });

    expect(sendText).toHaveBeenCalledWith("send this");
    expect(transcripts).toEqual([
      { text: "send this", isFinal: false },
      { text: "send this", isFinal: true },
    ]);
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
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserVoiceController({
      recognitionFactory: () => recognition,
      sendText: () => true,
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.start()).resolves.toBe(true);
    recognition.result({ isFinal: false, transcript: "unfinished" });
    controller.reset();

    expect(recognition.stops).toBe(1);
    expect(recognition.onresult).toBeNull();
    expect(transcripts).toEqual([
      { text: "unfinished", isFinal: false },
      { text: "", isFinal: true },
    ]);
  });

  it("clears an interim transcript when recognition reports an empty correction", async () => {
    const recognition = new FakeRecognition();
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserVoiceController({
      recognitionFactory: () => recognition,
      sendText: () => true,
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.start()).resolves.toBe(true);
    recognition.result({ isFinal: false, transcript: "draft" });
    recognition.result({ isFinal: false, transcript: "" });

    expect(transcripts.at(-1)).toEqual({ text: "", isFinal: false });
    controller.reset();
  });
});

describe("BrowserHandsFreeController", () => {
  afterEach(() => vi.useRealTimers());

  it("discards the wake phrase and keeps sending wake-free follow-ups", async () => {
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
    await Promise.resolve();
    expect(states).toContain("follow_up");
    expect(recognitions).toHaveLength(2);
    recognitions[1].result({ isFinal: true, transcript: "and tomorrow?" });
    expect(sendText).toHaveBeenCalledTimes(2);
    controller.turnFinished();
    await Promise.resolve();
    expect(states.at(-1)).toBe("follow_up");
    expect(recognitions).toHaveLength(3);
    recognitions[2].result({ isFinal: true, transcript: "what about Friday?" });
    expect(sendText).toHaveBeenCalledTimes(3);
    controller.turnFinished();
    await Promise.resolve();
    expect(states.at(-1)).toBe("follow_up");
    expect(recognitions).toHaveLength(4);
    recognitions[3].result({ isFinal: true, transcript: "STOP." });
    expect(sendText).toHaveBeenCalledTimes(3);
    expect(states.at(-1)).toBe("wake_ready");
    controller.disarm();
  });

  it("reports interim and final hands-free question text but never the wake phrase", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText: () => true,
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "hey hermes" });
    vi.advanceTimersByTime(150);

    recognitions[0].result({ isFinal: false, transcript: "what is the weather" });
    recognitions[0].result({ isFinal: true, transcript: "what is the weather?" });

    expect(transcripts).toEqual([
      { text: "what is the weather", isFinal: false },
      { text: "what is the weather?", isFinal: true },
    ]);
    controller.disarm();
  });

  it("clears an interim hands-free transcript when capture is disarmed", async () => {
    vi.useFakeTimers();
    const recognition = new FakeRecognition();
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => recognition,
      wakePhrases: ["hey hermes"],
      sendText: () => true,
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognition.result({ isFinal: true, transcript: "hey hermes" });
    vi.advanceTimersByTime(150);
    recognition.result({ isFinal: false, transcript: "unfinished" });
    controller.disarm();

    expect(transcripts.at(-1)).toEqual({ text: "", isFinal: true });
  });

  it("retries a follow-up recognizer that silently hangs after playback", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const states: string[] = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        // The first post-playback instance models Safari's silent hang: start()
        // succeeds, but no start/result/end callback ever arrives.
        const recognition = new FakeRecognition(recognitions.length !== 1);
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
      onState: (state) => states.push(state),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({
      isFinal: true,
      transcript: "hey hermes what is the weather",
    });
    controller.turnFinished();
    await Promise.resolve();

    expect(states.at(-1)).toBe("follow_up");
    expect(recognitions).toHaveLength(2);
    vi.advanceTimersByTime(1500);

    expect(recognitions.length).toBeGreaterThan(2);
    recognitions.at(-1)?.result({ isFinal: true, transcript: "and tomorrow?" });
    expect(sendText).toHaveBeenCalledTimes(2);
    expect(sendText).toHaveBeenLastCalledWith("and tomorrow?");
    controller.disarm();
  });

  it("retries when Safari reports started but never returns follow-up speech", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        // This variant has an onstart callback but no result, error, or end.
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({
      isFinal: true,
      transcript: "hey hermes what is the weather",
    });
    controller.turnFinished();
    await Promise.resolve();
    expect(recognitions).toHaveLength(2);

    vi.advanceTimersByTime(4_000);
    expect(recognitions.length).toBeGreaterThan(2);
    recognitions.at(-1)?.result({ isFinal: true, transcript: "and tomorrow?" });
    expect(sendText).toHaveBeenCalledTimes(2);
    controller.disarm();
  });

  it("primes the microphone once before starting follow-up recognition", async () => {
    const events: string[] = [];
    const recognitions: FakeRecognition[] = [];
    const prepareRecognition = vi.fn(() => {
      events.push("prime");
    });
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        events.push("recognition");
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText: () => true,
      prepareRecognition,
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({
      isFinal: true,
      transcript: "hey hermes what is the weather",
    });
    controller.turnFinished();
    await Promise.resolve();

    expect(prepareRecognition).toHaveBeenCalledOnce();
    expect(events.indexOf("prime")).toBeLessThan(events.lastIndexOf("recognition"));
    controller.disarm();
  });

  it("stops the temporary browser microphone stream used for follow-up recovery", async () => {
    const originalMediaDevices = Object.getOwnPropertyDescriptor(navigator, "mediaDevices");
    const stop = vi.fn();
    const getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop }] }));
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia },
    });
    const recognitions: FakeRecognition[] = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText: () => true,
    });

    try {
      await expect(controller.arm()).resolves.toBe(true);
      recognitions[0].result({
        isFinal: true,
        transcript: "hey hermes what is the weather",
      });
      controller.turnFinished();
      await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ audio: true }));

      expect(stop).toHaveBeenCalledOnce();
      controller.disarm();
    } finally {
      if (originalMediaDevices) {
        Object.defineProperty(navigator, "mediaDevices", originalMediaDevices);
      } else {
        Reflect.deleteProperty(navigator, "mediaDevices");
      }
    }
  });

  it("leaves hands-free instead of phantom-listening after bounded recovery fails", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const errors: string[] = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition(recognitions.length === 0);
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      followUpSeconds: 20,
      sendText: () => true,
      onError: (message) => errors.push(message),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({
      isFinal: true,
      transcript: "hey hermes what is the weather",
    });
    controller.turnFinished();
    await Promise.resolve();
    vi.advanceTimersByTime(12_000);

    expect(controller.isArmed).toBe(false);
    expect(controller.state).toBe("off");
    expect(errors).toEqual(["Speech recognition could not resume after playback"]);
  });

  it("handles wake-plus-text and exact stop locally", async () => {
    vi.useFakeTimers();
    const recognitions: FakeRecognition[] = [];
    const sendText = vi.fn(() => true);
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "hey hermes, stop." });
    expect(sendText).not.toHaveBeenCalled();
    expect(controller.state).toBe("wake_ready");
    vi.advanceTimersByTime(50);

    recognitions.at(-1)?.result({ isFinal: true, transcript: "hey hermes what time is it" });
    expect(sendText).toHaveBeenCalledWith("what time is it");
    expect(transcripts.at(-1)).toEqual({ text: "what time is it", isFinal: true });
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
    const transcripts: Array<{ text: string; isFinal: boolean }> = [];
    const controller = new BrowserHandsFreeController({
      recognitionFactory: () => {
        const recognition = new FakeRecognition();
        recognitions.push(recognition);
        return recognition;
      },
      wakePhrases: ["hey hermes"],
      sendText,
      onTranscript: (text, isFinal) => transcripts.push({ text, isFinal }),
    });

    await expect(controller.arm()).resolves.toBe(true);
    recognitions[0].result({ isFinal: true, transcript: "hey hermes" });
    recognitions[0].result({ isFinal: false, transcript: "stop" });
    recognitions[0].result({ isFinal: true, transcript: "stop!" });
    expect(sendText).not.toHaveBeenCalled();
    expect(transcripts).toEqual([
      { text: "stop", isFinal: false },
      { text: "", isFinal: true },
    ]);
    expect(controller.state).toBe("wake_ready");
    vi.advanceTimersByTime(50);

    recognitions.at(-1)?.result({ isFinal: true, transcript: "hey hermes what is the weather" });
    expect(sendText).toHaveBeenCalledTimes(1);
    controller.turnFinished();
    await Promise.resolve();
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

  it("carries an incomplete PCM frame into the next chunk", () => {
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
      state: "running" as const,
      currentTime: 0,
      destination: {},
      resume: vi.fn(async () => {}),
      createBuffer: vi.fn(() => buffer),
      createBufferSource: vi.fn(() => source),
    };
    const player = new PcmAudioPlayer({ audioContextFactory: () => context });

    player.start({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-partial-frame",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    });
    player.append(new Uint8Array([0x00]).buffer);

    expect(context.createBuffer).not.toHaveBeenCalled();

    player.append(new Uint8Array([0x80, 0xff, 0x7f]).buffer);

    expect(context.createBuffer).toHaveBeenCalledWith(1, 2, 24000);
    expect(buffer.copyToChannel).toHaveBeenCalledWith(
      new Float32Array([-1, 32767 / 32768]),
      0,
    );
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
