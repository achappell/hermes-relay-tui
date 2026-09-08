<script lang="ts">
  import { onMount } from "svelte";
  import { CanvasDisplayHost } from "../state/canvas";
  import type { DisplayAction } from "../state/protocol";
  import type { WasmDisplayReducer } from "../state/wasm";

  export let reducer: WasmDisplayReducer;
  export let dispatchAction: (action: DisplayAction) => Promise<boolean> | boolean = async () => false;
  export let errorMessage: string | null = null;
  export let onRuntimeError: (message: string) => void = () => {};

  let canvas: HTMLCanvasElement;
  let hostError: string | null = null;

  onMount(() => {
    try {
      const host = new CanvasDisplayHost(canvas, reducer, {
        onAction: dispatchAction,
        onError: (error) => {
          hostError = error.message;
          onRuntimeError(error.message);
        },
      });
      host.start();
      return () => host.stop();
    } catch (error) {
      hostError = error instanceof Error
        ? error.message
        : "Display canvas failed to start";
      onRuntimeError(hostError);
    }
  });

  $: visibleError = hostError ?? errorMessage;
</script>

<main class="wasm-canvas-shell" data-state={visibleError ? "error" : "ready"}>
  <canvas
    bind:this={canvas}
    class="wasm-display-canvas"
    data-display-canvas
    aria-label="Hermes home display"
  ></canvas>
  {#if visibleError}
    <div class="wasm-canvas-error" data-canvas-error role="alert">{visibleError}</div>
  {/if}
</main>
