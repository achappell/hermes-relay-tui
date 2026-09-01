import { afterEach, describe, expect, it, vi } from "vitest";

import { StateChannel, type WebSocketLike } from "./channel";

class FakeSocket implements WebSocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  closed = false;

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.onopen?.();
  }

  message(data: string): void {
    this.onmessage?.({ data } as MessageEvent<string>);
  }

  closeFromServer(): void {
    this.onclose?.();
  }
}

const rawSnapshot = (sequence: number) => JSON.stringify({
  type: "snapshot",
  schema: 1,
  sequence,
  state: "speaking",
  response_text: `response ${sequence}`,
  status_text: null,
  media: null,
});

describe("StateChannel", () => {
  afterEach(() => vi.useRealTimers());

  it("emits only newer snapshots and resets the sequence on a new socket", () => {
    const sockets: FakeSocket[] = [];
    const received: number[] = [];
    const channel = new StateChannel(
      "ws://display.test/state",
      (snapshot) => received.push(snapshot.sequence),
      () => {},
      () => {},
      () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    );

    channel.start();
    sockets[0].open();
    sockets[0].message(rawSnapshot(2));
    sockets[0].message(rawSnapshot(1));
    sockets[0].message(rawSnapshot(2));
    expect(received).toEqual([2]);

    vi.useFakeTimers();
    sockets[0].closeFromServer();
    vi.advanceTimersByTime(250);
    sockets[1].open();
    sockets[1].message(rawSnapshot(0));
    expect(received).toEqual([2, 0]);
  });

  it("reports connection state transitions", () => {
    const socket = new FakeSocket();
    const states: string[] = [];
    const channel = new StateChannel(
      "ws://display.test/state",
      () => {},
      (state) => states.push(state),
      () => {},
      () => socket,
    );

    channel.start();
    socket.open();
    socket.closeFromServer();
    expect(states).toEqual(["connecting", "connected", "disconnected"]);
  });

  it("uses exponential reconnect backoff with one pending timer", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const factory = vi.fn(() => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    });
    const channel = new StateChannel("ws://display.test/state", () => {}, () => {}, () => {}, factory);

    channel.start();
    let connectionCount = 1;
    for (const delay of [250, 500, 1000, 2000, 4000, 4000]) {
      sockets.at(-1)?.closeFromServer();
      sockets.at(-1)?.closeFromServer();
      vi.advanceTimersByTime(delay - 1);
      expect(factory).toHaveBeenCalledTimes(connectionCount);
      vi.advanceTimersByTime(1);
      connectionCount += 1;
      expect(factory).toHaveBeenCalledTimes(connectionCount);
    }
  });

  it("reports malformed messages without losing the last snapshot", () => {
    const socket = new FakeSocket();
    const received: number[] = [];
    const protocolErrors: string[] = [];
    const channel = new StateChannel(
      "ws://display.test/state",
      (snapshot) => received.push(snapshot.sequence),
      () => {},
      (message) => protocolErrors.push(message),
      () => socket,
    );

    channel.start();
    socket.open();
    socket.message(rawSnapshot(3));
    socket.message("not JSON");
    expect(received).toEqual([3]);
    expect(protocolErrors).toEqual(["display data unavailable"]);
  });

  it("cleans up its socket and pending reconnect when stopped", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const factory = vi.fn(() => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    });
    const channel = new StateChannel("ws://display.test/state", () => {}, () => {}, () => {}, factory);

    channel.start();
    channel.stop();
    vi.advanceTimersByTime(4000);
    expect(sockets[0].closed).toBe(true);
    expect(factory).toHaveBeenCalledTimes(1);
  });
});
