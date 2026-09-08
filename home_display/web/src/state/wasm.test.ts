import { describe, expect, it, vi } from "vitest";

import {
  DisplayWasmLoadError,
  WasmDisplayReducer,
  loadDisplayWasm,
  type DisplayWasmModule,
} from "./wasm";
import type { DisplayAction, DisplaySnapshot } from "./protocol";

const promptSnapshot: DisplaySnapshot = {
  type: "snapshot",
  schema: 1,
  sequence: 7,
  state: "prompt",
  response_text: "",
  status_text: null,
  media: null,
  prompt: {
    kind: "confirm",
    title: "Set home?",
    body: "Use this display as home?",
    options: [{ id: "yes", label: "Yes" }],
    action_id: "sethome",
    timeout_seconds: null,
  },
  capabilities: {
    actions: ["prompt.choose"],
    features: ["prompt_overlay"],
  },
};

const action: DisplayAction = {
  type: "action",
  schema: 1,
  action_id: "sethome",
  choice: "yes",
};

function fakeModule(
  overrides: Record<string, (...args: any[]) => number | string> = {},
): DisplayWasmModule {
  const functions: Record<string, (...args: any[]) => number | string> = {
    display_wasm_abi_version: () => 2,
    display_wasm_init: () => 0,
    display_wasm_reset: () => 0,
    display_wasm_apply_snapshot: () => 0,
    display_wasm_validate_choice: () => 0,
    display_wasm_validate_dismiss: () => 0,
    display_wasm_set_connection_state: () => 0,
    display_wasm_set_pointer: () => 0,
    display_wasm_action_pending: () => 0,
    display_wasm_action_id: () => "",
    display_wasm_action_choice: () => "",
    display_wasm_action_clear: () => 0,
    display_wasm_view_state: () => 9,
    display_wasm_view_sequence: () => 7,
    display_wasm_view_is_busy: () => 0,
    display_wasm_view_connection_healthy: () => 1,
    display_wasm_view_can_choose: () => 1,
    display_wasm_view_can_dismiss: () => 0,
    display_wasm_framebuffer: () => 1,
    display_wasm_framebuffer_width: () => 1024,
    display_wasm_framebuffer_height: () => 600,
    display_wasm_tick: () => 0,
    ...overrides,
  };
  const cwrap = vi.fn((name: string) => functions[name]);
  return {
    cwrap: cwrap as unknown as DisplayWasmModule["cwrap"],
    HEAPU8: new Uint8Array(1024 * 600 * 4 + 1),
  };
}

describe("WasmDisplayReducer", () => {
  it("encodes normalized prompt snapshots and reads the C view flags", () => {
    const module = fakeModule();
    const reducer = new WasmDisplayReducer(module);

    const result = reducer.applySnapshot(promptSnapshot);

    expect(result).toMatchObject({
      kind: "accepted",
      view: {
        state: "prompt",
        sequence: 7,
        is_busy: false,
        connection_healthy: true,
        can_choose: true,
        can_dismiss: false,
      },
    });
    expect(module.cwrap).toHaveBeenCalledWith(
      "display_wasm_apply_snapshot",
      "number",
      [
        "number",
        "string", // state
        "string", // response text
        "string", // status text
        "string", // account
        "string", // prompt kind
        "string", // prompt title
        "string", // prompt body
        "string", // action id
        "number", // timeout
        "number", // can choose
        "number", // can dismiss
        "number", // option count
        "string", "string", // option 0
        "string", "string", // option 1
        "string", "string", // option 2
        "string", "string", // option 3
      ],
    );
    expect(reducer.validateAction(action)).toBe("accepted");
  });

  it("maps stale and invalid transition results without replacing the last view", () => {
    const applySnapshot = vi
      .fn<(...args: any[]) => number>()
      .mockReturnValueOnce(0)
      .mockReturnValueOnce(1)
      .mockReturnValueOnce(4);
    const module = fakeModule({ display_wasm_apply_snapshot: applySnapshot });
    const reducer = new WasmDisplayReducer(module);

    expect(reducer.applySnapshot(promptSnapshot)).toMatchObject({ kind: "accepted" });
    expect(reducer.applySnapshot({ ...promptSnapshot, sequence: 6 })).toEqual({ kind: "stale" });
    expect(reducer.applySnapshot({ ...promptSnapshot, sequence: 8, state: "speaking", prompt: null })).toEqual({
      kind: "invalid_transition",
    });
  });

  it("resets the C reducer and local view together", () => {
    const reset = vi.fn(() => 0);
    const module = fakeModule({
      display_wasm_reset: reset,
      display_wasm_validate_choice: () => 5,
    });
    const reducer = new WasmDisplayReducer(module);

    reducer.applySnapshot(promptSnapshot);
    reducer.reset();

    expect(reset).toHaveBeenCalledOnce();
    expect(reducer.validateAction(action)).toBe("prompt_not_active");
  });

  it("pumps the LVGL framebuffer and turns browser pointer actions into domain actions", () => {
    const tick = vi.fn(() => 0);
    const setPointer = vi.fn(() => 0);
    const module = fakeModule({
      display_wasm_framebuffer: () => 16,
      display_wasm_framebuffer_width: () => 2,
      display_wasm_framebuffer_height: () => 1,
      display_wasm_tick: tick,
      display_wasm_set_pointer: setPointer,
      display_wasm_action_pending: () => 1,
      display_wasm_action_id: () => "sethome",
      display_wasm_action_choice: () => "yes",
    });
    module.HEAPU8.set([1, 2, 3, 4, 5, 6, 7, 8], 16);
    const reducer = new WasmDisplayReducer(module);

    reducer.tick(16);
    reducer.setPointer(200, 338, true);
    const frame = reducer.framebuffer();
    const pendingAction = reducer.pollAction();

    expect(tick).toHaveBeenCalledWith(16);
    expect(setPointer).toHaveBeenCalledWith(200, 338, 1);
    expect(frame).toEqual({
      width: 2,
      height: 1,
      data: module.HEAPU8.subarray(16, 24),
    });
    expect(pendingAction).toEqual(action);
    expect(module.cwrap).toHaveBeenCalledWith("display_wasm_action_clear", "number", []);
  });

  it("loads a reducer from an injected Emscripten module factory", async () => {
    const reducer = await loadDisplayWasm(async () => fakeModule());

    expect(reducer).toBeInstanceOf(WasmDisplayReducer);
  });

  it("turns a missing artifact into an actionable setup error", async () => {
    await expect(loadDisplayWasm(async () => {
      throw new Error("missing display_core.js");
    })).rejects.toBeInstanceOf(DisplayWasmLoadError);
    await expect(loadDisplayWasm(async () => {
      throw new Error("missing display_core.js");
    })).rejects.toThrow("scripts/build_display_wasm.sh");
  });
});
