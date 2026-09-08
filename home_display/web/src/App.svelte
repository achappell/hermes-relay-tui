<script lang="ts">
  import { onMount } from "svelte";
  import "./styles.css";
  import WasmCanvas from "./surfaces/WasmCanvas.svelte";
  import { DisplayBridge, type DisplayAction } from "./state/bridge";
  import { loadDisplayWasm, type WasmDisplayReducer } from "./state/wasm";

  let displayReducer: WasmDisplayReducer | null = null;
  let protocolError: string | null = null;
  let dispatchAction: (action: DisplayAction) => Promise<boolean> = async () => false;

  const stateChannelUrl = () => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/state`;
  };

  onMount(() => {
    let disposed = false;
    let bridge: DisplayBridge | null = null;

    const start = async () => {
      try {
        const reducer = await loadDisplayWasm();
        if (disposed) return;

        displayReducer = reducer;
        bridge = new DisplayBridge({
          url: stateChannelUrl(),
          reducer,
          onView: () => {
            protocolError = null;
          },
          onConnectionState: () => {},
          onProtocolError: (message) => {
            protocolError = message;
          },
          onValidSnapshot: () => {
            protocolError = null;
          },
          onActionError: (error) => {
            protocolError = error === "transport_error"
              ? "Display action could not be sent"
              : "That display action is no longer available";
          },
        });
        dispatchAction = (action) => bridge?.dispatchAction(action) ?? Promise.resolve(false);
        bridge.start();
      } catch (error) {
        if (!disposed) {
          protocolError = error instanceof Error
            ? error.message
            : "Display WebAssembly is unavailable. Run scripts/build_display_wasm.sh";
        }
      }
    };
    void start();

    return () => {
      disposed = true;
      bridge?.stop();
    };
  });
</script>

{#if displayReducer !== null}
  <WasmCanvas
    reducer={displayReducer}
    {dispatchAction}
    errorMessage={protocolError}
    onRuntimeError={(message) => protocolError = message}
  />
{:else}
  <main class="wasm-bootstrap-shell" data-state={protocolError ? "error" : "connecting"}>
    <p data-bootstrap-message>{protocolError ?? "Starting the shared Hermes display…"}</p>
  </main>
{/if}
