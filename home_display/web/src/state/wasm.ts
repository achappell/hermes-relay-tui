import type { DisplayAction, DisplaySnapshot } from "./protocol";
import type {
  ActionValidationResult,
  DisplayReducer,
  DisplayView,
  SnapshotReduction,
} from "./reducer";

export type WasmArgumentType = "number" | "string";
export type WasmFunction<TResult extends number | string = number> =
  (...args: Array<number | string>) => TResult;

export interface DisplayWasmModule {
  cwrap(
    name: string,
    returnType: "number",
    argumentTypes: ReadonlyArray<WasmArgumentType>,
  ): WasmFunction<number>;
  cwrap(
    name: string,
    returnType: "string",
    argumentTypes: ReadonlyArray<WasmArgumentType>,
  ): WasmFunction<string>;
  HEAPU8: Uint8Array;
}

export type DisplayWasmModuleFactory = () => Promise<DisplayWasmModule>;
export const DISPLAY_WASM_MODULE_PATH = "/wasm/display_core.js";

export class DisplayWasmError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DisplayWasmError";
  }
}

export class DisplayWasmLoadError extends DisplayWasmError {
  readonly cause: unknown;

  constructor(cause: unknown) {
    const detail = cause instanceof Error && cause.message ? ` ${cause.message}` : "";
    super(
      `Display WebAssembly is unavailable. Run scripts/build_display_wasm.sh before starting the kiosk.${detail}`,
    );
    this.name = "DisplayWasmLoadError";
    this.cause = cause;
  }
}

export interface DisplayFramebuffer {
  /** Raw LVGL 32-bit pixels in browser memory, one pixel per four bytes. */
  data: Uint8Array;
  width: number;
  height: number;
}

const ABI_VERSION = 2;
const ACCEPTED = 0;
const STALE = 1;
const INVALID_ARGUMENT = 2;
const INVALID_SNAPSHOT = 3;
const INVALID_TRANSITION = 4;
const PROMPT_NOT_ACTIVE = 5;
const ACTION_NOT_ALLOWED = 6;
const ACTION_ID_MISMATCH = 7;
const UNKNOWN_CHOICE = 8;

const snapshotArguments: ReadonlyArray<WasmArgumentType> = [
  "number",
  "string",
  "string",
  "string",
  "string",
  "string",
  "string",
  "string",
  "string",
  "number",
  "number",
  "number",
  "number",
  "string",
  "string",
  "string",
  "string",
  "string",
  "string",
  "string",
  "string",
];

function cwrap(
  module: DisplayWasmModule,
  name: string,
  argumentTypes: ReadonlyArray<WasmArgumentType>,
): WasmFunction<number> {
  const wrapped = module.cwrap(name, "number", argumentTypes);
  if (typeof wrapped !== "function") {
    throw new DisplayWasmError(`Display WebAssembly export is missing: ${name}`);
  }
  return wrapped;
}

function cwrapString(
  module: DisplayWasmModule,
  name: string,
  argumentTypes: ReadonlyArray<WasmArgumentType>,
): WasmFunction<string> {
  const wrapped = module.cwrap(name, "string", argumentTypes);
  if (typeof wrapped !== "function") {
    throw new DisplayWasmError(`Display WebAssembly export is missing: ${name}`);
  }
  return wrapped;
}

function actionValidation(result: number): ActionValidationResult {
  switch (result) {
    case ACCEPTED:
      return "accepted";
    case INVALID_ARGUMENT:
      return "invalid_argument";
    case PROMPT_NOT_ACTIVE:
      return "prompt_not_active";
    case ACTION_NOT_ALLOWED:
      return "action_not_allowed";
    case ACTION_ID_MISMATCH:
      return "action_id_mismatch";
    case UNKNOWN_CHOICE:
      return "unknown_choice";
    default:
      return "invalid_argument";
  }
}

function validActionShape(action: DisplayAction): boolean {
  return (
    action.type === "action" &&
    action.schema === 1 &&
    typeof action.action_id === "string" &&
    action.action_id.length > 0 &&
    action.action_id.length <= 64 &&
    typeof action.choice === "string" &&
    action.choice.length > 0 &&
    action.choice.length <= 32
  );
}

export class WasmDisplayReducer implements DisplayReducer {
  private readonly module: DisplayWasmModule;
  private readonly resetC: WasmFunction;
  private readonly applySnapshotC: WasmFunction;
  private readonly validateChoiceC: WasmFunction;
  private readonly validateDismissC: WasmFunction;
  private readonly setConnectionStateC: WasmFunction;
  private readonly setPointerC: WasmFunction;
  private readonly actionPendingC: WasmFunction;
  private readonly actionIdC: WasmFunction<string>;
  private readonly actionChoiceC: WasmFunction<string>;
  private readonly actionClearC: WasmFunction;
  private readonly viewStateC: WasmFunction;
  private readonly viewSequenceC: WasmFunction;
  private readonly viewIsBusyC: WasmFunction;
  private readonly viewConnectionHealthyC: WasmFunction;
  private readonly viewCanChooseC: WasmFunction;
  private readonly viewCanDismissC: WasmFunction;
  private readonly framebufferC: WasmFunction;
  private readonly framebufferWidthC: WasmFunction;
  private readonly framebufferHeightC: WasmFunction;
  private readonly tickC: WasmFunction;
  private current: DisplayView | null = null;

  constructor(module: DisplayWasmModule) {
    this.module = module;
    const abiVersion = cwrap(module, "display_wasm_abi_version", [])();
    if (abiVersion !== ABI_VERSION) {
      throw new DisplayWasmError(
        `Unsupported display WebAssembly ABI ${abiVersion}; expected ${ABI_VERSION}`,
      );
    }

    const init = cwrap(module, "display_wasm_init", []);
    if (init() !== ACCEPTED) {
      throw new DisplayWasmError("Display WebAssembly reducer failed to initialize");
    }

    this.resetC = cwrap(module, "display_wasm_reset", []);
    this.applySnapshotC = cwrap(module, "display_wasm_apply_snapshot", snapshotArguments);
    this.validateChoiceC = cwrap(module, "display_wasm_validate_choice", ["string", "string"]);
    this.validateDismissC = cwrap(module, "display_wasm_validate_dismiss", []);
    this.setConnectionStateC = cwrap(module, "display_wasm_set_connection_state", ["number"]);
    this.setPointerC = cwrap(module, "display_wasm_set_pointer", ["number", "number", "number"]);
    this.actionPendingC = cwrap(module, "display_wasm_action_pending", []);
    this.actionIdC = cwrapString(module, "display_wasm_action_id", []);
    this.actionChoiceC = cwrapString(module, "display_wasm_action_choice", []);
    this.actionClearC = cwrap(module, "display_wasm_action_clear", []);
    this.viewStateC = cwrap(module, "display_wasm_view_state", []);
    this.viewSequenceC = cwrap(module, "display_wasm_view_sequence", []);
    this.viewIsBusyC = cwrap(module, "display_wasm_view_is_busy", []);
    this.viewConnectionHealthyC = cwrap(module, "display_wasm_view_connection_healthy", []);
    this.viewCanChooseC = cwrap(module, "display_wasm_view_can_choose", []);
    this.viewCanDismissC = cwrap(module, "display_wasm_view_can_dismiss", []);
    this.framebufferC = cwrap(module, "display_wasm_framebuffer", []);
    this.framebufferWidthC = cwrap(module, "display_wasm_framebuffer_width", []);
    this.framebufferHeightC = cwrap(module, "display_wasm_framebuffer_height", []);
    this.tickC = cwrap(module, "display_wasm_tick", ["number"]);
  }

  reset(): void {
    if (this.resetC() !== ACCEPTED) {
      throw new DisplayWasmError("Display WebAssembly reducer failed to reset");
    }
    this.current = null;
  }

  applySnapshot(snapshot: DisplaySnapshot): SnapshotReduction {
    const prompt = snapshot.prompt;
    const options = [0, 1, 2, 3].flatMap((index) => [
      prompt?.options[index]?.id ?? "",
      prompt?.options[index]?.label ?? "",
    ]);
    const result = this.applySnapshotC(
      snapshot.sequence,
      snapshot.state,
      snapshot.response_text,
      snapshot.status_text ?? "",
      snapshot.account ?? "",
      prompt?.kind ?? "",
      prompt?.title ?? "",
      prompt?.body ?? "",
      prompt?.action_id ?? "",
      prompt?.timeout_seconds ?? -1,
      prompt !== null && snapshot.capabilities?.actions.includes("prompt.choose") ? 1 : 0,
      prompt !== null && snapshot.capabilities?.actions.includes("prompt.dismiss") ? 1 : 0,
      prompt?.options.length ?? 0,
      ...options,
    );

    switch (result) {
      case ACCEPTED: {
        const view: DisplayView = {
          ...snapshot,
          is_busy: this.viewIsBusyC() !== 0,
          connection_healthy: this.viewConnectionHealthyC() !== 0,
          can_choose: this.viewCanChooseC() !== 0,
          can_dismiss: this.viewCanDismissC() !== 0,
        };
        this.current = view;
        return { kind: "accepted", view };
      }
      case STALE:
        return { kind: "stale" };
      case INVALID_TRANSITION:
        return { kind: "invalid_transition" };
      case INVALID_ARGUMENT:
      case INVALID_SNAPSHOT:
      default:
        return { kind: "invalid_snapshot" };
    }
  }

  validateAction(action: DisplayAction): ActionValidationResult {
    if (!validActionShape(action)) return "invalid_argument";
    return actionValidation(this.validateChoiceC(action.action_id, action.choice));
  }

  validateDismiss(): ActionValidationResult {
    return actionValidation(this.validateDismissC());
  }

  setConnectionState(state: "connected" | "disconnected" | "error"): void {
    const stateValue = { connected: 0, disconnected: 1, error: 2 }[state];
    if (this.setConnectionStateC(stateValue) !== ACCEPTED) {
      throw new DisplayWasmError(`Display WebAssembly rejected connection state: ${state}`);
    }
  }

  setPointer(x: number, y: number, pressed: boolean): void {
    if (this.setPointerC(x, y, pressed ? 1 : 0) !== ACCEPTED) {
      throw new DisplayWasmError("Display WebAssembly rejected pointer input");
    }
  }

  pollAction(): DisplayAction | null {
    if (this.actionPendingC() === 0) return null;

    const actionId = this.actionIdC();
    const choice = this.actionChoiceC();
    if (this.actionClearC() !== ACCEPTED) {
      throw new DisplayWasmError("Display WebAssembly failed to clear the pending action");
    }
    if (actionId.length === 0 || choice.length === 0) return null;
    return {
      type: "action",
      schema: 1,
      action_id: actionId,
      choice,
    };
  }

  framebuffer(): DisplayFramebuffer {
    const width = this.framebufferWidthC();
    const height = this.framebufferHeightC();
    const pointer = this.framebufferC();
    const byteLength = width * height * 4;
    if (
      !Number.isInteger(width) || width <= 0 ||
      !Number.isInteger(height) || height <= 0 ||
      !Number.isInteger(pointer) || pointer < 0 ||
      !Number.isSafeInteger(byteLength) || pointer + byteLength > this.module.HEAPU8.length
    ) {
      throw new DisplayWasmError("Display WebAssembly returned an invalid framebuffer");
    }
    return {
      data: this.module.HEAPU8.subarray(pointer, pointer + byteLength),
      width,
      height,
    };
  }

  tick(elapsedMs: number): void {
    if (!Number.isInteger(elapsedMs) || elapsedMs < 0 || elapsedMs > 0xffffffff) {
      throw new DisplayWasmError("Display WebAssembly received an invalid tick interval");
    }
    if (this.tickC(elapsedMs) !== ACCEPTED) {
      throw new DisplayWasmError("Display WebAssembly failed to advance LVGL");
    }
  }

  viewState(): DisplaySnapshot["state"] | null {
    const state = this.viewStateC();
    const states: DisplaySnapshot["state"][] = [
      "idle",
      "heard",
      "listening",
      "thinking",
      "speaking",
      "buffering",
      "error",
      "disconnected",
      "prompt",
    ];
    return state >= 1 && state <= states.length ? states[state - 1] : null;
  }

  viewSequence(): number {
    return this.viewSequenceC();
  }

  currentView(): DisplayView | null {
    return this.current;
  }
}

async function defaultDisplayWasmFactory(): Promise<DisplayWasmModule> {
  const imported = (await import(/* @vite-ignore */ DISPLAY_WASM_MODULE_PATH)) as {
    default?: () => Promise<DisplayWasmModule>;
  };
  if (typeof imported.default !== "function") {
    throw new DisplayWasmError("display_core.js does not export an Emscripten module factory");
  }
  return imported.default();
}

export async function loadDisplayWasm(
  factory: DisplayWasmModuleFactory = defaultDisplayWasmFactory,
): Promise<WasmDisplayReducer> {
  try {
    return new WasmDisplayReducer(await factory());
  } catch (error) {
    if (error instanceof DisplayWasmLoadError) throw error;
    throw new DisplayWasmLoadError(error);
  }
}
