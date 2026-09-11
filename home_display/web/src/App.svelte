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
  let audioPlaybackFailed = false;
  let userTranscript = "";
  let responseVisible = false;
  let responseRetentionTimer: ReturnType<typeof setTimeout> | null = null;
  let responseRetentionGeneration = 0;
  let trackedResponseText = "";
  let responseTurnActive = false;
  let responseRetentionExpired = false;

  const responseActiveStates = new Set([
    "heard",
    "listening",
    "thinking",
    "buffering",
    "speaking",
  ]);
  const RESPONSE_RETENTION_MS = 60_000;

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

  function handsFreeSurfaceState(state: HandsFreeState): DisplayView["state"] | null {
    if (state === "heard") return "heard";
    if (state === "listening" || state === "follow_up") return "listening";
    if (state === "submitting") return "thinking";
    return null;
  }

  $: localHandsFreeState = handsFreeSurfaceState(handsFreeState);
  $: surfaceView = localHandsFreeState !== null && displayView.state === "idle"
    ? { ...displayView, state: localHandsFreeState, status_text: null }
    : displayView;

  function clearResponseRetentionTimer(): void {
    responseRetentionGeneration += 1;
    if (responseRetentionTimer !== null) {
      clearTimeout(responseRetentionTimer);
      responseRetentionTimer = null;
    }
  }

  function clearConversationPresentation(): void {
    clearResponseRetentionTimer();
    userTranscript = "";
    responseVisible = false;
    trackedResponseText = "";
    responseTurnActive = false;
    responseRetentionExpired = false;
  }

  function beginCapturePresentation(): void {
    clearConversationPresentation();
  }

  function scheduleResponseRetention(view: DisplayView): void {
    if (
      view.state !== "idle" ||
      (responseHasAudio && !playbackFinished) ||
      trackedResponseText.length === 0 ||
      !responseVisible ||
      responseRetentionExpired ||
      responseRetentionTimer !== null
    ) return;

    const generation = responseRetentionGeneration;
    responseRetentionTimer = setTimeout(() => {
      if (generation !== responseRetentionGeneration) return;
      responseRetentionTimer = null;
      responseVisible = false;
      responseRetentionExpired = true;
      userTranscript = "";
    }, RESPONSE_RETENTION_MS);
  }

  function updateResponsePresentation(view: DisplayView): void {
    const activeTurn = responseActiveStates.has(view.state);
    if (activeTurn) responseTurnActive = true;

    if (view.response_text.length === 0) {
      trackedResponseText = "";
      responseVisible = false;
      responseRetentionExpired = false;
      clearResponseRetentionTimer();
      if (view.state === "idle" || view.state === "prompt") responseTurnActive = false;
    } else if (
      view.response_text !== trackedResponseText &&
      (activeTurn || responseTurnActive)
    ) {
      trackedResponseText = view.response_text;
      responseVisible = true;
      responseRetentionExpired = false;
      clearResponseRetentionTimer();
    }

    scheduleResponseRetention(view);
  }

  function setUserTranscript(text: string): void {
    userTranscript = text.trim();
  }

  function handleHandsFreeTranscript(text: string): void {
    if (text && handsFreeState === "wake_ready") beginCapturePresentation();
    setUserTranscript(text);
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
        if (view.state === "error" || view.state === "disconnected") {
          clearConversationPresentation();
        } else {
          updateResponsePresentation(view);
        }
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
        if (state !== "connected") clearConversationPresentation();
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
        clearConversationPresentation();
        resetPlayback();
        voiceController?.reset();
        handsFreeController?.abort("Display data unavailable — hands-free is off");
      },
      onAudioEvent: (event) => {
        if (event.type === "audio_start") {
          responseHasAudio = true;
          playbackFinished = false;
          pendingAudioTurnId = event.turn_id;
          audioPlaybackFailed = false;
          clearResponseRetentionTimer();
          audioPlayer?.start(event);
        } else if (event.type === "audio_end") {
          audioPlayer?.end(event.turn_id);
          if (pendingAudioTurnId === event.turn_id && !audioPlayer?.hasPendingPlayback) {
            playbackFinished = true;
          }
          maybeCompleteHandsFreeTurn();
        } else {
          audioPlayer?.abort(event.turn_id);
          if (pendingAudioTurnId !== event.turn_id) return;
          clearConversationPresentation();
          resetPlayback();
          handsFreeController?.abort("Response interrupted — hands-free is off");
        }
      },
      onAudioChunk: (chunk) => audioPlayer?.append(chunk),
      onVoiceError: () => {
        clearConversationPresentation();
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
        resetPlayback();
        audioPlaybackFailed = true;
        handsFreeController?.abort("Audio playback is unavailable — hands-free is off");
        clearConversationPresentation();
        voiceError = message;
        voiceState = "error";
      },
      onPlaybackFinished: (turnId) => {
        if (pendingAudioTurnId !== turnId) return;
        playbackFinished = true;
        updateResponsePresentation(displayView);
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
        clearConversationPresentation();
        voiceError = message;
      },
      onTranscript: (text) => setUserTranscript(text),
    });
    handsFreeController = new BrowserHandsFreeController({
      sendText: (text) => bridge?.sendVoiceTurn(text) ?? false,
      wakePhrases: [],
      onState: (state) => {
        const previousState = handsFreeState;
        handsFreeState = state;
        if (
          state === "heard" ||
          state === "follow_up" ||
          (state === "listening" && previousState !== "heard")
        ) {
          beginCapturePresentation();
        }
        if (state !== "error") handsFreeError = null;
      },
      onError: (message) => {
        clearConversationPresentation();
        handsFreeError = message;
      },
      onTranscript: (text) => handleHandsFreeTranscript(text),
    });
    bridge.start();

    return () => {
      voiceController?.reset();
      handsFreeController?.disarm();
      clearResponseRetentionTimer();
      resetPlayback();
      bridge?.stop();
    };
  });

  function resetPlayback(): void {
    audioPlayer?.stop();
    responseHasAudio = false;
    playbackFinished = false;
    pendingAudioTurnId = null;
    audioPlaybackFailed = false;
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
    beginCapturePresentation();
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
    snapshot={surfaceView}
    {connectionState}
    protocolError={protocolError}
    {userTranscript}
    {responseVisible}
    {audioPlaybackFailed}
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
