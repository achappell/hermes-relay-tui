import { mount } from "svelte";
import App from "./App.svelte";

const target = document.getElementById("app");

if (target === null) {
  throw new Error("Home display mount point is missing");
}

mount(App, { target });
