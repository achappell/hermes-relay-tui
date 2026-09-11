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
  onstart?: (() => void) | null;
  onresult: ((event: SpeechRecognitionResultEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

export type SpeechRecognitionFactory = () => SpeechRecognitionLike;
export type VoiceTextSender = (text: string) => Promise<boolean> | boolean;
export type SpeechRecognitionPreparer = () => Promise<void> | void;
export type VoiceTranscriptListener = (text: string, isFinal: boolean) => void;

export interface BrowserVoiceControllerOptions {
  sendText: VoiceTextSender;
  onState?: (state: VoiceState) => void;
  onError?: (message: string) => void;
  onTranscript?: VoiceTranscriptListener;
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

async function defaultRecognitionPreparer(): Promise<void> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
  } catch {
    // SpeechRecognition can still own the already-granted microphone.
  }
}

export class BrowserVoiceController {
  private readonly sendText: VoiceTextSender;
  private readonly onState: (state: VoiceState) => void;
  private readonly onError: (message: string) => void;
  private readonly onTranscript: VoiceTranscriptListener;
  private readonly recognitionFactory: SpeechRecognitionFactory;
  private readonly language: string;
  private recognition: SpeechRecognitionLike | null = null;
  private listening = false;
  private submitting = false;

  constructor(options: BrowserVoiceControllerOptions) {
    this.sendText = options.sendText;
    this.onState = options.onState ?? (() => {});
    this.onError = options.onError ?? (() => {});
    this.onTranscript = options.onTranscript ?? (() => {});
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
        if (this.recognition === recognition) this.recognition = null;
        if (!this.submitting) {
          this.listening = false;
          this.onTranscript("", true);
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
    this.stopRecognition();
    this.onTranscript("", true);
    if (!this.submitting) this.emit("idle");
  }

  reset(): void {
    this.stopRecognition();
    this.listening = false;
    this.submitting = false;
    this.onTranscript("", true);
    this.emit("idle");
  }

  private handleResult(event: SpeechRecognitionResultEventLike): void {
    if (!this.listening) return;

    const { liveText, finalText: text } = recognitionText(event);
    const visibleText = text || liveText;
    this.onTranscript(visibleText, text.length > 0);
    if (!text) return;

    this.listening = false;
    this.submitting = true;
    this.emit("submitting");
    this.stopRecognition();

    let sendResult: Promise<boolean> | boolean;
    try {
      sendResult = this.sendText(text);
    } catch {
      this.fail("Turn could not be sent");
      return;
    }
    Promise.resolve(sendResult).then((sent) => {
      if (!sent) this.fail("Turn could not be sent");
    }).catch(() => this.fail("Turn could not be sent"));
  }

  private fail(message = "Microphone or speech recognition is unavailable"): void {
    this.stopRecognition();
    this.listening = false;
    this.submitting = false;
    this.onTranscript("", true);
    this.emit("error");
    this.onError(message);
  }

  private stopRecognition(): void {
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition === null) return;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    try {
      recognition.stop();
    } catch {
      // A browser can report a late stop after it has already ended capture.
    }
  }

  private emit(state: VoiceState): void {
    this.onState(state);
  }
}

export type HandsFreeState =
  | "off"
  | "arming"
  | "wake_ready"
  | "heard"
  | "listening"
  | "follow_up"
  | "submitting"
  | "error";

export interface BrowserHandsFreeControllerOptions {
  sendText: VoiceTextSender;
  wakePhrases: string[];
  wakeListenSeconds?: number;
  followUpSeconds?: number;
  onState?: (state: HandsFreeState) => void;
  onError?: (message: string) => void;
  onTranscript?: VoiceTranscriptListener;
  recognitionFactory?: SpeechRecognitionFactory;
  prepareRecognition?: SpeechRecognitionPreparer;
  language?: string;
}

type HandsFreePhase =
  | "off"
  | "wake_ready"
  | "heard"
  | "initial_capture"
  | "follow_up"
  | "submitting";

const DEFAULT_HANDS_FREE_SECONDS = 8;
const MAX_HANDS_FREE_TIMER_SECONDS = 2_147_483.647;
const FOLLOW_UP_START_TIMEOUT_MS = 1_000;
const FOLLOW_UP_ACTIVITY_TIMEOUT_MS = 3_500;
const FOLLOW_UP_RETRY_DELAYS_MS = [300, 1_000, 2_000, 3_500];

function normaliseSpeech(text: string): string {
  return text.trim().replace(/\s+/g, " ");
}

export function isLocalStopCommand(text: string): boolean {
  return normaliseSpeech(text)
    .replace(/[.,!?;:…]+$/g, "")
    .trim()
    .toLocaleLowerCase() === "stop";
}

function wakeRemainder(text: string, wakePhrases: string[]): string | null {
  const source = normaliseSpeech(text);
  const lowerSource = source.toLocaleLowerCase();
  const phrases = wakePhrases
    .map(normaliseSpeech)
    .filter(Boolean)
    .sort((left, right) => right.length - left.length);

  for (const phrase of phrases) {
    const lowerPhrase = phrase.toLocaleLowerCase();
    if (lowerSource !== lowerPhrase && !lowerSource.startsWith(lowerPhrase)) continue;

    const next = lowerSource[lowerPhrase.length];
    if (next !== undefined && !/^[\s,.:;!?;…-]$/.test(next)) continue;
    return normaliseSpeech(source.slice(lowerPhrase.length).replace(/^[\s,.:;!?…-]+/, ""));
  }
  return null;
}

function recognitionText(event: SpeechRecognitionResultEventLike): {
  liveText: string;
  finalText: string;
} {
  const liveParts: string[] = [];
  const finalParts: string[] = [];
  for (let index = event.resultIndex; index < event.results.length; index += 1) {
    const result = event.results[index];
    const transcript = result[0]?.transcript;
    if (!transcript) continue;
    const normalized = normaliseSpeech(transcript);
    if (!normalized) continue;
    liveParts.push(normalized);
    if (result.isFinal) finalParts.push(normalized);
  }
  return {
    liveText: normaliseSpeech(liveParts.join(" ")),
    finalText: normaliseSpeech(finalParts.join(" ")),
  };
}

/**
 * Browser-native hands-free orchestration. Recognition is a local wake and
 * capture sensor; only the final question crosses the existing text bridge.
 */
export class BrowserHandsFreeController {
  private readonly sendText: VoiceTextSender;
  private wakePhrases: string[];
  private wakeListenSeconds: number;
  private followUpSeconds: number;
  private readonly onState: (state: HandsFreeState) => void;
  private readonly onError: (message: string) => void;
  private readonly onTranscript: VoiceTranscriptListener;
  private readonly recognitionFactory: SpeechRecognitionFactory;
  private readonly prepareRecognition: SpeechRecognitionPreparer;
  private readonly language: string;
  private phase: HandsFreePhase = "off";
  private armed = false;
  private generation = 0;
  private recognition: SpeechRecognitionLike | null = null;
  private captureTimer: ReturnType<typeof setTimeout> | null = null;
  private heardTimer: ReturnType<typeof setTimeout> | null = null;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;
  private followUpRetryTimer: ReturnType<typeof setTimeout> | null = null;
  private followUpWatchdogTimer: ReturnType<typeof setTimeout> | null = null;
  private followUpAttempt = 0;
  private turnInFlight = false;

  constructor(options: BrowserHandsFreeControllerOptions) {
    this.sendText = options.sendText;
    this.wakePhrases = options.wakePhrases.map(normaliseSpeech).filter(Boolean);
    this.wakeListenSeconds = positiveSeconds(options.wakeListenSeconds);
    this.followUpSeconds = positiveSeconds(options.followUpSeconds);
    this.onState = options.onState ?? (() => {});
    this.onError = options.onError ?? (() => {});
    this.onTranscript = options.onTranscript ?? (() => {});
    this.recognitionFactory = options.recognitionFactory ?? defaultRecognitionFactory;
    this.prepareRecognition = options.prepareRecognition ?? defaultRecognitionPreparer;
    this.language = options.language ?? "en-US";
  }

  configure(options: Pick<
    BrowserHandsFreeControllerOptions,
    "wakePhrases" | "wakeListenSeconds" | "followUpSeconds"
  >): void {
    const wakePhrases = options.wakePhrases.map(normaliseSpeech).filter(Boolean);
    const wakeListenSeconds = positiveSeconds(options.wakeListenSeconds);
    const followUpSeconds = positiveSeconds(options.followUpSeconds);
    if (this.armed) {
      const phrasesChanged = wakePhrases.length !== this.wakePhrases.length
        || wakePhrases.some((phrase, index) => phrase !== this.wakePhrases[index]);
      if (
        phrasesChanged ||
        wakeListenSeconds !== this.wakeListenSeconds ||
        followUpSeconds !== this.followUpSeconds
      ) {
        this.abort("Display configuration changed — hands-free is off");
      }
      return;
    }
    this.wakePhrases = wakePhrases;
    this.wakeListenSeconds = wakeListenSeconds;
    this.followUpSeconds = followUpSeconds;
  }

  get isArmed(): boolean {
    return this.armed;
  }

  get state(): HandsFreeState {
    return this.stateForPhase();
  }

  async arm(): Promise<boolean> {
    if (this.armed) return true;
    if (this.wakePhrases.length === 0) {
      this.fail("No wake phrase is configured for this display");
      return false;
    }

    this.generation += 1;
    const generation = this.generation;
    this.armed = true;
    this.phase = "wake_ready";
    this.turnInFlight = false;
    this.emit("arming");

    if (!this.startRecognition(generation)) {
      this.fail("Microphone or speech recognition is unavailable");
      return false;
    }
    this.emit("wake_ready");
    return true;
  }

  disarm(): void {
    this.generation += 1;
    this.armed = false;
    this.phase = "off";
    this.turnInFlight = false;
    this.clearTimers();
    this.stopRecognition();
    this.onTranscript("", true);
    this.emit("off");
  }

  abort(message = "Display disconnected — hands-free is off"): void {
    if (!this.armed && this.phase === "off") return;
    this.fail(message);
  }

  /** Called by the display after the current response has really finished. */
  turnFinished(): void {
    if (!this.armed || !this.turnInFlight || this.phase !== "submitting") return;
    const generation = this.generation;
    this.turnInFlight = false;
    this.clearCaptureTimer();
    this.beginFollowUp(generation);
  }

  private stateForPhase(): HandsFreeState {
    switch (this.phase) {
      case "wake_ready": return "wake_ready";
      case "heard": return "heard";
      case "initial_capture": return "listening";
      case "follow_up": return "follow_up";
      case "submitting": return "submitting";
      default: return "off";
    }
  }

  private startRecognition(generation: number): boolean {
    if (!this.isCurrent(generation) || this.recognition !== null) return true;

    let recognition: SpeechRecognitionLike;
    try {
      recognition = this.recognitionFactory();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = this.language;
    } catch {
      return false;
    }

    let started = false;
    recognition.onstart = () => {
      if (!this.isCurrent(generation) || this.recognition !== recognition) return;
      started = true;
      if (this.phase === "follow_up") {
        this.scheduleFollowUpWatchdog(
          generation,
          recognition,
          FOLLOW_UP_ACTIVITY_TIMEOUT_MS,
        );
      }
    };
    recognition.onresult = (event) => {
      this.clearFollowUpWatchdog();
      this.handleResult(event, generation);
    };
    recognition.onerror = (event) => {
      if (!this.isCurrent(generation) || this.recognition !== recognition) return;
      const code = event.error?.toLocaleLowerCase();
      if (code === "no-speech" || code === "aborted") {
        if (this.phase === "follow_up") {
          this.stopRecognition();
          this.scheduleFollowUpRetry(generation);
        } else {
          this.scheduleRecognitionRestart(generation);
        }
        return;
      }
      this.fail("Microphone or speech recognition is unavailable");
    };
    recognition.onend = () => {
      if (!this.isCurrent(generation) || this.recognition !== recognition) return;
      this.recognition = null;
      this.clearFollowUpWatchdog();
      if (this.phase === "submitting") return;
      if (this.phase === "follow_up") {
        this.scheduleFollowUpRetry(generation);
      } else {
        this.scheduleRecognitionRestart(generation);
      }
    };
    this.recognition = recognition;

    try {
      recognition.start();
      if (this.phase === "follow_up" && !started && this.recognition === recognition) {
        this.scheduleFollowUpWatchdog(
          generation,
          recognition,
          FOLLOW_UP_START_TIMEOUT_MS,
        );
      }
      return true;
    } catch {
      this.recognition = null;
      this.clearFollowUpWatchdog();
      return false;
    }
  }

  private scheduleRecognitionRestart(generation: number): void {
    if (
      !this.isCurrent(generation) ||
      this.recognition !== null ||
      this.restartTimer !== null ||
      this.phase === "submitting"
    ) {
      return;
    }
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.isCurrent(generation) || this.recognition !== null) return;
      if (!this.startRecognition(generation)) {
        this.fail("Microphone or speech recognition is unavailable");
      }
    }, 50);
  }

  private handleResult(event: SpeechRecognitionResultEventLike, generation: number): void {
    if (!this.isCurrent(generation) || this.phase === "submitting") return;
    const { liveText, finalText: text } = recognitionText(event);

    if (this.phase === "wake_ready") {
      if (!text) return;
      const remainder = wakeRemainder(text, this.wakePhrases);
      if (remainder === null) return;
      if (!remainder || isLocalStopCommand(remainder)) {
        if (remainder) this.finishCapture(generation);
        else this.beginInitialCapture(generation);
        return;
      }
      this.onTranscript(remainder, true);
      this.submit(remainder, generation);
      return;
    }

    if (
      this.phase !== "heard" &&
      this.phase !== "initial_capture" &&
      this.phase !== "follow_up"
    ) return;
    if (!text) {
      this.onTranscript(liveText, false);
      return;
    }
    if (isLocalStopCommand(text)) {
      this.finishCapture(generation);
      return;
    }
    this.onTranscript(text, true);
    this.submit(text, generation);
  }

  private beginInitialCapture(generation: number): void {
    if (!this.isCurrent(generation)) return;
    this.phase = "heard";
    this.emit("heard");
    this.startCaptureTimer(generation, this.wakeListenSeconds);
    this.clearHeardTimer();
    this.heardTimer = setTimeout(() => {
      this.heardTimer = null;
      if (!this.isCurrent(generation) || this.phase !== "heard") return;
      this.phase = "initial_capture";
      this.emit("listening");
    }, 150);
  }

  private beginFollowUp(generation: number): void {
    if (!this.isCurrent(generation)) return;
    this.phase = "follow_up";
    this.followUpAttempt = 0;
    this.emit("follow_up");
    this.startCaptureTimer(generation, this.followUpSeconds);
    void this.prepareAndStartFollowUp(generation);
  }

  private async prepareAndStartFollowUp(generation: number): Promise<void> {
    try {
      await this.prepareRecognition();
    } catch {
      // A priming failure must not suppress the normal SpeechRecognition path.
    }
    if (!this.isCurrent(generation) || this.phase !== "follow_up") return;
    if (!this.startRecognition(generation)) this.scheduleFollowUpRetry(generation);
  }

  private scheduleFollowUpRetry(generation: number): void {
    if (
      !this.isCurrent(generation) ||
      this.phase !== "follow_up" ||
      this.followUpRetryTimer !== null
    ) return;

    const nextAttempt = this.followUpAttempt + 1;
    const delay = FOLLOW_UP_RETRY_DELAYS_MS[nextAttempt - 1];
    if (delay === undefined) {
      this.fail("Speech recognition could not resume after playback");
      return;
    }

    this.followUpRetryTimer = setTimeout(() => {
      this.followUpRetryTimer = null;
      if (!this.isCurrent(generation) || this.phase !== "follow_up") return;
      this.followUpAttempt = nextAttempt;
      if (!this.startRecognition(generation)) {
        this.scheduleFollowUpRetry(generation);
      }
    }, delay);
  }

  private scheduleFollowUpWatchdog(
    generation: number,
    recognition: SpeechRecognitionLike,
    delay: number,
  ): void {
    this.clearFollowUpWatchdog();
    this.followUpWatchdogTimer = setTimeout(() => {
      this.followUpWatchdogTimer = null;
      if (
        !this.isCurrent(generation) ||
        this.phase !== "follow_up" ||
        this.recognition !== recognition
      ) return;
      this.stopRecognition();
      this.scheduleFollowUpRetry(generation);
    }, delay);
  }

  private enterWakeReady(generation: number, deferRecognition = false): void {
    if (!this.isCurrent(generation)) return;
    this.clearFollowUpRetryTimer();
    this.phase = "wake_ready";
    this.clearHeardTimer();
    this.emit("wake_ready");
    if (deferRecognition || !this.startRecognition(generation)) {
      this.scheduleRecognitionRestart(generation);
    }
  }

  private finishCapture(generation: number): void {
    if (!this.isCurrent(generation)) return;
    this.onTranscript("", true);
    this.clearCaptureTimer();
    this.stopRecognition();
    this.enterWakeReady(generation, true);
  }

  private startCaptureTimer(generation: number, seconds: number): void {
    this.clearCaptureTimer();
    this.captureTimer = setTimeout(() => {
      this.captureTimer = null;
      if (!this.isCurrent(generation)) return;
      this.onTranscript("", true);
      this.stopRecognition();
      this.enterWakeReady(generation, true);
    }, Math.min(seconds, MAX_HANDS_FREE_TIMER_SECONDS) * 1000);
  }

  private submit(text: string, generation: number): void {
    if (!this.isCurrent(generation)) return;
    this.clearCaptureTimer();
    this.clearHeardTimer();
    this.clearFollowUpRetryTimer();
    this.stopRecognition();
    this.phase = "submitting";
    this.turnInFlight = true;
    this.emit("submitting");

    let sendResult: Promise<boolean> | boolean;
    try {
      sendResult = this.sendText(text);
    } catch {
      this.fail("Turn could not be sent");
      return;
    }
    Promise.resolve(sendResult).then((sent) => {
      if (!this.isCurrent(generation) || sent) return;
      this.fail("Turn could not be sent");
    }).catch(() => {
      if (this.isCurrent(generation)) this.fail("Turn could not be sent");
    });
  }

  private fail(message: string): void {
    this.generation += 1;
    this.armed = false;
    this.phase = "off";
    this.turnInFlight = false;
    this.clearTimers();
    this.stopRecognition();
    this.onTranscript("", true);
    this.emit("error");
    this.onError(message);
  }

  private clearCaptureTimer(): void {
    if (this.captureTimer !== null) {
      clearTimeout(this.captureTimer);
      this.captureTimer = null;
    }
  }

  private clearHeardTimer(): void {
    if (this.heardTimer !== null) {
      clearTimeout(this.heardTimer);
      this.heardTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearCaptureTimer();
    this.clearHeardTimer();
    if (this.restartTimer !== null) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    this.clearFollowUpRetryTimer();
    this.clearFollowUpWatchdog();
  }

  private clearFollowUpRetryTimer(): void {
    if (this.followUpRetryTimer !== null) {
      clearTimeout(this.followUpRetryTimer);
      this.followUpRetryTimer = null;
    }
  }

  private clearFollowUpWatchdog(): void {
    if (this.followUpWatchdogTimer !== null) {
      clearTimeout(this.followUpWatchdogTimer);
      this.followUpWatchdogTimer = null;
    }
  }

  private stopRecognition(): void {
    this.clearFollowUpWatchdog();
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition === null) return;
    recognition.onstart = null;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    try {
      recognition.stop();
    } catch {
      // A browser may report a late stop after an automatic end.
    }
  }

  private isCurrent(generation: number): boolean {
    return this.armed && this.generation === generation;
  }

  private emit(state: HandsFreeState): void {
    this.onState(state);
  }
}

function positiveSeconds(value: number | undefined): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0
    ? value
    : DEFAULT_HANDS_FREE_SECONDS;
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
  onPlaybackFinished?: (turnId: string) => void;
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
  private readonly onPlaybackFinished: (turnId: string) => void;
  private context: AudioContextLike | null = null;
  private activeTurnId: string | null = null;
  private endedTurnId: string | null = null;
  private sampleRate = 0;
  private channels = 0;
  private nextStartAt = 0;
  private pendingBytes = new Uint8Array();
  private readonly sources = new Set<AudioBufferSourceLike>();

  constructor(options: PcmAudioPlayerOptions = {}) {
    this.audioContextFactory = options.audioContextFactory ?? defaultAudioContextFactory;
    this.onError = options.onError ?? (() => {});
    this.onPlaybackFinished = options.onPlaybackFinished ?? (() => {});
  }

  get hasPendingPlayback(): boolean {
    return this.sources.size > 0;
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

    const incoming = new Uint8Array(chunk);
    const bytesPerFrame = this.channels * 2;
    const combined = new Uint8Array(this.pendingBytes.byteLength + incoming.byteLength);
    combined.set(this.pendingBytes);
    combined.set(incoming, this.pendingBytes.byteLength);
    const completeByteLength = combined.byteLength - (combined.byteLength % bytesPerFrame);
    this.pendingBytes = combined.slice(completeByteLength);
    if (completeByteLength === 0) return;

    const bytes = combined.subarray(0, completeByteLength);
    const frameCount = completeByteLength / bytesPerFrame;

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
      source.onended = () => {
        this.sources.delete(source);
        this.notifyPlaybackFinished();
      };
    } catch {
      this.onError("Audio playback could not start");
      this.stop();
    }
  }

  end(turnId: string): void {
    if (this.activeTurnId === turnId) {
      this.activeTurnId = null;
      this.pendingBytes = new Uint8Array();
      this.endedTurnId = turnId;
      this.notifyPlaybackFinished();
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
    this.endedTurnId = null;
    this.nextStartAt = 0;
    this.pendingBytes = new Uint8Array();
  }

  private notifyPlaybackFinished(): void {
    if (this.endedTurnId === null || this.sources.size > 0) return;
    const turnId = this.endedTurnId;
    this.endedTurnId = null;
    try {
      this.onPlaybackFinished(turnId);
    } catch {
      // A surface callback must not escape an audio event.
    }
  }

  private ensureContext(): AudioContextLike {
    if (this.context === null) {
      this.context = this.audioContextFactory();
    }
    return this.context;
  }
}
