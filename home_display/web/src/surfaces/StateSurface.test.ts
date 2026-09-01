// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";
import StateSurface from "./StateSurface.svelte";

const snapshot = (state: string, response_text = "", status_text: string | null = null) => ({
  type: "snapshot" as const,
  schema: 1 as const,
  sequence: 1,
  state: state as never,
  response_text,
  status_text,
  media: null,
});

describe("StateSurface", () => {
  afterEach(cleanup);

  it.each(["idle", "listening", "thinking", "speaking", "buffering", "error", "disconnected"])(
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
