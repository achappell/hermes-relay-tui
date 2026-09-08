import {
  StateChannel,
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

export interface DisplayBridgeOptions {
  url: string;
  onView: (view: DisplayView) => void;
  onConnectionState: (state: ConnectionState) => void;
  reducer?: DisplayReducer;
  actionTransport?: ActionTransport;
  onProtocolError?: ProtocolErrorListener;
  onValidSnapshot?: (snapshot: DisplaySnapshot) => void;
  onActionError?: (error: ActionDispatchError) => void;
  socketFactory?: SocketFactory;
}

export const postDisplayAction: ActionTransport = async (action) => {
  const query = new URLSearchParams({
    action_id: action.action_id,
    choice: action.choice,
  });
  const response = await fetch(`/action?${query.toString()}`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`display action failed with HTTP ${response.status}`);
  }
};

export class DisplayBridge {
  private readonly reducer: DisplayReducer;
  private readonly actionTransport: ActionTransport;
  private readonly onActionError: (error: ActionDispatchError) => void;
  private readonly channel: StateChannel;

  /**
   * Keep browser transport and action encoding at the edge. The reducer is an
   * injected port so a generated WebAssembly implementation can replace the
   * current browser reducer implementation without changing the kiosk
   * lifecycle or surfaces.
   */
  constructor(options: DisplayBridgeOptions) {
    this.reducer = options.reducer ?? createDisplayReducer();
    this.actionTransport = options.actionTransport ?? postDisplayAction;
    this.onActionError = options.onActionError ?? (() => {});

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
        } else if (state === "disconnected") {
          this.reducer.setConnectionState?.("disconnected");
        }
        this.deliver(() => options.onConnectionState(state));
      },
      options.onProtocolError,
      options.socketFactory,
      options.onValidSnapshot,
    );
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

  private deliver(callback: () => void): void {
    try {
      callback();
    } catch {
      // A surface or diagnostic listener must not escape an event callback.
    }
  }
}
