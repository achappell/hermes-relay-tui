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
      { method: "POST" }
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
      { method: "POST" }
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

  it("keeps the prompt open when the bridge rejects an action", async () => {
    const onAction = vi.fn(async (_action: DisplayAction) => false);
    render(PromptOverlay, {
      props: { prompt: samplePrompt, onAction },
    });

    await fireEvent.click(screen.getByText("Set home"));

    expect(screen.getByRole("dialog")).toBeInTheDocument();
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
      { method: "POST" }
    );
  });
});
