import { describe, expect, it } from "vitest";

import badTimeout from "../../../../shared/display/fixtures/invalid/bad_timeout.json";
import emptyOptions from "../../../../shared/display/fixtures/invalid/empty_options.json";
import missingType from "../../../../shared/display/fixtures/invalid/missing_type.json";
import negativeSequence from "../../../../shared/display/fixtures/invalid/negative_sequence.json";
import nullSnapshot from "../../../../shared/display/fixtures/invalid/null_snapshot.json";
import promptMissing from "../../../../shared/display/fixtures/invalid/prompt_missing.json";
import promptOnIdle from "../../../../shared/display/fixtures/invalid/prompt_on_idle.json";
import unknownState from "../../../../shared/display/fixtures/invalid/unknown_state.json";
import buffering from "../../../../shared/display/fixtures/snapshots/buffering.json";
import disconnected from "../../../../shared/display/fixtures/snapshots/disconnected.json";
import error from "../../../../shared/display/fixtures/snapshots/error.json";
import heard from "../../../../shared/display/fixtures/snapshots/heard.json";
import idle from "../../../../shared/display/fixtures/snapshots/idle.json";
import legacyIdle from "../../../../shared/display/fixtures/snapshots/legacy_idle.json";
import listening from "../../../../shared/display/fixtures/snapshots/listening.json";
import prompt from "../../../../shared/display/fixtures/snapshots/prompt.json";
import promptChooseOnly from "../../../../shared/display/fixtures/snapshots/prompt_choose_only.json";
import speaking from "../../../../shared/display/fixtures/snapshots/speaking.json";
import thinking from "../../../../shared/display/fixtures/snapshots/thinking.json";
import unknownField from "../../../../shared/display/fixtures/snapshots/unknown_field.json";
import { parseSnapshot } from "./protocol";
import { createDisplayReducer } from "./reducer";

const validSnapshots = [
  idle,
  legacyIdle,
  unknownField,
  heard,
  listening,
  thinking,
  speaking,
  buffering,
  error,
  disconnected,
  prompt,
  promptChooseOnly,
];

const invalidSnapshots = [
  badTimeout,
  emptyOptions,
  missingType,
  negativeSequence,
  nullSnapshot,
  promptMissing,
  promptOnIdle,
  unknownState,
];

describe("shared display fixture conformance", () => {
  it.each(validSnapshots)("accepts the valid %j snapshot", (fixture) => {
    const parsed = parseSnapshot(fixture);

    expect(parsed).not.toBeNull();
    expect(parsed).toMatchObject({
      type: "snapshot",
      schema: 1,
      sequence: fixture.sequence,
      state: fixture.state,
      response_text: fixture.response_text,
      status_text: fixture.status_text ?? null,
      media: fixture.media ?? null,
      prompt: fixture.prompt ?? null,
    });
  });

  it.each(invalidSnapshots)("rejects the invalid %j snapshot", (fixture) => {
    expect(parseSnapshot(fixture)).toBeNull();
  });

  it.each(validSnapshots)("normalizes the valid %j snapshot like the shared reducer", (fixture) => {
    const parsed = parseSnapshot(fixture);
    expect(parsed).not.toBeNull();
    if (parsed === null) return;

    const result = createDisplayReducer().applySnapshot(parsed);
    const capabilities = "capabilities" in fixture ? fixture.capabilities : undefined;

    expect(result).toMatchObject({
      kind: "accepted",
      view: {
        state: fixture.state,
        sequence: fixture.sequence,
        is_busy: ["listening", "thinking", "speaking", "buffering"].includes(fixture.state),
        connection_healthy: !["error", "disconnected"].includes(fixture.state),
        can_choose: fixture.state === "prompt" &&
          capabilities?.actions.includes("prompt.choose") === true,
        can_dismiss: fixture.state === "prompt" &&
          capabilities?.actions.includes("prompt.dismiss") === true,
      },
    });
  });
});
