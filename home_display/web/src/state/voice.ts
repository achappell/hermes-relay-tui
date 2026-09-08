import type { DisplayAudioStart } from "./protocol";

export type VoiceState = "idle" | "listening" | "submitting" | "error";

export interface SpeechRecognitionResultLike {
  isFinal: boolean;
  0?: { transcript?: string };
}

export interface SpeechRecognitionResultEventLike {
  resultIndex: number;
  results: ArrayLike<SpeechRecognitionResultLike>;
}

export interface SpeechRecognitionErrorEventLike {
  error?: string;
}

export interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

export type SpeechRecognitionFactory = () => SpeechRecognitionLike;
export type VoiceTextSender = (text: string) => Promise<boolean> | boolean;

export interface BrowserVoiceControllerOptions {
  sendText: VoiceTextSender;
  onState?: (state: VoiceState) => void;
  onError?: (message: string) => void;
  recognitionFactory?: SpeechRecognitionFactory;
  language?: string;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

function defaultRecognitionFactory(): SpeechRecognitionLike {
  const windowWithSpeech = window as Window & {
    SpeechRecognition?: SpeechRecognitionConstructor;
    webkitSpeechRecognition?: SpeechRecognitionConstructor;
  };
  const Constructor =
    windowWithSpeech.SpeechRecognition ?? windowWithSpeech.webkitSpeechRecognition;
  if (!Constructor) {
    throw new Error("Speech recognition is unavailable in this browser");
  }
  return new Constructor();
}

export class BrowserVoiceController {
  private readonly sendText: VoiceTextSender;
  private readonly onState: (state: VoiceState) => void;
  private readonly onError: (message: string) => void;
  private readonly recognitionFactory: SpeechRecognitionFactory;
  private readonly language: string;
  private recognition: SpeechRecognitionLike | null = null;
  private listening = false;
  private submitting = false;

  constructor(options: BrowserVoiceControllerOptions) {
    this.sendText = options.sendText;
    this.onState = options.onState ?? (() => {});
    this.onError = options.onError ?? (() => {});
    this.recognitionFactory = options.recognitionFactory ?? defaultRecognitionFactory;
    this.language = options.language ?? "en-US";
  }

  async start(): Promise<boolean> {
    if (this.listening || this.submitting) return false;

    try {
      const recognition = this.recognitionFactory();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = this.language;
      recognition.onresult = (event) => this.handleResult(event);
      recognition.onerror = () => this.fail();
      recognition.onend = () => {
        if (!this.submitting) {
          this.listening = false;
          this.emit("idle");
        }
      };
      this.recognition = recognition;
      this.listening = true;
      this.emit("listening");
      recognition.start();
      return true;
    } catch {
      this.fail();
      return false;
    }
  }

  stop(): void {
    if (!this.listening || this.recognition === null) return;
    this.listening = false;
    try {
      this.recognition.stop();
    } catch {
      // A browser can report a late stop after it has already ended capture.
    }
    if (!this.submitting) this.emit("idle");
  }

  reset(): void {
    this.listening = false;
    this.submitting = false;
    this.emit("idle");
  }

  private handleResult(event: SpeechRecognitionResultEventLike): void {
    if (!this.listening) return;

    const finalText: string[] = [];
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result?.isFinal) {
        const transcript = result[0]?.transcript?.trim();
        if (transcript) finalText.push(transcript);
      }
    }
    const text = finalText.join(" ").trim();
    if (!text) return;

    this.listening = false;
    this.submitting = true;
    this.emit("submitting");
    try {
      this.recognition?.stop();
    } catch {
      // The final result may arrive after the browser has already stopped.
    }

    Promise.resolve(this.sendText(text)).then((sent) => {
      if (!sent) this.fail("Turn could not be sent");
    }).catch(() => this.fail("Turn could not be sent"));
  }

  private fail(message = "Microphone or speech recognition is unavailable"): void {
    this.listening = false;
    this.submitting = false;
    this.emit("error");
    this.onError(message);
  }

  private emit(state: VoiceState): void {
    this.onState(state);
  }
}

export interface AudioBufferLike {
  duration: number;
  copyToChannel(data: Float32Array, channelNumber: number): void;
}

export interface AudioBufferSourceLike {
  buffer: AudioBufferLike | null;
  onended?: (() => void) | null;
  connect(destination: unknown): void;
  start(when?: number): void;
  stop(): void;
}

export interface AudioContextLike {
  state: "suspended" | "running" | "closed" | string;
  currentTime: number;
  destination: unknown;
  resume(): Promise<void>;
  createBuffer(
    numberOfChannels: number,
    length: number,
    sampleRate: number,
  ): AudioBufferLike;
  createBufferSource(): AudioBufferSourceLike;
}

export type AudioContextFactory = () => AudioContextLike;

export interface PcmAudioPlayerOptions {
  audioContextFactory?: AudioContextFactory;
  onError?: (message: string) => void;
}

type AudioContextConstructor = new () => AudioContextLike;

function defaultAudioContextFactory(): AudioContextLike {
  const windowWithAudio = window as Window & {
    AudioContext?: AudioContextConstructor;
    webkitAudioContext?: AudioContextConstructor;
  };
  const Constructor = windowWithAudio.AudioContext ?? windowWithAudio.webkitAudioContext;
  if (!Constructor) {
    throw new Error("Web Audio is unavailable in this browser");
  }
  return new Constructor();
}

export class PcmAudioPlayer {
  private readonly audioContextFactory: AudioContextFactory;
  private readonly onError: (message: string) => void;
  private context: AudioContextLike | null = null;
  private activeTurnId: string | null = null;
  private sampleRate = 0;
  private channels = 0;
  private nextStartAt = 0;
  private readonly sources = new Set<AudioBufferSourceLike>();

  constructor(options: PcmAudioPlayerOptions = {}) {
    this.audioContextFactory = options.audioContextFactory ?? defaultAudioContextFactory;
    this.onError = options.onError ?? (() => {});
  }

  async resume(): Promise<boolean> {
    try {
      const context = this.ensureContext();
      if (context.state === "suspended") {
        await context.resume();
      }
      return true;
    } catch {
      this.onError("Audio playback is unavailable in this browser");
      return false;
    }
  }

  start(event: DisplayAudioStart): void {
    this.stop();
    try {
      const context = this.ensureContext();
      this.activeTurnId = event.turn_id;
      this.sampleRate = event.sample_rate;
      this.channels = event.channels;
      this.nextStartAt = context.currentTime;
    } catch {
      this.onError("Audio playback is unavailable in this browser");
    }
  }

  append(chunk: ArrayBuffer): void {
    if (this.activeTurnId === null || this.context === null || this.channels <= 0) return;

    const bytes = new Uint8Array(chunk);
    const bytesPerFrame = this.channels * 2;
    const frameCount = Math.floor(bytes.byteLength / bytesPerFrame);
    if (frameCount === 0) return;

    try {
      const buffer = this.context.createBuffer(this.channels, frameCount, this.sampleRate);
      for (let channel = 0; channel < this.channels; channel += 1) {
        const samples = new Float32Array(frameCount);
        for (let frame = 0; frame < frameCount; frame += 1) {
          const offset = (frame * this.channels + channel) * 2;
          const sample = bytes[offset] | (bytes[offset + 1] << 8);
          const signed = sample & 0x8000 ? sample - 0x10000 : sample;
          samples[frame] = signed / 32768;
        }
        buffer.copyToChannel(samples, channel);
      }

      const source = this.context.createBufferSource();
      source.buffer = buffer;
      source.connect(this.context.destination);
      const startAt = Math.max(this.nextStartAt, this.context.currentTime);
      source.start(startAt);
      this.nextStartAt = startAt + buffer.duration;
      this.sources.add(source);
      source.onended = () => this.sources.delete(source);
    } catch {
      this.onError("Audio playback could not start");
      this.stop();
    }
  }

  end(turnId: string): void {
    if (this.activeTurnId === turnId) {
      this.activeTurnId = null;
    }
  }

  abort(turnId: string): void {
    if (this.activeTurnId !== turnId) return;
    this.stop();
  }

  stop(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // A source that has already ended cannot be stopped again.
      }
    }
    this.sources.clear();
    this.activeTurnId = null;
    this.nextStartAt = 0;
  }

  private ensureContext(): AudioContextLike {
    if (this.context === null) {
      this.context = this.audioContextFactory();
    }
    return this.context;
  }
}
