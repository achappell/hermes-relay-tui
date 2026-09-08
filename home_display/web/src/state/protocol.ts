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

export const displayActionNames = ["prompt.choose", "prompt.dismiss"] as const;
export type DisplayActionName = (typeof displayActionNames)[number];

export interface DisplayCapabilities {
  actions: DisplayActionName[];
  features: string[];
}

export interface DisplayAction {
  type: "action";
  schema: 1;
  action_id: string;
  choice: string;
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
  account?: string | null;
  capabilities?: DisplayCapabilities;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

function parsePromptOption(raw: unknown): PromptOption | null {
  if (!isRecord(raw)) return null;
  const { id, label } = raw;
  if (typeof id !== "string" || !id) return null;
  if (id.length > 32) return null;
  if (typeof label !== "string" || !label || label.length > 48) return null;
  return { id, label };
}

function parseDisplayPrompt(raw: unknown): DisplayPrompt | null {
  if (!isRecord(raw)) return null;
  const { kind, title, body, options, action_id, timeout_seconds } = raw;
  if (typeof kind !== "string" || !kind || kind.length > 24) return null;
  if (typeof title !== "string" || !title || title.length > 64) return null;
  if (typeof body !== "string" || body.length > 192) return null;
  if (!Array.isArray(options) || options.length === 0 || options.length > 4) return null;
  const parsedOptions: PromptOption[] = [];
  for (const opt of options) {
    const parsed = parsePromptOption(opt);
    if (!parsed) return null;
    parsedOptions.push(parsed);
  }
  if (parsedOptions.length === 0) return null;
  if (typeof action_id !== "string" || !action_id || action_id.length > 64) return null;
  if (timeout_seconds === undefined) return null;
  if (
    timeout_seconds !== null &&
    (typeof timeout_seconds !== "number" ||
      !Number.isSafeInteger(timeout_seconds) ||
      timeout_seconds <= 0)
  ) {
    return null;
  }
  return {
    kind,
    title,
    body,
    options: parsedOptions,
    action_id,
    timeout_seconds: timeout_seconds as number | null,
  };
}

function parseCapabilities(raw: unknown): DisplayCapabilities | null {
  if (!isRecord(raw)) return null;
  const { actions, features } = raw;
  if (!Array.isArray(actions) || !Array.isArray(features)) return null;

  const parsedActions: DisplayActionName[] = [];
  for (const action of actions) {
    if (
      typeof action !== "string" ||
      !displayActionNames.includes(action as DisplayActionName) ||
      parsedActions.includes(action as DisplayActionName)
    ) {
      return null;
    }
    parsedActions.push(action as DisplayActionName);
  }

  const parsedFeatures: string[] = [];
  for (const feature of features) {
    if (typeof feature !== "string" || !feature || parsedFeatures.includes(feature)) {
      return null;
    }
    parsedFeatures.push(feature);
  }

  return { actions: parsedActions, features: parsedFeatures };
}

export function parseSnapshot(raw: unknown): DisplaySnapshot | null {
  if (!isRecord(raw)) {
    return null;
  }

  const {
    type,
    schema,
    sequence,
    state,
    response_text,
    status_text,
    media,
    prompt,
    account,
    capabilities,
  } = raw;

  if (
    type !== "snapshot" ||
    schema !== 1 ||
    typeof sequence !== "number" ||
    !Number.isSafeInteger(sequence) ||
    sequence < 0 ||
    sequence > 0xffffffff ||
    !displayStates.includes(state as DisplayState) ||
    typeof response_text !== "string" ||
    (status_text !== null && typeof status_text !== "string") ||
    (media !== null && !isRecord(media)) ||
    (account !== undefined && account !== null && typeof account !== "string")
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

  let parsedCapabilities: DisplayCapabilities | undefined;
  if (capabilities !== undefined) {
    const parsed = parseCapabilities(capabilities);
    if (parsed === null) return null;
    parsedCapabilities = parsed;
  }

  const snapshot: DisplaySnapshot = {
    type,
    schema,
    sequence,
    state: state as DisplayState,
    response_text,
    status_text,
    media,
    prompt: parsedPrompt,
  };
  if (account !== undefined) snapshot.account = account as string | null;
  if (parsedCapabilities !== undefined) snapshot.capabilities = parsedCapabilities;
  return snapshot;
}

export function parseAction(raw: unknown): DisplayAction | null {
  if (!isRecord(raw)) return null;
  const { type, schema, action_id, choice } = raw;
  if (
    type !== "action" ||
    schema !== 1 ||
    typeof action_id !== "string" ||
    action_id.length === 0 ||
    action_id.length > 64 ||
    typeof choice !== "string" ||
    choice.length === 0 ||
    choice.length > 32
  ) {
    return null;
  }
  return { type, schema, action_id, choice };
}
