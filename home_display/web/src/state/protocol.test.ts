import { describe, expect, it } from "vitest";

import { parseSnapshot } from "./protocol";

const snapshot = {
  type: "snapshot",
  schema: 1,
  sequence: 1,
  state: "speaking",
  response_text: "Hello",
  status_text: null,
  media: null,
  prompt: null,
};

describe("parseSnapshot", () => {
  it("accepts a schema-1 snapshot with an approved state", () => {
    expect(parseSnapshot(snapshot)).toEqual(snapshot);
  });

  it("accepts a prompt state with valid prompt payload", () => {
    const promptSnapshot = {
      type: "snapshot",
      schema: 1,
      sequence: 2,
      state: "prompt",
      response_text: "",
      status_text: null,
      media: null,
      prompt: {
        kind: "notice",
        title: "Setup needed",
        body: "Set this display as the home channel?",
        options: [
          { id: "yes", label: "Set home" },
          { id: "no", label: "Skip" },
        ],
        action_id: "sethome",
        timeout_seconds: 30,
      },
    };
    expect(parseSnapshot(promptSnapshot)).toEqual(promptSnapshot);
  });

  it("rejects prompt state with null prompt", () => {
    expect(parseSnapshot({ ...snapshot, state: "prompt", prompt: null })).toBeNull();
  });

  it("rejects non-prompt state with prompt payload", () => {
    const promptPayload = {
      kind: "notice",
      title: "Title",
      body: "Body",
      options: [{ id: "ok", label: "OK" }],
      action_id: "act1",
      timeout_seconds: null,
    };
    expect(parseSnapshot({ ...snapshot, state: "idle", prompt: promptPayload })).toBeNull();
  });

  it("rejects an unknown state", () => {
    expect(parseSnapshot({ ...snapshot, state: "unknown" })).toBeNull();
  });

  it.each([
    ["another schema", { ...snapshot, schema: 2 }],
    ["a negative sequence", { ...snapshot, sequence: -1 }],
    ["a fractional sequence", { ...snapshot, sequence: 1.5 }],
    ["a non-string response", { ...snapshot, response_text: 1 }],
    ["a non-string status", { ...snapshot, status_text: 1 }],
    ["a non-object media", { ...snapshot, media: "image" }],
    ["a missing type", { ...snapshot, type: undefined }],
  ])("rejects %s", (_description, raw) => {
    expect(parseSnapshot(raw)).toBeNull();
  });
});

