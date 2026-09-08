import { afterEach, describe, expect, it, vi } from "vitest";

import type { DisplayAction } from "./protocol";
import type { WasmDisplayReducer } from "./wasm";
import { CanvasDisplayHost, DISPLAY_HEIGHT, DISPLAY_WIDTH } from "./canvas";

type Listener = (event: PointerEvent | Event) => void;

function fakeCanvas(rect: { left: number; top: number; width: number; height: number }) {
  const listeners = new Map<string, Listener>();
  const context = {
    clearRect: vi.fn(),
    drawImage: vi.fn(),
    imageSmoothingEnabled: true,
    putImageData: vi.fn(),
  };
  const canvas = {
    height: 0,
    width: 0,
    style: {
      aspectRatio: "",
      display: "",
      height: "",
      imageRendering: "",
      touchAction: "",
      width: "",
    },
    addEventListener: vi.fn((type: string, listener: Listener) => listeners.set(type, listener)),
    getBoundingClientRect: vi.fn(() => rect),
    getContext: vi.fn(() => context),
    releasePointerCapture: vi.fn(),
    removeEventListener: vi.fn((type: string) => listeners.delete(type)),
    setPointerCapture: vi.fn(),
  } as unknown as HTMLCanvasElement;
  return { canvas, context, listeners };
}

function fakeReducer(action: DisplayAction | null = null) {
  const frame = new Uint8Array(DISPLAY_WIDTH * DISPLAY_HEIGHT * 4);
  frame.set([1, 2, 3, 4, 5, 6, 7, 8]);
  return {
    reducer: {
      framebuffer: vi.fn(() => ({ data: frame, width: DISPLAY_WIDTH, height: DISPLAY_HEIGHT })),
      pollAction: vi.fn(() => action),
      setPointer: vi.fn(),
      tick: vi.fn(),
    } as unknown as WasmDisplayReducer,
    frame,
  };
}

describe("CanvasDisplayHost", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders RGBA pixels, pumps LVGL, dispatches its action, and maps pointer input", () => {
    const { canvas, context, listeners } = fakeCanvas({
      left: 100,
      top: 50,
      width: 512,
      height: 300,
    });
    const action: DisplayAction = {
      type: "action",
      schema: 1,
      action_id: "sethome",
      choice: "yes",
    };
    const { reducer } = fakeReducer(action);
    let callback: ((timestamp: number) => void) | undefined;
    const requestFrame = vi.fn((next: (timestamp: number) => void) => {
      callback = next;
      return 41;
    });
    const cancelFrame = vi.fn();
    const imageDataFactory = vi.fn((data: Uint8ClampedArray, width: number, height: number) => ({
      data,
      width,
      height,
    }));
    const onAction = vi.fn();
    const host = new CanvasDisplayHost(canvas, reducer, {
      cancelAnimationFrame: cancelFrame,
      imageDataFactory,
      now: () => 100,
      onAction,
      requestAnimationFrame: requestFrame,
    });

    host.start();
    if (callback !== undefined) callback(116);

    expect(canvas.width).toBe(DISPLAY_WIDTH);
    expect(canvas.height).toBe(DISPLAY_HEIGHT);
    expect(reducer.tick).toHaveBeenCalledWith(16);
    expect(imageDataFactory).toHaveBeenCalledWith(expect.any(Uint8ClampedArray), DISPLAY_WIDTH, DISPLAY_HEIGHT);
    expect(context.putImageData).toHaveBeenCalledWith(expect.anything(), 0, 0);
    const imageData = (context.putImageData as ReturnType<typeof vi.fn>).mock.calls[0][0] as {
      data: Uint8ClampedArray;
    };
    expect(Array.from(imageData.data.slice(0, 8))).toEqual([3, 2, 1, 4, 7, 6, 5, 8]);
    expect(onAction).toHaveBeenCalledWith(action);

    const pointerDown = listeners.get("pointerdown");
    const pointerUp = listeners.get("pointerup");
    const preventDefault = vi.fn();
    pointerDown?.({ clientX: 356, clientY: 200, pointerId: 9, preventDefault } as unknown as PointerEvent);
    pointerUp?.({ clientX: 356, clientY: 200, pointerId: 9, preventDefault } as unknown as PointerEvent);

    expect(reducer.setPointer).toHaveBeenNthCalledWith(1, 512, 300, true);
    expect(reducer.setPointer).toHaveBeenNthCalledWith(2, 512, 300, false);
    expect(canvas.setPointerCapture).toHaveBeenCalledWith(9);
    expect(canvas.releasePointerCapture).toHaveBeenCalledWith(9);
    expect(preventDefault).toHaveBeenCalledTimes(2);

    host.stop();
    expect(cancelFrame).toHaveBeenCalledWith(41);
  });

  it("uses a high-DPI backing canvas while keeping touch coordinates logical", () => {
    const { canvas, context, listeners } = fakeCanvas({
      left: 0,
      top: 0,
      width: DISPLAY_WIDTH,
      height: DISPLAY_HEIGHT,
    });
    const staging = fakeCanvas({ left: 0, top: 0, width: DISPLAY_WIDTH, height: DISPLAY_HEIGHT });
    const { reducer } = fakeReducer();
    const onError = vi.fn();
    let callback: ((timestamp: number) => void) | undefined;
    const host = new CanvasDisplayHost(canvas, reducer, {
      createStagingCanvas: () => staging.canvas,
      getDevicePixelRatio: () => 2,
      imageDataFactory: (data, width, height) => ({ data, width, height }),
      now: () => 0,
      onAction: () => {},
      onError,
      requestAnimationFrame: (next) => {
        callback = next;
        return 1;
      },
    });

    host.start();
    if (callback !== undefined) callback(1);

    expect(canvas.width).toBe(DISPLAY_WIDTH * 2);
    expect(canvas.height).toBe(DISPLAY_HEIGHT * 2);
    expect(onError).not.toHaveBeenCalled();
    expect(staging.context.putImageData).toHaveBeenCalledOnce();
    expect(context.drawImage).toHaveBeenCalledWith(staging.canvas, 0, 0, DISPLAY_WIDTH * 2, DISPLAY_HEIGHT * 2);

    const preventDefault = vi.fn();
    listeners.get("pointerdown")?.({
      clientX: DISPLAY_WIDTH / 2,
      clientY: DISPLAY_HEIGHT / 2,
      pointerId: 1,
      preventDefault,
    } as unknown as PointerEvent);
    expect(reducer.setPointer).toHaveBeenCalledWith(DISPLAY_WIDTH / 2, DISPLAY_HEIGHT / 2, true);
    host.stop();
  });
});
