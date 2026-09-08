import { describe, expect, it, vi } from "vitest";

import {
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
});

describe("PcmAudioPlayer", () => {
  it("converts signed 16-bit little-endian chunks into scheduled browser audio", async () => {
    const source = {
      buffer: null as AudioBufferLike | null,
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
});
