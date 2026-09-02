<script lang="ts">
  import type { ConnectionState } from "../state/channel";
  import type { DisplaySnapshot, DisplayState } from "../state/protocol";

  export let snapshot: DisplaySnapshot;
  export let connectionState: ConnectionState;
  export let protocolError: string | null = null;

  const labels: Record<DisplayState, string> = {
    idle: "Ready",
    heard: "Heard you",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    buffering: "Buffering",
    error: "Error",
    disconnected: "Disconnected",
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
  $: status = protocolError ?? snapshot.status_text ?? fallbackStatus[displayState] ?? null;
  $: showResponse = protocolError === null && displayState === "speaking" && snapshot.response_text.length > 0;
  // Hermes announces the audio format about two seconds before the first
  // audible sample. Across that gap the unit is genuinely working and
  // genuinely silent, so it gets a sign of life that is visibly not a claim
  // to be talking.
  $: working = displayState === "thinking" || displayState === "buffering";
</script>

<main class:has-response={showResponse} class="state-surface" data-state={displayState} aria-live="polite">
  <div class="ambient-canvas" aria-hidden="true"></div>

  <section class="state-overlay" aria-label={labels[displayState]}>
    <p class="state-label">{labels[displayState]}</p>
    {#if status}
      <p class="status-text">
        {status}{#if working}<span class="working-dot" data-working-dot aria-hidden="true"></span>{/if}
      </p>
    {/if}
    <p class:visible={showResponse} class="response-text" data-response-text>{showResponse ? snapshot.response_text : ""}</p>
  </section>
</main>
