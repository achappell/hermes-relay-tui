import type { DisplayAction } from "./protocol";
import type { WasmDisplayReducer } from "./wasm";

export const DISPLAY_WIDTH = 1024;
export const DISPLAY_HEIGHT = 600;

interface CanvasImageData {
  data: Uint8ClampedArray;
  width: number;
  height: number;
}

interface CanvasContext {
  clearRect(x: number, y: number, width: number, height: number): void;
  drawImage(image: HTMLCanvasElement, x: number, y: number, width: number, height: number): void;
  imageSmoothingEnabled: boolean;
  putImageData(imageData: CanvasImageData, x: number, y: number): void;
}

type FrameCallback = (timestamp: number) => void;

export interface CanvasDisplayHostOptions {
  cancelAnimationFrame?: (handle: number) => void;
  createStagingCanvas?: (width: number, height: number) => HTMLCanvasElement;
  getDevicePixelRatio?: () => number;
  imageDataFactory?: (data: Uint8ClampedArray, width: number, height: number) => CanvasImageData;
  now?: () => number;
  onAction: (action: DisplayAction) => Promise<boolean> | boolean | void;
  onError?: (error: Error) => void;
  requestAnimationFrame?: (callback: FrameCallback) => number;
}

const defaultImageDataFactory = (
  data: Uint8ClampedArray,
  width: number,
  height: number,
): CanvasImageData => new ImageData(data as unknown as ImageDataArray, width, height);

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error("Display canvas runtime failed");
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

/** Hosts the shared LVGL framebuffer in a browser and feeds its pointer port. */
export class CanvasDisplayHost {
  private readonly context: CanvasContext;
  private readonly imageDataFactory: NonNullable<CanvasDisplayHostOptions["imageDataFactory"]>;
  private readonly requestFrame: (callback: FrameCallback) => number;
  private readonly cancelFrame: (handle: number) => void;
  private readonly now: () => number;
  private stagingCanvas: HTMLCanvasElement | null = null;
  private stagingContext: CanvasContext | null = null;
  private frameHandle: number | null = null;
  private lastTimestamp: number | null = null;
  private running = false;
  private pointerId: number | null = null;

  private readonly renderFrame = (timestamp: number): void => {
    if (!this.running) return;

    const elapsed = this.lastTimestamp === null
      ? 0
      : clamp(Math.round(timestamp - this.lastTimestamp), 0, 250);
    this.lastTimestamp = timestamp;

    try {
      this.reducer.tick(elapsed);
      this.drawFrame();
      const action = this.reducer.pollAction();
      if (action !== null) {
        const result = this.options.onAction(action);
        if (result !== null && typeof result === "object" && "then" in result) {
          void Promise.resolve(result).catch((error: unknown) => this.report(error));
        }
      }
    } catch (error) {
      this.stop();
      this.report(error);
      return;
    }

    this.frameHandle = this.requestFrame(this.renderFrame);
  };

  private readonly handleResize = (): void => {
    try {
      this.resizeCanvas();
    } catch (error) {
      this.stop();
      this.report(error);
    }
  };

  private readonly handlePointerDown = (event: PointerEvent): void => {
    event.preventDefault();
    this.pointerId = event.pointerId;
    this.canvas.setPointerCapture?.(event.pointerId);
    this.setPointer(event, true);
  };

  private readonly handlePointerMove = (event: PointerEvent): void => {
    if (event.pointerId !== this.pointerId) return;
    event.preventDefault();
    this.setPointer(event, true);
  };

  private readonly handlePointerUp = (event: PointerEvent): void => {
    if (event.pointerId !== this.pointerId) return;
    event.preventDefault();
    this.setPointer(event, false);
    this.canvas.releasePointerCapture?.(event.pointerId);
    this.pointerId = null;
  };

  private readonly handlePointerCancel = (event: PointerEvent): void => {
    if (event.pointerId !== this.pointerId) return;
    event.preventDefault();
    this.setPointer(event, false);
    this.canvas.releasePointerCapture?.(event.pointerId);
    this.pointerId = null;
  };

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly reducer: WasmDisplayReducer,
    private readonly options: CanvasDisplayHostOptions,
  ) {
    const context = canvas.getContext("2d") as CanvasContext | null;
    if (context === null) {
      throw new Error("Display canvas cannot create a 2D rendering context");
    }
    this.context = context;
    this.imageDataFactory = options.imageDataFactory ?? defaultImageDataFactory;
    this.now = options.now ?? (() => performance.now());
    this.requestFrame = options.requestAnimationFrame ?? ((callback) => {
      if (typeof window === "undefined") {
        throw new Error("Display canvas animation is unavailable outside a browser");
      }
      return window.requestAnimationFrame(callback);
    });
    this.cancelFrame = options.cancelAnimationFrame ?? ((handle) => {
      if (typeof window !== "undefined") window.cancelAnimationFrame(handle);
    });
  }

  start(): void {
    if (this.running) return;
    this.resizeCanvas();
    this.canvas.addEventListener("pointerdown", this.handlePointerDown);
    this.canvas.addEventListener("pointermove", this.handlePointerMove);
    this.canvas.addEventListener("pointerup", this.handlePointerUp);
    this.canvas.addEventListener("pointercancel", this.handlePointerCancel);
    window.addEventListener("resize", this.handleResize);
    this.running = true;
    this.lastTimestamp = this.now();
    this.frameHandle = this.requestFrame(this.renderFrame);
  }

  stop(): void {
    if (!this.running) return;
    this.running = false;
    if (this.frameHandle !== null) {
      this.cancelFrame(this.frameHandle);
      this.frameHandle = null;
    }
    this.canvas.removeEventListener("pointerdown", this.handlePointerDown);
    this.canvas.removeEventListener("pointermove", this.handlePointerMove);
    this.canvas.removeEventListener("pointerup", this.handlePointerUp);
    this.canvas.removeEventListener("pointercancel", this.handlePointerCancel);
    window.removeEventListener("resize", this.handleResize);
    this.pointerId = null;
  }

  private resizeCanvas(): void {
    const rawPixelRatio = this.options.getDevicePixelRatio?.() ?? window.devicePixelRatio ?? 1;
    const pixelRatio = clamp(Number.isFinite(rawPixelRatio) ? rawPixelRatio : 1, 1, 3);
    this.canvas.width = Math.round(DISPLAY_WIDTH * pixelRatio);
    this.canvas.height = Math.round(DISPLAY_HEIGHT * pixelRatio);
    this.canvas.style.aspectRatio = `${DISPLAY_WIDTH} / ${DISPLAY_HEIGHT}`;
    this.canvas.style.display = "block";
    this.canvas.style.height = "auto";
    this.canvas.style.imageRendering = "auto";
    this.canvas.style.touchAction = "none";
    this.canvas.style.width = "100%";
    this.context.imageSmoothingEnabled = false;

    if (pixelRatio > 1) {
      if (this.stagingCanvas === null) {
        const createCanvas = this.options.createStagingCanvas ?? ((width: number, height: number) => {
          const stagingCanvas = document.createElement("canvas");
          stagingCanvas.width = width;
          stagingCanvas.height = height;
          return stagingCanvas;
        });
        this.stagingCanvas = createCanvas(DISPLAY_WIDTH, DISPLAY_HEIGHT);
        this.stagingCanvas.width = DISPLAY_WIDTH;
        this.stagingCanvas.height = DISPLAY_HEIGHT;
        this.stagingContext = this.stagingCanvas.getContext("2d") as CanvasContext | null;
        if (this.stagingContext === null) {
          throw new Error("Display canvas cannot create its high-DPI staging context");
        }
        this.stagingContext.imageSmoothingEnabled = false;
      }
    }
  }

  private drawFrame(): void {
    const frame = this.reducer.framebuffer();
    if (frame.width !== DISPLAY_WIDTH || frame.height !== DISPLAY_HEIGHT) {
      throw new Error(`Display WebAssembly framebuffer must be ${DISPLAY_WIDTH}x${DISPLAY_HEIGHT}`);
    }

    // LVGL's 32-bit color struct is laid out B, G, R, A in the little-endian
    // WebAssembly memory. ImageData requires the browser's R, G, B, A order.
    const rgba = new Uint8ClampedArray(frame.data.length);
    for (let offset = 0; offset < frame.data.length; offset += 4) {
      rgba[offset] = frame.data[offset + 2];
      rgba[offset + 1] = frame.data[offset + 1];
      rgba[offset + 2] = frame.data[offset];
      rgba[offset + 3] = frame.data[offset + 3];
    }
    const imageData = this.imageDataFactory(rgba, frame.width, frame.height);

    if (this.stagingCanvas !== null && this.stagingContext !== null) {
      this.stagingContext.putImageData(imageData, 0, 0);
      this.context.clearRect(0, 0, this.canvas.width, this.canvas.height);
      this.context.drawImage(this.stagingCanvas, 0, 0, this.canvas.width, this.canvas.height);
    } else {
      this.context.putImageData(imageData, 0, 0);
    }
  }

  private setPointer(event: PointerEvent, pressed: boolean): void {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const x = clamp(
      Math.round(((event.clientX - rect.left) / rect.width) * DISPLAY_WIDTH),
      0,
      DISPLAY_WIDTH - 1,
    );
    const y = clamp(
      Math.round(((event.clientY - rect.top) / rect.height) * DISPLAY_HEIGHT),
      0,
      DISPLAY_HEIGHT - 1,
    );
    try {
      this.reducer.setPointer(x, y, pressed);
    } catch (error) {
      this.report(error);
    }
  }

  private report(error: unknown): void {
    this.options.onError?.(asError(error));
  }
}
