<script lang="ts">
  import { onDestroy } from "svelte";
  import type { DisplayAction, DisplayPrompt, PromptOption } from "../state/protocol";

  export let prompt: DisplayPrompt;
  /** The account name shown at the top, passed through from the snapshot. */
  export let account: string | null = null;
  export let canChoose = true;
  export let canExplore = false;
  /** The bridge-owned domain action handler. Standalone use keeps HTTP compatibility. */
  export let onAction: ((action: DisplayAction) => Promise<boolean> | boolean | void) | null = null;
  /** Safe action failure text supplied by the owning bridge, when available. */
  export let errorMessage: string | null = null;

  const ACTION_TIMEOUT_MS = 10_000;
  const MAX_PROMPT_TIMEOUT_SECONDS = 2_147_483.647;
  let dismissed = false;
  let submitting = false;
  let typedActionSubmitted = false;
  let localError: string | null = null;
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  let timeoutKey: string | null = null;
  let selectedOptionId: string | null = null;
  let choiceContextKey: string | null = null;
  $: canChooseTyped = canChoose && (prompt.choice?.operations.includes("choose") ?? false);
  $: canExploreTyped = canExplore && (prompt.choice?.operations.includes("explore") ?? false);
  $: {
    const nextChoiceContextKey = prompt.choice === undefined
      ? null
      : `${prompt.action_id}:${prompt.choice.object_id}:${prompt.choice.freshness}`;
    if (nextChoiceContextKey !== choiceContextKey) {
      choiceContextKey = nextChoiceContextKey;
      selectedOptionId = null;
      typedActionSubmitted = false;
    }
  }

  // Auto-dismiss: choose the first option after timeout_seconds.
  $: {
    const nextTimeoutKey = JSON.stringify({
      action_id: prompt.action_id,
      timeout_seconds: prompt.timeout_seconds,
      default_choice: prompt.options[0]?.id ?? "no",
      typed_choice: prompt.choice !== undefined,
    });
    if (nextTimeoutKey !== timeoutKey) {
      timeoutKey = nextTimeoutKey;
      if (timeoutId !== null) {
        clearTimeout(timeoutId);
        timeoutId = null;
      }
      if (
        prompt.choice === undefined &&
        prompt.timeout_seconds !== null &&
        prompt.timeout_seconds > 0 &&
        !dismissed
      ) {
        const defaultChoice = prompt.options[0]?.id ?? "no";
        timeoutId = setTimeout(() => {
          void sendAction({
            type: "action",
            schema: 1,
            action_id: prompt.action_id,
            choice: defaultChoice,
          });
        }, Math.min(prompt.timeout_seconds, MAX_PROMPT_TIMEOUT_SECONDS) * 1000);
      }
    }
  }

  onDestroy(() => {
    if (timeoutId !== null) clearTimeout(timeoutId);
  });

  function withTimeout<T>(value: PromiseLike<T> | T): Promise<T> {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("display action timed out")), ACTION_TIMEOUT_MS);
      Promise.resolve(value).then(
        (result) => {
          clearTimeout(timer);
          resolve(result);
        },
        (error) => {
          clearTimeout(timer);
          reject(error);
        },
      );
    });
  }

  async function sendAction(action: DisplayAction): Promise<void> {
    if (dismissed || submitting || typedActionSubmitted) return;
    submitting = true;

    let accepted = true;
    try {
      if (onAction !== null) {
        accepted = (await withTimeout(onAction(action))) !== false;
      } else {
        const query = new URLSearchParams({ action_id: action.action_id });
        if ("choice" in action) {
          query.set("choice", action.choice);
        } else {
          query.set("operation", action.operation);
          query.set("option_id", action.option_id);
          query.set("object_id", action.object_id);
          query.set("freshness", action.freshness);
        }
        const url = `/action?${query.toString()}`;
        const controller = new AbortController();
        const requestTimeoutId = setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS);
        try {
          const response = await fetch(url, { method: "POST", signal: controller.signal });
          accepted = response.ok;
        } finally {
          clearTimeout(requestTimeoutId);
        }
      }
    } catch {
      accepted = false;
    }

    if (!accepted) {
      submitting = false;
      localError = "Display action could not be sent";
      return;
    }

    localError = null;
    submitting = false;
    if (prompt.choice !== undefined) {
      typedActionSubmitted = true;
      return;
    }
    dismissed = true;
    if (timeoutId !== null) {
      clearTimeout(timeoutId);
      timeoutId = null;
    }
  }

  function handleOption(option: PromptOption) {
    if (prompt.choice !== undefined) {
      selectedOptionId = option.id;
      localError = null;
      return;
    }
    void sendAction({
      type: "action",
      schema: 1,
      action_id: prompt.action_id,
      choice: option.id,
    });
  }

  function sendTypedAction(operation: "choose" | "explore") {
    const choice = prompt.choice;
    if (choice === undefined || selectedOptionId === null) return;
    void sendAction({
      type: "action",
      schema: 1,
      action_id: prompt.action_id,
      operation,
      option_id: selectedOptionId,
      object_id: choice.object_id,
      freshness: choice.freshness,
    });
  }
</script>

{#if !dismissed}
  <div class="prompt-overlay" role="dialog" aria-modal="true" aria-labelledby="prompt-title">
    <div class="ambient-canvas" aria-hidden="true"></div>

    <div class="prompt-card">
      {#if account}
        <div class="prompt-account">{account}</div>
      {/if}

      <h1 class="prompt-title" id="prompt-title">{prompt.title}</h1>
      <p class="prompt-body">{prompt.body}</p>
      {#if errorMessage ?? localError}
        <p class="prompt-error" data-action-error role="alert">{errorMessage ?? localError}</p>
      {/if}
      {#if typedActionSubmitted}
        <p class="prompt-pending" data-prompt-pending role="status" aria-live="polite">
          Waiting for Home to update this choice.
        </p>
      {/if}

      <div
        class="prompt-actions"
        class:prompt-actions--typed={prompt.choice !== undefined}
        role={prompt.choice ? "group" : undefined}
        aria-label={prompt.choice ? "Choices" : undefined}
      >
        {#each prompt.options as option (option.id)}
          <button
            class="prompt-btn prompt-btn--{option.id}"
            disabled={submitting || typedActionSubmitted}
            aria-pressed={prompt.choice ? selectedOptionId === option.id : undefined}
            data-selected={prompt.choice && selectedOptionId === option.id ? "true" : undefined}
            on:click={() => handleOption(option)}
          >
            {option.label}
          </button>
        {/each}
      </div>
      {#if prompt.choice}
        <div class="prompt-actions prompt-actions--typed">
          <button
            class="prompt-btn prompt-btn--choose"
            disabled={submitting || typedActionSubmitted || selectedOptionId === null || !canChooseTyped}
            on:click={() => sendTypedAction("choose")}
          >Choose</button>
          <button
            class="prompt-btn prompt-btn--explore"
            disabled={submitting || typedActionSubmitted || selectedOptionId === null || !canExploreTyped}
            on:click={() => sendTypedAction("explore")}
          >Explore</button>
        </div>
      {/if}
    </div>
  </div>
{/if}

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

  .prompt-error {
    color: var(--signal-error);
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
  .prompt-actions:not(.prompt-actions--typed) .prompt-btn:first-child {
    background: var(--signal-heard);
    border-color: var(--signal-heard);
    color: var(--canvas-night);
  }

  .prompt-actions:not(.prompt-actions--typed) .prompt-btn:first-child:hover,
  .prompt-actions:not(.prompt-actions--typed) .prompt-btn:first-child:focus-visible {
    background: var(--ink-primary);
    border-color: var(--ink-primary);
  }

  .prompt-btn[data-selected="true"] {
    background: var(--signal-heard);
    border-color: var(--signal-heard);
    color: var(--canvas-night);
  }

  .prompt-actions--typed {
    margin-top: 0;
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
