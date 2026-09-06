export const displayStates = [
  "idle",
  "heard",
  "listening",
  "thinking",
  "speaking",
  "buffering",
  "error",
  "disconnected",
  "prompt",
] as const;

export type DisplayState = (typeof displayStates)[number];

export interface PromptOption {
  id: string;
  label: string;
}

export interface DisplayPrompt {
  kind: string;
  title: string;
  body: string;
  options: PromptOption[];
  action_id: string;
  timeout_seconds: number | null;
}

export interface DisplaySnapshot {
  type: "snapshot";
  schema: 1;
  sequence: number;
  state: DisplayState;
  response_text: string;
  status_text: string | null;
  media: Record<string, unknown> | null;
  prompt: DisplayPrompt | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function parsePromptOption(raw: unknown): PromptOption | null {
  if (!isRecord(raw)) return null;
  const { id, label } = raw;
  if (typeof id !== "string" || !id) return null;
  if (typeof label !== "string" || !label) return null;
  return { id, label };
}

function parseDisplayPrompt(raw: unknown): DisplayPrompt | null {
  if (!isRecord(raw)) return null;
  const { kind, title, body, options, action_id, timeout_seconds } = raw;
  if (typeof kind !== "string" || !kind) return null;
  if (typeof title !== "string" || !title) return null;
  if (typeof body !== "string") return null;
  if (!Array.isArray(options)) return null;
  const parsedOptions: PromptOption[] = [];
  for (const opt of options) {
    const parsed = parsePromptOption(opt);
    if (!parsed) return null;
    parsedOptions.push(parsed);
  }
  if (parsedOptions.length === 0) return null;
  if (typeof action_id !== "string" || !action_id) return null;
  if (timeout_seconds !== null && typeof timeout_seconds !== "number") return null;
  return {
    kind,
    title,
    body,
    options: parsedOptions,
    action_id,
    timeout_seconds: timeout_seconds as number | null,
  };
}

export function parseSnapshot(raw: unknown): DisplaySnapshot | null {
  if (!isRecord(raw)) {
    return null;
  }

  const { type, schema, sequence, state, response_text, status_text, media, prompt } = raw;

  if (
    type !== "snapshot" ||
    schema !== 1 ||
    typeof sequence !== "number" ||
    !Number.isSafeInteger(sequence) ||
    sequence < 0 ||
    !displayStates.includes(state as DisplayState) ||
    typeof response_text !== "string" ||
    (status_text !== null && typeof status_text !== "string") ||
    (media !== null && !isRecord(media))
  ) {
    return null;
  }

  let parsedPrompt: DisplayPrompt | null = null;
  if (prompt !== null && prompt !== undefined) {
    parsedPrompt = parseDisplayPrompt(prompt);
    if (parsedPrompt === null) return null; // malformed prompt → reject whole snapshot
  }

  // Enforce invariant: prompt state must have a prompt, others must not.
  if (state === "prompt" && parsedPrompt === null) return null;
  if (state !== "prompt" && parsedPrompt !== null) return null;

  return {
    type,
    schema,
    sequence,
    state: state as DisplayState,
    response_text,
    status_text,
    media,
    prompt: parsedPrompt,
  };
}
