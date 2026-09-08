// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/svelte";
import { tick } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DisplayAction } from "../state/protocol";
import type { WasmDisplayReducer } from "../state/wasm";

const canvasHosts = vi.hoisted(() => ({
  instances: [] as Array<{ start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> }>,
  startError: null as Error | null,
}));

vi.mock("../state/canvas", () => ({
  CanvasDisplayHost: class {
    start = vi.fn(() => {
      if (canvasHosts.startError !== null) throw canvasHosts.startError;
    });
    stop = vi.fn();

    constructor() {
      canvasHosts.instances.push(this);
    }
  },
}));

import WasmCanvas from "./WasmCanvas.svelte";

describe("WasmCanvas", () => {
  afterEach(() => {
    canvasHosts.instances.length = 0;
    canvasHosts.startError = null;
  });

  it("hosts the shared display canvas and tears down its animation loop", () => {
    const reducer = {} as WasmDisplayReducer;
    const dispatchAction = vi.fn(async (_action: DisplayAction) => true);
    const { container, unmount } = render(WasmCanvas, {
      props: { reducer, dispatchAction },
    });

    expect(container.querySelector("[data-display-canvas]")).not.toBeNull();
    expect(canvasHosts.instances).toHaveLength(1);
    expect(canvasHosts.instances[0].start).toHaveBeenCalledOnce();

    unmount();
    expect(canvasHosts.instances[0].stop).toHaveBeenCalledOnce();
  });

  it("keeps a transport error visible over the canvas", () => {
    const { container } = render(WasmCanvas, {
      props: {
        reducer: {} as WasmDisplayReducer,
        dispatchAction: async () => false,
        errorMessage: "Display action could not be sent",
      },
    });

    expect(container.querySelector("[data-canvas-error]")).toHaveTextContent(
      "Display action could not be sent",
    );
  });

  it("surfaces a canvas startup failure instead of leaving a blank kiosk", async () => {
    canvasHosts.startError = new Error("Display canvas cannot create a 2D rendering context");
    const onRuntimeError = vi.fn();
    const { container } = render(WasmCanvas, {
      props: {
        reducer: {} as WasmDisplayReducer,
        dispatchAction: async () => false,
        onRuntimeError,
      },
    });
    await tick();

    expect(container.querySelector("[data-canvas-error]")).toHaveTextContent(
      "Display canvas cannot create a 2D rendering context",
    );
    expect(onRuntimeError).toHaveBeenCalledWith(
      "Display canvas cannot create a 2D rendering context",
    );
  });
});
