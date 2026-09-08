import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DisplayBridge,
  postDisplayAction,
  type DisplayAction,
  type DisplayReducer,
  type DisplayView,
  type WebSocketLike,
} from "./bridge";
import { createDisplayReducer } from "./reducer";
import type { ActionValidationResult, SnapshotReduction } from "./reducer";
import type { DisplayAudioEvent, DisplaySnapshot } from "./protocol";

class FakeSocket implements WebSocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];

  close(): void {}

  send(data: string): void {
    this.sent.push(data);
  }

  open(): void {
    this.onopen?.();
  }

  message(data: string | ArrayBuffer): void {
    this.onmessage?.({ data } as MessageEvent<string>);
  }

  closeFromServer(): void {
    this.onclose?.();
  }
}

const snapshot: DisplaySnapshot = {
  type: "snapshot",
  schema: 1,
  sequence: 1,
  state: "prompt",
  response_text: "",
  status_text: null,
  media: null,
  prompt: {
    kind: "confirm",
    title: "Set home?",
    body: "Use this display as home?",
    options: [{ id: "yes", label: "Yes" }],
    action_id: "sethome",
    timeout_seconds: null,
  },
  capabilities: {
    actions: ["prompt.choose", "prompt.dismiss"],
    features: ["prompt_overlay"],
  },
};

const view: DisplayView = {
  ...snapshot,
  is_busy: false,
  connection_healthy: true,
  can_choose: true,
  can_dismiss: false,
};

const action: DisplayAction = {
  type: "action",
  schema: 1,
  action_id: "sethome",
  choice: "yes",
};

describe("DisplayBridge", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("routes snapshots through the reducer and emits approved domain actions", async () => {
    const socket = new FakeSocket();
    const reducer: DisplayReducer = {
      reset: vi.fn(),
      applySnapshot: vi.fn((_snapshot: DisplaySnapshot): SnapshotReduction => ({
        kind: "accepted",
        view,
      })),
      validateAction: vi.fn((_action: DisplayAction): ActionValidationResult => "accepted"),
    };
    const actionTransport = vi.fn(async (_action: DisplayAction) => {});
    const onView = vi.fn();

    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      reducer,
      onView,
      onConnectionState: () => {},
      socketFactory: () => socket,
      actionTransport,
    });

    bridge.start();
    socket.open();
    socket.message(JSON.stringify(snapshot));

    expect(reducer.reset).toHaveBeenCalledOnce();
    expect(reducer.applySnapshot).toHaveBeenCalledWith(snapshot);
    expect(onView).toHaveBeenCalledWith(view);

    await expect(bridge.dispatchAction(action)).resolves.toBe(true);
    expect(reducer.validateAction).toHaveBeenCalledWith(action);
    expect(actionTransport).toHaveBeenCalledWith(action);

    bridge.stop();
  });

  it("sends browser voice text and routes streamed PCM frames", async () => {
    const socket = new FakeSocket();
    const audioEvents: DisplayAudioEvent[] = [];
    const audioChunks: ArrayBuffer[] = [];
    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      onView: () => {},
      onConnectionState: () => {},
      onAudioEvent: (event) => audioEvents.push(event),
      onAudioChunk: (chunk) => audioChunks.push(chunk),
      socketFactory: () => socket,
    });

    bridge.start();
    socket.open();
    socket.message(JSON.stringify({
      ...snapshot,
      state: "idle",
      sequence: 1,
      prompt: null,
      capabilities: undefined,
    }));

    await expect(bridge.sendVoiceTurn("what is the weather?")).resolves.toBe(true);
    expect(JSON.parse(socket.sent[0])).toEqual({
      type: "voice_turn",
      schema: 1,
      text: "what is the weather?",
    });

    socket.message(JSON.stringify({
      type: "audio_start",
      schema: 1,
      turn_id: "turn-1",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    }));
    const pcm = new Uint8Array([1, 2, 3, 4]).buffer;
    socket.message(pcm);

    expect(audioEvents).toEqual([{
      type: "audio_start",
      schema: 1,
      turn_id: "turn-1",
      sample_rate: 24000,
      channels: 1,
      sample_width: 2,
    }]);
    expect(audioChunks).toHaveLength(1);
    expect(Array.from(new Uint8Array(audioChunks[0]))).toEqual([1, 2, 3, 4]);
    bridge.stop();
  });

  it("re-hydrates a reset reducer after reconnect and ignores stale snapshots", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const views: DisplayView[] = [];
    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      reducer: createDisplayReducer(),
      onView: (nextView) => views.push(nextView),
      onConnectionState: () => {},
      socketFactory: () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    });

    bridge.start();
    sockets[0].open();
    sockets[0].message(JSON.stringify({
      ...snapshot,
      state: "idle",
      sequence: 12,
      prompt: null,
    }));
    sockets[0].message(JSON.stringify({
      ...snapshot,
      state: "speaking",
      sequence: 11,
      prompt: null,
    }));
    expect(views.map((view) => view.sequence)).toEqual([12]);

    sockets[0].closeFromServer();
    vi.advanceTimersByTime(250);
    sockets[1].open();
    sockets[1].message(JSON.stringify({
      ...snapshot,
      state: "idle",
      sequence: 0,
      prompt: null,
    }));

    expect(views.map((view) => view.sequence)).toEqual([12, 0]);
    bridge.stop();
  });

  it("pushes a socket loss into a reducer that owns a rendered connection state", () => {
    const socket = new FakeSocket();
    const setConnectionState = vi.fn();
    const reducer: DisplayReducer = {
      reset: vi.fn(),
      applySnapshot: vi.fn((_snapshot: DisplaySnapshot): SnapshotReduction => ({
        kind: "accepted",
        view,
      })),
      validateAction: vi.fn((_action: DisplayAction): ActionValidationResult => "accepted"),
      setConnectionState,
    };
    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      reducer,
      onView: () => {},
      onConnectionState: () => {},
      socketFactory: () => socket,
    });

    bridge.start();
    socket.open();
    socket.message(JSON.stringify(snapshot));
    expect(setConnectionState).not.toHaveBeenCalledWith("connected");

    socket.closeFromServer();
    expect(setConnectionState).toHaveBeenCalledWith("disconnected");
    bridge.stop();
  });

  it("retains the last view when a partial JSON message is received", () => {
    const socket = new FakeSocket();
    const views: DisplayView[] = [];
    const protocolErrors: string[] = [];
    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      reducer: createDisplayReducer(),
      onView: (nextView) => views.push(nextView),
      onConnectionState: () => {},
      onProtocolError: (message) => protocolErrors.push(message),
      socketFactory: () => socket,
    });

    bridge.start();
    socket.open();
    socket.message(JSON.stringify({ ...snapshot, state: "idle", prompt: null }));
    socket.message('{"type":"snapshot"');

    expect(views.map((view) => view.sequence)).toEqual([1]);
    expect(protocolErrors).toEqual(["display data unavailable"]);
    bridge.stop();
  });

  it("does not transport a reducer-rejected action", async () => {
    const socket = new FakeSocket();
    const actionTransport = vi.fn();
    const actionErrors: string[] = [];
    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      reducer: createDisplayReducer(),
      onView: () => {},
      onConnectionState: () => {},
      socketFactory: () => socket,
      actionTransport,
      onActionError: (error) => actionErrors.push(error),
    });

    bridge.start();
    socket.open();
    socket.message(JSON.stringify(snapshot));

    await expect(bridge.dispatchAction({ ...action, choice: "later" })).resolves.toBe(false);
    expect(actionTransport).not.toHaveBeenCalled();
    expect(actionErrors).toEqual(["unknown_choice"]);
    bridge.stop();
  });

  it("reports action transport failure without throwing", async () => {
    const socket = new FakeSocket();
    const actionErrors: string[] = [];
    const bridge = new DisplayBridge({
      url: "ws://display.test/state",
      reducer: createDisplayReducer(),
      onView: () => {},
      onConnectionState: () => {},
      socketFactory: () => socket,
      actionTransport: () => Promise.reject(new Error("offline")),
      onActionError: (error) => actionErrors.push(error),
    });

    bridge.start();
    socket.open();
    socket.message(JSON.stringify(snapshot));

    await expect(bridge.dispatchAction(action)).resolves.toBe(false);
    expect(actionErrors).toEqual(["transport_error"]);
    bridge.stop();
  });

  it("encodes normalized actions through the same-origin HTTP adapter", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("{}", { status: 200 }),
    );

    await postDisplayAction({
      ...action,
      action_id: "set home",
      choice: "yes/no",
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/action?action_id=set+home&choice=yes%2Fno",
      { method: "POST" },
    );
  });

  it("rejects a failed HTTP action response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("", { status: 503 }),
    );

    await expect(postDisplayAction(action)).rejects.toThrow("HTTP 503");
  });
});
