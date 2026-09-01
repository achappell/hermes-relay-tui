// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";
import StateSurface from "./StateSurface.svelte";

const snapshot = (state: string, response_text = "") => ({
  type: "snapshot" as const,
  schema: 1 as const,
  sequence: 1,
  state: state as never,
  response_text,
  status_text: null,
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

    expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
    expect(screen.queryByText("stale response")).not.toBeInTheDocument();
  });
});
