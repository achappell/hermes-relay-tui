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
  choice?: DisplayChoice;
}

export interface DisplayChoice {
  object_id: string;
  operations: Array<"choose" | "explore">;
  freshness: string;
}

export const displayActionNames = ["prompt.choose", "prompt.explore", "prompt.dismiss"] as const;
export type DisplayActionName = (typeof displayActionNames)[number];

export interface DisplayCapabilities {
  actions: DisplayActionName[];
  features: string[];
  timing?: "absent";
  wake_phrases?: string[];
  wake_listen_seconds?: number;
  wake_followup_seconds?: number;
}

export type DisplayAction =
  | {
      type: "action";
      schema: 1;
      action_id: string;
      choice: string;
    }
  | {
      type: "action";
      schema: 1;
      action_id: string;
      operation: "choose" | "explore";
      option_id: string;
      object_id: string;
      freshness: string;
    };

export interface DisplayAudioStart {
  type: "audio_start";
  schema: 1;
  turn_id: string;
  sample_rate: number;
  channels: number;
  sample_width: 2;
}

export interface DisplayAudioEnd {
  type: "audio_end";
  schema: 1;
  turn_id: string;
}

export interface DisplayAudioAbort {
  type: "audio_abort";
  schema: 1;
  turn_id: string;
  reason: string;
}

export type DisplayAudioEvent = DisplayAudioStart | DisplayAudioEnd | DisplayAudioAbort;

export interface DisplayProfileRouteAck {
  type: "profile_route_ack";
  schema: 1;
  request_id: string;
  accepted: boolean;
  account?: string;
  reason?: string;
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

function parsePromptOption(
  raw: unknown,
  idLimit: number,
  labelLimit: number,
): PromptOption | null {
  if (!isRecord(raw)) return null;
  const { id, label } = raw;
  if (typeof id !== "string" || !id) return null;
  if (id.length > idLimit) return null;
  if (typeof label !== "string" || !label || label.length > labelLimit) return null;
  return { id, label };
}

function parseDisplayPrompt(raw: unknown): DisplayPrompt | null {
  if (!isRecord(raw)) return null;
  const { kind, title, body, options, action_id, timeout_seconds } = raw;
  if (typeof kind !== "string" || !kind || kind.length > 24) return null;
  if (typeof title !== "string" || !title || title.length > 64) return null;
  const typedChoice = raw.choice !== undefined;
  if (typedChoice && kind !== "choice") return null;
  if (typeof body !== "string" || body.length > (typedChoice ? 1024 : 192)) return null;
  const optionLimit = typedChoice ? 32 : 4;
  if (!Array.isArray(options) || options.length === 0 || options.length > optionLimit) return null;
  const idLimit = typedChoice ? 64 : 32;
  const labelLimit = typedChoice ? 256 : 48;
  const parsedOptions: PromptOption[] = [];
  for (const opt of options) {
    const parsed = parsePromptOption(opt, idLimit, labelLimit);
    if (!parsed) return null;
    if (parsedOptions.some((existing) => existing.id === parsed.id)) return null;
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
  let choice: DisplayChoice | undefined;
  if (typedChoice) {
    if (kind !== "choice" || !isRecord(raw.choice)) return null;
    const objectId = raw.choice.object_id;
    const freshness = raw.choice.freshness;
    const operations = raw.choice.operations;
    if (
      typeof objectId !== "string" ||
      !objectId ||
      objectId.length > 64 ||
      typeof freshness !== "string" ||
      !freshness ||
      freshness.length > 64 ||
      !Array.isArray(operations) ||
      operations.length === 0 ||
      operations.length > 2
    ) {
      return null;
    }
    const parsedOperations: Array<"choose" | "explore"> = [];
    for (const operation of operations) {
      if (
        (operation !== "choose" && operation !== "explore") ||
        parsedOperations.includes(operation)
      ) {
        return null;
      }
      parsedOperations.push(operation);
    }
    choice = { object_id: objectId, operations: parsedOperations, freshness };
  }
  const prompt: DisplayPrompt = {
    kind,
    title,
    body,
    options: parsedOptions,
    action_id,
    timeout_seconds: timeout_seconds as number | null,
  };
  if (choice !== undefined) prompt.choice = choice;
  return prompt;
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

  let wakePhrases: string[] | undefined;
  if (raw.wake_phrases !== undefined) {
    if (!Array.isArray(raw.wake_phrases) || raw.wake_phrases.length > 8) return null;
    wakePhrases = [];
    for (const phrase of raw.wake_phrases) {
      if (
        typeof phrase !== "string" ||
        !phrase.trim() ||
        phrase.length > 128 ||
        wakePhrases.some((existing) => existing === phrase)
      ) {
        return null;
      }
      wakePhrases.push(phrase);
    }
  }

  const parseSeconds = (value: unknown): number | null | undefined => {
    if (value === undefined) return undefined;
    if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
    return value;
  };
  const wakeListenSeconds = parseSeconds(raw.wake_listen_seconds);
  const wakeFollowupSeconds = parseSeconds(raw.wake_followup_seconds);
  if (wakeListenSeconds === null || wakeFollowupSeconds === null) return null;

  let timing: "absent" | undefined;
  if (raw.timing !== undefined) {
    if (raw.timing !== "absent") return null;
    timing = "absent";
  }

  const capabilities: DisplayCapabilities = {
    actions: parsedActions,
    features: parsedFeatures,
  };
  if (timing !== undefined) capabilities.timing = timing;
  if (wakePhrases !== undefined) capabilities.wake_phrases = wakePhrases;
  if (wakeListenSeconds !== undefined) capabilities.wake_listen_seconds = wakeListenSeconds;
  if (wakeFollowupSeconds !== undefined) {
    capabilities.wake_followup_seconds = wakeFollowupSeconds;
  }
  return capabilities;
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
    action_id.length > 64
  ) {
    return null;
  }
  const typedNames = ["operation", "option_id", "object_id", "freshness"] as const;
  const typedPresent = typedNames.filter((name) => name in raw);
  if (typedPresent.length === 0) {
    if (typeof choice !== "string" || choice.length === 0 || choice.length > 32) return null;
    return { type, schema, action_id, choice };
  }
  if (
    typedPresent.length !== typedNames.length ||
    "choice" in raw ||
    (raw.operation !== "choose" && raw.operation !== "explore") ||
    typeof raw.option_id !== "string" ||
    !raw.option_id ||
    raw.option_id.length > 64 ||
    typeof raw.object_id !== "string" ||
    !raw.object_id ||
    raw.object_id.length > 64 ||
    typeof raw.freshness !== "string" ||
    !raw.freshness ||
    raw.freshness.length > 64
  ) {
    return null;
  }
  return {
    type,
    schema,
    action_id,
    operation: raw.operation,
    option_id: raw.option_id,
    object_id: raw.object_id,
    freshness: raw.freshness,
  };
}

export function parseProfileRouteAck(raw: unknown): DisplayProfileRouteAck | null {
  if (!isRecord(raw)) return null;
  const { type, schema, request_id, accepted, account, reason } = raw;
  if (
    type !== "profile_route_ack" ||
    schema !== 1 ||
    typeof request_id !== "string" ||
    request_id.length === 0 ||
    request_id.length > 64 ||
    [...request_id].some((character) => /\s/.test(character) || character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127) ||
    typeof accepted !== "boolean"
  ) {
    return null;
  }
  if (
    account !== undefined &&
    (typeof account !== "string" || account.length === 0 || account.length > 128)
  ) {
    return null;
  }
  if (
    reason !== undefined &&
    (typeof reason !== "string" || reason.length === 0 || reason.length > 64)
  ) {
    return null;
  }
  const result: DisplayProfileRouteAck = {
    type,
    schema,
    request_id,
    accepted,
  };
  if (account !== undefined) result.account = account;
  if (reason !== undefined) result.reason = reason;
  return result;
}

function parseTurnId(raw: unknown): string | null {
  return typeof raw === "string" && raw.length > 0 && raw.length <= 128 ? raw : null;
}

export function parseAudioEvent(raw: unknown): DisplayAudioEvent | null {
  if (!isRecord(raw) || raw.schema !== 1 || typeof raw.type !== "string") {
    return null;
  }

  const turnId = parseTurnId(raw.turn_id);
  if (turnId === null) return null;

  if (raw.type === "audio_start") {
    const { sample_rate, channels, sample_width } = raw;
    if (
      typeof sample_rate !== "number" ||
      !Number.isSafeInteger(sample_rate) ||
      sample_rate <= 0 ||
      typeof channels !== "number" ||
      !Number.isSafeInteger(channels) ||
      channels < 1 ||
      channels > 8 ||
      sample_width !== 2
    ) {
      return null;
    }
    return {
      type: "audio_start",
      schema: 1,
      turn_id: turnId,
      sample_rate,
      channels,
      sample_width: 2,
    };
  }

  if (raw.type === "audio_end") {
    return { type: "audio_end", schema: 1, turn_id: turnId };
  }

  if (raw.type === "audio_abort") {
    return typeof raw.reason === "string" && raw.reason.length > 0
      ? { type: "audio_abort", schema: 1, turn_id: turnId, reason: raw.reason }
      : null;
  }

  return null;
}
