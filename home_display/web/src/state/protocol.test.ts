import { describe, expect, it } from "vitest";

import { parseAction, parseSnapshot } from "./protocol";

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

  it("preserves account and validates shared capability fields", () => {
    const parsed = parseSnapshot({
      ...snapshot,
      account: "Spark",
      capabilities: {
        actions: ["prompt.choose"],
        features: ["prompt_overlay"],
      },
    });

    expect(parsed).toMatchObject({
      account: "Spark",
      capabilities: {
        actions: ["prompt.choose"],
        features: ["prompt_overlay"],
      },
    });
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
    ["an oversized sequence", { ...snapshot, sequence: 0x1_0000_0000 }],
    ["a missing type", { ...snapshot, type: undefined }],
  ])("rejects %s", (_description, raw) => {
    expect(parseSnapshot(raw)).toBeNull();
  });

  it("rejects prompt fields that exceed embedded contract bounds", () => {
    const prompt = {
      kind: "notice",
      title: "Setup needed",
      body: "Body",
      options: [{ id: "ok", label: "OK" }],
      action_id: "act1",
      timeout_seconds: null,
    };

    expect(parseSnapshot({
      ...snapshot,
      state: "prompt",
      prompt: { ...prompt, title: "x".repeat(65) },
    })).toBeNull();
    expect(parseSnapshot({
      ...snapshot,
      state: "prompt",
      prompt: { ...prompt, options: [{ id: "ok", label: "x".repeat(49) }] },
    })).toBeNull();
  });
});

describe("parseAction", () => {
  it("accepts the normalized prompt choice payload", () => {
    expect(parseAction({
      type: "action",
      schema: 1,
      action_id: "sethome",
      choice: "yes",
    })).toEqual({
      type: "action",
      schema: 1,
      action_id: "sethome",
      choice: "yes",
    });
  });

  it.each([
    { type: "action", schema: 2, action_id: "sethome", choice: "yes" },
    { type: "action", schema: 1, action_id: "", choice: "yes" },
    { type: "action", schema: 1, action_id: "sethome", choice: "" },
    { type: "action", schema: 1, action_id: "sethome", choice: 1 },
  ])("rejects malformed action %#", (raw) => {
    expect(parseAction(raw)).toBeNull();
  });
});
