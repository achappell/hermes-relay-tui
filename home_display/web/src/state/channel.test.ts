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

  it("stays connecting when a socket closes before it hydrates", () => {
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
    expect(states).toEqual(["connecting", "disconnected"]);
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

  it("signals valid snapshot recovery before filtering duplicate or older data", () => {
    const socket = new FakeSocket();
    const received: number[] = [];
    const protocolErrors: string[] = [];
    const recovered: number[] = [];
    const channel = new StateChannel(
      "ws://display.test/state",
      (snapshot) => received.push(snapshot.sequence),
      () => {},
      (message) => protocolErrors.push(message),
      () => socket,
      (snapshot) => recovered.push(snapshot.sequence),
    );

    channel.start();
    socket.open();
    socket.message(rawSnapshot(3));
    socket.message("not JSON");
    socket.message(rawSnapshot(3));
    socket.message(rawSnapshot(2));

    expect(protocolErrors).toEqual(["display data unavailable"]);
    expect(recovered).toEqual([3, 3, 2]);
    expect(received).toEqual([3]);
    channel.stop();
  });

  it("does not let a snapshot listener error escape the message callback", () => {
    const socket = new FakeSocket();
    const onSnapshot = vi.fn(() => {
      throw new Error("surface failed");
    });
    const channel = new StateChannel(
      "ws://display.test/state",
      onSnapshot,
      () => {},
      () => {},
      () => socket,
    );

    channel.start();
    socket.open();
    expect(() => socket.message(rawSnapshot(1))).not.toThrow();
    expect(onSnapshot).toHaveBeenCalledOnce();
    channel.stop();
  });

  it("does not let a connection-state listener error escape socket callbacks", () => {
    const socket = new FakeSocket();
    const onConnectionState = vi.fn((state: string) => {
      if (state !== "connecting") {
        throw new Error("surface failed");
      }
    });
    const channel = new StateChannel(
      "ws://display.test/state",
      () => {},
      onConnectionState,
      () => {},
      () => socket,
    );

    channel.start();
    expect(() => socket.open()).not.toThrow();
    expect(() => socket.message(rawSnapshot(1))).not.toThrow();
    expect(() => socket.closeFromServer()).not.toThrow();
    expect(onConnectionState).toHaveBeenCalledWith("connected");
    expect(onConnectionState).toHaveBeenCalledWith("disconnected");
    channel.stop();
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

  it("stopping with a pending reconnect prevents a new socket", () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const factory = vi.fn(() => {
      const socket = new FakeSocket();
      sockets.push(socket);
      return socket;
    });
    const channel = new StateChannel("ws://display.test/state", () => {}, () => {}, () => {}, factory);

    channel.start();
    sockets[0].closeFromServer();
    expect(factory).toHaveBeenCalledOnce();
    channel.stop();
    vi.advanceTimersByTime(250);
    expect(factory).toHaveBeenCalledOnce();
  });
});
