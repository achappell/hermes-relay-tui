<script lang="ts">
  import type { DisplayPrompt, PromptOption } from "../state/protocol";

  export let prompt: DisplayPrompt;
  /** The account name shown at the top, passed through from the snapshot. */
  export let account: string | null = null;

  let dismissed = false;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;

  // Auto-dismiss: choose the first option after timeout_seconds.
  $: {
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    if (prompt.timeout_seconds !== null && prompt.timeout_seconds > 0 && !dismissed) {
      const defaultChoice = prompt.options[0]?.id ?? "no";
      timeoutId = setTimeout(() => {
        sendAction(prompt.action_id, defaultChoice);
      }, prompt.timeout_seconds * 1000);
    }
  }

  function sendAction(actionId: string, choice: string) {
    if (dismissed) return;
    dismissed = true;
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
    const url = `/action?action_id=${encodeURIComponent(actionId)}&choice=${encodeURIComponent(choice)}`;
    fetch(url, { method: "POST" }).catch(() => {
      // Fire-and-forget; the server schedules the action asynchronously.
    });
  }

  function handleOption(option: PromptOption) {
    sendAction(prompt.action_id, option.id);
  }
</script>

<div class="prompt-overlay" role="dialog" aria-modal="true" aria-labelledby="prompt-title">
  <div class="ambient-canvas" aria-hidden="true"></div>

  <div class="prompt-card">
    {#if account}
      <div class="prompt-account">{account}</div>
    {/if}

    <h1 class="prompt-title" id="prompt-title">{prompt.title}</h1>
    <p class="prompt-body">{prompt.body}</p>

    <div class="prompt-actions">
      {#each prompt.options as option (option.id)}
        <button
          class="prompt-btn prompt-btn--{option.id}"
          on:click={() => handleOption(option)}
        >
          {option.label}
        </button>
      {/each}
    </div>
  </div>
</div>

<style>
  .prompt-overlay {
    align-items: center;
    background: var(--canvas-night);
    display: grid;
    inset: 0;
    isolation: isolate;
    justify-items: center;
    min-height: 100dvh;
    overflow: hidden;
    padding: clamp(1.5rem, 5vw, 6rem);
    position: fixed;
    z-index: 100;
  }

  .ambient-canvas {
    background:
      radial-gradient(circle at 60% 30%, rgb(200 185 255 / 28%), transparent 28rem),
      radial-gradient(circle at 25% 70%, rgb(154 200 255 / 20%), transparent 32rem),
      linear-gradient(135deg, var(--canvas-night), var(--canvas-deep) 60%, var(--canvas-light));
    inset: 0;
    position: absolute;
    z-index: -1;
  }

  .prompt-card {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: clamp(1rem, 3vw, 2rem);
    max-width: 36rem;
    text-align: center;
    width: 100%;
  }

  .prompt-account {
    color: var(--signal-heard);
    font-size: clamp(0.75rem, 2vw, 1rem);
    font-weight: 500;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    opacity: 0.7;
  }

  .prompt-title {
    color: var(--ink-primary);
    font-size: clamp(1.5rem, 5vw, 3rem);
    font-weight: 600;
    line-height: 1.15;
    margin: 0;
  }

  .prompt-body {
    color: var(--ink-secondary);
    font-size: clamp(1rem, 2.5vw, 1.5rem);
    line-height: 1.5;
    margin: 0;
  }

  .prompt-actions {
    display: flex;
    flex-wrap: wrap;
    gap: clamp(0.75rem, 2vw, 1.25rem);
    justify-content: center;
    margin-top: clamp(0.5rem, 2vw, 1rem);
  }

  .prompt-btn {
    background: transparent;
    border: 2px solid var(--ink-secondary);
    border-radius: 100vw;
    color: var(--ink-primary);
    cursor: pointer;
    font-size: clamp(0.9rem, 2vw, 1.2rem);
    font-weight: 500;
    line-height: 1;
    min-width: 8rem;
    padding: clamp(0.6rem, 1.5vw, 1rem) clamp(1.5rem, 4vw, 2.5rem);
    transition: background 0.15s, border-color 0.15s, color 0.15s;
  }

  /* The first button (primary action) gets a filled style */
  .prompt-btn:first-child {
    background: var(--signal-heard);
    border-color: var(--signal-heard);
    color: var(--canvas-night);
  }

  .prompt-btn:first-child:hover,
  .prompt-btn:first-child:focus-visible {
    background: var(--ink-primary);
    border-color: var(--ink-primary);
  }

  .prompt-btn:not(:first-child):hover,
  .prompt-btn:not(:first-child):focus-visible {
    border-color: var(--ink-primary);
    color: var(--ink-primary);
  }

  .prompt-btn:focus-visible {
    outline: 3px solid var(--signal-heard);
    outline-offset: 3px;
  }

  .prompt-btn:active {
    opacity: 0.75;
    transform: scale(0.97);
  }
</style>
