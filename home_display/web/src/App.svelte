<script lang="ts">
  import { onMount } from "svelte";
  import "./styles.css";
  import StateSurface from "./surfaces/StateSurface.svelte";
  import { StateChannel, type ConnectionState } from "./state/channel";
  import type { DisplaySnapshot } from "./state/protocol";

  const initialSnapshot: DisplaySnapshot = {
    type: "snapshot",
    schema: 1,
    sequence: 0,
    state: "idle",
    response_text: "",
    status_text: null,
    media: null,
  };

  let snapshot = initialSnapshot;
  let connectionState: ConnectionState = "connecting";
  let protocolError: string | null = null;

  const stateChannelUrl = () => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/state`;
  };

  onMount(() => {
    const channel = new StateChannel(
      stateChannelUrl(),
      (nextSnapshot) => {
        snapshot = nextSnapshot;
        protocolError = null;
      },
      (nextConnectionState) => {
        connectionState = nextConnectionState;
      },
      (message) => {
        protocolError = message;
      },
    );
    channel.start();

    return () => channel.stop();
  });
</script>

<StateSurface {snapshot} {connectionState} {protocolError} />
