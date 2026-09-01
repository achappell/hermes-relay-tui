import { parseSnapshot, type DisplaySnapshot } from "./protocol";

export type ConnectionState = "connecting" | "connected" | "disconnected";
export type SnapshotListener = (snapshot: DisplaySnapshot) => void;
export type SocketFactory = (url: string) => WebSocketLike;
export type ProtocolErrorListener = (message: string) => void;
export type ValidSnapshotListener = (snapshot: DisplaySnapshot) => void;

export interface WebSocketLike {
  onopen: (() => void) | null;
  onmessage: ((event: MessageEvent<string>) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
  close(): void;
}

export const defaultSocketFactory: SocketFactory = (url) => new WebSocket(url) as unknown as WebSocketLike;

const RECONNECT_DELAYS_MS = [250, 500, 1000, 2000, 4000] as const;

export class StateChannel {
  private socket: WebSocketLike | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private lastSequence = -1;
  private running = false;

  constructor(
    private readonly url: string,
    private readonly onSnapshot: SnapshotListener,
    private readonly onConnectionState: (state: ConnectionState) => void,
    private readonly onProtocolError: ProtocolErrorListener = () => {},
    private readonly socketFactory: SocketFactory = defaultSocketFactory,
    private readonly onValidSnapshot: ValidSnapshotListener = () => {},
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
      this.deliver(() => this.onConnectionState("disconnected"));
      this.scheduleReconnect();
      return;
    }

    this.socket = socket;
    socket.onopen = () => {
      if (!this.isCurrent(socket)) {
        return;
      }

      this.lastSequence = -1;
      this.reconnectAttempt = 0;
      this.deliver(() => this.onConnectionState("connected"));
    };
    socket.onmessage = (event) => {
      if (!this.isCurrent(socket)) {
        return;
      }

      this.handleMessage(event.data);
    };
    socket.onerror = () => {};
    socket.onclose = () => {
      if (!this.isCurrent(socket)) {
        return;
      }

      this.socket = null;
      this.deliver(() => this.onConnectionState("disconnected"));
      this.scheduleReconnect();
    };
  }

  private handleMessage(data: unknown): void {
    let raw: unknown;
    try {
      raw = typeof data === "string" ? JSON.parse(data) : null;
    } catch {
      this.reportProtocolError();
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

  private deliver(callback: () => void): void {
    try {
      callback();
    } catch {
      // Consumer failures must not escape a WebSocket event callback.
    }
  }
}
