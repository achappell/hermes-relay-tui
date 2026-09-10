<script lang="ts">
  import { onMount } from "svelte";
  import "./styles.css";
  import PromptOverlay from "./surfaces/PromptOverlay.svelte";
  import StateSurface from "./surfaces/StateSurface.svelte";
  import { DisplayBridge, type DisplayAction } from "./state/bridge";
  import type { ConnectionState } from "./state/channel";
  import { createInitialDisplayView, type DisplayView } from "./state/reducer";
  import {
    BrowserHandsFreeController,
    BrowserVoiceController,
    PcmAudioPlayer,
    type HandsFreeState,
    type VoiceState,
  } from "./state/voice";

  let protocolError: string | null = null;
  let displayView: DisplayView = createInitialDisplayView();
  let connectionState: ConnectionState = "connecting";
  let voiceState: VoiceState = "idle";
  let voiceError: string | null = null;
  let handsFreeState: HandsFreeState = "off";
  let handsFreeError: string | null = null;
  let voiceController: BrowserVoiceController | null = null;
  let handsFreeController: BrowserHandsFreeController | null = null;
  let audioPlayer: PcmAudioPlayer | null = null;
  let dispatchAction: (action: DisplayAction) => Promise<boolean> = async () => false;
  let responseHasAudio = false;
  let playbackFinished = false;
  let pendingAudioTurnId: string | null = null;

  $: browserVoiceEnabled = displayView.capabilities?.features.includes("browser_voice") ?? false;
  $: browserHandsFreeEnabled = displayView.capabilities?.features.includes("browser_hands_free") ?? false;
  $: handsFreeArmed = handsFreeState !== "off" && handsFreeState !== "error";
  $: displayReady = protocolError === null && connectionState === "connected"
    && displayView.state === "idle" && displayView.connection_healthy && !displayView.is_busy;
  $: wakePhraseLabel = displayView.capabilities?.wake_phrases?.join(" or ") ?? "the wake phrase";
  $: promptVisible = protocolError === null && connectionState === "connected"
    && displayView.state === "prompt" && displayView.prompt !== null && displayView.can_choose;
  $: promptKey = displayView.prompt === null ? "" : JSON.stringify(displayView.prompt);

  function isDisplayReady(): boolean {
    return protocolError === null && connectionState === "connected" && displayView.state === "idle"
      && displayView.connection_healthy && !displayView.is_busy;
  }

  const stateChannelUrl = () => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/state`;
  };

  onMount(() => {
    let bridge: DisplayBridge | null = null;

    bridge = new DisplayBridge({
      url: stateChannelUrl(),
      onView: (view) => {
        displayView = view;
        protocolError = null;
        handsFreeController?.configure({
          wakePhrases: view.capabilities?.wake_phrases ?? [],
          wakeListenSeconds: view.capabilities?.wake_listen_seconds,
          followUpSeconds: view.capabilities?.wake_followup_seconds,
        });
        if (
          view.state === "prompt" ||
          (view.state !== "idle" &&
            view.state !== "error" &&
            view.state !== "disconnected" &&
            handsFreeController?.state !== "submitting")
        ) {
          handsFreeController?.abort("Display is busy — hands-free is off");
        }
        if (["heard", "listening", "thinking", "error", "disconnected", "prompt"].includes(view.state)) {
          resetPlayback();
        }
        if (voiceState === "listening" && view.state !== "idle") {
          voiceController?.reset();
        }
        if (view.state === "error") {
          voiceController?.reset();
          handsFreeController?.abort(view.status_text ?? "Turn could not be completed");
        } else if (view.state === "disconnected") {
          voiceController?.reset();
          handsFreeController?.abort("Display disconnected — hands-free is off");
        } else if (view.state === "idle") {
          if (voiceState === "submitting") voiceController?.reset();
          maybeCompleteHandsFreeTurn();
        }
      },
      onConnectionState: (state) => {
        connectionState = state;
        if (state === "disconnected") {
          resetPlayback();
          voiceController?.reset();
          handsFreeController?.abort("Display disconnected — hands-free is off");
        } else if (state === "connecting") {
          handsFreeController?.abort("Display disconnected — hands-free is off");
        }
      },
      onProtocolError: (message) => {
        protocolError = message;
        resetPlayback();
        voiceController?.reset();
        handsFreeController?.abort("Display data unavailable — hands-free is off");
      },
      onAudioEvent: (event) => {
        if (event.type === "audio_start") {
          responseHasAudio = true;
          playbackFinished = false;
          pendingAudioTurnId = event.turn_id;
          audioPlayer?.start(event);
        } else if (event.type === "audio_end") {
          audioPlayer?.end(event.turn_id);
          if (pendingAudioTurnId === event.turn_id && !audioPlayer?.hasPendingPlayback) {
            playbackFinished = true;
          }
          maybeCompleteHandsFreeTurn();
        } else {
          audioPlayer?.abort(event.turn_id);
          if (pendingAudioTurnId === event.turn_id) {
            playbackFinished = true;
            handsFreeController?.abort("Response interrupted — hands-free is off");
          }
        }
      },
      onAudioChunk: (chunk) => audioPlayer?.append(chunk),
      onVoiceError: () => {
        voiceError = "Turn could not be sent";
        voiceState = "error";
      },
    });
    dispatchAction = (action) => {
      if (
        connectionState !== "connected" ||
        displayView.state !== "prompt" ||
        !displayView.can_choose
      ) {
        return Promise.resolve(false);
      }
      return bridge?.dispatchAction(action) ?? Promise.resolve(false);
    };
    audioPlayer = new PcmAudioPlayer({
      onError: (message) => {
        voiceError = message;
        voiceState = "error";
      },
      onPlaybackFinished: (turnId) => {
        if (pendingAudioTurnId !== turnId) return;
        playbackFinished = true;
        maybeCompleteHandsFreeTurn();
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
    handsFreeController = new BrowserHandsFreeController({
      sendText: (text) => bridge?.sendVoiceTurn(text) ?? false,
      wakePhrases: [],
      onState: (state) => {
        handsFreeState = state;
        if (state !== "error") handsFreeError = null;
      },
      onError: (message) => {
        handsFreeError = message;
      },
    });
    bridge.start();

    return () => {
      voiceController?.reset();
      handsFreeController?.disarm();
      resetPlayback();
      bridge?.stop();
    };
  });

  function resetPlayback(): void {
    audioPlayer?.stop();
    responseHasAudio = false;
    playbackFinished = false;
    pendingAudioTurnId = null;
  }

  async function toggleVoice(): Promise<void> {
    if (voiceController === null || voiceState === "submitting" || handsFreeArmed) return;
    if (voiceState === "listening") {
      voiceController.stop();
      return;
    }
    if (!displayReady || !browserVoiceEnabled) return;

    voiceError = null;
    if (audioPlayer !== null && !(await audioPlayer.resume())) return;
    if (!isDisplayReady() || handsFreeController?.isArmed) return;
    await voiceController.start();
  }

  async function toggleHandsFree(): Promise<void> {
    if (handsFreeController === null) return;
    if (handsFreeArmed) {
      handsFreeController.disarm();
      return;
    }
    if (!displayReady || !browserHandsFreeEnabled) return;

    handsFreeError = null;
    if (audioPlayer !== null && !(await audioPlayer.resume())) return;
    if (!isDisplayReady() || !browserHandsFreeEnabled) return;
    await handsFreeController.arm();
  }

  function maybeCompleteHandsFreeTurn(): void {
    if (
      displayView.state !== "idle" ||
      connectionState !== "connected" ||
      (responseHasAudio && !playbackFinished)
    ) {
      return;
    }
    responseHasAudio = false;
    playbackFinished = false;
    pendingAudioTurnId = null;
    handsFreeController?.turnFinished();
  }
</script>

<div aria-hidden={promptVisible ? "true" : undefined}>
  <StateSurface
    snapshot={displayView}
    {connectionState}
    protocolError={protocolError}
  />
</div>
{#if promptVisible && displayView.prompt}
  {#key promptKey}
    <PromptOverlay
      prompt={displayView.prompt}
      account={displayView.account ?? null}
      onAction={dispatchAction}
    />
  {/key}
{/if}
{#if browserVoiceEnabled}
  <section class="browser-voice-controls" data-voice-state={voiceState} aria-label="Browser voice">
    <button
      type="button"
      data-voice-button
      aria-pressed={voiceState === "listening"}
      disabled={!displayReady || voiceState === "submitting" || handsFreeArmed}
      on:click={toggleVoice}
    >
      {voiceState === "listening" ? "Stop listening" : "Tap to talk"}
    </button>
    {#if browserHandsFreeEnabled}
      <button
        type="button"
        data-handsfree-button
        aria-pressed={handsFreeArmed}
        disabled={!handsFreeArmed && !displayReady}
        on:click={toggleHandsFree}
      >
        {handsFreeArmed ? "Disable hands-free" : "Enable hands-free"}
      </button>
    {/if}
    {#if voiceError}
      <p data-voice-error role="alert">{voiceError}</p>
    {:else if voiceState === "listening"}
      <p data-voice-status>Listening…</p>
    {:else if voiceState === "submitting"}
      <p data-voice-status>Sending…</p>
    {/if}
    {#if handsFreeError}
      <p data-handsfree-error role="alert">{handsFreeError}</p>
    {:else if handsFreeState === "wake_ready"}
      <p data-handsfree-status>Say {wakePhraseLabel}</p>
    {:else if handsFreeState === "heard"}
      <p data-handsfree-status>Heard you</p>
    {:else if handsFreeState === "listening"}
      <p data-handsfree-status>Listening…</p>
    {:else if handsFreeState === "follow_up"}
      <p data-handsfree-status>Listening for a follow-up…</p>
    {:else if handsFreeState === "submitting"}
      <p data-handsfree-status>Sending…</p>
    {/if}
  </section>
{/if}
