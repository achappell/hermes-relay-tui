import {
  StateChannel,
  type AudioChunkListener,
  type AudioEventListener,
  type ConnectionState,
  type ProtocolErrorListener,
  type SocketFactory,
} from "./channel";
import type { DisplayAction, DisplaySnapshot } from "./protocol";
import {
  createDisplayReducer,
  type ActionValidationResult,
  type DisplayReducer,
  type DisplayView,
} from "./reducer";

export type { DisplayAction } from "./protocol";
export type { DisplayReducer, DisplayView } from "./reducer";
export type { WebSocketLike } from "./channel";

export type ActionTransport = (action: DisplayAction) => Promise<void> | void;
export type ActionDispatchError = ActionValidationResult | "transport_error";
export type VoiceTransport = (text: string, wakePhrase?: string) => Promise<void> | void;
export type VoiceRouteTransport = (wakePhrase: string) => Promise<boolean> | boolean;

const DISPLAY_ACTION_TIMEOUT_MS = 10_000;

export interface DisplayBridgeOptions {
  url: string;
  onView: (view: DisplayView) => void;
  onConnectionState: (state: ConnectionState) => void;
  reducer?: DisplayReducer;
  actionTransport?: ActionTransport;
  onProtocolError?: ProtocolErrorListener;
  onValidSnapshot?: (snapshot: DisplaySnapshot) => void;
  onActionError?: (error: ActionDispatchError) => void;
  onAudioEvent?: AudioEventListener;
  onAudioChunk?: AudioChunkListener;
  voiceTransport?: VoiceTransport;
  profileRouteTransport?: VoiceRouteTransport;
  onVoiceError?: (error: "transport_error") => void;
  socketFactory?: SocketFactory;
}

export const postDisplayAction: ActionTransport = async (action) => {
  const query = new URLSearchParams({
    action_id: action.action_id,
    choice: action.choice,
  });
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DISPLAY_ACTION_TIMEOUT_MS);
  try {
    const response = await fetch(`/action?${query.toString()}`, {
      method: "POST",
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`display action failed with HTTP ${response.status}`);
    }
  } finally {
    clearTimeout(timeoutId);
  }
};

export class DisplayBridge {
  private readonly reducer: DisplayReducer;
  private readonly actionTransport: ActionTransport;
  private readonly onActionError: (error: ActionDispatchError) => void;
  private readonly voiceTransport: VoiceTransport | null;
  private readonly profileRouteTransport: VoiceRouteTransport | null;
  private readonly onVoiceError: (error: "transport_error") => void;
  private readonly channel: StateChannel;

  /**
   * Keep browser transport and action encoding at the edge. The reducer is an
   * injected port so a generated WebAssembly implementation can replace the
   * current browser reducer implementation without changing the kiosk
   * lifecycle or surfaces.
   */
  constructor(options: DisplayBridgeOptions) {
    this.reducer = options.reducer ?? createDisplayReducer();
    this.onActionError = options.onActionError ?? (() => {});
    this.voiceTransport = options.voiceTransport ?? null;
    this.profileRouteTransport = options.profileRouteTransport ?? null;
    this.onVoiceError = options.onVoiceError ?? (() => {});

    this.channel = new StateChannel(
      options.url,
      (snapshot) => {
        const result = this.reducer.applySnapshot(snapshot);
        if (result.kind === "accepted") {
          this.deliver(() => options.onView(result.view));
        } else if (result.kind === "invalid_transition" || result.kind === "invalid_snapshot") {
          this.deliver(() => options.onProtocolError?.("display data unavailable"));
        }
      },
      (state) => {
        if (state === "connecting") {
          this.reducer.reset();
        } else if (state === "disconnected" || state === "capacity") {
          this.reducer.setConnectionState?.("disconnected");
        }
        this.deliver(() => options.onConnectionState(state));
      },
      options.onProtocolError,
      options.socketFactory,
      options.onValidSnapshot,
      options.onAudioEvent,
      options.onAudioChunk,
    );
    this.actionTransport = options.actionTransport ?? ((action) => {
      if (!this.channel.sendAction(action)) {
        throw new Error("display action unavailable");
      }
    });
  }

  start(): void {
    this.channel.start();
  }

  stop(): void {
    this.channel.stop();
  }

  async dispatchAction(action: DisplayAction): Promise<boolean> {
    const validation = this.reducer.validateAction(action);
    if (validation !== "accepted") {
      this.deliver(() => this.onActionError(validation));
      return false;
    }

    try {
      await this.actionTransport(action);
      return true;
    } catch {
      this.deliver(() => this.onActionError("transport_error"));
      return false;
    }
  }

  async sendVoiceTurn(text: string, wakePhrase?: string): Promise<boolean> {
    const normalized = text.trim();
    const normalizedWakePhrase = wakePhrase === undefined
      ? undefined
      : wakePhrase.trim().replace(/\s+/g, " ");
    if (
      !normalized ||
      normalized.length > 4000 ||
      normalizedWakePhrase !== undefined &&
        (!normalizedWakePhrase || normalizedWakePhrase.length > 128 || /[\u0000-\u001f\u007f]/.test(normalizedWakePhrase))
    ) {
      this.deliver(() => this.onVoiceError("transport_error"));
      return false;
    }

    try {
      if (this.voiceTransport !== null) {
        if (normalizedWakePhrase === undefined) {
          await this.voiceTransport(normalized);
        } else {
          await this.voiceTransport(normalized, normalizedWakePhrase);
        }
        return true;
      }
      if (this.channel.sendVoiceTurn(normalized, normalizedWakePhrase)) {
        return true;
      }
    } catch {
      // The caller receives one safe transport error, never a socket detail.
    }
    this.deliver(() => this.onVoiceError("transport_error"));
    return false;
  }

  async routeProfile(wakePhrase: string): Promise<boolean> {
    const normalized = wakePhrase.trim().replace(/\s+/g, " ");
    if (
      !normalized ||
      normalized.length > 128 ||
      /[\u0000-\u001f\u007f]/.test(normalized)
    ) {
      return false;
    }
    try {
      if (this.profileRouteTransport !== null) {
        return Boolean(await this.profileRouteTransport(normalized));
      }
      return await this.channel.sendProfileRoute(normalized);
    } catch {
      return false;
    }
  }

  private deliver(callback: () => void): void {
    try {
      callback();
    } catch {
      // A surface or diagnostic listener must not escape an event callback.
    }
  }
}
