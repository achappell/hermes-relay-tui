import type {
  DisplayAction,
  DisplaySnapshot,
} from "./protocol";

export type DisplayView = DisplaySnapshot & {
  is_busy: boolean;
  connection_healthy: boolean;
  can_choose: boolean;
  can_dismiss: boolean;
};

export type SnapshotReduction =
  | { kind: "accepted"; view: DisplayView }
  | { kind: "stale" }
  | { kind: "invalid_transition" }
  | { kind: "invalid_snapshot" };

export type ActionValidationResult =
  | "accepted"
  | "invalid_argument"
  | "prompt_not_active"
  | "action_not_allowed"
  | "action_id_mismatch"
  | "unknown_choice";

export type DisplayConnectionState = "connected" | "disconnected" | "error";

export interface DisplayReducer {
  reset(): void;
  applySnapshot(snapshot: DisplaySnapshot): SnapshotReduction;
  validateAction(action: DisplayAction): ActionValidationResult;
  setConnectionState?(state: DisplayConnectionState): void;
}

const busyStates = new Set(["listening", "thinking", "speaking", "buffering"]);

const allowedTransitions: Record<
  DisplaySnapshot["state"],
  ReadonlySet<DisplaySnapshot["state"]>
> = {
  idle: new Set(["idle", "heard", "listening", "prompt"]),
  heard: new Set(["heard", "listening", "thinking", "idle", "prompt"]),
  listening: new Set(["listening", "thinking", "heard", "idle"]),
  thinking: new Set(["thinking", "speaking", "buffering", "prompt", "idle"]),
  speaking: new Set(["speaking", "buffering", "prompt", "idle"]),
  buffering: new Set(["buffering", "speaking", "thinking", "prompt", "idle"]),
  error: new Set(["error", "idle"]),
  disconnected: new Set(["disconnected", "idle", "heard", "listening"]),
  prompt: new Set(["prompt", "idle", "thinking"]),
};

function connectionHealthy(state: DisplaySnapshot["state"]): boolean {
  return state !== "error" && state !== "disconnected";
}

function canPerformAction(
  snapshot: DisplaySnapshot,
  actionName: "prompt.choose" | "prompt.dismiss",
): boolean {
  return snapshot.capabilities?.actions.includes(actionName) ?? false;
}

function toView(snapshot: DisplaySnapshot): DisplayView {
  return {
    ...snapshot,
    is_busy: busyStates.has(snapshot.state),
    connection_healthy: connectionHealthy(snapshot.state),
    can_choose: snapshot.prompt !== null && canPerformAction(snapshot, "prompt.choose"),
    can_dismiss: snapshot.prompt !== null && canPerformAction(snapshot, "prompt.dismiss"),
  };
}

class SnapshotReducer implements DisplayReducer {
  private current: DisplayView | null = null;

  reset(): void {
    this.current = null;
  }

  applySnapshot(snapshot: DisplaySnapshot): SnapshotReduction {
    if (this.current !== null && snapshot.sequence <= this.current.sequence) {
      return { kind: "stale" };
    }
    if (
      this.current !== null &&
      snapshot.state !== "error" &&
      snapshot.state !== "disconnected" &&
      !allowedTransitions[this.current.state].has(snapshot.state)
    ) {
      return { kind: "invalid_transition" };
    }

    const view = toView(snapshot);
    this.current = view;
    return { kind: "accepted", view };
  }

  validateAction(action: DisplayAction): ActionValidationResult {
    if (
      action.type !== "action" ||
      action.schema !== 1 ||
      typeof action.action_id !== "string" ||
      action.action_id.length === 0 ||
      action.action_id.length > 64 ||
      typeof action.choice !== "string" ||
      action.choice.length === 0 ||
      action.choice.length > 32
    ) {
      return "invalid_argument";
    }

    if (this.current === null || this.current.state !== "prompt" || this.current.prompt === null) {
      return "prompt_not_active";
    }
    if (!this.current.can_choose) {
      return "action_not_allowed";
    }
    if (this.current.prompt.action_id !== action.action_id) {
      return "action_id_mismatch";
    }
    return this.current.prompt.options.some((option) => option.id === action.choice)
      ? "accepted"
      : "unknown_choice";
  }
}

export function createDisplayReducer(): DisplayReducer {
  return new SnapshotReducer();
}

export function createInitialDisplayView(): DisplayView {
  return toView({
    type: "snapshot",
    schema: 1,
    sequence: 0,
    state: "idle",
    response_text: "",
    status_text: null,
    media: null,
    prompt: null,
  });
}
