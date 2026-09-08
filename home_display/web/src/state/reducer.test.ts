import { describe, expect, it } from "vitest";

import {
  createDisplayReducer,
  createInitialDisplayView,
  type DisplayView,
} from "./reducer";
import type { DisplayAction, DisplaySnapshot } from "./protocol";

const snapshot = (
  sequence: number,
  state: DisplaySnapshot["state"],
  overrides: Partial<DisplaySnapshot> = {},
): DisplaySnapshot => ({
  type: "snapshot",
  schema: 1,
  sequence,
  state,
  response_text: "",
  status_text: null,
  media: null,
  prompt: null,
  ...overrides,
});

const promptSnapshot = (sequence = 1): DisplaySnapshot => snapshot(sequence, "prompt", {
  prompt: {
    kind: "confirm",
    title: "Set home?",
    body: "Use this display as home?",
    options: [
      { id: "yes", label: "Yes" },
      { id: "no", label: "No" },
    ],
    action_id: "sethome",
    timeout_seconds: null,
  },
  capabilities: {
    actions: ["prompt.choose", "prompt.dismiss"],
    features: ["prompt_overlay"],
  },
});

const action: DisplayAction = {
  type: "action",
  schema: 1,
  action_id: "sethome",
  choice: "yes",
};

describe("display reducer", () => {
  it("derives view flags from the accepted snapshot and gates prompt actions", () => {
    const reducer = createDisplayReducer();

    const result = reducer.applySnapshot(promptSnapshot());

    expect(result).toMatchObject({ kind: "accepted" });
    if (result.kind !== "accepted") return;
    expect(result.view).toMatchObject<Partial<DisplayView>>({
      state: "prompt",
      is_busy: false,
      connection_healthy: true,
      can_choose: true,
      can_dismiss: true,
    });
    expect(reducer.validateAction(action)).toBe("accepted");
    expect(reducer.validateAction({ ...action, choice: "later" })).toBe("unknown_choice");
    expect(reducer.validateAction({ ...action, action_id: "other" })).toBe("action_id_mismatch");
  });

  it("rejects stale snapshots without replacing the current view", () => {
    const reducer = createDisplayReducer();
    reducer.applySnapshot(snapshot(4, "speaking", { response_text: "fresh" }));

    expect(reducer.applySnapshot(snapshot(3, "idle"))).toEqual({ kind: "stale" });
    expect(reducer.validateAction(action)).toBe("prompt_not_active");
    expect(reducer.applySnapshot(snapshot(5, "idle"))).toEqual({
      kind: "accepted",
      view: expect.objectContaining({ state: "idle", sequence: 5 }),
    });
  });

  it("rejects illegal transitions and resets for a newly hydrated socket", () => {
    const reducer = createDisplayReducer();
    reducer.applySnapshot(snapshot(8, "idle"));

    expect(reducer.applySnapshot(snapshot(9, "speaking"))).toEqual({
      kind: "invalid_transition",
    });

    reducer.reset();
    expect(reducer.applySnapshot(snapshot(0, "speaking"))).toMatchObject({
      kind: "accepted",
      view: { sequence: 0, state: "speaking", is_busy: true },
    });
  });

  it("accepts a browser turn that starts in thinking", () => {
    const reducer = createDisplayReducer();
    reducer.applySnapshot(snapshot(1, "idle"));

    expect(reducer.applySnapshot(snapshot(2, "thinking"))).toMatchObject({
      kind: "accepted",
      view: { state: "thinking", is_busy: true },
    });
  });

  it("accepts explicit error and disconnected states from any current state", () => {
    const reducer = createDisplayReducer();
    reducer.applySnapshot(snapshot(1, "speaking"));

    expect(reducer.applySnapshot(snapshot(2, "error"))).toMatchObject({
      kind: "accepted",
      view: { state: "error" },
    });

    reducer.reset();
    reducer.applySnapshot(snapshot(1, "idle"));
    expect(reducer.applySnapshot(snapshot(2, "disconnected"))).toMatchObject({
      kind: "accepted",
      view: { state: "disconnected" },
    });
  });

  it("does not allow a prompt action when the capability is absent", () => {
    const reducer = createDisplayReducer();
    reducer.applySnapshot({ ...promptSnapshot(), capabilities: { actions: [], features: [] } });

    expect(reducer.validateAction(action)).toBe("action_not_allowed");
    expect(reducer.validateAction({ ...action, action_id: "" })).toBe("invalid_argument");
  });
});

describe("createInitialDisplayView", () => {
  it("provides a safe idle view before the first socket snapshot", () => {
    expect(createInitialDisplayView()).toMatchObject({
      state: "idle",
      sequence: 0,
      is_busy: false,
      connection_healthy: true,
      can_choose: false,
      can_dismiss: false,
    });
  });
});
