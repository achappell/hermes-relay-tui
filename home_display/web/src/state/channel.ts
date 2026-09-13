import {
  parseAudioEvent,
  parseProfileRouteAck,
  parseSnapshot,
  type DisplayAction,
  type DisplayAudioEvent,
  type DisplayProfileRouteAck,
  type DisplaySnapshot,
} from "./protocol";

export type ConnectionState = "connecting" | "connected" | "disconnected" | "capacity";
export type SnapshotListener = (snapshot: DisplaySnapshot) => void;
export type SocketFactory = (url: string) => WebSocketLike;
export type ProtocolErrorListener = (message: string) => void;
export type ValidSnapshotListener = (snapshot: DisplaySnapshot) => void;
export type AudioEventListener = (event: DisplayAudioEvent) => void;
export type AudioChunkListener = (chunk: ArrayBuffer) => void;

interface PendingProfileRoute {
  resolve: (accepted: boolean) => void;
  timer: ReturnType<typeof setTimeout>;
}

export interface WebSocketCloseEventLike {
  code?: number;
}

export interface WebSocketLike {
  onopen: (() => void) | null;
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  onerror: (() => void) | null;
  onclose: ((event?: WebSocketCloseEventLike) => void) | null;
  binaryType?: "blob" | "arraybuffer";
  send?: (data: string) => void;
  close(): void;
}

export const defaultSocketFactory: SocketFactory = (url) => new WebSocket(url) as unknown as WebSocketLike;

const RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000] as const;
// Admission may try several catalog profiles. Keep the browser waiting beyond
// the server's bounded connect/cleanup sequence so it cannot resume capture
// while the server is still committing a route.
const PROFILE_ROUTE_ACK_TIMEOUT_MS = 20_000;

function normaliseWakePhrase(value: string): string {
  return value.trim().replace(/\s+/g, " ");
}

function hasControlCharacter(value: string): boolean {
  return [...value].some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127;
  });
}

export class StateChannel {
  private socket: WebSocketLike | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private lastSequence = -1;
  private hasHydratedSocket = false;
  private socketOpen = false;
  private running = false;
  private routeSequence = 0;
  private readonly pendingProfileRoutes = new Map<string, PendingProfileRoute>();

  constructor(
    private readonly url: string,
    private readonly onSnapshot: SnapshotListener,
    private readonly onConnectionState: (state: ConnectionState) => void,
    private readonly onProtocolError: ProtocolErrorListener = () => {},
    private readonly socketFactory: SocketFactory = defaultSocketFactory,
    private readonly onValidSnapshot: ValidSnapshotListener = () => {},
    private readonly onAudioEvent: AudioEventListener = () => {},
    private readonly onAudioChunk: AudioChunkListener = () => {},
  ) {}

  start(): void {
    if (this.running) {
      return;
    }

    this.running = true;
    this.connect();
  }

  stop(): void {
    this.running = false;
    this.socketOpen = false;
    this.settlePendingProfileRoutes();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close();
    }
  }

  private connect(): void {
    if (!this.running) {
      return;
    }

    this.deliver(() => this.onConnectionState("connecting"));
    let socket: WebSocketLike;
    try {
      socket = this.socketFactory(this.url);
    } catch {
      this.settlePendingProfileRoutes();
      this.deliver(() => this.onConnectionState("disconnected"));
      this.scheduleReconnect();
      return;
    }

    socket.binaryType = "arraybuffer";
    this.socket = socket;
    this.hasHydratedSocket = false;
    socket.onopen = () => {
      if (!this.isCurrent(socket)) {
        return;
      }

      this.socketOpen = true;
      this.lastSequence = -1;
    };
    socket.onmessage = (event) => {
      if (!this.isCurrent(socket)) {
        return;
      }

      this.handleMessage(event.data);
    };
    socket.onerror = () => {};
    socket.onclose = (event) => {
      if (!this.isCurrent(socket)) {
        return;
      }

      this.socket = null;
      this.socketOpen = false;
      this.settlePendingProfileRoutes();
      this.deliver(() => this.onConnectionState(event?.code === 1013 ? "capacity" : "disconnected"));
      this.scheduleReconnect();
    };
  }

  sendVoiceTurn(text: string, wakePhrase?: string): boolean {
    const normalized = text.trim();
    const normalizedWakePhrase = wakePhrase === undefined
      ? undefined
      : normaliseWakePhrase(wakePhrase);
    if (
      !this.socketOpen ||
      !this.hasHydratedSocket ||
      !this.socket ||
      !normalized ||
      normalized.length > 4000 ||
      normalizedWakePhrase !== undefined &&
        (!normalizedWakePhrase ||
          normalizedWakePhrase.length > 128 ||
          hasControlCharacter(normalizedWakePhrase))
    ) {
      return false;
    }
    if (typeof this.socket.send !== "function") {
      return false;
    }
    try {
      const payload: {
        type: "voice_turn";
        schema: 1;
        text: string;
        wake_phrase?: string;
      } = { type: "voice_turn", schema: 1, text: normalized };
      if (normalizedWakePhrase !== undefined) payload.wake_phrase = normalizedWakePhrase;
      this.socket.send(JSON.stringify(payload));
      return true;
    } catch {
      return false;
    }
  }

  sendProfileRoute(wakePhrase: string): Promise<boolean> {
    const normalized = normaliseWakePhrase(wakePhrase);
    const socket = this.socket;
    const send = socket?.send;
    if (
      !this.socketOpen ||
      !this.hasHydratedSocket ||
      !socket ||
      typeof send !== "function" ||
      !normalized ||
      normalized.length > 128 ||
      hasControlCharacter(normalized)
    ) {
      return Promise.resolve(false);
    }

    const requestId = `route-${this.routeSequence + 1}`;
    if (requestId.length > 64) {
      return Promise.resolve(false);
    }
    this.routeSequence += 1;

    return new Promise<boolean>((resolve) => {
      const timer = setTimeout(() => {
        const pending = this.pendingProfileRoutes.get(requestId);
        if (pending === undefined) return;
        this.pendingProfileRoutes.delete(requestId);
        pending.resolve(false);
      }, PROFILE_ROUTE_ACK_TIMEOUT_MS);
      this.pendingProfileRoutes.set(requestId, { resolve, timer });
      try {
        send.call(socket, JSON.stringify({
          type: "profile_route",
          schema: 1,
          request_id: requestId,
          wake_phrase: normalized,
        }));
      } catch {
        clearTimeout(timer);
        this.pendingProfileRoutes.delete(requestId);
        resolve(false);
      }
    });
  }

  sendAction(action: DisplayAction): boolean {
    if (
      !this.socketOpen ||
      !this.hasHydratedSocket ||
      !this.socket ||
      typeof this.socket.send !== "function"
    ) {
      return false;
    }
    try {
      this.socket.send(JSON.stringify(action));
      return true;
    } catch {
      return false;
    }
  }

  private handleMessage(data: unknown): void {
    if (data instanceof ArrayBuffer) {
      this.deliver(() => this.onAudioChunk(data));
      return;
    }
    if (ArrayBuffer.isView(data)) {
      const view = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      const copy = view.slice().buffer;
      this.deliver(() => this.onAudioChunk(copy));
      return;
    }
    if (typeof Blob !== "undefined" && data instanceof Blob) {
      void data.arrayBuffer().then((buffer) => {
        if (this.running) {
          this.deliver(() => this.onAudioChunk(buffer));
        }
      }).catch(() => this.reportProtocolError());
      return;
    }

    // The browser WebSocket API delivers one complete message event even when
    // the protocol fragmented it on the wire. A partial/malformed application
    // payload must therefore be rejected atomically without replacing the
    // last accepted snapshot.
    let raw: unknown;
    try {
      raw = typeof data === "string" ? JSON.parse(data) : null;
    } catch {
      this.reportProtocolError();
      return;
    }

    const audioEvent = parseAudioEvent(raw);
    if (audioEvent !== null) {
      this.deliver(() => this.onAudioEvent(audioEvent));
      return;
    }

    const routeAck = parseProfileRouteAck(raw);
    if (routeAck !== null) {
      this.resolveProfileRoute(routeAck);
      return;
    }

    const snapshot = parseSnapshot(raw);
    if (snapshot === null) {
      this.reportProtocolError();
      return;
    }

    this.deliver(() => this.onValidSnapshot(snapshot));

    if (snapshot.sequence <= this.lastSequence) {
      return;
    }

    this.lastSequence = snapshot.sequence;
    this.deliver(() => this.onSnapshot(snapshot));

    if (!this.hasHydratedSocket) {
      this.hasHydratedSocket = true;
      this.reconnectAttempt = 0;
      this.deliver(() => this.onConnectionState("connected"));
    }
  }

  private scheduleReconnect(): void {
    if (!this.running || this.reconnectTimer !== null) {
      return;
    }

    const delay = RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }

  private isCurrent(socket: WebSocketLike): boolean {
    return this.running && this.socket === socket;
  }

  private reportProtocolError(): void {
    this.deliver(() => this.onProtocolError("display data unavailable"));
  }

  private resolveProfileRoute(ack: DisplayProfileRouteAck): void {
    const pending = this.pendingProfileRoutes.get(ack.request_id);
    if (pending === undefined) return;
    this.pendingProfileRoutes.delete(ack.request_id);
    clearTimeout(pending.timer);
    pending.resolve(ack.accepted);
  }

  private settlePendingProfileRoutes(): void {
    for (const [requestId, pending] of this.pendingProfileRoutes) {
      clearTimeout(pending.timer);
      pending.resolve(false);
      this.pendingProfileRoutes.delete(requestId);
    }
  }

  private deliver(callback: () => void): void {
    try {
      callback();
    } catch {
      // Consumer failures must not escape a WebSocket event callback.
    }
  }
}
