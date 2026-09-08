<script lang="ts">
  import { onMount } from "svelte";
  import "./styles.css";
  import WasmCanvas from "./surfaces/WasmCanvas.svelte";
  import { DisplayBridge, type DisplayAction } from "./state/bridge";
  import { createInitialDisplayView, type DisplayView } from "./state/reducer";
  import { loadDisplayWasm, type WasmDisplayReducer } from "./state/wasm";
  import {
    BrowserVoiceController,
    PcmAudioPlayer,
    type VoiceState,
  } from "./state/voice";

  let displayReducer: WasmDisplayReducer | null = null;
  let protocolError: string | null = null;
  let displayView: DisplayView = createInitialDisplayView();
  let voiceState: VoiceState = "idle";
  let voiceError: string | null = null;
  let voiceController: BrowserVoiceController | null = null;
  let audioPlayer: PcmAudioPlayer | null = null;
  let dispatchAction: (action: DisplayAction) => Promise<boolean> = async () => false;

  $: browserVoiceEnabled = displayView.capabilities?.features.includes("browser_voice") ?? false;

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
          onView: (view) => {
            displayView = view;
            protocolError = null;
            if (["heard", "listening", "thinking", "error", "disconnected"].includes(view.state)) {
              audioPlayer?.stop();
            }
            if (view.state === "idle" && voiceState === "submitting") {
              voiceController?.reset();
            }
          },
          onConnectionState: (state) => {
            if (state === "disconnected") {
              audioPlayer?.stop();
              voiceController?.reset();
            }
          },
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
          onAudioEvent: (event) => {
            if (event.type === "audio_start") {
              audioPlayer?.start(event);
            } else if (event.type === "audio_end") {
              audioPlayer?.end(event.turn_id);
            } else {
              audioPlayer?.abort(event.turn_id);
            }
          },
          onAudioChunk: (chunk) => audioPlayer?.append(chunk),
          onVoiceError: () => {
            voiceError = "Turn could not be sent";
          },
        });
        dispatchAction = (action) => bridge?.dispatchAction(action) ?? Promise.resolve(false);
        audioPlayer = new PcmAudioPlayer({
          onError: (message) => {
            voiceError = message;
            voiceState = "error";
          },
        });
        voiceController = new BrowserVoiceController({
          sendText: (text) => bridge?.sendVoiceTurn(text) ?? false,
          onState: (state) => {
            voiceState = state;
            if (state !== "error") voiceError = null;
          },
          onError: (message) => {
            voiceError = message;
          },
        });
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
      voiceController?.reset();
      audioPlayer?.stop();
      bridge?.stop();
    };
  });

  async function toggleVoice(): Promise<void> {
    if (voiceController === null || voiceState === "submitting") return;
    if (voiceState === "listening") {
      voiceController.stop();
      return;
    }
    if (displayView.is_busy) return;

    voiceError = null;
    if (audioPlayer !== null && !(await audioPlayer.resume())) return;
    await voiceController.start();
  }
</script>

{#if displayReducer !== null}
  <WasmCanvas
    reducer={displayReducer}
    {dispatchAction}
    errorMessage={protocolError}
    onRuntimeError={(message) => protocolError = message}
  />
  {#if browserVoiceEnabled}
    <section class="browser-voice-controls" data-voice-state={voiceState} aria-label="Browser voice">
      <button
        type="button"
        data-voice-button
        aria-pressed={voiceState === "listening"}
        disabled={voiceState === "submitting" || (displayView.is_busy && voiceState !== "listening")}
        on:click={toggleVoice}
      >
        {voiceState === "listening" ? "Stop listening" : "Tap to talk"}
      </button>
      {#if voiceError}
        <p data-voice-error role="alert">{voiceError}</p>
      {:else if voiceState === "listening"}
        <p data-voice-status>Listening…</p>
      {:else if voiceState === "submitting"}
        <p data-voice-status>Sending…</p>
      {/if}
    </section>
  {/if}
{:else}
  <main class="wasm-bootstrap-shell" data-state={protocolError ? "error" : "connecting"}>
    <p data-bootstrap-message>{protocolError ?? "Starting the shared Hermes display…"}</p>
  </main>
{/if}
