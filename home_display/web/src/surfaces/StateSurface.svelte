<script lang="ts">
  import { afterUpdate, onDestroy } from "svelte";
  import type { ConnectionState } from "../state/channel";
  import type { DisplaySnapshot, DisplayState } from "../state/protocol";

  export let snapshot: DisplaySnapshot;
  export let connectionState: ConnectionState;
  export let protocolError: string | null = null;
  export let accessibleOnly = false;
  export let userTranscript = "";
  export let responseVisible = true;
  export let audioPlaybackFailed = false;

  const labels: Record<DisplayState, string> = {
    idle: "Ready",
    heard: "Heard you",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    buffering: "Buffering",
    error: "Error",
    disconnected: "Disconnected",
    prompt: "Prompt",
  };

  const fallbackStatus: Partial<Record<DisplayState, string>> = {
    buffering: "Still working — please wait",
    error: "Something needs attention — try again",
    disconnected: "Display disconnected — check the host connection",
  };

  $: displayState = protocolError !== null
    ? "error"
    : connectionState === "connected"
      ? snapshot.state
      : "disconnected";
  $: renderedState = audioPlaybackFailed && displayState === "speaking" ? "buffering" : displayState;
  $: status = protocolError ?? (
    audioPlaybackFailed && displayState === "speaking"
      ? "Audio unavailable — response text remains visible"
      : snapshot.status_text ?? fallbackStatus[renderedState] ?? null
  );
  $: showResponse = protocolError === null && snapshot.response_text.length > 0
    && responseVisible && ["thinking", "speaking", "buffering", "idle"].includes(renderedState);
  $: visibleUserTranscript = userTranscript.trim();
  $: showUserTranscript = protocolError === null && visibleUserTranscript.length > 0
    && ["heard", "listening", "thinking", "speaking", "buffering", "idle"].includes(renderedState);
  let liveMode: "off" | "polite";
  let responseLiveMode: "off" | "polite";
  $: liveMode = renderedState === "speaking" || (renderedState === "idle" && showResponse)
    ? "off"
    : "polite";
  $: responseLiveMode = renderedState === "idle" && showResponse ? "polite" : "off";
  $: responsePhase = renderedState === "idle" && showResponse
    ? "complete"
    : renderedState === "buffering" && showResponse
      ? "buffering"
      : ["thinking", "speaking"].includes(renderedState) && showResponse
        ? "streaming"
        : ["error", "disconnected"].includes(renderedState)
          ? "unavailable"
          : "hidden";
  // Hermes announces the audio format about two seconds before the first
  // audible sample. Across that gap the unit is genuinely working and
  // genuinely silent, so it gets a sign of life that is visibly not a claim
  // to be talking.
  $: working = renderedState === "thinking" || renderedState === "buffering";

  let responseViewport: HTMLDivElement | undefined;
  let showingResponse = false;
  let previousResponse = "";
  let lastTargetScroll = 0;

  function prefersReducedMotion(): boolean {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function resetResponseScroll(): void {
    if (responseViewport) {
      if (typeof responseViewport.scrollTo === "function") {
        responseViewport.scrollTo({ top: 0, behavior: "instant" });
      } else {
        responseViewport.scrollTop = 0;
      }
      lastTargetScroll = 0;
    }
  }

  function keepResponseInView(): void {
    if (!showResponse || !responseViewport) return;

    const maxScroll = responseViewport.scrollHeight - responseViewport.clientHeight;
    if (maxScroll <= 0) {
      if (responseViewport.scrollTop !== 0) {
        resetResponseScroll();
      }
      lastTargetScroll = 0;
      return;
    }

    if (maxScroll !== lastTargetScroll) {
      lastTargetScroll = maxScroll;
      const behavior = prefersReducedMotion() ? "instant" : "smooth";
      if (typeof responseViewport.scrollTo === "function") {
        responseViewport.scrollTo({
          top: maxScroll,
          behavior,
        });
      } else {
        responseViewport.scrollTop = maxScroll;
      }
    }
  }

  afterUpdate(() => {
    if (!showResponse) {
      resetResponseScroll();
      showingResponse = false;
      previousResponse = "";
      return;
    }

    const newResponse =
      !showingResponse ||
      snapshot.response_text.length < previousResponse.length ||
      !snapshot.response_text.startsWith(previousResponse);

    if (newResponse) {
      resetResponseScroll();
    }

    showingResponse = true;
    previousResponse = snapshot.response_text;
    keepResponseInView();
  });

  onDestroy(resetResponseScroll);
</script>

<main
  class:has-response={showResponse}
  class:has-user-transcript={showUserTranscript}
  class:accessible-only={accessibleOnly}
  class="state-surface"
  data-state={renderedState}
  aria-live={liveMode}
  aria-atomic="true"
>
  <div class="ambient-canvas" aria-hidden="true"></div>

  <section class="state-overlay" aria-label={labels[renderedState]}>
    <p class="state-label">{labels[renderedState]}</p>
    {#if snapshot.account}
      <p class="account-label">Profile: {snapshot.account}</p>
    {/if}
    {#if status}
      <p class="status-text">
        {status}{#if working}<span class="working-dot" data-working-dot aria-hidden="true"></span>{/if}
      </p>
    {/if}
    {#if showUserTranscript}
      <section
        class="user-transcription"
        data-user-transcription
        aria-label="Your transcription"
      >
        <p class="transcription-label">You said</p>
        <p
          class="transcription-text"
          data-user-transcription-text
          aria-live={renderedState === "speaking" ? "polite" : "off"}
          aria-atomic="true"
        >{visibleUserTranscript}</p>
      </section>
    {/if}
    <div
      class:visible={showResponse}
      class="response-viewport"
      data-response-viewport
      data-response-phase={responsePhase}
      aria-live={responseLiveMode}
      aria-atomic="true"
      aria-label={responsePhase === "complete"
        ? "Completed Hermes response"
        : responsePhase === "buffering"
          ? "Hermes response (audio unavailable)"
          : responsePhase === "unavailable"
            ? "Unavailable Hermes response"
            : "Hermes response"}
      role="region"
      bind:this={responseViewport}
    >
      <p class="response-text" data-response-text>{showResponse ? snapshot.response_text : ""}</p>
    </div>
    {#if renderedState === "prompt" && snapshot.prompt}
      <section class="prompt-summary" aria-label={snapshot.prompt.title}>
        <h2>{snapshot.prompt.title}</h2>
        <p>{snapshot.prompt.body}</p>
        <ul>
          {#each snapshot.prompt.options as option}
            <li>{option.label}</li>
          {/each}
        </ul>
      </section>
    {/if}
  </section>
</main>
