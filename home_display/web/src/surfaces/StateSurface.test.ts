// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import StateSurface from "./StateSurface.svelte";
import { StateChannel, type ConnectionState, type WebSocketLike } from "../state/channel";
import type { DisplaySnapshot } from "../state/protocol";

const snapshot = (state: string, response_text = "", status_text: string | null = null) => ({
  type: "snapshot" as const,
  schema: 1 as const,
  sequence: 1,
  state: state as never,
  response_text,
  status_text,
  media: null,
});

class FakeSocket implements WebSocketLike {
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;

  close(): void {}

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

const rawSnapshot = (sequence: number, responseText: string) => JSON.stringify({
  ...snapshot("speaking", responseText),
  sequence,
});

describe("StateSurface", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it.each(["idle", "heard", "listening", "thinking", "speaking", "buffering", "error", "disconnected"])(
    "renders data-state for %s",
    (state) => {
      const { container } = render(StateSurface, {
        props: { snapshot: snapshot(state), connectionState: "connected" },
      });

      expect(container.querySelector(`[data-state="${state}"]`)).not.toBeNull();
    },
  );

  it("keeps streamed response text in one DOM region", async () => {
    const { container, rerender } = render(StateSurface, {
      props: { snapshot: snapshot("speaking", "one"), connectionState: "connected" },
    });
    const response = container.querySelector("[data-response-text]");

    await rerender({
      snapshot: snapshot("speaking", "one stable block"),
      connectionState: "connected",
    });

    expect(container.querySelector("[data-response-text]")).toBe(response);
    expect(response).toHaveTextContent("one stable block");
  });

  it("shows disconnected when the channel is down", () => {
    render(StateSurface, {
      props: { snapshot: snapshot("speaking", "stale response"), connectionState: "disconnected" },
    });

    expect(screen.getByText("Display disconnected — check the host connection")).toBeInTheDocument();
    expect(screen.queryByText("stale response")).not.toBeInTheDocument();
  });

  it("hides stale speaking content while the channel is reconnecting", () => {
    const { container } = render(StateSurface, {
      props: { snapshot: snapshot("speaking", "stale response"), connectionState: "connecting" },
    });

    expect(container.querySelector('[data-state="disconnected"]')).not.toBeNull();
    expect(screen.getByText("Display disconnected — check the host connection")).toBeInTheDocument();
    expect(screen.queryByText("stale response")).not.toBeInTheDocument();
  });

  it("waits for a reopened socket to hydrate before replacing the disconnected fallback", async () => {
    vi.useFakeTimers();
    const sockets: FakeSocket[] = [];
    const connectionStates: ConnectionState[] = [];
    let currentSnapshot: DisplaySnapshot = snapshot("idle");
    let connectionState: ConnectionState = "connecting";
    const { container, rerender } = render(StateSurface, {
      props: { snapshot: currentSnapshot, connectionState },
    });
    const channel = new StateChannel(
      "ws://display.test/state",
      (nextSnapshot) => {
        currentSnapshot = nextSnapshot;
      },
      (nextConnectionState) => {
        connectionState = nextConnectionState;
        connectionStates.push(nextConnectionState);
      },
      () => {},
      () => {
        const socket = new FakeSocket();
        sockets.push(socket);
        return socket;
      },
    );

    channel.start();
    sockets[0].open();
    sockets[0].message(rawSnapshot(1, "stale speaking response"));
    await rerender({ snapshot: currentSnapshot, connectionState });
    expect(container.querySelector('[data-state="speaking"]')).not.toBeNull();

    connectionStates.length = 0;
    sockets[0].closeFromServer();
    vi.advanceTimersByTime(250);
    sockets[1].open();
    await rerender({ snapshot: currentSnapshot, connectionState });

    expect(connectionStates).toEqual(["disconnected", "connecting"]);
    expect(container.querySelector('[data-state="disconnected"]')).not.toBeNull();
    expect(screen.getByText("Display disconnected — check the host connection")).toBeInTheDocument();
    expect(screen.queryByText("stale speaking response")).not.toBeInTheDocument();

    sockets[1].message(rawSnapshot(2, "fresh speaking response"));
    await rerender({ snapshot: currentSnapshot, connectionState });

    expect(connectionStates).toEqual(["disconnected", "connecting", "connected"]);
    expect(container.querySelector('[data-state="speaking"]')).not.toBeNull();
    expect(screen.getByText("fresh speaking response")).toBeInTheDocument();
    channel.stop();
  });

  it("shows a safe error surface and clears stale response text for protocol errors", () => {
    const { container } = render(StateSurface, {
      props: {
        snapshot: snapshot("speaking", "stale response"),
        connectionState: "connected",
        protocolError: "display data unavailable",
      },
    });

    expect(container.querySelector('[data-state="error"]')).not.toBeNull();
    expect(screen.getByText("display data unavailable")).toBeInTheDocument();
    expect(screen.queryByText("stale response")).not.toBeInTheDocument();
    expect(container.querySelector("[data-response-text]")).toHaveTextContent("");
  });

  it.each([
    ["buffering", "Still working — please wait"],
    ["error", "Something needs attention — try again"],
    ["disconnected", "Display disconnected — check the host connection"],
  ])("uses an actionable fallback for %s without server status text", (state, expected) => {
    render(StateSurface, {
      props: { snapshot: snapshot(state), connectionState: "connected" },
    });

    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("preserves server-provided status text", () => {
    render(StateSurface, {
      props: { snapshot: snapshot("buffering", "", "The response is catching up"), connectionState: "connected" },
    });

    expect(screen.getByText("The response is catching up")).toBeInTheDocument();
    expect(screen.queryByText("Still working — please wait")).not.toBeInTheDocument();
  });
});

describe("StateSurface acknowledgement (HOME-10)", () => {
  afterEach(cleanup);

  it("names the moment the wake phrase lands", () => {
    // The label and the status line both say it, exactly as they do for
    // "Listening" — so assert on the elements rather than on the text.
    const { container } = render(StateSurface, {
      props: { snapshot: snapshot("heard", "", "Heard you"), connectionState: "connected" },
    });

    expect(container.querySelector(".state-label")?.textContent).toBe("Heard you");
    expect(container.querySelector(".status-text")?.textContent?.trim()).toBe("Heard you");
  });

  it("does not claim to be listening before the microphone is open", () => {
    const { container } = render(StateSurface, {
      props: { snapshot: snapshot("heard"), connectionState: "connected" },
    });

    expect(container.querySelector('[data-state="heard"]')).not.toBeNull();
    expect(container.querySelector('[data-state="listening"]')).toBeNull();
  });

  it("shows a sign of life across the silence before the answer", () => {
    const { container } = render(StateSurface, {
      props: { snapshot: snapshot("thinking", "", "Thinking"), connectionState: "connected" },
    });

    expect(container.querySelector("[data-working-dot]")).not.toBeNull();
  });

  it("keeps the sign of life up while audio is buffering", () => {
    const { container } = render(StateSurface, {
      props: { snapshot: snapshot("buffering", "", "Buffering"), connectionState: "connected" },
    });

    expect(container.querySelector("[data-working-dot]")).not.toBeNull();
  });

  it("never shows the working indicator over a spoken answer", () => {
    const { container } = render(StateSurface, {
      props: {
        snapshot: snapshot("speaking", "Sunny and warm.", "Speaking"),
        connectionState: "connected",
      },
    });

    expect(container.querySelector("[data-working-dot]")).toBeNull();
  });
});
