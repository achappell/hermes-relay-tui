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
};

describe("parseSnapshot", () => {
  it("accepts a schema-1 snapshot with an approved state", () => {
    expect(parseSnapshot(snapshot)).toEqual(snapshot);
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
