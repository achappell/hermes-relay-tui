export const displayStates = [
  "idle",
  "listening",
  "thinking",
  "speaking",
  "buffering",
  "error",
  "disconnected",
] as const;

export type DisplayState = (typeof displayStates)[number];

export interface DisplaySnapshot {
  type: "snapshot";
  schema: 1;
  sequence: number;
  state: DisplayState;
  response_text: string;
  status_text: string | null;
  media: Record<string, unknown> | null;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

export function parseSnapshot(raw: unknown): DisplaySnapshot | null {
  if (!isRecord(raw)) {
    return null;
  }

  const { type, schema, sequence, state, response_text, status_text, media } = raw;

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

  return {
    type,
    schema,
    sequence,
    state: state as DisplayState,
    response_text,
    status_text,
    media,
  };
}
