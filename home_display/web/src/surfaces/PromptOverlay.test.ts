// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PromptOverlay from "./PromptOverlay.svelte";
import type { DisplayAction, DisplayPrompt } from "../state/protocol";

const samplePrompt: DisplayPrompt = {
  kind: "notice",
  title: "Setup needed",
  body: "Set this display as the home channel?",
  options: [
    { id: "yes", label: "Set home" },
    { id: "no", label: "Skip" },
  ],
  action_id: "sethome",
  timeout_seconds: 30,
};

describe("PromptOverlay", () => {
  let fetchSpy: any;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(() =>
      Promise.resolve(new Response("{}", { status: 200 }))
    );
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders title, body, and options", () => {
    render(PromptOverlay, {
      props: { prompt: samplePrompt, account: "Spark" },
    });

    expect(screen.getByText("Spark")).toBeInTheDocument();
    expect(screen.getByText("Setup needed")).toBeInTheDocument();
    expect(screen.getByText("Set this display as the home channel?")).toBeInTheDocument();
    expect(screen.getByText("Set home")).toBeInTheDocument();
    expect(screen.getByText("Skip")).toBeInTheDocument();
  });

  it("posts to /action when an option button is clicked", async () => {
    render(PromptOverlay, {
      props: { prompt: samplePrompt },
    });

    const button = screen.getByText("Set home");
    await fireEvent.click(button);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/action?action_id=sethome&choice=yes",
      expect.objectContaining({
        method: "POST",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("posts second option on click", async () => {
    render(PromptOverlay, {
      props: { prompt: samplePrompt },
    });

    const button = screen.getByText("Skip");
    await fireEvent.click(button);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/action?action_id=sethome&choice=no",
      expect.objectContaining({
        method: "POST",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("emits a normalized domain action through the bridge handler", async () => {
    const onAction = vi.fn(async (_action: DisplayAction) => true);
    render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    await fireEvent.click(screen.getByText("Set home"));

    expect(onAction).toHaveBeenCalledWith({
      type: "action",
      schema: 1,
      action_id: "sethome",
      choice: "yes",
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("dismisses only after the bridge accepts the action", async () => {
    const onAction = vi.fn(async (_action: DisplayAction) => true);
    const { container } = render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    await fireEvent.click(screen.getByText("Set home"));

    expect(container.querySelector(".prompt-overlay")).toBeNull();
    expect(onAction).toHaveBeenCalledOnce();
  });

  it("keeps the prompt open when the bridge rejects an action", async () => {
    const onAction = vi.fn(async (_action: DisplayAction) => false);
    render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    await fireEvent.click(screen.getByText("Set home"));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Display action could not be sent");
    expect(onAction).toHaveBeenCalledOnce();
  });

  it("auto-dismisses with default choice after timeout", () => {
    vi.useFakeTimers();

    render(PromptOverlay, {
      props: { prompt: samplePrompt },
    });

    vi.advanceTimersByTime(30000);

    expect(fetchSpy).toHaveBeenCalledWith(
      "/action?action_id=sethome&choice=yes",
      expect.objectContaining({
        method: "POST",
        signal: expect.any(AbortSignal),
      }),
    );
  });

  it("does not dispatch a timed action after the overlay is unmounted", () => {
    vi.useFakeTimers();
    const onAction = vi.fn();
    const { unmount } = render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    unmount();
    vi.advanceTimersByTime(30000);

    expect(onAction).not.toHaveBeenCalled();
  });

  it("does not fire an oversized prompt timeout immediately", () => {
    vi.useFakeTimers();
    const onAction = vi.fn();
    const { unmount } = render(PromptOverlay, {
      props: {
        prompt: { ...samplePrompt, timeout_seconds: 2_147_483.648 },
        onAction,
      },
    });

    vi.advanceTimersByTime(1);

    expect(onAction).not.toHaveBeenCalled();
    unmount();
  });

  it("does not restart the timeout for an identical republished prompt", async () => {
    vi.useFakeTimers();
    const onAction = vi.fn();
    const { rerender, unmount } = render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    vi.advanceTimersByTime(29999);
    await rerender({ prompt: { ...samplePrompt }, onAction });
    vi.advanceTimersByTime(1);

    expect(onAction).toHaveBeenCalledOnce();
    unmount();
  });

  it("shows a safe error when an action transport hangs", async () => {
    vi.useFakeTimers();
    const onAction = vi.fn(() => new Promise<boolean>(() => {}));
    render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    await fireEvent.click(screen.getByText("Set home"));
    await vi.advanceTimersByTimeAsync(10000);

    expect(screen.getByRole("alert")).toHaveTextContent("Display action could not be sent");
    expect(screen.getByText("Set home")).not.toBeDisabled();
  });
});
