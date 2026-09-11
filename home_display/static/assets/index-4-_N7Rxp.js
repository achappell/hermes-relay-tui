var __defProp = Object.defineProperty;
var __typeError = (msg) => {
  throw TypeError(msg);
};
var __defNormalProp = (obj, key2, value) => key2 in obj ? __defProp(obj, key2, { enumerable: true, configurable: true, writable: true, value }) : obj[key2] = value;
var __publicField = (obj, key2, value) => __defNormalProp(obj, typeof key2 !== "symbol" ? key2 + "" : key2, value);
var __accessCheck = (obj, member, msg) => member.has(obj) || __typeError("Cannot " + msg);
var __privateGet = (obj, member, getter) => (__accessCheck(obj, member, "read from private field"), getter ? getter.call(obj) : member.get(obj));
var __privateAdd = (obj, member, value) => member.has(obj) ? __typeError("Cannot add the same private member more than once") : member instanceof WeakSet ? member.add(obj) : member.set(obj, value);
var __privateSet = (obj, member, value, setter) => (__accessCheck(obj, member, "write to private field"), setter ? setter.call(obj, value) : member.set(obj, value), value);
var __privateMethod = (obj, member, method) => (__accessCheck(obj, member, "access private method"), method);
var _started, _prev, _next, _commit_callbacks, _discard_callbacks, _pending, _blocking_pending, _deferred, _roots, _new_effects, _dirty_effects, _maybe_dirty_effects, _skipped_branches, _unskipped_branches, _decrement_queued, _Batch_instances, is_deferred_fn, process_fn, traverse_fn, find_earlier_batch_fn, merge_fn, defer_effects_fn, commit_fn, unlink_fn, _a, _anchor, _hydrate_open, _props, _children, _effect, _main_effect, _pending_effect, _failed_effect, _offscreen_fragment, _local_pending_count, _pending_count, _pending_count_update_queued, _dirty_effects2, _maybe_dirty_effects2, _effect_pending, _effect_pending_subscriber, _Boundary_instances, hydrate_resolved_content_fn, hydrate_failed_content_fn, create_reset_fn, hydrate_pending_content_fn, render_fn, resolve_fn, run_fn, update_pending_count_fn, handle_error_fn, _batches, _onscreen, _offscreen, _outroing, _transition, _commit, _discard, _b;
(function polyfill() {
  const relList = document.createElement("link").relList;
  if (relList && relList.supports && relList.supports("modulepreload")) {
    return;
  }
  for (const link2 of document.querySelectorAll('link[rel="modulepreload"]')) {
    processPreload(link2);
  }
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type !== "childList") {
        continue;
      }
      for (const node of mutation.addedNodes) {
        if (node.tagName === "LINK" && node.rel === "modulepreload")
          processPreload(node);
      }
    }
  }).observe(document, { childList: true, subtree: true });
  function getFetchOpts(link2) {
    const fetchOpts = {};
    if (link2.integrity) fetchOpts.integrity = link2.integrity;
    if (link2.referrerPolicy) fetchOpts.referrerPolicy = link2.referrerPolicy;
    if (link2.crossOrigin === "use-credentials")
      fetchOpts.credentials = "include";
    else if (link2.crossOrigin === "anonymous") fetchOpts.credentials = "omit";
    else fetchOpts.credentials = "same-origin";
    return fetchOpts;
  }
  function processPreload(link2) {
    if (link2.ep)
      return;
    link2.ep = true;
    const fetchOpts = getFetchOpts(link2);
    fetch(link2.href, fetchOpts);
  }
})();
const DEV = false;
var is_array = Array.isArray;
var index_of = Array.prototype.indexOf;
var includes = Array.prototype.includes;
var array_from = Array.from;
var define_property = Object.defineProperty;
var get_descriptor = Object.getOwnPropertyDescriptor;
var get_descriptors = Object.getOwnPropertyDescriptors;
var object_prototype = Object.prototype;
var array_prototype = Array.prototype;
var get_prototype_of = Object.getPrototypeOf;
var is_extensible = Object.isExtensible;
const noop = () => {
};
function run(fn) {
  return fn();
}
function run_all(arr) {
  for (var i = 0; i < arr.length; i++) {
    arr[i]();
  }
}
function deferred() {
  var resolve;
  var reject;
  var promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
const DERIVED = 1 << 1;
const EFFECT = 1 << 2;
const RENDER_EFFECT = 1 << 3;
const MANAGED_EFFECT = 1 << 24;
const BLOCK_EFFECT = 1 << 4;
const BRANCH_EFFECT = 1 << 5;
const ROOT_EFFECT = 1 << 6;
const BOUNDARY_EFFECT = 1 << 7;
const PAUSED = 1 << 8;
const CONNECTED = 1 << 9;
const CLEAN = 1 << 10;
const DIRTY = 1 << 11;
const MAYBE_DIRTY = 1 << 12;
const INERT = 1 << 13;
const DESTROYED = 1 << 14;
const REACTION_RAN = 1 << 15;
const DESTROYING = 1 << 25;
const EFFECT_TRANSPARENT = 1 << 16;
const EAGER_EFFECT = 1 << 17;
const HEAD_EFFECT = 1 << 18;
const EFFECT_PRESERVED = 1 << 19;
const USER_EFFECT = 1 << 20;
const EFFECT_OFFSCREEN = 1 << 25;
const WAS_MARKED = 1 << 16;
const REACTION_IS_UPDATING = 1 << 21;
const ASYNC = 1 << 22;
const ERROR_VALUE = 1 << 23;
const STATE_SYMBOL = Symbol("$state");
const COMPONENT_SYMBOL = Symbol("component");
const LEGACY_PROPS = Symbol("legacy props");
const LOADING_ATTR_SYMBOL = Symbol("");
const ATTRIBUTES_CACHE = Symbol("attributes");
const CLASS_CACHE = Symbol("class");
const STYLE_CACHE = Symbol("style");
const TEXT_CACHE = Symbol("text");
const STALE_REACTION = new class StaleReactionError extends Error {
  constructor() {
    super(...arguments);
    __publicField(this, "name", "StaleReactionError");
    __publicField(this, "message", "The reaction that called `getAbortSignal()` was re-run or destroyed");
  }
}();
const EACH_ITEM_REACTIVE = 1;
const EACH_INDEX_REACTIVE = 1 << 1;
const EACH_ITEM_IMMUTABLE = 1 << 4;
const PROPS_IS_RUNES = 1 << 1;
const PROPS_IS_UPDATED = 1 << 2;
const PROPS_IS_BINDABLE = 1 << 3;
const TEMPLATE_FRAGMENT = 1;
const TEMPLATE_USE_IMPORT_NODE = 1 << 1;
const UNINITIALIZED = Symbol("uninitialized");
const NAMESPACE_HTML = "http://www.w3.org/1999/xhtml";
function derived_inert() {
  {
    console.warn(`https://svelte.dev/e/derived_inert`);
  }
}
function svelte_boundary_reset_noop() {
  {
    console.warn(`https://svelte.dev/e/svelte_boundary_reset_noop`);
  }
}
function equals(value) {
  return value === this.v;
}
function safe_not_equal(a, b) {
  return a != a ? b == b : a !== b || a !== null && typeof a === "object" || typeof a === "function";
}
function safe_equals(value) {
  return !safe_not_equal(value, this.v);
}
function lifecycle_outside_component(name) {
  {
    throw new Error(`https://svelte.dev/e/lifecycle_outside_component`);
  }
}
function async_derived_orphan() {
  {
    throw new Error(`https://svelte.dev/e/async_derived_orphan`);
  }
}
function each_key_duplicate(a, b, value) {
  {
    throw new Error(`https://svelte.dev/e/each_key_duplicate`);
  }
}
function effect_in_teardown(rune) {
  {
    throw new Error(`https://svelte.dev/e/effect_in_teardown`);
  }
}
function effect_in_unowned_derived() {
  {
    throw new Error(`https://svelte.dev/e/effect_in_unowned_derived`);
  }
}
function effect_orphan(rune) {
  {
    throw new Error(`https://svelte.dev/e/effect_orphan`);
  }
}
function effect_update_depth_exceeded() {
  {
    throw new Error(`https://svelte.dev/e/effect_update_depth_exceeded`);
  }
}
function lifecycle_legacy_only(name) {
  {
    throw new Error(`https://svelte.dev/e/lifecycle_legacy_only`);
  }
}
function props_invalid_value(key2) {
  {
    throw new Error(`https://svelte.dev/e/props_invalid_value`);
  }
}
function state_descriptors_fixed() {
  {
    throw new Error(`https://svelte.dev/e/state_descriptors_fixed`);
  }
}
function state_prototype_fixed() {
  {
    throw new Error(`https://svelte.dev/e/state_prototype_fixed`);
  }
}
function state_unsafe_mutation() {
  {
    throw new Error(`https://svelte.dev/e/state_unsafe_mutation`);
  }
}
function svelte_boundary_reset_onerror() {
  {
    throw new Error(`https://svelte.dev/e/svelte_boundary_reset_onerror`);
  }
}
let legacy_mode_flag = false;
let tracing_mode_flag = false;
function enable_legacy_mode_flag() {
  legacy_mode_flag = true;
}
let component_context = null;
function set_component_context(context) {
  component_context = context;
}
function push(props, runes = false, fn) {
  component_context = {
    p: component_context,
    i: false,
    c: null,
    e: null,
    s: props,
    x: null,
    r: (
      /** @type {Effect} */
      active_effect
    ),
    l: legacy_mode_flag && !runes ? { s: null, u: null, $: [] } : null
  };
}
function pop(component) {
  var context = (
    /** @type {ComponentContext} */
    component_context
  );
  var effects = context.e;
  if (effects !== null) {
    context.e = null;
    for (var fn of effects) {
      create_user_effect(fn);
    }
  }
  context.i = true;
  component_context = context.p;
  return mark_as_component(component);
}
function mark_as_component(component = {}) {
  define_property(component, COMPONENT_SYMBOL, { value: true });
  return component;
}
function is_runes() {
  return !legacy_mode_flag || component_context !== null && component_context.l === null;
}
let micro_tasks = [];
function run_micro_tasks() {
  var tasks = micro_tasks;
  micro_tasks = [];
  run_all(tasks);
}
function queue_micro_task(fn) {
  if (micro_tasks.length === 0 && true) {
    var tasks = micro_tasks;
    queueMicrotask(() => {
      if (tasks === micro_tasks) run_micro_tasks();
    });
  }
  micro_tasks.push(fn);
}
const STATUS_MASK = -7169;
function set_signal_status(signal, status) {
  signal.f = signal.f & STATUS_MASK | status;
}
function update_derived_status(derived2) {
  if ((derived2.f & CONNECTED) !== 0 || derived2.deps === null) {
    set_signal_status(derived2, CLEAN);
  } else {
    set_signal_status(derived2, MAYBE_DIRTY);
  }
}
function clear_marked(deps) {
  if (deps === null) return;
  for (const dep of deps) {
    if ((dep.f & DERIVED) === 0 || (dep.f & WAS_MARKED) === 0) {
      continue;
    }
    dep.f ^= WAS_MARKED;
    clear_marked(
      /** @type {Derived} */
      dep.deps
    );
  }
}
function defer_effect(effect2, dirty_effects, maybe_dirty_effects) {
  if ((effect2.f & DIRTY) !== 0) {
    dirty_effects.add(effect2);
  } else if ((effect2.f & MAYBE_DIRTY) !== 0) {
    maybe_dirty_effects.add(effect2);
  }
  clear_marked(effect2.deps);
  set_signal_status(effect2, CLEAN);
}
let is_store_binding = false;
function capture_store_binding(fn) {
  var previous_is_store_binding = is_store_binding;
  try {
    is_store_binding = false;
    return [fn(), is_store_binding];
  } finally {
    is_store_binding = previous_is_store_binding;
  }
}
function without_reactive_context(fn) {
  var previous_reaction = active_reaction;
  var previous_effect = active_effect;
  set_active_reaction(null);
  set_active_effect(null);
  try {
    return fn();
  } finally {
    set_active_reaction(previous_reaction);
    set_active_effect(previous_effect);
  }
}
function flatten(blockers, sync, async, fn) {
  const d = is_runes() ? derived : derived_safe_equal;
  var pending = blockers.filter((b) => !b.settled);
  var deriveds = sync.map(d);
  if (async.length === 0 && pending.length === 0) {
    fn(deriveds);
    return;
  }
  var parent = (
    /** @type {Effect} */
    active_effect
  );
  var restore = capture();
  var blocker_promise = pending.length === 1 ? pending[0].promise : pending.length > 1 ? Promise.all(pending.map((b) => b.promise)) : null;
  function finish(async2) {
    if ((parent.f & DESTROYED) !== 0) {
      return;
    }
    restore();
    try {
      fn([...deriveds, ...async2]);
    } catch (error) {
      invoke_error_boundary(error, parent);
    }
    unset_context();
  }
  var decrement_pending = increment_pending();
  if (async.length === 0) {
    blocker_promise.then(() => finish([])).finally(decrement_pending);
    return;
  }
  function run2() {
    Promise.all(async.map((expression) => /* @__PURE__ */ async_derived(expression))).then(finish).catch((error) => invoke_error_boundary(error, parent)).finally(decrement_pending);
  }
  if (blocker_promise) {
    blocker_promise.then(() => {
      restore();
      run2();
      unset_context();
    });
  } else {
    run2();
  }
}
function capture() {
  var previous_effect = (
    /** @type {Effect} */
    active_effect
  );
  var previous_reaction = active_reaction;
  var previous_component_context = component_context;
  var previous_batch2 = (
    /** @type {Batch} */
    current_batch
  );
  return function restore(activate_batch = true) {
    set_active_effect(previous_effect);
    set_active_reaction(previous_reaction);
    set_component_context(previous_component_context);
    if (activate_batch && (previous_effect.f & DESTROYED) === 0) {
      previous_batch2 == null ? void 0 : previous_batch2.activate();
      previous_batch2 == null ? void 0 : previous_batch2.apply();
    }
  };
}
function unset_context(deactivate_batch = true) {
  set_active_effect(null);
  set_active_reaction(null);
  set_component_context(null);
  if (deactivate_batch) current_batch == null ? void 0 : current_batch.deactivate();
}
function increment_pending() {
  var effect2 = (
    /** @type {Effect} */
    active_effect
  );
  var boundary2 = effect2.b;
  var batch = (
    /** @type {Batch} */
    current_batch
  );
  var blocking = !!(boundary2 == null ? void 0 : boundary2.is_rendered());
  boundary2 == null ? void 0 : boundary2.update_pending_count(1, batch);
  batch.increment(blocking, effect2);
  return () => {
    boundary2 == null ? void 0 : boundary2.update_pending_count(-1, batch);
    batch.decrement(blocking, effect2);
  };
}
// @__NO_SIDE_EFFECTS__
function derived(fn) {
  var flags2 = DERIVED | DIRTY;
  if (active_effect !== null) {
    active_effect.f |= EFFECT_PRESERVED;
  }
  const signal = {
    ctx: component_context,
    deps: null,
    effects: null,
    equals,
    f: flags2,
    fn,
    reactions: null,
    rv: 0,
    v: (
      /** @type {V} */
      UNINITIALIZED
    ),
    wv: 0,
    parent: active_effect,
    ac: null
  };
  return signal;
}
const OBSOLETE = Symbol("obsolete");
// @__NO_SIDE_EFFECTS__
function async_derived(fn, label, location) {
  let parent = (
    /** @type {Effect | null} */
    active_effect
  );
  if (parent === null) {
    async_derived_orphan();
  }
  var promise = (
    /** @type {Promise<V>} */
    /** @type {unknown} */
    void 0
  );
  var signal = source(
    /** @type {V} */
    UNINITIALIZED
  );
  var should_suspend = !active_reaction;
  var deferreds = /* @__PURE__ */ new Set();
  async_effect(() => {
    var _a2, _b2;
    var effect2 = (
      /** @type {Effect} */
      active_effect
    );
    var d = deferred();
    promise = d.promise;
    try {
      Promise.resolve(fn()).then(d.resolve, (e) => {
        if (e !== STALE_REACTION) d.reject(e);
      }).finally(unset_context);
    } catch (error) {
      d.reject(error);
      unset_context();
    }
    var batch = (
      /** @type {Batch} */
      current_batch
    );
    if (should_suspend) {
      if ((effect2.f & REACTION_RAN) !== 0) {
        var decrement_pending = increment_pending();
      }
      if (
        // boundary can be null if the async derived is inside an $effect.root not connected to the component render tree
        (_a2 = parent.b) == null ? void 0 : _a2.is_rendered()
      ) {
        (_b2 = batch.async_deriveds.get(effect2)) == null ? void 0 : _b2.reject(OBSOLETE);
      } else {
        for (const d2 of deferreds.values()) {
          d2.reject(OBSOLETE);
        }
      }
      deferreds.add(d);
      batch.async_deriveds.set(effect2, d);
    }
    const handler = (value, error = void 0) => {
      decrement_pending == null ? void 0 : decrement_pending();
      deferreds.delete(d);
      if (error === OBSOLETE) return;
      batch.activate();
      if (error) {
        signal.f |= ERROR_VALUE;
        internal_set(signal, error);
      } else {
        if ((signal.f & ERROR_VALUE) !== 0) {
          signal.f ^= ERROR_VALUE;
        }
        internal_set(signal, value);
      }
      batch.deactivate();
    };
    d.promise.then(handler, (e) => handler(null, e || "unknown"));
  });
  teardown(() => {
    for (const d of deferreds) {
      d.reject(OBSOLETE);
    }
  });
  return new Promise((fulfil) => {
    function next(p) {
      function go() {
        if (p === promise) {
          fulfil(signal);
        } else {
          next(promise);
        }
      }
      p.then(go, go);
    }
    next(promise);
  });
}
// @__NO_SIDE_EFFECTS__
function derived_safe_equal(fn) {
  const signal = /* @__PURE__ */ derived(fn);
  signal.equals = safe_equals;
  return signal;
}
function destroy_derived_effects(derived2) {
  var effects = derived2.effects;
  if (effects !== null) {
    derived2.effects = null;
    for (var i = 0; i < effects.length; i += 1) {
      destroy_effect(
        /** @type {Effect} */
        effects[i]
      );
    }
  }
}
function execute_derived(derived2) {
  var value;
  var prev_active_effect = active_effect;
  var parent = derived2.parent;
  if (!is_destroying_effect && parent !== null && derived2.v !== UNINITIALIZED && // if it was never evaluated before, it's guaranteed to fail downstream, so we try to execute instead
  (parent.f & (DESTROYED | INERT)) !== 0) {
    derived_inert();
    return derived2.v;
  }
  set_active_effect(parent);
  {
    try {
      derived2.f &= ~WAS_MARKED;
      destroy_derived_effects(derived2);
      value = update_reaction(derived2);
    } finally {
      set_active_effect(prev_active_effect);
    }
  }
  return value;
}
function update_derived(derived2) {
  var value = execute_derived(derived2);
  if (!derived2.equals(value)) {
    derived2.wv = increment_write_version();
    if (!(current_batch == null ? void 0 : current_batch.is_fork) || derived2.deps === null) {
      if (current_batch !== null) {
        current_batch.capture(derived2, value, true);
        previous_batch == null ? void 0 : previous_batch.capture(derived2, value, true);
      } else {
        derived2.v = value;
      }
      if (derived2.deps === null) {
        set_signal_status(derived2, CLEAN);
        return;
      }
    }
  }
  if (is_destroying_effect) {
    return;
  }
  if (batch_values !== null) {
    if (effect_tracking() || (current_batch == null ? void 0 : current_batch.is_fork)) {
      batch_values.set(derived2, value);
    }
  } else {
    update_derived_status(derived2);
  }
}
function freeze_derived_effects(derived2) {
  var _a2;
  if (derived2.effects === null) return;
  for (const e of derived2.effects) {
    if (e.teardown || e.ac) {
      (_a2 = e.teardown) == null ? void 0 : _a2.call(e);
      if (e.ac !== null) {
        without_reactive_context(() => {
          e.ac.abort(STALE_REACTION);
          e.ac = null;
        });
      }
      if (e.fn !== null) e.teardown = noop;
      remove_reactions(e, 0);
      destroy_effect_children(e);
    }
  }
}
function unfreeze_derived_effects(derived2) {
  if (derived2.effects === null) return;
  for (const e of derived2.effects) {
    if (e.teardown && e.fn !== null) {
      update_effect(e);
    }
  }
}
let first_batch = null;
let last_batch = null;
let current_batch = null;
let previous_batch = null;
let batch_values = null;
let last_scheduled_effect = null;
let is_processing = false;
let collected_effects = null;
let legacy_updates = null;
var flush_count = 0;
var source_stacks = /* @__PURE__ */ new Set();
let uid = 1;
const _Batch = class _Batch {
  constructor() {
    __privateAdd(this, _Batch_instances);
    __publicField(this, "id", uid++);
    /** True as soon as `#process` was called */
    __privateAdd(this, _started, false);
    __publicField(this, "linked", true);
    /** @type {Batch | null} */
    __privateAdd(this, _prev, null);
    /** @type {Batch | null} */
    __privateAdd(this, _next, null);
    /** @type {Map<Effect, ReturnType<typeof deferred<any>>>} */
    __publicField(this, "async_deriveds", /* @__PURE__ */ new Map());
    /**
     * The current values of any signals that are updated in this batch.
     * Tuple format: [value, is_derived] (note: is_derived is false for deriveds, too, if they were overridden via assignment)
     * They keys of this map are identical to `this.#previous`
     * @type {Map<Value, [any, boolean]>}
     */
    __publicField(this, "current", /* @__PURE__ */ new Map());
    /**
     * The values of any signals (sources and deriveds) that are updated in this batch _before_ those updates took place.
     * They keys of this map are identical to `this.#current`
     * @type {Map<Value, any>}
     */
    __publicField(this, "previous", /* @__PURE__ */ new Map());
    /**
     * When the batch is committed (and the DOM is updated), we need to remove old branches
     * and append new ones by calling the functions added inside (if/each/key/etc) blocks
     * @type {Set<(batch: Batch) => void>}
     */
    __privateAdd(this, _commit_callbacks, /* @__PURE__ */ new Set());
    /**
     * If a fork is discarded, we need to destroy any effects that are no longer needed
     * @type {Set<(batch: Batch) => void>}
     */
    __privateAdd(this, _discard_callbacks, /* @__PURE__ */ new Set());
    /**
     * The number of async effects that are currently in flight
     */
    __privateAdd(this, _pending, 0);
    /**
     * Async effects that are currently in flight, _not_ inside a pending boundary
     * @type {Map<Effect, number>}
     */
    __privateAdd(this, _blocking_pending, /* @__PURE__ */ new Map());
    /**
     * A deferred that resolves when the batch is committed, used with `settled()`
     * TODO replace with Promise.withResolvers once supported widely enough
     * @type {{ promise: Promise<void>, resolve: (value?: any) => void, reject: (reason: unknown) => void } | null}
     */
    __privateAdd(this, _deferred, null);
    /**
     * The root effects that need to be flushed
     * @type {Effect[]}
     */
    __privateAdd(this, _roots, []);
    /**
     * Effects created while this batch was active.
     * @type {Effect[]}
     */
    __privateAdd(this, _new_effects, []);
    /**
     * Deferred effects (which run after async work has completed) that are DIRTY
     * @type {Set<Effect>}
     */
    __privateAdd(this, _dirty_effects, /* @__PURE__ */ new Set());
    /**
     * Deferred effects that are MAYBE_DIRTY
     * @type {Set<Effect>}
     */
    __privateAdd(this, _maybe_dirty_effects, /* @__PURE__ */ new Set());
    /**
     * A map of branches that still exist, but will be destroyed when this batch
     * is committed — we skip over these during `process`.
     * The value contains child effects that were dirty/maybe_dirty before being reset,
     * so they can be rescheduled if the branch survives.
     * @type {Map<Effect, { d: Effect[], m: Effect[] }>}
     */
    __privateAdd(this, _skipped_branches, /* @__PURE__ */ new Map());
    /**
     * Inverse of #skipped_branches which we need to tell prior batches to unskip them when committing
     * @type {Set<Effect>}
     */
    __privateAdd(this, _unskipped_branches, /* @__PURE__ */ new Set());
    __publicField(this, "is_fork", false);
    __privateAdd(this, _decrement_queued, false);
    if (last_batch === null) {
      first_batch = last_batch = this;
    } else {
      __privateSet(last_batch, _next, this);
      __privateSet(this, _prev, last_batch);
    }
    last_batch = this;
  }
  /**
   * Add an effect to the #skipped_branches map and reset its children
   * @param {Effect} effect
   */
  skip_effect(effect2) {
    if (!__privateGet(this, _skipped_branches).has(effect2)) {
      __privateGet(this, _skipped_branches).set(effect2, { d: [], m: [] });
    }
    __privateGet(this, _unskipped_branches).delete(effect2);
  }
  /**
   * Remove an effect from the #skipped_branches map and reschedule
   * any tracked dirty/maybe_dirty child effects
   * @param {Effect} effect
   * @param {(e: Effect) => void} callback
   */
  unskip_effect(effect2, callback = (e) => this.schedule(e)) {
    var tracked = __privateGet(this, _skipped_branches).get(effect2);
    if (tracked) {
      __privateGet(this, _skipped_branches).delete(effect2);
      for (var e of tracked.d) {
        set_signal_status(e, DIRTY);
        callback(e);
      }
      for (e of tracked.m) {
        set_signal_status(e, MAYBE_DIRTY);
        callback(e);
      }
    }
    __privateGet(this, _unskipped_branches).add(effect2);
  }
  /**
   * Associate a change to a given source with the current
   * batch, noting its previous and current values
   * @param {Value} source
   * @param {any} value
   * @param {boolean} [is_derived]
   */
  capture(source2, value, is_derived = false) {
    if (source2.v !== UNINITIALIZED && !this.previous.has(source2)) {
      this.previous.set(source2, source2.v);
    }
    if ((source2.f & ERROR_VALUE) === 0) {
      this.current.set(source2, [value, is_derived]);
      batch_values == null ? void 0 : batch_values.set(source2, value);
    }
    if (!this.is_fork) {
      source2.v = value;
    }
  }
  activate() {
    current_batch = this;
  }
  deactivate() {
    current_batch = null;
    batch_values = null;
  }
  flush() {
    try {
      if (DEV) ;
      is_processing = true;
      current_batch = this;
      __privateMethod(this, _Batch_instances, process_fn).call(this);
    } finally {
      flush_count = 0;
      last_scheduled_effect = null;
      collected_effects = null;
      legacy_updates = null;
      is_processing = false;
      current_batch = null;
      batch_values = null;
      old_values.clear();
    }
  }
  discard() {
    var _a2;
    for (const fn of __privateGet(this, _discard_callbacks)) fn(this);
    __privateGet(this, _discard_callbacks).clear();
    for (const deferred2 of this.async_deriveds.values()) {
      deferred2.reject(OBSOLETE);
    }
    __privateMethod(this, _Batch_instances, unlink_fn).call(this);
    (_a2 = __privateGet(this, _deferred)) == null ? void 0 : _a2.resolve();
  }
  /**
   * @param {Effect} effect
   */
  register_created_effect(effect2) {
    __privateGet(this, _new_effects).push(effect2);
  }
  /**
   * @param {boolean} blocking
   * @param {Effect} effect
   */
  increment(blocking, effect2) {
    __privateSet(this, _pending, __privateGet(this, _pending) + 1);
    if (blocking) {
      let blocking_pending_count = __privateGet(this, _blocking_pending).get(effect2) ?? 0;
      __privateGet(this, _blocking_pending).set(effect2, blocking_pending_count + 1);
    }
  }
  /**
   * @param {boolean} blocking
   * @param {Effect} effect
   */
  decrement(blocking, effect2) {
    __privateSet(this, _pending, __privateGet(this, _pending) - 1);
    if (blocking) {
      let blocking_pending_count = __privateGet(this, _blocking_pending).get(effect2) ?? 0;
      if (blocking_pending_count === 1) {
        __privateGet(this, _blocking_pending).delete(effect2);
      } else {
        __privateGet(this, _blocking_pending).set(effect2, blocking_pending_count - 1);
      }
    }
    if (__privateGet(this, _decrement_queued)) return;
    __privateSet(this, _decrement_queued, true);
    queue_micro_task(() => {
      __privateSet(this, _decrement_queued, false);
      if (this.linked) {
        this.flush();
      }
    });
  }
  /**
   * @param {Set<Effect>} dirty_effects
   * @param {Set<Effect>} maybe_dirty_effects
   */
  transfer_effects(dirty_effects, maybe_dirty_effects) {
    for (const e of dirty_effects) {
      __privateGet(this, _dirty_effects).add(e);
    }
    for (const e of maybe_dirty_effects) {
      __privateGet(this, _maybe_dirty_effects).add(e);
    }
    dirty_effects.clear();
    maybe_dirty_effects.clear();
  }
  /** @param {(batch: Batch) => void} fn */
  oncommit(fn) {
    __privateGet(this, _commit_callbacks).add(fn);
  }
  /** @param {(batch: Batch) => void} fn */
  ondiscard(fn) {
    __privateGet(this, _discard_callbacks).add(fn);
  }
  settled() {
    return (__privateGet(this, _deferred) ?? __privateSet(this, _deferred, deferred())).promise;
  }
  static ensure() {
    if (current_batch === null) {
      const batch = current_batch = new _Batch();
      if (!is_processing && true) {
        queue_micro_task(() => {
          if (!__privateGet(batch, _started)) {
            batch.flush();
          }
        });
      }
    }
    return current_batch;
  }
  apply() {
    {
      batch_values = null;
      return;
    }
  }
  /**
   *
   * @param {Effect} effect
   */
  schedule(effect2) {
    var _a2;
    last_scheduled_effect = effect2;
    if (((_a2 = effect2.b) == null ? void 0 : _a2.is_pending) && (effect2.f & (EFFECT | RENDER_EFFECT | MANAGED_EFFECT)) !== 0 && (effect2.f & REACTION_RAN) === 0) {
      effect2.b.defer_effect(effect2);
      return;
    }
    var e = effect2;
    while (e.parent !== null) {
      e = e.parent;
      var flags2 = e.f;
      if (collected_effects !== null && e === active_effect) {
        if ((active_reaction === null || (active_reaction.f & DERIVED) === 0) && true) {
          return;
        }
      }
      if ((flags2 & (ROOT_EFFECT | BRANCH_EFFECT)) !== 0) {
        if ((flags2 & CLEAN) === 0) {
          return;
        }
        e.f ^= CLEAN;
      }
    }
    __privateGet(this, _roots).push(e);
  }
};
_started = new WeakMap();
_prev = new WeakMap();
_next = new WeakMap();
_commit_callbacks = new WeakMap();
_discard_callbacks = new WeakMap();
_pending = new WeakMap();
_blocking_pending = new WeakMap();
_deferred = new WeakMap();
_roots = new WeakMap();
_new_effects = new WeakMap();
_dirty_effects = new WeakMap();
_maybe_dirty_effects = new WeakMap();
_skipped_branches = new WeakMap();
_unskipped_branches = new WeakMap();
_decrement_queued = new WeakMap();
_Batch_instances = new WeakSet();
is_deferred_fn = function() {
  if (this.is_fork) return true;
  for (const effect2 of __privateGet(this, _blocking_pending).keys()) {
    var e = effect2;
    var skipped = false;
    while (e.parent !== null) {
      if (__privateGet(this, _skipped_branches).has(e)) {
        skipped = true;
        break;
      }
      e = e.parent;
    }
    if (!skipped) {
      return true;
    }
  }
  return false;
};
process_fn = function() {
  var _a2, _b2, _c, _d;
  __privateSet(this, _started, true);
  if (flush_count++ > 1e3) {
    __privateMethod(this, _Batch_instances, unlink_fn).call(this);
    infinite_loop_guard();
  }
  for (const e of __privateGet(this, _dirty_effects)) {
    __privateGet(this, _maybe_dirty_effects).delete(e);
    set_signal_status(e, DIRTY);
    this.schedule(e);
  }
  for (const e of __privateGet(this, _maybe_dirty_effects)) {
    set_signal_status(e, MAYBE_DIRTY);
    this.schedule(e);
  }
  const roots = __privateGet(this, _roots);
  __privateSet(this, _roots, []);
  this.apply();
  var effects = collected_effects = [];
  var render_effects = [];
  var updates = legacy_updates = [];
  for (const root2 of roots) {
    try {
      __privateMethod(this, _Batch_instances, traverse_fn).call(this, root2, effects, render_effects);
    } catch (e) {
      reset_all(root2);
      if (!__privateMethod(this, _Batch_instances, is_deferred_fn).call(this)) this.discard();
      throw e;
    }
  }
  current_batch = null;
  if (updates.length > 0) {
    var batch = _Batch.ensure();
    for (const e of updates) {
      batch.schedule(e);
    }
  }
  collected_effects = null;
  legacy_updates = null;
  if (__privateMethod(this, _Batch_instances, is_deferred_fn).call(this)) {
    __privateMethod(this, _Batch_instances, defer_effects_fn).call(this, render_effects);
    __privateMethod(this, _Batch_instances, defer_effects_fn).call(this, effects);
    for (const [e, t] of __privateGet(this, _skipped_branches)) {
      reset_branch(e, t);
    }
    if (updates.length > 0) {
      /** @type {unknown} */
      __privateMethod(_a2 = current_batch, _Batch_instances, process_fn).call(_a2);
    }
    return;
  }
  const earlier_batch = __privateMethod(this, _Batch_instances, find_earlier_batch_fn).call(this);
  if (earlier_batch) {
    __privateMethod(this, _Batch_instances, defer_effects_fn).call(this, render_effects);
    __privateMethod(this, _Batch_instances, defer_effects_fn).call(this, effects);
    __privateMethod(_b2 = earlier_batch, _Batch_instances, merge_fn).call(_b2, this);
    return;
  }
  __privateGet(this, _dirty_effects).clear();
  __privateGet(this, _maybe_dirty_effects).clear();
  for (const fn of __privateGet(this, _commit_callbacks)) fn(this);
  __privateGet(this, _commit_callbacks).clear();
  previous_batch = this;
  flush_queued_effects(render_effects);
  flush_queued_effects(effects);
  previous_batch = null;
  (_c = __privateGet(this, _deferred)) == null ? void 0 : _c.resolve();
  var next_batch = (
    /** @type {Batch | null} */
    /** @type {unknown} */
    current_batch
  );
  if (__privateGet(this, _pending) === 0 && (__privateGet(this, _roots).length === 0 || next_batch !== null)) {
    __privateMethod(this, _Batch_instances, unlink_fn).call(this);
  }
  if (__privateGet(this, _roots).length > 0) {
    if (next_batch !== null) {
      const batch2 = next_batch;
      __privateGet(batch2, _roots).push(...__privateGet(this, _roots).filter((r) => !__privateGet(batch2, _roots).includes(r)));
    } else {
      next_batch = this;
    }
  }
  if (next_batch !== null) {
    old_values.clear();
    __privateMethod(_d = next_batch, _Batch_instances, process_fn).call(_d);
  }
};
/**
 * Traverse the effect tree, executing effects or stashing
 * them for later execution as appropriate
 * @param {Effect} root
 * @param {Effect[]} effects
 * @param {Effect[]} render_effects
 */
traverse_fn = function(root2, effects, render_effects) {
  root2.f ^= CLEAN;
  var effect2 = root2.first;
  while (effect2 !== null) {
    var flags2 = effect2.f;
    var is_branch = (flags2 & (BRANCH_EFFECT | ROOT_EFFECT)) !== 0;
    var is_skippable_branch = is_branch && (flags2 & CLEAN) !== 0;
    var skip = is_skippable_branch || (flags2 & INERT) !== 0 || __privateGet(this, _skipped_branches).has(effect2);
    if (!skip && effect2.fn !== null) {
      if (is_branch) {
        effect2.f ^= CLEAN;
      } else if ((flags2 & EFFECT) !== 0) {
        effects.push(effect2);
      } else if (is_dirty(effect2)) {
        if ((flags2 & BLOCK_EFFECT) !== 0) __privateGet(this, _maybe_dirty_effects).add(effect2);
        update_effect(effect2);
      }
      var child2 = effect2.first;
      if (child2 !== null) {
        effect2 = child2;
        continue;
      }
    }
    while (effect2 !== null) {
      var next = effect2.next;
      if (next !== null) {
        effect2 = next;
        break;
      }
      effect2 = effect2.parent;
    }
  }
};
find_earlier_batch_fn = function() {
  var batch = __privateGet(this, _prev);
  while (batch !== null) {
    if (!batch.is_fork) {
      for (const [value, [, is_derived]] of this.current) {
        if (batch.current.has(value) && !is_derived) {
          return batch;
        }
      }
    }
    batch = __privateGet(batch, _prev);
  }
  return null;
};
/**
 * @param {Batch} batch
 */
merge_fn = function(batch) {
  var _a2;
  for (const [source2, value] of batch.current) {
    if (!this.previous.has(source2) && batch.previous.has(source2)) {
      this.previous.set(source2, batch.previous.get(source2));
    }
    this.current.set(source2, value);
  }
  for (const [effect2, deferred2] of batch.async_deriveds) {
    const d = this.async_deriveds.get(effect2);
    if (d) deferred2.promise.then(d.resolve).catch(d.reject);
  }
  batch.async_deriveds.clear();
  this.transfer_effects(__privateGet(batch, _dirty_effects), __privateGet(batch, _maybe_dirty_effects));
  const mark = (value) => {
    var reactions = value.reactions;
    if (reactions === null) return;
    if ((value.f & DERIVED) !== 0 && (value.f & (DIRTY | MAYBE_DIRTY)) === 0) {
      return;
    }
    for (const reaction of reactions) {
      var flags2 = reaction.f;
      if ((flags2 & DERIVED) !== 0) {
        mark(
          /** @type {Derived} */
          reaction
        );
      } else {
        var effect2 = (
          /** @type {Effect} */
          reaction
        );
        if (flags2 & (ASYNC | BLOCK_EFFECT) && !this.async_deriveds.has(effect2)) {
          __privateGet(this, _maybe_dirty_effects).delete(effect2);
          set_signal_status(effect2, DIRTY);
          this.schedule(effect2);
        }
      }
    }
  };
  for (const source2 of this.current.keys()) {
    mark(source2);
  }
  this.oncommit(() => batch.discard());
  __privateMethod(_a2 = batch, _Batch_instances, unlink_fn).call(_a2);
  current_batch = this;
  __privateMethod(this, _Batch_instances, process_fn).call(this);
};
/**
 * @param {Effect[]} effects
 */
defer_effects_fn = function(effects) {
  for (var i = 0; i < effects.length; i += 1) {
    defer_effect(effects[i], __privateGet(this, _dirty_effects), __privateGet(this, _maybe_dirty_effects));
  }
};
commit_fn = function() {
  var _a2;
  for (let batch = first_batch; batch !== null; batch = __privateGet(batch, _next)) {
    var is_earlier = batch.id < this.id;
    var sources = [];
    for (const [source3, [value, is_derived]] of this.current) {
      if (batch.current.has(source3)) {
        var batch_value = (
          /** @type {[any, boolean]} */
          batch.current.get(source3)[0]
        );
        if (is_earlier && value !== batch_value) {
          batch.current.set(source3, [value, is_derived]);
        } else {
          continue;
        }
      }
      sources.push(source3);
    }
    if (is_earlier) {
      for (const [effect2, deferred2] of this.async_deriveds) {
        const d = batch.async_deriveds.get(effect2);
        if (d) deferred2.promise.then(d.resolve).catch(d.reject);
      }
    }
    var current = [...batch.current.keys()].filter(
      (source3) => !/** @type {[any, boolean]} */
      batch.current.get(source3)[1]
    );
    if (!__privateGet(batch, _started) || current.length === 0) continue;
    var others = current.filter((source3) => !this.current.has(source3));
    if (others.length === 0) {
      if (is_earlier) {
        batch.discard();
      }
    } else if (sources.length > 0) {
      if (is_earlier) {
        for (const unskipped of __privateGet(this, _unskipped_branches)) {
          batch.unskip_effect(unskipped, (e) => {
            var _a3;
            if ((e.f & (BLOCK_EFFECT | ASYNC)) !== 0) {
              batch.schedule(e);
            } else {
              __privateMethod(_a3 = batch, _Batch_instances, defer_effects_fn).call(_a3, [e]);
            }
          });
        }
      }
      batch.activate();
      var marked = /* @__PURE__ */ new Set();
      var checked = /* @__PURE__ */ new Map();
      for (var source2 of sources) {
        mark_effects(source2, others, marked, checked);
      }
      checked = /* @__PURE__ */ new Map();
      var current_unequal = [...batch.current].filter(([c, v1]) => {
        const v2 = this.current.get(c);
        if (!v2) return true;
        return v2[0] !== v1[0] || v2[1] !== v1[1];
      }).map(([c]) => c);
      if (current_unequal.length > 0) {
        for (const effect2 of __privateGet(this, _new_effects)) {
          if ((effect2.f & (DESTROYED | INERT | EAGER_EFFECT)) === 0 && depends_on(effect2, current_unequal, checked)) {
            if ((effect2.f & (ASYNC | BLOCK_EFFECT)) !== 0) {
              set_signal_status(effect2, DIRTY);
              batch.schedule(effect2);
            } else {
              __privateGet(batch, _dirty_effects).add(effect2);
            }
          }
        }
      }
      if (__privateGet(batch, _roots).length > 0 && !__privateGet(batch, _decrement_queued)) {
        batch.apply();
        for (var root2 of __privateGet(batch, _roots)) {
          __privateMethod(_a2 = batch, _Batch_instances, traverse_fn).call(_a2, root2, [], []);
        }
        __privateSet(batch, _roots, []);
      }
      batch.deactivate();
    }
  }
};
unlink_fn = function() {
  if (!this.linked) return;
  var prev = __privateGet(this, _prev);
  var next = __privateGet(this, _next);
  if (prev === null) {
    first_batch = next;
  } else {
    __privateSet(prev, _next, next);
  }
  if (next === null) {
    last_batch = prev;
  } else {
    __privateSet(next, _prev, prev);
  }
  this.linked = false;
};
let Batch = _Batch;
function infinite_loop_guard() {
  try {
    effect_update_depth_exceeded();
  } catch (error) {
    invoke_error_boundary(error, last_scheduled_effect);
  }
}
let eager_block_effects = null;
function flush_queued_effects(effects) {
  var length = effects.length;
  if (length === 0) return;
  var i = 0;
  while (i < length) {
    var effect2 = effects[i++];
    if ((effect2.f & (DESTROYED | INERT)) === 0 && is_dirty(effect2)) {
      eager_block_effects = /* @__PURE__ */ new Set();
      update_effect(effect2);
      if (effect2.deps === null && effect2.first === null && effect2.nodes === null && effect2.teardown === null && effect2.ac === null) {
        unlink_effect(effect2);
      }
      if ((eager_block_effects == null ? void 0 : eager_block_effects.size) > 0) {
        old_values.clear();
        for (const e of eager_block_effects) {
          if ((e.f & (DESTROYED | INERT)) !== 0) continue;
          const ordered_effects = [e];
          let ancestor = e.parent;
          while (ancestor !== null) {
            if (eager_block_effects.has(ancestor)) {
              eager_block_effects.delete(ancestor);
              ordered_effects.push(ancestor);
            }
            ancestor = ancestor.parent;
          }
          for (let j = ordered_effects.length - 1; j >= 0; j--) {
            const e2 = ordered_effects[j];
            if ((e2.f & (DESTROYED | INERT)) !== 0) continue;
            update_effect(e2);
          }
        }
        eager_block_effects.clear();
      }
    }
  }
  eager_block_effects = null;
}
function mark_effects(value, sources, marked, checked) {
  if (marked.has(value)) return;
  marked.add(value);
  if (value.reactions !== null) {
    for (const reaction of value.reactions) {
      const flags2 = reaction.f;
      if ((flags2 & DERIVED) !== 0) {
        mark_effects(
          /** @type {Derived} */
          reaction,
          sources,
          marked,
          checked
        );
      } else if ((flags2 & (ASYNC | BLOCK_EFFECT)) !== 0 && (flags2 & DIRTY) === 0 && depends_on(reaction, sources, checked)) {
        set_signal_status(reaction, DIRTY);
        schedule_effect(
          /** @type {Effect} */
          reaction
        );
      }
    }
  }
}
function depends_on(reaction, sources, checked) {
  const depends = checked.get(reaction);
  if (depends !== void 0) return depends;
  if (reaction.deps !== null) {
    for (const dep of reaction.deps) {
      if (includes.call(sources, dep)) {
        return true;
      }
      if ((dep.f & DERIVED) !== 0 && depends_on(
        /** @type {Derived} */
        dep,
        sources,
        checked
      )) {
        checked.set(
          /** @type {Derived} */
          dep,
          true
        );
        return true;
      }
    }
  }
  checked.set(reaction, false);
  return false;
}
function schedule_effect(effect2) {
  current_batch.schedule(effect2);
}
function reset_branch(effect2, tracked) {
  if ((effect2.f & BRANCH_EFFECT) !== 0 && (effect2.f & CLEAN) !== 0) {
    return;
  }
  if ((effect2.f & DIRTY) !== 0) {
    tracked.d.push(effect2);
  } else if ((effect2.f & MAYBE_DIRTY) !== 0) {
    tracked.m.push(effect2);
  }
  set_signal_status(effect2, CLEAN);
  var e = effect2.first;
  while (e !== null) {
    reset_branch(e, tracked);
    e = e.next;
  }
}
function reset_all(effect2) {
  set_signal_status(effect2, CLEAN);
  var e = effect2.first;
  while (e !== null) {
    reset_all(e);
    e = e.next;
  }
}
let eager_effects = /* @__PURE__ */ new Set();
const old_values = /* @__PURE__ */ new Map();
let eager_effects_deferred = false;
function source(v, stack) {
  var signal = {
    f: 0,
    // TODO ideally we could skip this altogether, but it causes type errors
    v,
    reactions: null,
    equals,
    rv: 0,
    wv: 0
  };
  return signal;
}
// @__NO_SIDE_EFFECTS__
function state(v, stack) {
  const s = source(v);
  push_reaction_value(s);
  return s;
}
// @__NO_SIDE_EFFECTS__
function mutable_source(initial_value, immutable = false, trackable = true) {
  var _a2;
  const s = source(initial_value);
  if (!immutable) {
    s.equals = safe_equals;
  }
  if (legacy_mode_flag && trackable && component_context !== null && component_context.l !== null) {
    ((_a2 = component_context.l).s ?? (_a2.s = [])).push(s);
  }
  return s;
}
function mutate(source2, value) {
  set(
    source2,
    untrack(() => get(source2))
  );
  return value;
}
function set(source2, value, should_proxy = false) {
  if (active_reaction !== null && // since we are untracking the function inside `$inspect.with` we need to add this check
  // to ensure we error if state is set inside an inspect effect
  (!untracking || (active_reaction.f & EAGER_EFFECT) !== 0) && is_runes() && (active_reaction.f & (DERIVED | BLOCK_EFFECT | ASYNC | EAGER_EFFECT)) !== 0 && (current_sources === null || !current_sources.has(source2))) {
    state_unsafe_mutation();
  }
  let new_value = should_proxy ? proxy(value) : value;
  return internal_set(source2, new_value, legacy_updates);
}
function internal_set(source2, value, updated_during_traversal = null) {
  if (!source2.equals(value)) {
    if (is_destroying_effect) {
      old_values.set(source2, value);
    } else if (!old_values.has(source2)) {
      old_values.set(source2, source2.v);
    }
    var batch = Batch.ensure();
    batch.capture(source2, value);
    if ((source2.f & DERIVED) !== 0) {
      const derived2 = (
        /** @type {Derived} */
        source2
      );
      if ((source2.f & DIRTY) !== 0) {
        execute_derived(derived2);
      }
      if (batch_values === null) {
        update_derived_status(derived2);
      }
    }
    source2.wv = increment_write_version();
    mark_reactions(source2, DIRTY, updated_during_traversal);
    if (is_runes() && active_effect !== null && (active_effect.f & CLEAN) !== 0 && (active_effect.f & (BRANCH_EFFECT | ROOT_EFFECT)) === 0) {
      if (untracked_writes === null) {
        set_untracked_writes([source2]);
      } else {
        untracked_writes.push(source2);
      }
    }
    if (!batch.is_fork && eager_effects.size > 0 && !eager_effects_deferred) {
      flush_eager_effects();
    }
  }
  return value;
}
function flush_eager_effects() {
  eager_effects_deferred = false;
  for (const effect2 of eager_effects) {
    if ((effect2.f & CLEAN) !== 0) {
      set_signal_status(effect2, MAYBE_DIRTY);
    }
    let dirty;
    try {
      dirty = is_dirty(effect2);
    } catch {
      dirty = true;
    }
    if (dirty) {
      update_effect(effect2);
    }
  }
  eager_effects.clear();
}
function increment(source2) {
  set(source2, source2.v + 1);
}
function mark_reactions(signal, status, updated_during_traversal) {
  var reactions = signal.reactions;
  if (reactions === null) return;
  var runes = is_runes();
  var length = reactions.length;
  for (var i = 0; i < length; i++) {
    var reaction = reactions[i];
    var flags2 = reaction.f;
    if (!runes && reaction === active_effect) continue;
    var not_dirty = (flags2 & DIRTY) === 0;
    if (not_dirty) {
      set_signal_status(reaction, status);
    }
    if ((flags2 & EAGER_EFFECT) !== 0) {
      eager_effects.add(
        /** @type {Effect} */
        reaction
      );
    } else if ((flags2 & DERIVED) !== 0) {
      var derived2 = (
        /** @type {Derived} */
        reaction
      );
      batch_values == null ? void 0 : batch_values.delete(derived2);
      if ((flags2 & WAS_MARKED) === 0) {
        if (flags2 & CONNECTED && (active_effect === null || (active_effect.f & REACTION_IS_UPDATING) === 0)) {
          reaction.f |= WAS_MARKED;
        }
        mark_reactions(derived2, MAYBE_DIRTY, updated_during_traversal);
      }
    } else if (not_dirty) {
      var effect2 = (
        /** @type {Effect} */
        reaction
      );
      if ((flags2 & BLOCK_EFFECT) !== 0 && eager_block_effects !== null) {
        eager_block_effects.add(effect2);
      }
      if (updated_during_traversal !== null) {
        updated_during_traversal.push(effect2);
      } else {
        schedule_effect(effect2);
      }
    }
  }
}
function proxy(value) {
  if (typeof value !== "object" || value === null || STATE_SYMBOL in value || COMPONENT_SYMBOL in value) {
    return value;
  }
  const prototype = get_prototype_of(value);
  if (prototype !== object_prototype && prototype !== array_prototype) {
    return value;
  }
  var sources = /* @__PURE__ */ new Map();
  var is_proxied_array = is_array(value);
  var version = /* @__PURE__ */ state(0);
  var parent_version = update_version;
  var with_parent = (fn) => {
    if (update_version === parent_version) {
      return fn();
    }
    var reaction = active_reaction;
    var version2 = update_version;
    set_active_reaction(null);
    set_update_version(parent_version);
    var result = fn();
    set_active_reaction(reaction);
    set_update_version(version2);
    return result;
  };
  if (is_proxied_array) {
    sources.set("length", /* @__PURE__ */ state(
      /** @type {any[]} */
      value.length
    ));
  }
  return new Proxy(
    /** @type {any} */
    value,
    {
      defineProperty(_, prop2, descriptor) {
        if (!("value" in descriptor) || descriptor.configurable === false || descriptor.enumerable === false || descriptor.writable === false) {
          state_descriptors_fixed();
        }
        var s = sources.get(prop2);
        if (s === void 0) {
          with_parent(() => {
            var s2 = /* @__PURE__ */ state(descriptor.value);
            sources.set(prop2, s2);
            return s2;
          });
        } else {
          set(s, descriptor.value, true);
        }
        return true;
      },
      deleteProperty(target2, prop2) {
        var s = sources.get(prop2);
        if (s === void 0) {
          if (prop2 in target2) {
            const s2 = with_parent(() => /* @__PURE__ */ state(UNINITIALIZED));
            sources.set(prop2, s2);
            increment(version);
          }
        } else {
          set(s, UNINITIALIZED);
          increment(version);
        }
        return true;
      },
      get(target2, prop2, receiver) {
        var _a2;
        if (prop2 === STATE_SYMBOL) {
          return value;
        }
        var s = sources.get(prop2);
        var exists = prop2 in target2;
        if (s === void 0 && (!exists || ((_a2 = get_descriptor(target2, prop2)) == null ? void 0 : _a2.writable))) {
          s = with_parent(() => {
            var p = proxy(exists ? target2[prop2] : UNINITIALIZED);
            var s2 = /* @__PURE__ */ state(p);
            return s2;
          });
          sources.set(prop2, s);
        }
        if (s !== void 0) {
          var v = get(s);
          return v === UNINITIALIZED ? void 0 : v;
        }
        return Reflect.get(target2, prop2, receiver);
      },
      getOwnPropertyDescriptor(target2, prop2) {
        var descriptor = Reflect.getOwnPropertyDescriptor(target2, prop2);
        if (descriptor && "value" in descriptor) {
          var s = sources.get(prop2);
          if (s) descriptor.value = get(s);
        } else if (descriptor === void 0) {
          var source2 = sources.get(prop2);
          var value2 = source2 == null ? void 0 : source2.v;
          if (source2 !== void 0 && value2 !== UNINITIALIZED) {
            return {
              enumerable: true,
              configurable: true,
              value: value2,
              writable: true
            };
          }
        }
        return descriptor;
      },
      has(target2, prop2) {
        var _a2;
        if (prop2 === STATE_SYMBOL) {
          return true;
        }
        var s = sources.get(prop2);
        var has = s !== void 0 && s.v !== UNINITIALIZED || Reflect.has(target2, prop2);
        if (s !== void 0 || active_effect !== null && (!has || ((_a2 = get_descriptor(target2, prop2)) == null ? void 0 : _a2.writable))) {
          if (s === void 0) {
            s = with_parent(() => {
              var p = has ? proxy(target2[prop2]) : UNINITIALIZED;
              var s2 = /* @__PURE__ */ state(p);
              return s2;
            });
            sources.set(prop2, s);
          }
          var value2 = get(s);
          if (value2 === UNINITIALIZED) {
            return false;
          }
        }
        return has;
      },
      set(target2, prop2, value2, receiver) {
        var _a2;
        var s = sources.get(prop2);
        var has = prop2 in target2;
        if (is_proxied_array && prop2 === "length") {
          for (var i = value2; i < /** @type {Source<number>} */
          s.v; i += 1) {
            var other_s = sources.get(i + "");
            if (other_s !== void 0) {
              set(other_s, UNINITIALIZED);
            } else if (i in target2) {
              other_s = with_parent(() => /* @__PURE__ */ state(UNINITIALIZED));
              sources.set(i + "", other_s);
            }
          }
        }
        if (s === void 0) {
          if (!has || ((_a2 = get_descriptor(target2, prop2)) == null ? void 0 : _a2.writable)) {
            s = with_parent(() => /* @__PURE__ */ state(void 0));
            set(s, proxy(value2));
            sources.set(prop2, s);
          }
        } else {
          has = s.v !== UNINITIALIZED;
          var p = with_parent(() => proxy(value2));
          set(s, p);
        }
        var descriptor = Reflect.getOwnPropertyDescriptor(target2, prop2);
        if (descriptor == null ? void 0 : descriptor.set) {
          descriptor.set.call(receiver, value2);
        }
        if (!has) {
          if (is_proxied_array && typeof prop2 === "string") {
            var ls = (
              /** @type {Source<number>} */
              sources.get("length")
            );
            var n = Number(prop2);
            if (Number.isInteger(n) && n >= ls.v) {
              set(ls, n + 1);
            }
          }
          increment(version);
        }
        return true;
      },
      ownKeys(target2) {
        get(version);
        var own_keys = Reflect.ownKeys(target2).filter((key3) => {
          var source3 = sources.get(key3);
          return source3 === void 0 || source3.v !== UNINITIALIZED;
        });
        for (var [key2, source2] of sources) {
          if (source2.v !== UNINITIALIZED && !(key2 in target2)) {
            own_keys.push(key2);
          }
        }
        return own_keys;
      },
      setPrototypeOf() {
        state_prototype_fixed();
      }
    }
  );
}
var $window;
var is_firefox;
var first_child_getter;
var next_sibling_getter;
function init_operations() {
  if ($window !== void 0) {
    return;
  }
  $window = window;
  is_firefox = /Firefox/.test(navigator.userAgent);
  var element_prototype = Element.prototype;
  var node_prototype = Node.prototype;
  var text_prototype = Text.prototype;
  first_child_getter = get_descriptor(node_prototype, "firstChild").get;
  next_sibling_getter = get_descriptor(node_prototype, "nextSibling").get;
  if (is_extensible(element_prototype)) {
    element_prototype[CLASS_CACHE] = void 0;
    element_prototype[ATTRIBUTES_CACHE] = null;
    element_prototype[STYLE_CACHE] = void 0;
    element_prototype.__e = void 0;
  }
  if (is_extensible(text_prototype)) {
    text_prototype[TEXT_CACHE] = void 0;
  }
}
function create_text(value = "") {
  return document.createTextNode(value);
}
// @__NO_SIDE_EFFECTS__
function get_first_child(node) {
  return (
    /** @type {TemplateNode | null} */
    first_child_getter.call(node)
  );
}
// @__NO_SIDE_EFFECTS__
function get_next_sibling(node) {
  return (
    /** @type {TemplateNode | null} */
    next_sibling_getter.call(node)
  );
}
function child(node, is_text) {
  {
    return /* @__PURE__ */ get_first_child(node);
  }
}
function first_child(node, is_text = false) {
  {
    var first = /* @__PURE__ */ get_first_child(node);
    if (first instanceof Comment && first.data === "") return /* @__PURE__ */ get_next_sibling(first);
    return first;
  }
}
function only_child(node, is_text = false) {
  {
    return /* @__PURE__ */ get_first_child(node);
  }
}
function sibling(node, count = 1, is_text = false) {
  let next_sibling = node;
  while (count--) {
    next_sibling = /** @type {TemplateNode} */
    /* @__PURE__ */ get_next_sibling(next_sibling);
  }
  {
    return next_sibling;
  }
}
function clear_text_content(node) {
  node.textContent = "";
}
function should_defer_append() {
  return false;
}
function create_element(tag, namespace, is) {
  {
    return (
      /** @type {T extends keyof HTMLElementTagNameMap ? HTMLElementTagNameMap[T] : Element} */
      is ? document.createElement(tag, { is }) : document.createElement(tag)
    );
  }
}
function handle_error(error) {
  var effect2 = active_effect;
  if (effect2 === null) {
    active_reaction.f |= ERROR_VALUE;
    return error;
  }
  if ((effect2.f & REACTION_RAN) === 0 && (effect2.f & EFFECT) === 0) {
    throw error;
  }
  invoke_error_boundary(error, effect2);
}
function invoke_error_boundary(error, effect2) {
  if (effect2 !== null && (effect2.f & DESTROYED) !== 0) {
    return;
  }
  while (effect2 !== null) {
    if ((effect2.f & BOUNDARY_EFFECT) !== 0 && (effect2.f & (DESTROYED | DESTROYING)) === 0) {
      if ((effect2.f & REACTION_RAN) === 0) {
        throw error;
      }
      try {
        effect2.b.error(error);
        return;
      } catch (e) {
        error = e;
      }
    }
    effect2 = effect2.parent;
  }
  throw error;
}
function validate_effect(rune) {
  if (active_effect === null) {
    if (active_reaction === null) {
      effect_orphan();
    }
    effect_in_unowned_derived();
  }
  if (is_destroying_effect) {
    effect_in_teardown();
  }
}
function push_effect(effect2, parent_effect) {
  var parent_last = parent_effect.last;
  if (parent_last === null) {
    parent_effect.last = parent_effect.first = effect2;
  } else {
    parent_last.next = effect2;
    effect2.prev = parent_last;
    parent_effect.last = effect2;
  }
}
function create_effect(type, fn) {
  var parent = active_effect;
  if (parent !== null && (parent.f & INERT) !== 0) {
    type |= INERT;
  }
  var effect2 = {
    ctx: component_context,
    deps: null,
    nodes: null,
    f: type | DIRTY | CONNECTED,
    first: null,
    fn,
    last: null,
    next: null,
    parent,
    b: parent && parent.b,
    prev: null,
    teardown: null,
    wv: 0,
    ac: null
  };
  current_batch == null ? void 0 : current_batch.register_created_effect(effect2);
  var e = effect2;
  if ((type & EFFECT) !== 0) {
    if (collected_effects !== null) {
      collected_effects.push(effect2);
    } else {
      Batch.ensure().schedule(effect2);
    }
  } else if (fn !== null) {
    try {
      update_effect(effect2);
    } catch (e2) {
      destroy_effect(effect2);
      throw e2;
    }
    if (e.deps === null && e.teardown === null && e.nodes === null && e.first === e.last && // either `null`, or a singular child
    (e.f & EFFECT_PRESERVED) === 0) {
      e = e.first;
      if ((type & BLOCK_EFFECT) !== 0 && (type & EFFECT_TRANSPARENT) !== 0 && e !== null) {
        e.f |= EFFECT_TRANSPARENT;
      }
    }
  }
  if (e !== null) {
    e.parent = parent;
    if (parent !== null) {
      push_effect(e, parent);
    }
    if (active_reaction !== null && (active_reaction.f & DERIVED) !== 0 && (type & ROOT_EFFECT) === 0) {
      var derived2 = (
        /** @type {Derived} */
        active_reaction
      );
      (derived2.effects ?? (derived2.effects = [])).push(e);
    }
  }
  return effect2;
}
function effect_tracking() {
  return active_reaction !== null && !untracking;
}
function teardown(fn) {
  const effect2 = create_effect(RENDER_EFFECT, null);
  set_signal_status(effect2, CLEAN);
  effect2.teardown = fn;
  return effect2;
}
function user_effect(fn) {
  validate_effect();
  var flags2 = (
    /** @type {Effect} */
    active_effect.f
  );
  var defer = !active_reaction && (flags2 & BRANCH_EFFECT) !== 0 && component_context !== null && !component_context.i;
  if (defer) {
    var context = (
      /** @type {ComponentContext} */
      component_context
    );
    (context.e ?? (context.e = [])).push(fn);
  } else {
    return create_user_effect(fn);
  }
}
function create_user_effect(fn) {
  return create_effect(EFFECT | USER_EFFECT, fn);
}
function user_pre_effect(fn) {
  validate_effect();
  return create_effect(RENDER_EFFECT | USER_EFFECT, fn);
}
function component_root(fn) {
  Batch.ensure();
  const effect2 = create_effect(ROOT_EFFECT | EFFECT_PRESERVED, fn);
  return (options = {}) => {
    return new Promise((fulfil) => {
      if (options.outro) {
        pause_effect(effect2, () => {
          destroy_effect(effect2);
          fulfil(void 0);
        });
      } else {
        destroy_effect(effect2);
        fulfil(void 0);
      }
    });
  };
}
function effect(fn) {
  return create_effect(EFFECT, fn);
}
function legacy_pre_effect(deps, fn) {
  var context = (
    /** @type {ComponentContextLegacy} */
    component_context
  );
  var token = { effect: null, ran: false, deps };
  context.l.$.push(token);
  token.effect = render_effect(() => {
    deps();
    if (token.ran) return;
    token.ran = true;
    var effect2 = (
      /** @type {Effect} */
      active_effect
    );
    try {
      set_active_effect(effect2.parent);
      untrack(fn);
    } finally {
      set_active_effect(effect2);
    }
  });
}
function legacy_pre_effect_reset() {
  var context = (
    /** @type {ComponentContextLegacy} */
    component_context
  );
  render_effect(() => {
    for (var token of context.l.$) {
      token.deps();
      var effect2 = token.effect;
      if ((effect2.f & CLEAN) !== 0 && effect2.deps !== null) {
        set_signal_status(effect2, MAYBE_DIRTY);
      }
      if (is_dirty(effect2)) {
        update_effect(effect2);
      }
      token.ran = false;
    }
  });
}
function async_effect(fn) {
  return create_effect(ASYNC | EFFECT_PRESERVED, fn);
}
function render_effect(fn, flags2 = 0) {
  return create_effect(RENDER_EFFECT | flags2, fn);
}
function template_effect(fn, sync = [], async = [], blockers = []) {
  flatten(blockers, sync, async, (values) => {
    create_effect(RENDER_EFFECT, () => {
      fn(...values.map(get));
    });
  });
}
function block(fn, flags2 = 0) {
  var effect2 = create_effect(BLOCK_EFFECT | flags2, fn);
  return effect2;
}
function branch(fn) {
  return create_effect(BRANCH_EFFECT | EFFECT_PRESERVED, fn);
}
function execute_effect_teardown(effect2) {
  var teardown2 = effect2.teardown;
  if (teardown2 !== null) {
    const previously_destroying_effect = is_destroying_effect;
    const previous_reaction = active_reaction;
    set_is_destroying_effect(true);
    set_active_reaction(null);
    try {
      teardown2.call(null);
    } catch (error) {
      invoke_error_boundary(error, effect2.parent);
    } finally {
      set_is_destroying_effect(previously_destroying_effect);
      set_active_reaction(previous_reaction);
    }
  }
}
function destroy_effect_children(signal, remove_dom = false) {
  var effect2 = signal.first;
  signal.first = signal.last = null;
  while (effect2 !== null) {
    const controller = effect2.ac;
    if (controller !== null) {
      without_reactive_context(() => {
        controller.abort(STALE_REACTION);
      });
    }
    var next = effect2.next;
    if ((effect2.f & ROOT_EFFECT) !== 0) {
      effect2.parent = null;
    } else {
      destroy_effect(effect2, remove_dom);
    }
    effect2 = next;
  }
}
function destroy_block_effect_children(signal) {
  var effect2 = signal.first;
  while (effect2 !== null) {
    var next = effect2.next;
    if ((effect2.f & BRANCH_EFFECT) === 0) {
      destroy_effect(effect2);
    }
    effect2 = next;
  }
}
function destroy_effect(effect2, remove_dom = true) {
  var removed = false;
  if ((remove_dom || (effect2.f & HEAD_EFFECT) !== 0) && effect2.nodes !== null && effect2.nodes.end !== null) {
    remove_effect_dom(
      effect2.nodes.start,
      /** @type {TemplateNode} */
      effect2.nodes.end
    );
    removed = true;
  }
  effect2.f |= DESTROYING;
  destroy_effect_children(effect2, remove_dom && !removed);
  remove_reactions(effect2, 0);
  var transitions = effect2.nodes && effect2.nodes.t;
  if (transitions !== null) {
    for (const transition of transitions) {
      transition.stop();
    }
  }
  execute_effect_teardown(effect2);
  effect2.f ^= DESTROYING;
  effect2.f |= DESTROYED;
  var parent = effect2.parent;
  if (parent !== null && parent.first !== null) {
    unlink_effect(effect2);
  }
  effect2.next = effect2.prev = effect2.teardown = effect2.ctx = effect2.deps = effect2.fn = effect2.nodes = effect2.ac = effect2.b = null;
}
function remove_effect_dom(node, end) {
  while (node !== null) {
    var next = node === end ? null : /* @__PURE__ */ get_next_sibling(node);
    node.remove();
    node = next;
  }
}
function unlink_effect(effect2) {
  var parent = effect2.parent;
  var prev = effect2.prev;
  var next = effect2.next;
  if (prev !== null) prev.next = next;
  if (next !== null) next.prev = prev;
  if (parent !== null) {
    if (parent.first === effect2) parent.first = next;
    if (parent.last === effect2) parent.last = prev;
  }
}
function pause_effect(effect2, callback, destroy = true) {
  var transitions = [];
  effect2.f |= PAUSED;
  pause_children(effect2, transitions, true);
  var fn = () => {
    if (destroy) destroy_effect(effect2);
    if (callback) callback();
  };
  var remaining = transitions.length;
  if (remaining > 0) {
    var check = () => --remaining || fn();
    for (var transition of transitions) {
      transition.out(check);
    }
  } else {
    fn();
  }
}
function pause_children(effect2, transitions, local) {
  if ((effect2.f & INERT) !== 0) return;
  effect2.f ^= INERT;
  var t = effect2.nodes && effect2.nodes.t;
  if (t !== null) {
    for (const transition of t) {
      if (transition.is_global || local) {
        transitions.push(transition);
      }
    }
  }
  var child2 = effect2.first;
  while (child2 !== null) {
    var sibling2 = child2.next;
    if ((child2.f & ROOT_EFFECT) === 0) {
      var transparent = (child2.f & EFFECT_TRANSPARENT) !== 0 || // If this is a branch effect without a block effect parent,
      // it means the parent block effect was pruned. In that case,
      // transparency information was transferred to the branch effect.
      (child2.f & BRANCH_EFFECT) !== 0 && (effect2.f & BLOCK_EFFECT) !== 0;
      pause_children(child2, transitions, transparent ? local : false);
    }
    child2 = sibling2;
  }
}
function resume_effect(effect2) {
  effect2.f &= ~PAUSED;
  resume_children(effect2, true);
}
function resume_children(effect2, local) {
  if ((effect2.f & PAUSED) !== 0) return;
  if ((effect2.f & INERT) === 0) return;
  effect2.f ^= INERT;
  if ((effect2.f & CLEAN) === 0) {
    set_signal_status(effect2, DIRTY);
    Batch.ensure().schedule(effect2);
  }
  var child2 = effect2.first;
  while (child2 !== null) {
    var sibling2 = child2.next;
    var transparent = (child2.f & EFFECT_TRANSPARENT) !== 0 || (child2.f & BRANCH_EFFECT) !== 0;
    resume_children(child2, transparent ? local : false);
    child2 = sibling2;
  }
  var t = effect2.nodes && effect2.nodes.t;
  if (t !== null) {
    for (const transition of t) {
      if (transition.is_global || local) {
        transition.in();
      }
    }
  }
}
function move_effect(effect2, fragment) {
  if (!effect2.nodes) return;
  var node = effect2.nodes.start;
  var end = effect2.nodes.end;
  while (node !== null) {
    var next = node === end ? null : /* @__PURE__ */ get_next_sibling(node);
    fragment.append(node);
    node = next;
  }
}
let is_updating_effect = false;
let is_destroying_effect = false;
function set_is_destroying_effect(value) {
  is_destroying_effect = value;
}
let active_reaction = null;
let untracking = false;
function set_active_reaction(reaction) {
  active_reaction = reaction;
}
let active_effect = null;
function set_active_effect(effect2) {
  active_effect = effect2;
}
let current_sources = null;
function push_reaction_value(value) {
  if (active_reaction !== null && true) {
    (current_sources ?? (current_sources = /* @__PURE__ */ new Set())).add(value);
  }
}
let new_deps = null;
let skipped_deps = 0;
let untracked_writes = null;
function set_untracked_writes(value) {
  untracked_writes = value;
}
let write_version = 1;
let read_version = 0;
let update_version = read_version;
function set_update_version(value) {
  update_version = value;
}
function increment_write_version() {
  return ++write_version;
}
function is_dirty(reaction) {
  var flags2 = reaction.f;
  if ((flags2 & DIRTY) !== 0) {
    return true;
  }
  if (flags2 & DERIVED) {
    reaction.f &= ~WAS_MARKED;
  }
  if ((flags2 & MAYBE_DIRTY) !== 0) {
    var dependencies = (
      /** @type {Value[]} */
      reaction.deps
    );
    var length = dependencies.length;
    for (var i = 0; i < length; i++) {
      var dependency = dependencies[i];
      if (is_dirty(
        /** @type {Derived} */
        dependency
      )) {
        update_derived(
          /** @type {Derived} */
          dependency
        );
      }
      if (dependency.wv > reaction.wv) {
        return true;
      }
    }
    if ((flags2 & CONNECTED) !== 0 && // During time traveling we don't want to reset the status so that
    // traversal of the graph in the other batches still happens
    batch_values === null) {
      set_signal_status(reaction, CLEAN);
    }
  }
  return false;
}
function schedule_possible_effect_self_invalidation(signal, effect2, root2 = true) {
  var reactions = signal.reactions;
  if (reactions === null) return;
  if (current_sources !== null && current_sources.has(signal)) {
    return;
  }
  for (var i = 0; i < reactions.length; i++) {
    var reaction = reactions[i];
    if ((reaction.f & DERIVED) !== 0) {
      schedule_possible_effect_self_invalidation(
        /** @type {Derived} */
        reaction,
        effect2,
        false
      );
    } else if (effect2 === reaction) {
      if (root2) {
        set_signal_status(reaction, DIRTY);
      } else if ((reaction.f & CLEAN) !== 0) {
        set_signal_status(reaction, MAYBE_DIRTY);
      }
      schedule_effect(
        /** @type {Effect} */
        reaction
      );
    }
  }
}
function update_reaction(reaction) {
  var previous_deps = new_deps;
  var previous_skipped_deps = skipped_deps;
  var previous_untracked_writes = untracked_writes;
  var previous_reaction = active_reaction;
  var previous_sources = current_sources;
  var previous_component_context = component_context;
  var previous_untracking = untracking;
  var previous_update_version = update_version;
  var flags2 = reaction.f;
  new_deps = /** @type {null | Value[]} */
  null;
  skipped_deps = 0;
  untracked_writes = null;
  active_reaction = (flags2 & (BRANCH_EFFECT | ROOT_EFFECT)) === 0 ? reaction : null;
  current_sources = null;
  set_component_context(reaction.ctx);
  untracking = false;
  update_version = ++read_version;
  if (reaction.ac !== null) {
    without_reactive_context(() => {
      reaction.ac.abort(STALE_REACTION);
    });
    reaction.ac = null;
  }
  try {
    reaction.f |= REACTION_IS_UPDATING;
    var fn = (
      /** @type {Function} */
      reaction.fn
    );
    var result = fn();
    reaction.f |= REACTION_RAN;
    var deps = update_dependencies(reaction);
    if (is_runes() && untracked_writes !== null && !untracking && deps !== null && (reaction.f & (DERIVED | MAYBE_DIRTY | DIRTY)) === 0) {
      for (var i = 0; i < /** @type {Source[]} */
      untracked_writes.length; i++) {
        schedule_possible_effect_self_invalidation(
          untracked_writes[i],
          /** @type {Effect} */
          reaction
        );
      }
    }
    if (previous_reaction !== null && previous_reaction !== reaction) {
      read_version++;
      if (previous_reaction.deps !== null) {
        for (let i2 = 0; i2 < previous_skipped_deps; i2 += 1) {
          previous_reaction.deps[i2].rv = read_version;
        }
      }
      if (previous_deps !== null) {
        for (const dep of previous_deps) {
          dep.rv = read_version;
        }
      }
      if (untracked_writes !== null) {
        if (previous_untracked_writes === null) {
          previous_untracked_writes = untracked_writes;
        } else {
          previous_untracked_writes.push(.../** @type {Source[]} */
          untracked_writes);
        }
      }
    }
    if ((reaction.f & ERROR_VALUE) !== 0) {
      reaction.f ^= ERROR_VALUE;
    }
    return result;
  } catch (error) {
    update_dependencies(reaction);
    return handle_error(error);
  } finally {
    reaction.f ^= REACTION_IS_UPDATING;
    new_deps = previous_deps;
    skipped_deps = previous_skipped_deps;
    untracked_writes = previous_untracked_writes;
    active_reaction = previous_reaction;
    current_sources = previous_sources;
    set_component_context(previous_component_context);
    untracking = previous_untracking;
    update_version = previous_update_version;
  }
}
function update_dependencies(reaction) {
  var _a2;
  var deps = reaction.deps;
  var is_fork = current_batch == null ? void 0 : current_batch.is_fork;
  if (new_deps !== null) {
    var i;
    if (!is_fork) {
      remove_reactions(reaction, skipped_deps);
    }
    if (deps !== null && skipped_deps > 0) {
      deps.length = skipped_deps + new_deps.length;
      for (i = 0; i < new_deps.length; i++) {
        deps[skipped_deps + i] = new_deps[i];
      }
    } else {
      reaction.deps = deps = new_deps;
    }
    if (effect_tracking() && (reaction.f & CONNECTED) !== 0) {
      for (i = skipped_deps; i < deps.length; i++) {
        ((_a2 = deps[i]).reactions ?? (_a2.reactions = [])).push(reaction);
      }
    }
  } else if (!is_fork && deps !== null && skipped_deps < deps.length) {
    remove_reactions(reaction, skipped_deps);
    deps.length = skipped_deps;
  }
  return deps;
}
function remove_reaction(signal, dependency) {
  let reactions = dependency.reactions;
  if (reactions !== null) {
    var index2 = index_of.call(reactions, signal);
    if (index2 !== -1) {
      var new_length = reactions.length - 1;
      if (new_length === 0) {
        reactions = dependency.reactions = null;
      } else {
        reactions[index2] = reactions[new_length];
        reactions.pop();
      }
    }
  }
  if (reactions === null && (dependency.f & DERIVED) !== 0 && // Destroying a child effect while updating a parent effect can cause a dependency to appear
  // to be unused, when in fact it is used by the currently-updating parent. Checking `new_deps`
  // allows us to skip the expensive work of disconnecting and immediately reconnecting it
  (new_deps === null || !includes.call(new_deps, dependency))) {
    var derived2 = (
      /** @type {Derived} */
      dependency
    );
    if ((derived2.f & CONNECTED) !== 0) {
      derived2.f ^= CONNECTED;
      derived2.f &= ~WAS_MARKED;
    }
    if (derived2.v !== UNINITIALIZED) {
      update_derived_status(derived2);
    }
    if (derived2.ac !== null) {
      without_reactive_context(() => {
        derived2.ac.abort(STALE_REACTION);
        derived2.ac = null;
        set_signal_status(derived2, DIRTY);
      });
    }
    freeze_derived_effects(derived2);
    remove_reactions(derived2, 0);
  }
}
function remove_reactions(signal, start_index) {
  var dependencies = signal.deps;
  if (dependencies === null) return;
  for (var i = start_index; i < dependencies.length; i++) {
    remove_reaction(signal, dependencies[i]);
  }
}
function update_effect(effect2) {
  var flags2 = effect2.f;
  if ((flags2 & DESTROYED) !== 0) {
    return;
  }
  set_signal_status(effect2, CLEAN);
  var previous_effect = active_effect;
  var was_updating_effect = is_updating_effect;
  active_effect = effect2;
  is_updating_effect = (flags2 & (BRANCH_EFFECT | ROOT_EFFECT)) === 0;
  try {
    if ((flags2 & (BLOCK_EFFECT | MANAGED_EFFECT)) !== 0) {
      destroy_block_effect_children(effect2);
    } else {
      destroy_effect_children(effect2);
    }
    execute_effect_teardown(effect2);
    var teardown2 = update_reaction(effect2);
    effect2.teardown = typeof teardown2 === "function" ? teardown2 : null;
    effect2.wv = write_version;
    var dep;
    if (DEV && tracing_mode_flag && (effect2.f & DIRTY) !== 0 && effect2.deps !== null) ;
  } finally {
    is_updating_effect = was_updating_effect;
    active_effect = previous_effect;
  }
}
function get(signal) {
  var flags2 = signal.f;
  var is_derived = (flags2 & DERIVED) !== 0;
  if (active_reaction !== null && !untracking) {
    var destroyed = active_effect !== null && (active_effect.f & DESTROYED) !== 0;
    if (!destroyed && (current_sources === null || !current_sources.has(signal))) {
      var deps = active_reaction.deps;
      if ((active_reaction.f & REACTION_IS_UPDATING) !== 0) {
        if (signal.rv < read_version) {
          signal.rv = read_version;
          if (new_deps === null && deps !== null && deps[skipped_deps] === signal) {
            skipped_deps++;
          } else if (new_deps === null) {
            new_deps = [signal];
          } else {
            new_deps.push(signal);
          }
        }
      } else {
        active_reaction.deps ?? (active_reaction.deps = []);
        if (!includes.call(active_reaction.deps, signal)) {
          active_reaction.deps.push(signal);
        }
        var reactions = signal.reactions;
        if (reactions === null) {
          signal.reactions = [active_reaction];
        } else if (!includes.call(reactions, active_reaction)) {
          reactions.push(active_reaction);
        }
      }
    }
  }
  if (is_destroying_effect && old_values.has(signal)) {
    return old_values.get(signal);
  }
  if (is_derived) {
    var derived2 = (
      /** @type {Derived} */
      signal
    );
    if (is_destroying_effect) {
      var value = derived2.v;
      if ((derived2.f & CLEAN) === 0 && derived2.reactions !== null || depends_on_old_values(derived2)) {
        value = execute_derived(derived2);
      }
      old_values.set(derived2, value);
      return value;
    }
    var should_connect = (derived2.f & CONNECTED) === 0 && !untracking && active_reaction !== null && (is_updating_effect || (active_reaction.f & CONNECTED) !== 0);
    var is_new = (derived2.f & REACTION_RAN) === 0;
    if (is_dirty(derived2)) {
      if (should_connect) {
        derived2.f |= CONNECTED;
      }
      update_derived(derived2);
    }
    if (should_connect && !is_new) {
      unfreeze_derived_effects(derived2);
      reconnect(derived2);
    }
  }
  if (batch_values == null ? void 0 : batch_values.has(signal)) {
    return batch_values.get(signal);
  }
  if ((signal.f & ERROR_VALUE) !== 0) {
    throw signal.v;
  }
  return signal.v;
}
function reconnect(derived2) {
  derived2.f |= CONNECTED;
  if (derived2.deps === null) return;
  for (const dep of derived2.deps) {
    (dep.reactions ?? (dep.reactions = [])).push(derived2);
    if ((dep.f & DERIVED) !== 0 && (dep.f & CONNECTED) === 0) {
      unfreeze_derived_effects(
        /** @type {Derived} */
        dep
      );
      reconnect(
        /** @type {Derived} */
        dep
      );
    }
  }
}
function depends_on_old_values(derived2) {
  if (derived2.v === UNINITIALIZED) return true;
  if (derived2.deps === null) return false;
  for (const dep of derived2.deps) {
    if (old_values.has(dep)) {
      return true;
    }
    if ((dep.f & DERIVED) !== 0 && depends_on_old_values(
      /** @type {Derived} */
      dep
    )) {
      return true;
    }
  }
  return false;
}
function untrack(fn) {
  var previous_untracking = untracking;
  try {
    untracking = true;
    return fn();
  } finally {
    untracking = previous_untracking;
  }
}
function deep_read_state(value) {
  if (typeof value !== "object" || !value || value instanceof EventTarget) {
    return;
  }
  if (STATE_SYMBOL in value) {
    deep_read(value);
  } else if (!Array.isArray(value)) {
    for (let key2 in value) {
      const prop2 = value[key2];
      if (typeof prop2 === "object" && prop2 && STATE_SYMBOL in prop2) {
        deep_read(prop2);
      }
    }
  }
}
function deep_read(value, visited = /* @__PURE__ */ new Set()) {
  if (typeof value === "object" && value !== null && // We don't want to traverse DOM elements
  !(value instanceof EventTarget) && !visited.has(value)) {
    visited.add(value);
    if (value instanceof Date) {
      value.getTime();
    }
    for (let key2 in value) {
      try {
        deep_read(value[key2], visited);
      } catch (e) {
      }
    }
    const proto = get_prototype_of(value);
    if (proto !== Object.prototype && proto !== Array.prototype && proto !== Map.prototype && proto !== Set.prototype && proto !== Date.prototype) {
      const descriptors = get_descriptors(proto);
      for (let key2 in descriptors) {
        const get2 = descriptors[key2].get;
        if (get2) {
          try {
            get2.call(value);
          } catch (e) {
          }
        }
      }
    }
  }
}
const PASSIVE_EVENTS = ["touchstart", "touchmove"];
function is_passive_event(name) {
  return PASSIVE_EVENTS.includes(name);
}
const event_symbol = Symbol("events");
const all_registered_events = /* @__PURE__ */ new Set();
const root_event_handles = /* @__PURE__ */ new Set();
function create_event(event_name, dom, handler, options = {}) {
  function target_handler(event2) {
    if (!options.capture) {
      handle_event_propagation.call(dom, event2);
    }
    if (!event2.cancelBubble) {
      return without_reactive_context(() => {
        return handler == null ? void 0 : handler.call(this, event2);
      });
    }
  }
  if (event_name.startsWith("pointer") || event_name.startsWith("touch") || event_name === "wheel") {
    queue_micro_task(() => {
      dom.addEventListener(event_name, target_handler, options);
    });
  } else {
    dom.addEventListener(event_name, target_handler, options);
  }
  return target_handler;
}
function event(event_name, dom, handler, capture2, passive) {
  var options = { capture: capture2, passive };
  var target_handler = create_event(event_name, dom, handler, options);
  if (dom === document.body || // @ts-ignore
  dom === window || // @ts-ignore
  dom === document || // Firefox has quirky behavior, it can happen that we still get "canplay" events when the element is already removed
  dom instanceof HTMLMediaElement) {
    teardown(() => {
      dom.removeEventListener(event_name, target_handler, options);
    });
  }
}
let last_propagated_event = null;
let last_propagated_event_clear_scheduled = false;
function handle_event_propagation(event2) {
  var _a2, _b2;
  var handler_element = this;
  var owner_document = (
    /** @type {Node} */
    handler_element.ownerDocument
  );
  var event_name = event2.type;
  var path = ((_a2 = event2.composedPath) == null ? void 0 : _a2.call(event2)) || [];
  var current_target = (
    /** @type {null | Element} */
    path[0] || event2.target
  );
  last_propagated_event = event2;
  if (!last_propagated_event_clear_scheduled) {
    last_propagated_event_clear_scheduled = true;
    setTimeout(() => {
      last_propagated_event_clear_scheduled = false;
      last_propagated_event = null;
    });
  }
  var path_idx = 0;
  var handled_at = last_propagated_event === event2 && event2[event_symbol];
  if (handled_at) {
    var at_idx = path.indexOf(handled_at);
    if (at_idx !== -1 && (handler_element === document || handler_element === /** @type {any} */
    window)) {
      event2[event_symbol] = handler_element;
      return;
    }
    var handler_idx = path.indexOf(handler_element);
    if (handler_idx === -1) {
      return;
    }
    if (at_idx <= handler_idx) {
      path_idx = at_idx;
    }
  }
  current_target = /** @type {Element} */
  path[path_idx] || event2.target;
  if (current_target === handler_element) return;
  define_property(event2, "currentTarget", {
    configurable: true,
    get() {
      return current_target || owner_document;
    }
  });
  var previous_reaction = active_reaction;
  var previous_effect = active_effect;
  set_active_reaction(null);
  set_active_effect(null);
  try {
    var throw_error;
    var other_errors = [];
    while (current_target !== null) {
      if (current_target === handler_element) break;
      try {
        var delegated = (_b2 = current_target[event_symbol]) == null ? void 0 : _b2[event_name];
        if (delegated != null && (!/** @type {any} */
        current_target.disabled || // DOM could've been updated already by the time this is reached, so we check this as well
        // -> the target could not have been disabled because it emits the event in the first place
        event2.target === current_target)) {
          delegated.call(current_target, event2);
        }
      } catch (error) {
        if (throw_error) {
          other_errors.push(error);
        } else {
          throw_error = error;
        }
      }
      if (event2.cancelBubble) break;
      path_idx++;
      current_target = path_idx < path.length ? (
        /** @type {Element} */
        path[path_idx]
      ) : null;
    }
    if (throw_error) {
      for (let error of other_errors) {
        queueMicrotask(() => {
          throw error;
        });
      }
      throw throw_error;
    }
  } finally {
    event2[event_symbol] = handler_element;
    delete event2.currentTarget;
    set_active_reaction(previous_reaction);
    set_active_effect(previous_effect);
  }
}
const policy = (
  // We gotta write it like this because after downleveling the pure comment may end up in the wrong location
  ((_a = globalThis == null ? void 0 : globalThis.window) == null ? void 0 : _a.trustedTypes) && /* @__PURE__ */ globalThis.window.trustedTypes.createPolicy("svelte-trusted-html", {
    /** @param {string} html */
    createHTML: (html) => {
      return html;
    }
  })
);
function create_trusted_html(html) {
  return (
    /** @type {string} */
    (policy == null ? void 0 : policy.createHTML(html)) ?? html
  );
}
function create_fragment_from_html(html) {
  var elem = create_element("template");
  elem.innerHTML = create_trusted_html(html.replaceAll("<!>", "<!---->"));
  return elem.content;
}
function assign_nodes(start, end) {
  var effect2 = (
    /** @type {Effect} */
    active_effect
  );
  if (effect2.nodes === null) {
    effect2.nodes = { start, end, a: null, t: null };
  }
}
// @__NO_SIDE_EFFECTS__
function from_html(content, flags2) {
  var is_fragment = (flags2 & TEMPLATE_FRAGMENT) !== 0;
  var use_import_node = (flags2 & TEMPLATE_USE_IMPORT_NODE) !== 0;
  var node;
  var has_start = !content.startsWith("<!>");
  return () => {
    if (node === void 0) {
      node = create_fragment_from_html(has_start ? content : "<!>" + content);
      if (!is_fragment) node = /** @type {TemplateNode} */
      /* @__PURE__ */ get_first_child(node);
    }
    var clone = (
      /** @type {TemplateNode} */
      use_import_node || is_firefox ? document.importNode(node, true) : node.cloneNode(true)
    );
    if (is_fragment) {
      var start = (
        /** @type {TemplateNode} */
        /* @__PURE__ */ get_first_child(clone)
      );
      var end = (
        /** @type {TemplateNode} */
        clone.lastChild
      );
      assign_nodes(start, end);
    } else {
      assign_nodes(clone, clone);
    }
    return clone;
  };
}
function comment() {
  var frag = document.createDocumentFragment();
  var start = document.createComment("");
  var anchor = create_text();
  frag.append(start, anchor);
  assign_nodes(start, anchor);
  return frag;
}
function append(anchor, dom) {
  if (anchor === null) {
    return;
  }
  anchor.before(
    /** @type {Node} */
    dom
  );
}
function createSubscriber(start) {
  let subscribers = 0;
  let version = source(0);
  let stop;
  return () => {
    if (effect_tracking()) {
      get(version);
      render_effect(() => {
        if (subscribers === 0) {
          stop = untrack(() => start(() => increment(version)));
        }
        subscribers += 1;
        return () => {
          queue_micro_task(() => {
            subscribers -= 1;
            if (subscribers === 0) {
              stop == null ? void 0 : stop();
              stop = void 0;
              increment(version);
            }
          });
        };
      });
    }
  };
}
var flags = EFFECT_TRANSPARENT | EFFECT_PRESERVED;
function boundary(node, props, children, transform_error) {
  new Boundary(node, props, children, transform_error);
}
class Boundary {
  /**
   * @param {TemplateNode} node
   * @param {BoundaryProps} props
   * @param {((anchor: Node) => void)} children
   * @param {((error: unknown) => unknown) | undefined} [transform_error]
   */
  constructor(node, props, children, transform_error) {
    __privateAdd(this, _Boundary_instances);
    /** @type {Boundary | null} */
    __publicField(this, "parent");
    __publicField(this, "is_pending", false);
    /**
     * API-level transformError transform function. Transforms errors before they reach the `failed` snippet.
     * Inherited from parent boundary, or defaults to identity.
     * @type {(error: unknown) => unknown}
     */
    __publicField(this, "transform_error");
    /** @type {TemplateNode} */
    __privateAdd(this, _anchor);
    /** @type {TemplateNode | null} */
    __privateAdd(this, _hydrate_open, null);
    /** @type {BoundaryProps} */
    __privateAdd(this, _props);
    /** @type {((anchor: Node) => void)} */
    __privateAdd(this, _children);
    /** @type {Effect} */
    __privateAdd(this, _effect);
    /** @type {Effect | null} */
    __privateAdd(this, _main_effect, null);
    /** @type {Effect | null} */
    __privateAdd(this, _pending_effect, null);
    /** @type {Effect | null} */
    __privateAdd(this, _failed_effect, null);
    /** @type {DocumentFragment | null} */
    __privateAdd(this, _offscreen_fragment, null);
    __privateAdd(this, _local_pending_count, 0);
    __privateAdd(this, _pending_count, 0);
    __privateAdd(this, _pending_count_update_queued, false);
    /** @type {Set<Effect>} */
    __privateAdd(this, _dirty_effects2, /* @__PURE__ */ new Set());
    /** @type {Set<Effect>} */
    __privateAdd(this, _maybe_dirty_effects2, /* @__PURE__ */ new Set());
    /**
     * A source containing the number of pending async deriveds/expressions.
     * Only created if `$effect.pending()` is used inside the boundary,
     * otherwise updating the source results in needless `Batch.ensure()`
     * calls followed by no-op flushes
     * @type {Source<number> | null}
     */
    __privateAdd(this, _effect_pending, null);
    __privateAdd(this, _effect_pending_subscriber, createSubscriber(() => {
      __privateSet(this, _effect_pending, source(__privateGet(this, _local_pending_count)));
      return () => {
        __privateSet(this, _effect_pending, null);
      };
    }));
    var _a2;
    __privateSet(this, _anchor, node);
    __privateSet(this, _props, props);
    __privateSet(this, _children, (anchor) => {
      var effect2 = (
        /** @type {Effect} */
        active_effect
      );
      effect2.b = this;
      effect2.f |= BOUNDARY_EFFECT;
      children(anchor);
    });
    this.parent = /** @type {Effect} */
    active_effect.b;
    this.transform_error = transform_error ?? ((_a2 = this.parent) == null ? void 0 : _a2.transform_error) ?? ((e) => e);
    __privateSet(this, _effect, block(() => {
      {
        __privateMethod(this, _Boundary_instances, render_fn).call(this);
      }
    }, flags));
  }
  /**
   * Defer an effect inside a pending boundary until the boundary resolves
   * @param {Effect} effect
   */
  defer_effect(effect2) {
    defer_effect(effect2, __privateGet(this, _dirty_effects2), __privateGet(this, _maybe_dirty_effects2));
  }
  /**
   * Returns `false` if the effect exists inside a boundary whose pending snippet is shown
   * @returns {boolean}
   */
  is_rendered() {
    return !this.is_pending && (!this.parent || this.parent.is_rendered());
  }
  has_pending_snippet() {
    return !!__privateGet(this, _props).pending;
  }
  /**
   * Update the source that powers `$effect.pending()` inside this boundary,
   * and controls when the current `pending` snippet (if any) is removed.
   * Do not call from inside the class
   * @param {1 | -1} d
   * @param {Batch} batch
   */
  update_pending_count(d, batch) {
    __privateMethod(this, _Boundary_instances, update_pending_count_fn).call(this, d, batch);
    __privateSet(this, _local_pending_count, __privateGet(this, _local_pending_count) + d);
    if (!__privateGet(this, _effect_pending) || __privateGet(this, _pending_count_update_queued)) return;
    __privateSet(this, _pending_count_update_queued, true);
    queue_micro_task(() => {
      __privateSet(this, _pending_count_update_queued, false);
      if (__privateGet(this, _effect_pending)) {
        internal_set(__privateGet(this, _effect_pending), __privateGet(this, _local_pending_count));
      }
    });
  }
  get_effect_pending() {
    __privateGet(this, _effect_pending_subscriber).call(this);
    return get(
      /** @type {Source<number>} */
      __privateGet(this, _effect_pending)
    );
  }
  /** @param {unknown} error */
  error(error) {
    if (!__privateGet(this, _props).onerror && !__privateGet(this, _props).failed) {
      throw error;
    }
    if (current_batch == null ? void 0 : current_batch.is_fork) {
      if (__privateGet(this, _main_effect)) current_batch.skip_effect(__privateGet(this, _main_effect));
      if (__privateGet(this, _pending_effect)) current_batch.skip_effect(__privateGet(this, _pending_effect));
      if (__privateGet(this, _failed_effect)) current_batch.skip_effect(__privateGet(this, _failed_effect));
      current_batch.oncommit(() => {
        __privateMethod(this, _Boundary_instances, handle_error_fn).call(this, error);
      });
    } else {
      __privateMethod(this, _Boundary_instances, handle_error_fn).call(this, error);
    }
  }
}
_anchor = new WeakMap();
_hydrate_open = new WeakMap();
_props = new WeakMap();
_children = new WeakMap();
_effect = new WeakMap();
_main_effect = new WeakMap();
_pending_effect = new WeakMap();
_failed_effect = new WeakMap();
_offscreen_fragment = new WeakMap();
_local_pending_count = new WeakMap();
_pending_count = new WeakMap();
_pending_count_update_queued = new WeakMap();
_dirty_effects2 = new WeakMap();
_maybe_dirty_effects2 = new WeakMap();
_effect_pending = new WeakMap();
_effect_pending_subscriber = new WeakMap();
_Boundary_instances = new WeakSet();
hydrate_resolved_content_fn = function() {
  try {
    __privateSet(this, _main_effect, branch(() => __privateGet(this, _children).call(this, __privateGet(this, _anchor))));
  } catch (error) {
    this.error(error);
  }
};
/**
 * @param {unknown} error The deserialized error from the server's hydration comment
 */
hydrate_failed_content_fn = function(error) {
  const failed = __privateGet(this, _props).failed;
  const { reset, invoke_onerror } = __privateMethod(this, _Boundary_instances, create_reset_fn).call(this, error);
  queue_micro_task(invoke_onerror);
  if (!failed) return;
  __privateSet(this, _failed_effect, branch(() => {
    failed(
      __privateGet(this, _anchor),
      () => error,
      () => reset
    );
  }));
};
/**
 * Creates the `reset` function for a failed boundary, along with a function
 * that invokes `onerror` with it (if provided)
 * @param {unknown} error
 * @returns {{ reset: () => void, invoke_onerror: () => void }}
 */
create_reset_fn = function(error) {
  var did_reset = false;
  var calling_on_error = false;
  const reset = () => {
    if (did_reset) {
      svelte_boundary_reset_noop();
      return;
    }
    did_reset = true;
    if (calling_on_error) {
      svelte_boundary_reset_onerror();
    }
    if (__privateGet(this, _failed_effect) !== null) {
      pause_effect(__privateGet(this, _failed_effect), () => {
        __privateSet(this, _failed_effect, null);
      });
    }
    __privateMethod(this, _Boundary_instances, run_fn).call(this, () => {
      __privateMethod(this, _Boundary_instances, render_fn).call(this);
    });
  };
  const invoke_onerror = () => {
    var _a2, _b2;
    try {
      calling_on_error = true;
      (_b2 = (_a2 = __privateGet(this, _props)).onerror) == null ? void 0 : _b2.call(_a2, error, reset);
      calling_on_error = false;
    } catch (err) {
      invoke_error_boundary(err, __privateGet(this, _effect) && __privateGet(this, _effect).parent);
    }
  };
  return { reset, invoke_onerror };
};
hydrate_pending_content_fn = function() {
  const pending = __privateGet(this, _props).pending;
  if (!pending) return;
  this.is_pending = true;
  __privateSet(this, _pending_effect, branch(() => pending(__privateGet(this, _anchor))));
  queue_micro_task(() => {
    var fragment = __privateSet(this, _offscreen_fragment, document.createDocumentFragment());
    var anchor = create_text();
    var handled = false;
    fragment.append(anchor);
    __privateSet(this, _main_effect, __privateMethod(this, _Boundary_instances, run_fn).call(this, () => {
      try {
        return branch(() => __privateGet(this, _children).call(this, anchor));
      } catch (error) {
        try {
          this.error(error);
          handled = true;
        } catch (error2) {
          invoke_error_boundary(error2, __privateGet(this, _effect).parent);
        }
        return null;
      }
    }));
    if (__privateGet(this, _main_effect) === null) {
      __privateSet(this, _offscreen_fragment, null);
      if (handled) __privateMethod(this, _Boundary_instances, resolve_fn).call(
        this,
        /** @type {Batch} */
        current_batch
      );
      return;
    }
    if (__privateGet(this, _pending_count) === 0) {
      __privateGet(this, _anchor).before(fragment);
      __privateSet(this, _offscreen_fragment, null);
      pause_effect(
        /** @type {Effect} */
        __privateGet(this, _pending_effect),
        () => {
          __privateSet(this, _pending_effect, null);
        }
      );
      __privateMethod(this, _Boundary_instances, resolve_fn).call(
        this,
        /** @type {Batch} */
        current_batch
      );
    }
  });
};
render_fn = function() {
  try {
    this.is_pending = this.has_pending_snippet();
    __privateSet(this, _pending_count, 0);
    __privateSet(this, _local_pending_count, 0);
    __privateSet(this, _main_effect, branch(() => {
      __privateGet(this, _children).call(this, __privateGet(this, _anchor));
    }));
    if (__privateGet(this, _pending_count) > 0) {
      var fragment = __privateSet(this, _offscreen_fragment, document.createDocumentFragment());
      move_effect(__privateGet(this, _main_effect), fragment);
      const pending = (
        /** @type {(anchor: Node) => void} */
        __privateGet(this, _props).pending
      );
      __privateSet(this, _pending_effect, branch(() => pending(__privateGet(this, _anchor))));
    } else {
      __privateMethod(this, _Boundary_instances, resolve_fn).call(
        this,
        /** @type {Batch} */
        current_batch
      );
    }
  } catch (error) {
    this.error(error);
  }
};
/**
 * @param {Batch} batch
 */
resolve_fn = function(batch) {
  this.is_pending = false;
  batch.transfer_effects(__privateGet(this, _dirty_effects2), __privateGet(this, _maybe_dirty_effects2));
};
/**
 * @template T
 * @param {() => T} fn
 */
run_fn = function(fn) {
  var previous_effect = active_effect;
  var previous_reaction = active_reaction;
  var previous_ctx = component_context;
  set_active_effect(__privateGet(this, _effect));
  set_active_reaction(__privateGet(this, _effect));
  set_component_context(__privateGet(this, _effect).ctx);
  try {
    Batch.ensure();
    return fn();
  } finally {
    set_active_effect(previous_effect);
    set_active_reaction(previous_reaction);
    set_component_context(previous_ctx);
  }
};
/**
 * Updates the pending count associated with the currently visible pending snippet,
 * if any, such that we can replace the snippet with content once work is done
 * @param {1 | -1} d
 * @param {Batch} batch
 */
update_pending_count_fn = function(d, batch) {
  var _a2;
  if (!this.has_pending_snippet()) {
    if (this.parent) {
      __privateMethod(_a2 = this.parent, _Boundary_instances, update_pending_count_fn).call(_a2, d, batch);
    }
    return;
  }
  __privateSet(this, _pending_count, __privateGet(this, _pending_count) + d);
  if (__privateGet(this, _pending_count) === 0) {
    __privateMethod(this, _Boundary_instances, resolve_fn).call(this, batch);
    if (__privateGet(this, _pending_effect)) {
      pause_effect(__privateGet(this, _pending_effect), () => {
        __privateSet(this, _pending_effect, null);
      });
    }
    if (__privateGet(this, _offscreen_fragment)) {
      __privateGet(this, _anchor).before(__privateGet(this, _offscreen_fragment));
      __privateSet(this, _offscreen_fragment, null);
    }
  }
};
/**
 * @param {unknown} error
 */
handle_error_fn = function(error) {
  if (__privateGet(this, _main_effect)) {
    destroy_effect(__privateGet(this, _main_effect));
    __privateSet(this, _main_effect, null);
  }
  if (__privateGet(this, _pending_effect)) {
    destroy_effect(__privateGet(this, _pending_effect));
    __privateSet(this, _pending_effect, null);
  }
  if (__privateGet(this, _failed_effect)) {
    destroy_effect(__privateGet(this, _failed_effect));
    __privateSet(this, _failed_effect, null);
  }
  let failed = __privateGet(this, _props).failed;
  const handle_error_result = (transformed_error) => {
    const { reset, invoke_onerror } = __privateMethod(this, _Boundary_instances, create_reset_fn).call(this, transformed_error);
    invoke_onerror();
    if (failed) {
      __privateSet(this, _failed_effect, __privateMethod(this, _Boundary_instances, run_fn).call(this, () => {
        try {
          return branch(() => {
            var effect2 = (
              /** @type {Effect} */
              active_effect
            );
            effect2.b = this;
            effect2.f |= BOUNDARY_EFFECT;
            failed(
              __privateGet(this, _anchor),
              () => transformed_error,
              () => reset
            );
          });
        } catch (error2) {
          invoke_error_boundary(
            error2,
            /** @type {Effect} */
            __privateGet(this, _effect).parent
          );
          return null;
        }
      }));
    }
  };
  queue_micro_task(() => {
    var result;
    try {
      result = this.transform_error(error);
    } catch (e) {
      invoke_error_boundary(e, __privateGet(this, _effect) && __privateGet(this, _effect).parent);
      return;
    }
    if (result !== null && typeof result === "object" && typeof /** @type {any} */
    result.then === "function") {
      result.then(
        handle_error_result,
        /** @param {unknown} e */
        (e) => invoke_error_boundary(e, __privateGet(this, _effect) && __privateGet(this, _effect).parent)
      );
    } else {
      handle_error_result(result);
    }
  });
};
function set_text(text, value) {
  var str = value == null ? "" : typeof value === "object" ? `${value}` : value;
  if (str !== /** @type {any} */
  (text[TEXT_CACHE] ?? (text[TEXT_CACHE] = text.nodeValue))) {
    text[TEXT_CACHE] = str;
    text.nodeValue = `${str}`;
  }
}
function mount(component, options) {
  return _mount(component, options);
}
const listeners = /* @__PURE__ */ new Map();
function _mount(Component, { target: target2, anchor, props = {}, events, context, intro = true, transformError }) {
  init_operations();
  var component = void 0;
  var unmount = component_root(() => {
    var anchor_node = anchor ?? target2.appendChild(create_text());
    boundary(
      /** @type {TemplateNode} */
      anchor_node,
      {
        pending: () => {
        }
      },
      (anchor_node2) => {
        push({});
        var ctx = (
          /** @type {ComponentContext} */
          component_context
        );
        if (context) ctx.c = context;
        if (events) {
          props.$$events = events;
        }
        component = Component(anchor_node2, props) || mark_as_component();
        pop();
      },
      transformError
    );
    var registered_events = /* @__PURE__ */ new Set();
    var event_handle = (events2) => {
      for (var i = 0; i < events2.length; i++) {
        var event_name = events2[i];
        if (registered_events.has(event_name)) continue;
        registered_events.add(event_name);
        var passive = is_passive_event(event_name);
        for (const node of [target2, document]) {
          var counts = listeners.get(node);
          if (counts === void 0) {
            counts = /* @__PURE__ */ new Map();
            listeners.set(node, counts);
          }
          var count = counts.get(event_name);
          if (count === void 0) {
            node.addEventListener(event_name, handle_event_propagation, { passive });
            counts.set(event_name, 1);
          } else {
            counts.set(event_name, count + 1);
          }
        }
      }
    };
    event_handle(array_from(all_registered_events));
    root_event_handles.add(event_handle);
    return () => {
      var _a2;
      for (var event_name of registered_events) {
        for (const node of [target2, document]) {
          var counts = (
            /** @type {Map<string, number>} */
            listeners.get(node)
          );
          var count = (
            /** @type {number} */
            counts.get(event_name)
          );
          if (--count == 0) {
            node.removeEventListener(event_name, handle_event_propagation);
            counts.delete(event_name);
            if (counts.size === 0) {
              listeners.delete(node);
            }
          } else {
            counts.set(event_name, count);
          }
        }
      }
      root_event_handles.delete(event_handle);
      if (anchor_node !== anchor) {
        (_a2 = anchor_node.parentNode) == null ? void 0 : _a2.removeChild(anchor_node);
      }
    };
  });
  mounted_components.set(component, unmount);
  return component;
}
let mounted_components = /* @__PURE__ */ new WeakMap();
class BranchManager {
  /**
   * @param {TemplateNode} anchor
   * @param {boolean} transition
   */
  constructor(anchor, transition = true) {
    /** @type {TemplateNode} */
    __publicField(this, "anchor");
    /** @type {Map<Batch, Key>} */
    __privateAdd(this, _batches, /* @__PURE__ */ new Map());
    /**
     * Map of keys to effects that are currently rendered in the DOM.
     * These effects are visible and actively part of the document tree.
     * Example:
     * ```
     * {#if condition}
     * 	foo
     * {:else}
     * 	bar
     * {/if}
     * ```
     * Can result in the entries `true->Effect` and `false->Effect`
     * @type {Map<Key, Effect>}
     */
    __privateAdd(this, _onscreen, /* @__PURE__ */ new Map());
    /**
     * Similar to #onscreen with respect to the keys, but contains branches that are not yet
     * in the DOM, because their insertion is deferred.
     * @type {Map<Key, Branch>}
     */
    __privateAdd(this, _offscreen, /* @__PURE__ */ new Map());
    /**
     * Keys of effects that are currently outroing
     * @type {Set<Key>}
     */
    __privateAdd(this, _outroing, /* @__PURE__ */ new Set());
    /**
     * Whether to pause (i.e. outro) on change, or destroy immediately.
     * This is necessary for `<svelte:element>`
     */
    __privateAdd(this, _transition, true);
    /**
     * @param {Batch} batch
     */
    __privateAdd(this, _commit, (batch) => {
      if (!__privateGet(this, _batches).has(batch)) return;
      var key2 = (
        /** @type {Key} */
        __privateGet(this, _batches).get(batch)
      );
      var onscreen = __privateGet(this, _onscreen).get(key2);
      if (onscreen) {
        resume_effect(onscreen);
        __privateGet(this, _outroing).delete(key2);
      } else {
        var offscreen = __privateGet(this, _offscreen).get(key2);
        if (offscreen) {
          resume_effect(offscreen.effect);
          __privateGet(this, _onscreen).set(key2, offscreen.effect);
          __privateGet(this, _offscreen).delete(key2);
          offscreen.fragment.lastChild.remove();
          this.anchor.before(offscreen.fragment);
          onscreen = offscreen.effect;
        }
      }
      for (const [b, k] of __privateGet(this, _batches)) {
        __privateGet(this, _batches).delete(b);
        if (b === batch) {
          break;
        }
        const offscreen2 = __privateGet(this, _offscreen).get(k);
        if (offscreen2) {
          destroy_effect(offscreen2.effect);
          __privateGet(this, _offscreen).delete(k);
        }
      }
      for (const [k, effect2] of __privateGet(this, _onscreen)) {
        if (k === key2 || __privateGet(this, _outroing).has(k)) continue;
        const on_destroy = () => {
          const keys = Array.from(__privateGet(this, _batches).values());
          if (keys.includes(k)) {
            var fragment = document.createDocumentFragment();
            move_effect(effect2, fragment);
            fragment.append(create_text());
            __privateGet(this, _offscreen).set(k, { effect: effect2, fragment });
          } else {
            destroy_effect(effect2);
          }
          __privateGet(this, _outroing).delete(k);
          __privateGet(this, _onscreen).delete(k);
        };
        if (__privateGet(this, _transition) || !onscreen) {
          __privateGet(this, _outroing).add(k);
          pause_effect(effect2, on_destroy, false);
        } else {
          on_destroy();
        }
      }
    });
    /**
     * @param {Batch} batch
     */
    __privateAdd(this, _discard, (batch) => {
      __privateGet(this, _batches).delete(batch);
      const keys = Array.from(__privateGet(this, _batches).values());
      for (const [k, branch2] of __privateGet(this, _offscreen)) {
        if (!keys.includes(k)) {
          destroy_effect(branch2.effect);
          __privateGet(this, _offscreen).delete(k);
        }
      }
    });
    this.anchor = anchor;
    __privateSet(this, _transition, transition);
  }
  /**
   *
   * @param {any} key
   * @param {null | ((target: TemplateNode) => void)} fn
   */
  ensure(key2, fn) {
    var batch = (
      /** @type {Batch} */
      current_batch
    );
    var defer = should_defer_append();
    if (fn && !__privateGet(this, _onscreen).has(key2) && !__privateGet(this, _offscreen).has(key2)) {
      if (defer) {
        var fragment = document.createDocumentFragment();
        var target2 = create_text();
        fragment.append(target2);
        __privateGet(this, _offscreen).set(key2, {
          effect: branch(() => fn(target2)),
          fragment
        });
      } else {
        __privateGet(this, _onscreen).set(
          key2,
          branch(() => fn(this.anchor))
        );
      }
    }
    __privateGet(this, _batches).set(batch, key2);
    if (defer) {
      for (const [k, effect2] of __privateGet(this, _onscreen)) {
        if (k === key2) {
          batch.unskip_effect(effect2);
        } else {
          batch.skip_effect(effect2);
        }
      }
      for (const [k, branch2] of __privateGet(this, _offscreen)) {
        if (k === key2) {
          batch.unskip_effect(branch2.effect);
        } else {
          batch.skip_effect(branch2.effect);
        }
      }
      batch.oncommit(__privateGet(this, _commit));
      batch.ondiscard(__privateGet(this, _discard));
    } else {
      __privateGet(this, _commit).call(this, batch);
    }
  }
}
_batches = new WeakMap();
_onscreen = new WeakMap();
_offscreen = new WeakMap();
_outroing = new WeakMap();
_transition = new WeakMap();
_commit = new WeakMap();
_discard = new WeakMap();
function if_block(node, fn, elseif = false) {
  var branches = new BranchManager(node);
  var flags2 = elseif ? EFFECT_TRANSPARENT : 0;
  function update_branch(key2, fn2) {
    branches.ensure(key2, fn2);
  }
  block(() => {
    var has_branch = false;
    fn((fn2, key2 = 0) => {
      has_branch = true;
      update_branch(key2, fn2);
    });
    if (!has_branch) {
      update_branch(-1, null);
    }
  }, flags2);
}
const NAN = Symbol("NaN");
function key(node, get_key, render_fn2) {
  var branches = new BranchManager(node);
  var legacy = !is_runes();
  block(() => {
    var key2 = get_key();
    if (key2 !== key2) {
      key2 = /** @type {any} */
      NAN;
    }
    if (legacy && key2 !== null && typeof key2 === "object") {
      key2 = /** @type {V} */
      {};
    }
    branches.ensure(key2, render_fn2);
  });
}
function index(_, i) {
  return i;
}
function pause_effects(state2, to_destroy, controlled_anchor) {
  var transitions = [];
  var length = to_destroy.length;
  var group;
  var remaining = to_destroy.length;
  for (var i = 0; i < length; i++) {
    let effect2 = to_destroy[i];
    pause_effect(
      effect2,
      () => {
        if (group) {
          group.pending.delete(effect2);
          group.done.add(effect2);
          if (group.pending.size === 0) {
            var groups = (
              /** @type {Set<EachOutroGroup>} */
              state2.outrogroups
            );
            destroy_effects(state2, array_from(group.done));
            groups.delete(group);
            if (groups.size === 0) {
              state2.outrogroups = null;
            }
          }
        } else {
          remaining -= 1;
        }
      },
      false
    );
  }
  if (remaining === 0) {
    var fast_path = transitions.length === 0 && controlled_anchor !== null && state2.pending.size === 0;
    if (fast_path) {
      var anchor = (
        /** @type {Element} */
        controlled_anchor
      );
      var parent_node = (
        /** @type {Element} */
        anchor.parentNode
      );
      clear_text_content(parent_node);
      parent_node.append(anchor);
      state2.items.clear();
    }
    destroy_effects(state2, to_destroy, !fast_path);
  } else {
    group = {
      pending: new Set(to_destroy),
      done: /* @__PURE__ */ new Set()
    };
    (state2.outrogroups ?? (state2.outrogroups = /* @__PURE__ */ new Set())).add(group);
  }
}
function destroy_effects(state2, to_destroy, remove_dom = true) {
  var preserved_effects;
  if (state2.pending.size > 0) {
    preserved_effects = /* @__PURE__ */ new Set();
    for (const keys of state2.pending.values()) {
      for (const key2 of keys) {
        preserved_effects.add(
          /** @type {EachItem} */
          state2.items.get(key2).e
        );
      }
    }
  }
  for (var i = 0; i < to_destroy.length; i++) {
    var e = to_destroy[i];
    if (preserved_effects == null ? void 0 : preserved_effects.has(e)) {
      e.f |= EFFECT_OFFSCREEN;
      const fragment = document.createDocumentFragment();
      move_effect(e, fragment);
    } else {
      destroy_effect(to_destroy[i], remove_dom);
    }
  }
}
var offscreen_anchor;
function each(node, flags2, get_collection, get_key, render_fn2, fallback_fn = null) {
  var anchor = node;
  var items = /* @__PURE__ */ new Map();
  {
    var parent_node = (
      /** @type {Element} */
      node
    );
    anchor = parent_node.appendChild(create_text());
  }
  var fallback = null;
  var each_array = /* @__PURE__ */ derived_safe_equal(() => {
    var collection = get_collection();
    return (
      /** @type {V[]} */
      is_array(collection) ? collection : collection == null ? [] : array_from(collection)
    );
  });
  var array;
  var pending = /* @__PURE__ */ new Map();
  var first_run = true;
  function commit(batch) {
    if ((state2.effect.f & DESTROYED) !== 0) {
      return;
    }
    state2.pending.delete(batch);
    state2.fallback = fallback;
    reconcile(state2, array, anchor, flags2, get_key);
    if (fallback !== null) {
      if (array.length === 0) {
        if ((fallback.f & EFFECT_OFFSCREEN) === 0) {
          resume_effect(fallback);
        } else {
          fallback.f ^= EFFECT_OFFSCREEN;
          move(fallback, null, anchor);
        }
      } else {
        pause_effect(fallback, () => {
          fallback = null;
        });
      }
    }
  }
  function discard(batch) {
    state2.pending.delete(batch);
  }
  var effect2 = block(() => {
    array = /** @type {V[]} */
    get(each_array);
    var length = array.length;
    var keys = /* @__PURE__ */ new Set();
    var batch = (
      /** @type {Batch} */
      current_batch
    );
    var defer = should_defer_append();
    for (var index2 = 0; index2 < length; index2 += 1) {
      var value = array[index2];
      var key2 = get_key(value, index2);
      var item = first_run ? null : items.get(key2);
      if (item) {
        if (item.v) internal_set(item.v, value);
        if (item.i) internal_set(item.i, index2);
        if (defer) {
          batch.unskip_effect(item.e);
        }
      } else {
        item = create_item(
          items,
          first_run ? anchor : offscreen_anchor ?? (offscreen_anchor = create_text()),
          value,
          key2,
          index2,
          render_fn2,
          flags2,
          get_collection
        );
        if (!first_run) {
          item.e.f |= EFFECT_OFFSCREEN;
        }
        items.set(key2, item);
      }
      keys.add(key2);
    }
    if (length === 0 && fallback_fn && !fallback) {
      if (first_run) {
        fallback = branch(() => fallback_fn(anchor));
      } else {
        fallback = branch(() => fallback_fn(offscreen_anchor ?? (offscreen_anchor = create_text())));
        fallback.f |= EFFECT_OFFSCREEN;
      }
    }
    if (length > keys.size) {
      {
        each_key_duplicate();
      }
    }
    if (!first_run) {
      pending.set(batch, keys);
      if (defer) {
        for (const [key3, item2] of items) {
          if (!keys.has(key3)) {
            batch.skip_effect(item2.e);
          }
        }
        batch.oncommit(commit);
        batch.ondiscard(discard);
      } else {
        commit(batch);
      }
    }
    get(each_array);
  });
  var state2 = { effect: effect2, items, pending, outrogroups: null, fallback };
  first_run = false;
}
function skip_to_branch(effect2) {
  while (effect2 !== null && (effect2.f & BRANCH_EFFECT) === 0) {
    effect2 = effect2.next;
  }
  return effect2;
}
function reconcile(state2, array, anchor, flags2, get_key) {
  var _a2;
  var length = array.length;
  var items = state2.items;
  var current = skip_to_branch(state2.effect.first);
  var seen;
  var prev = null;
  var matched = [];
  var stashed = [];
  var value;
  var key2;
  var effect2;
  var i;
  for (i = 0; i < length; i += 1) {
    value = array[i];
    key2 = get_key(value, i);
    effect2 = /** @type {EachItem} */
    items.get(key2).e;
    if (state2.outrogroups !== null) {
      for (const group of state2.outrogroups) {
        group.pending.delete(effect2);
        group.done.delete(effect2);
      }
    }
    if ((effect2.f & INERT) !== 0) {
      resume_effect(effect2);
    }
    if ((effect2.f & EFFECT_OFFSCREEN) !== 0) {
      effect2.f ^= EFFECT_OFFSCREEN;
      if (effect2 === current) {
        move(effect2, null, anchor);
      } else {
        var next = prev ? prev.next : current;
        if (effect2 === state2.effect.last) {
          state2.effect.last = effect2.prev;
        }
        if (effect2.prev) effect2.prev.next = effect2.next;
        if (effect2.next) effect2.next.prev = effect2.prev;
        link(state2, prev, effect2);
        link(state2, effect2, next);
        move(effect2, next, anchor);
        prev = effect2;
        matched = [];
        stashed = [];
        current = skip_to_branch(prev.next);
        continue;
      }
    }
    if (effect2 !== current) {
      if (seen !== void 0 && seen.has(effect2)) {
        if (matched.length < stashed.length) {
          var start = stashed[0];
          var j;
          prev = start.prev;
          var a = matched[0];
          var b = matched[matched.length - 1];
          for (j = 0; j < matched.length; j += 1) {
            move(matched[j], start, anchor);
          }
          for (j = 0; j < stashed.length; j += 1) {
            seen.delete(stashed[j]);
          }
          link(state2, a.prev, b.next);
          link(state2, prev, a);
          link(state2, b, start);
          current = start;
          prev = b;
          i -= 1;
          matched = [];
          stashed = [];
        } else {
          seen.delete(effect2);
          move(effect2, current, anchor);
          link(state2, effect2.prev, effect2.next);
          link(state2, effect2, prev === null ? state2.effect.first : prev.next);
          link(state2, prev, effect2);
          prev = effect2;
        }
        continue;
      }
      matched = [];
      stashed = [];
      while (current !== null && current !== effect2) {
        (seen ?? (seen = /* @__PURE__ */ new Set())).add(current);
        stashed.push(current);
        current = skip_to_branch(current.next);
      }
      if (current === null) {
        continue;
      }
    }
    if ((effect2.f & EFFECT_OFFSCREEN) === 0) {
      matched.push(effect2);
    }
    prev = effect2;
    current = skip_to_branch(effect2.next);
  }
  if (state2.outrogroups !== null) {
    for (const group of state2.outrogroups) {
      if (group.pending.size === 0) {
        destroy_effects(state2, array_from(group.done));
        (_a2 = state2.outrogroups) == null ? void 0 : _a2.delete(group);
      }
    }
    if (state2.outrogroups.size === 0) {
      state2.outrogroups = null;
    }
  }
  if (current !== null || seen !== void 0) {
    var to_destroy = [];
    if (seen !== void 0) {
      for (effect2 of seen) {
        if ((effect2.f & INERT) === 0) {
          to_destroy.push(effect2);
        }
      }
    }
    while (current !== null) {
      if ((current.f & INERT) === 0 && current !== state2.fallback) {
        to_destroy.push(current);
      }
      current = skip_to_branch(current.next);
    }
    var destroy_length = to_destroy.length;
    if (destroy_length > 0) {
      var controlled_anchor = length === 0 ? anchor : null;
      pause_effects(state2, to_destroy, controlled_anchor);
    }
  }
}
function create_item(items, anchor, value, key2, index2, render_fn2, flags2, get_collection) {
  var v = (flags2 & EACH_ITEM_REACTIVE) !== 0 ? (flags2 & EACH_ITEM_IMMUTABLE) === 0 ? /* @__PURE__ */ mutable_source(value, false, false) : source(value) : null;
  var i = (flags2 & EACH_INDEX_REACTIVE) !== 0 ? source(index2) : null;
  return {
    v,
    i,
    e: branch(() => {
      render_fn2(anchor, v ?? value, i ?? index2, get_collection);
      return () => {
        items.delete(key2);
      };
    })
  };
}
function move(effect2, next, anchor) {
  if (!effect2.nodes) return;
  var node = effect2.nodes.start;
  var end = effect2.nodes.end;
  var dest = next && (next.f & EFFECT_OFFSCREEN) === 0 ? (
    /** @type {EffectNodes} */
    next.nodes.start
  ) : anchor;
  while (node !== null) {
    var next_node = (
      /** @type {TemplateNode} */
      /* @__PURE__ */ get_next_sibling(node)
    );
    dest.before(node);
    if (node === end) {
      return;
    }
    node = next_node;
  }
}
function link(state2, prev, next) {
  if (prev === null) {
    state2.effect.first = next;
  } else {
    prev.next = next;
  }
  if (next === null) {
    state2.effect.last = prev;
  } else {
    next.prev = prev;
  }
}
const whitespace = [..." 	\n\r\f \v\uFEFF"];
function to_class(value, hash, directives) {
  var classname = value == null ? "" : "" + value;
  if (hash) {
    classname = classname ? classname + " " + hash : hash;
  }
  if (directives) {
    for (var key2 of Object.keys(directives)) {
      if (directives[key2]) {
        classname = classname ? classname + " " + key2 : key2;
      } else if (classname.length) {
        var len = key2.length;
        var a = 0;
        while ((a = classname.indexOf(key2, a)) >= 0) {
          var b = a + len;
          if ((a === 0 || whitespace.includes(classname[a - 1])) && (b === classname.length || whitespace.includes(classname[b]))) {
            classname = (a === 0 ? "" : classname.substring(0, a)) + classname.substring(b + 1);
          } else {
            a = b;
          }
        }
      }
    }
  }
  return classname === "" ? null : classname;
}
function set_class(dom, is_html, value, hash, prev_classes, next_classes) {
  var prev = (
    /** @type {any} */
    dom[CLASS_CACHE]
  );
  if (prev !== value || prev === void 0) {
    var next_class_name = to_class(value, hash, next_classes);
    {
      if (next_class_name == null) {
        dom.removeAttribute("class");
      } else {
        dom.className = next_class_name;
      }
    }
    dom[CLASS_CACHE] = value;
  } else if (next_classes && prev_classes !== next_classes) {
    for (var key2 in next_classes) {
      var is_present = !!next_classes[key2];
      if (prev_classes == null || is_present !== !!prev_classes[key2]) {
        dom.classList.toggle(key2, is_present);
      }
    }
  }
  return next_classes;
}
const IS_CUSTOM_ELEMENT = Symbol("is custom element");
const IS_HTML = Symbol("is html");
function set_attribute(element, attribute, value, skip_warning) {
  var attributes = get_attributes(element);
  if (attributes[attribute] === (attributes[attribute] = value)) return;
  if (attribute === "loading") {
    element[LOADING_ATTR_SYMBOL] = value;
  }
  if (value == null) {
    element.removeAttribute(attribute);
  } else if (typeof value !== "string" && get_setters(element).has(attribute)) {
    element[attribute] = value;
  } else {
    element.setAttribute(attribute, value);
  }
}
function get_attributes(element) {
  return (
    /** @type {Record<string | symbol, unknown>} **/
    /** @type {any} */
    element[ATTRIBUTES_CACHE] ?? (element[ATTRIBUTES_CACHE] = {
      [IS_CUSTOM_ELEMENT]: element.nodeName.includes("-"),
      [IS_HTML]: element.namespaceURI === NAMESPACE_HTML
    })
  );
}
var setters_cache = /* @__PURE__ */ new Map();
function get_setters(element) {
  var cache_key = element.getAttribute("is") || element.nodeName;
  var setters = setters_cache.get(cache_key);
  if (setters) return setters;
  setters_cache.set(cache_key, setters = /* @__PURE__ */ new Set());
  var descriptors;
  var proto = element;
  var element_proto = Element.prototype;
  while (element_proto !== proto) {
    descriptors = get_descriptors(proto);
    for (var key2 in descriptors) {
      if (descriptors[key2].set && // better safe than sorry, we don't want spread attributes to mess with HTML content
      key2 !== "innerHTML" && key2 !== "textContent" && key2 !== "innerText") {
        setters.add(key2);
      }
    }
    proto = get_prototype_of(proto);
  }
  return setters;
}
function is_bound_this(bound_value, element_or_component) {
  return bound_value === element_or_component || (bound_value == null ? void 0 : bound_value[STATE_SYMBOL]) === element_or_component;
}
function bind_this(element_or_component = mark_as_component(), update, get_value, get_parts) {
  var component_effect = (
    /** @type {ComponentContext} */
    component_context.r
  );
  var parent = (
    /** @type {Effect} */
    active_effect
  );
  effect(() => {
    var old_parts;
    var parts;
    render_effect(() => {
      old_parts = parts;
      parts = [];
      untrack(() => {
        if (!is_bound_this(get_value(...parts), element_or_component)) {
          update(element_or_component, ...parts);
          if (old_parts && is_bound_this(get_value(...old_parts), element_or_component)) {
            update(null, ...old_parts);
          }
        }
      });
    });
    return () => {
      let p = parent;
      while (p !== component_effect && p.parent !== null && p.parent.f & DESTROYING) {
        p = p.parent;
      }
      const teardown2 = () => {
        if (parts && is_bound_this(get_value(...parts), element_or_component)) {
          update(null, ...parts);
        }
      };
      const original_teardown = p.teardown;
      p.teardown = () => {
        teardown2();
        original_teardown == null ? void 0 : original_teardown();
      };
    };
  });
  return element_or_component;
}
function init(immutable = false) {
  const context = (
    /** @type {ComponentContextLegacy} */
    component_context
  );
  const callbacks = context.l.u;
  if (!callbacks) return;
  let props = () => deep_read_state(context.s);
  if (immutable) {
    let version = 0;
    let prev = (
      /** @type {Record<string, any>} */
      {}
    );
    const d = /* @__PURE__ */ derived(() => {
      let changed = false;
      const props2 = context.s;
      for (const key2 in props2) {
        if (props2[key2] !== prev[key2]) {
          prev[key2] = props2[key2];
          changed = true;
        }
      }
      if (changed) version++;
      return version;
    });
    props = () => get(d);
  }
  if (callbacks.b.length) {
    user_pre_effect(() => {
      observe_all(context, props);
      run_all(callbacks.b);
    });
  }
  user_effect(() => {
    const fns = untrack(() => callbacks.m.map(run));
    return () => {
      for (const fn of fns) {
        if (typeof fn === "function") {
          fn();
        }
      }
    };
  });
  if (callbacks.a.length) {
    user_effect(() => {
      observe_all(context, props);
      run_all(callbacks.a);
    });
  }
}
function observe_all(context, props) {
  if (context.l.s) {
    for (const signal of context.l.s) get(signal);
  }
  props();
}
function prop(props, key2, flags2, fallback) {
  var _a2;
  var runes = !legacy_mode_flag || (flags2 & PROPS_IS_RUNES) !== 0;
  var bindable = (flags2 & PROPS_IS_BINDABLE) !== 0;
  var fallback_value = (
    /** @type {V} */
    fallback
  );
  var fallback_dirty = true;
  var get_fallback = () => {
    if (fallback_dirty) {
      fallback_dirty = false;
      fallback_value = /** @type {V} */
      fallback;
    }
    return fallback_value;
  };
  let setter;
  {
    var is_entry_props = STATE_SYMBOL in props || LEGACY_PROPS in props;
    setter = ((_a2 = get_descriptor(props, key2)) == null ? void 0 : _a2.set) ?? (is_entry_props && key2 in props ? (v) => props[key2] = v : void 0);
  }
  var initial_value;
  var is_store_sub = false;
  {
    [initial_value, is_store_sub] = capture_store_binding(() => (
      /** @type {V} */
      props[key2]
    ));
  }
  if (initial_value === void 0 && fallback !== void 0) {
    initial_value = get_fallback();
    if (setter) {
      if (runes) props_invalid_value();
      setter(initial_value);
    }
  }
  var getter;
  if (runes) {
    getter = () => {
      var value = (
        /** @type {V} */
        props[key2]
      );
      if (value === void 0) return get_fallback();
      fallback_dirty = true;
      return value;
    };
  } else {
    getter = () => {
      var value = (
        /** @type {V} */
        props[key2]
      );
      if (value !== void 0) {
        fallback_value = /** @type {V} */
        void 0;
      }
      return value === void 0 ? fallback_value : value;
    };
  }
  if (runes && (flags2 & PROPS_IS_UPDATED) === 0) {
    return getter;
  }
  if (setter) {
    var legacy_parent = props.$$legacy;
    return (
      /** @type {() => V} */
      (function(value, mutation) {
        if (arguments.length > 0) {
          if (!runes || !mutation || legacy_parent || is_store_sub) {
            setter(mutation ? getter() : value);
          }
          return value;
        }
        return getter();
      })
    );
  }
  var overridden = false;
  var d = /* @__PURE__ */ derived_safe_equal(() => {
    overridden = false;
    return getter();
  });
  get(d);
  var parent_effect = (
    /** @type {Effect} */
    active_effect
  );
  return (
    /** @type {() => V} */
    (function(value, mutation) {
      if (arguments.length > 0) {
        const new_value = mutation ? get(d) : runes && bindable ? proxy(value) : value;
        set(d, new_value);
        overridden = true;
        if (fallback_value !== void 0) {
          fallback_value = new_value;
        }
        return value;
      }
      if (is_destroying_effect && overridden || (parent_effect.f & DESTROYED) !== 0) {
        return d.v;
      }
      return get(d);
    })
  );
}
function onMount(fn) {
  if (component_context === null) {
    lifecycle_outside_component();
  }
  if (legacy_mode_flag && component_context.l !== null) {
    init_update_callbacks(component_context).m.push(fn);
  } else {
    user_effect(() => {
      const cleanup = untrack(fn);
      if (typeof cleanup === "function") return (
        /** @type {() => void} */
        cleanup
      );
    });
  }
}
function onDestroy(fn) {
  if (component_context === null) {
    lifecycle_outside_component();
  }
  onMount(() => () => untrack(fn));
}
function afterUpdate(fn) {
  if (component_context === null) {
    lifecycle_outside_component();
  }
  if (component_context.l === null) {
    lifecycle_legacy_only();
  }
  init_update_callbacks(component_context).a.push(fn);
}
function init_update_callbacks(context) {
  var l = (
    /** @type {ComponentContextLegacy} */
    context.l
  );
  return l.u ?? (l.u = { a: [], b: [], m: [] });
}
const PUBLIC_VERSION = "5";
if (typeof window !== "undefined") {
  ((_b = window.__svelte ?? (window.__svelte = {})).v ?? (_b.v = /* @__PURE__ */ new Set())).add(PUBLIC_VERSION);
}
enable_legacy_mode_flag();
var root$2 = /* @__PURE__ */ from_html(`<div class="prompt-account svelte-glm292"> </div>`);
var root_1$2 = /* @__PURE__ */ from_html(`<p class="prompt-error svelte-glm292" data-action-error="" role="alert"> </p>`);
var root_2$2 = /* @__PURE__ */ from_html(`<button> </button>`);
var root_3$2 = /* @__PURE__ */ from_html(`<div class="prompt-overlay svelte-glm292" role="dialog" aria-modal="true" aria-labelledby="prompt-title"><div class="ambient-canvas svelte-glm292" aria-hidden="true"></div> <div class="prompt-card svelte-glm292"><!> <h1 class="prompt-title svelte-glm292" id="prompt-title"> </h1> <p class="prompt-body svelte-glm292"> </p> <!> <div class="prompt-actions svelte-glm292"></div></div></div>`);
function PromptOverlay($$anchor, $$props) {
  push($$props, false);
  let prompt = prop($$props, "prompt", 8);
  let account = prop($$props, "account", 8, null);
  let onAction = prop($$props, "onAction", 8, null);
  let errorMessage = prop($$props, "errorMessage", 8, null);
  const ACTION_TIMEOUT_MS = 1e4;
  const MAX_PROMPT_TIMEOUT_SECONDS = 2147483647e-3;
  let dismissed = /* @__PURE__ */ mutable_source(false);
  let submitting = /* @__PURE__ */ mutable_source(false);
  let localError = /* @__PURE__ */ mutable_source(null);
  let timeoutId = /* @__PURE__ */ mutable_source(null);
  let timeoutKey = /* @__PURE__ */ mutable_source(null);
  onDestroy(() => {
    if (get(timeoutId) !== null) clearTimeout(get(timeoutId));
  });
  function withTimeout(value) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("display action timed out")), ACTION_TIMEOUT_MS);
      Promise.resolve(value).then(
        (result) => {
          clearTimeout(timer);
          resolve(result);
        },
        (error) => {
          clearTimeout(timer);
          reject(error);
        }
      );
    });
  }
  async function sendAction(actionId, choice) {
    if (get(dismissed) || get(submitting)) return;
    set(submitting, true);
    const action = { type: "action", schema: 1, action_id: actionId, choice };
    let accepted = true;
    try {
      if (onAction() !== null) {
        accepted = await withTimeout(onAction()(action)) !== false;
      } else {
        const url = `/action?action_id=${encodeURIComponent(actionId)}&choice=${encodeURIComponent(choice)}`;
        const controller = new AbortController();
        const requestTimeoutId = setTimeout(() => controller.abort(), ACTION_TIMEOUT_MS);
        try {
          const response = await fetch(url, { method: "POST", signal: controller.signal });
          accepted = response.ok;
        } finally {
          clearTimeout(requestTimeoutId);
        }
      }
    } catch {
      accepted = false;
    }
    if (!accepted) {
      set(submitting, false);
      set(localError, "Display action could not be sent");
      return;
    }
    set(dismissed, true);
    set(localError, null);
    set(submitting, false);
    if (get(timeoutId) !== null) {
      clearTimeout(get(timeoutId));
      set(timeoutId, null);
    }
  }
  function handleOption(option) {
    void sendAction(prompt().action_id, option.id);
  }
  legacy_pre_effect(
    () => (deep_read_state(prompt()), get(timeoutKey), get(timeoutId), get(dismissed)),
    () => {
      var _a2, _b2;
      const nextTimeoutKey = JSON.stringify({
        action_id: prompt().action_id,
        timeout_seconds: prompt().timeout_seconds,
        default_choice: ((_a2 = prompt().options[0]) == null ? void 0 : _a2.id) ?? "no"
      });
      if (nextTimeoutKey !== get(timeoutKey)) {
        set(timeoutKey, nextTimeoutKey);
        if (get(timeoutId) !== null) {
          clearTimeout(get(timeoutId));
          set(timeoutId, null);
        }
        if (prompt().timeout_seconds !== null && prompt().timeout_seconds > 0 && !get(dismissed)) {
          const defaultChoice = ((_b2 = prompt().options[0]) == null ? void 0 : _b2.id) ?? "no";
          set(timeoutId, setTimeout(
            () => {
              void sendAction(prompt().action_id, defaultChoice);
            },
            Math.min(prompt().timeout_seconds, MAX_PROMPT_TIMEOUT_SECONDS) * 1e3
          ));
        }
      }
    }
  );
  legacy_pre_effect_reset();
  init();
  var fragment = comment();
  var node = first_child(fragment);
  {
    var consequent_2 = ($$anchor2) => {
      var div = root_3$2();
      var div_1 = sibling(child(div), 2);
      var node_1 = child(div_1);
      {
        var consequent = ($$anchor3) => {
          var div_2 = root$2();
          var text = only_child(div_2, true);
          template_effect(() => set_text(text, account()));
          append($$anchor3, div_2);
        };
        if_block(node_1, ($$render) => {
          if (account()) $$render(consequent);
        });
      }
      var h1 = sibling(node_1, 2);
      var text_1 = only_child(h1, true);
      var p = sibling(h1, 2);
      var text_2 = only_child(p, true);
      var node_2 = sibling(p, 2);
      {
        var consequent_1 = ($$anchor3) => {
          var p_1 = root_1$2();
          var text_3 = only_child(p_1, true);
          template_effect(() => set_text(text_3, errorMessage() ?? get(localError)));
          append($$anchor3, p_1);
        };
        if_block(node_2, ($$render) => {
          if (errorMessage() ?? get(localError)) $$render(consequent_1);
        });
      }
      var div_3 = sibling(node_2, 2);
      each(
        div_3,
        5,
        () => (deep_read_state(prompt()), untrack(() => prompt().options)),
        (option) => option.id,
        ($$anchor3, option) => {
          var button = root_2$2();
          var text_4 = only_child(button, true);
          template_effect(() => {
            set_class(button, 1, `prompt-btn prompt-btn--${(get(option), untrack(() => get(option).id)) ?? ""}`, "svelte-glm292");
            button.disabled = get(submitting);
            set_text(text_4, (get(option), untrack(() => get(option).label)));
          });
          event("click", button, () => handleOption(get(option)));
          append($$anchor3, button);
        }
      );
      template_effect(() => {
        set_text(text_1, (deep_read_state(prompt()), untrack(() => prompt().title)));
        set_text(text_2, (deep_read_state(prompt()), untrack(() => prompt().body)));
      });
      append($$anchor2, div);
    };
    if_block(node, ($$render) => {
      if (!get(dismissed)) $$render(consequent_2);
    });
  }
  append($$anchor, fragment);
  pop();
}
var root$1 = /* @__PURE__ */ from_html(`<p class="account-label"> </p>`);
var root_1$1 = /* @__PURE__ */ from_html(`<span class="working-dot" data-working-dot="" aria-hidden="true"></span>`);
var root_2$1 = /* @__PURE__ */ from_html(`<p class="status-text"> <!></p>`);
var root_3$1 = /* @__PURE__ */ from_html(`<section class="user-transcription" data-user-transcription="" aria-label="Your transcription"><p class="transcription-label">You said</p> <p class="transcription-text" data-user-transcription-text="" aria-atomic="true"> </p></section>`);
var root_4$1 = /* @__PURE__ */ from_html(`<li> </li>`);
var root_5$1 = /* @__PURE__ */ from_html(`<section class="prompt-summary"><h2> </h2> <p> </p> <ul></ul></section>`);
var root_6$1 = /* @__PURE__ */ from_html(`<main aria-atomic="true"><div class="ambient-canvas" aria-hidden="true"></div> <section class="state-overlay"><p class="state-label"> </p> <!> <!> <!> <div data-response-viewport="" aria-atomic="true" role="region"><p class="response-text" data-response-text=""> </p></div> <!></section></main>`);
function StateSurface($$anchor, $$props) {
  push($$props, false);
  const displayState = /* @__PURE__ */ mutable_source();
  const renderedState = /* @__PURE__ */ mutable_source();
  const status = /* @__PURE__ */ mutable_source();
  const showResponse = /* @__PURE__ */ mutable_source();
  const visibleUserTranscript = /* @__PURE__ */ mutable_source();
  const showUserTranscript = /* @__PURE__ */ mutable_source();
  const responsePhase = /* @__PURE__ */ mutable_source();
  const working = /* @__PURE__ */ mutable_source();
  let snapshot = prop($$props, "snapshot", 8);
  let connectionState = prop($$props, "connectionState", 8);
  let protocolError = prop($$props, "protocolError", 8, null);
  let accessibleOnly = prop($$props, "accessibleOnly", 8, false);
  let userTranscript = prop($$props, "userTranscript", 8, "");
  let responseVisible = prop($$props, "responseVisible", 8, true);
  let audioPlaybackFailed = prop($$props, "audioPlaybackFailed", 8, false);
  const labels = {
    idle: "Ready",
    heard: "Heard you",
    listening: "Listening",
    thinking: "Thinking",
    speaking: "Speaking",
    buffering: "Buffering",
    error: "Error",
    disconnected: "Disconnected",
    prompt: "Prompt"
  };
  const fallbackStatus = {
    buffering: "Still working — please wait",
    error: "Something needs attention — try again",
    disconnected: "Display disconnected — check the host connection"
  };
  let liveMode = /* @__PURE__ */ mutable_source();
  let responseLiveMode = /* @__PURE__ */ mutable_source();
  let responseViewport = /* @__PURE__ */ mutable_source();
  let showingResponse = false;
  let previousResponse = "";
  let lastTargetScroll = 0;
  function prefersReducedMotion() {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
      return false;
    }
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }
  function resetResponseScroll() {
    if (get(responseViewport)) {
      if (typeof get(responseViewport).scrollTo === "function") {
        get(responseViewport).scrollTo({ top: 0, behavior: "instant" });
      } else {
        mutate(responseViewport, get(responseViewport).scrollTop = 0);
      }
      lastTargetScroll = 0;
    }
  }
  function keepResponseInView() {
    if (!get(showResponse) || !get(responseViewport)) return;
    const maxScroll = get(responseViewport).scrollHeight - get(responseViewport).clientHeight;
    if (maxScroll <= 0) {
      if (get(responseViewport).scrollTop !== 0) {
        resetResponseScroll();
      }
      lastTargetScroll = 0;
      return;
    }
    if (maxScroll !== lastTargetScroll) {
      lastTargetScroll = maxScroll;
      const behavior = prefersReducedMotion() ? "instant" : "smooth";
      if (typeof get(responseViewport).scrollTo === "function") {
        get(responseViewport).scrollTo({ top: maxScroll, behavior });
      } else {
        mutate(responseViewport, get(responseViewport).scrollTop = maxScroll);
      }
    }
  }
  afterUpdate(() => {
    if (!get(showResponse)) {
      resetResponseScroll();
      showingResponse = false;
      previousResponse = "";
      return;
    }
    const newResponse = !showingResponse || snapshot().response_text.length < previousResponse.length || !snapshot().response_text.startsWith(previousResponse);
    if (newResponse) {
      resetResponseScroll();
    }
    showingResponse = true;
    previousResponse = snapshot().response_text;
    keepResponseInView();
  });
  onDestroy(resetResponseScroll);
  legacy_pre_effect(
    () => (deep_read_state(protocolError()), deep_read_state(connectionState()), deep_read_state(snapshot())),
    () => {
      set(displayState, protocolError() !== null ? "error" : connectionState() === "connected" ? snapshot().state : "disconnected");
    }
  );
  legacy_pre_effect(
    () => (deep_read_state(audioPlaybackFailed()), get(displayState)),
    () => {
      set(renderedState, audioPlaybackFailed() && get(displayState) === "speaking" ? "buffering" : get(displayState));
    }
  );
  legacy_pre_effect(
    () => (deep_read_state(protocolError()), deep_read_state(audioPlaybackFailed()), get(displayState), deep_read_state(snapshot()), get(renderedState)),
    () => {
      set(status, protocolError() ?? (audioPlaybackFailed() && get(displayState) === "speaking" ? "Audio unavailable — response text remains visible" : snapshot().status_text ?? fallbackStatus[get(renderedState)] ?? null));
    }
  );
  legacy_pre_effect(
    () => (deep_read_state(protocolError()), deep_read_state(snapshot()), deep_read_state(responseVisible()), get(renderedState)),
    () => {
      set(showResponse, protocolError() === null && snapshot().response_text.length > 0 && responseVisible() && ["thinking", "speaking", "buffering", "idle"].includes(get(renderedState)));
    }
  );
  legacy_pre_effect(() => deep_read_state(userTranscript()), () => {
    set(visibleUserTranscript, userTranscript().trim());
  });
  legacy_pre_effect(
    () => (deep_read_state(protocolError()), get(visibleUserTranscript), get(renderedState)),
    () => {
      set(showUserTranscript, protocolError() === null && get(visibleUserTranscript).length > 0 && [
        "heard",
        "listening",
        "thinking",
        "speaking",
        "buffering",
        "idle"
      ].includes(get(renderedState)));
    }
  );
  legacy_pre_effect(() => (get(renderedState), get(showResponse)), () => {
    set(liveMode, get(renderedState) === "speaking" || get(renderedState) === "idle" && get(showResponse) ? "off" : "polite");
  });
  legacy_pre_effect(() => (get(renderedState), get(showResponse)), () => {
    set(responseLiveMode, get(renderedState) === "idle" && get(showResponse) ? "polite" : "off");
  });
  legacy_pre_effect(() => (get(renderedState), get(showResponse)), () => {
    set(responsePhase, get(renderedState) === "idle" && get(showResponse) ? "complete" : get(renderedState) === "buffering" && get(showResponse) ? "buffering" : ["thinking", "speaking"].includes(get(renderedState)) && get(showResponse) ? "streaming" : ["error", "disconnected"].includes(get(renderedState)) ? "unavailable" : "hidden");
  });
  legacy_pre_effect(() => get(renderedState), () => {
    set(working, get(renderedState) === "thinking" || get(renderedState) === "buffering");
  });
  legacy_pre_effect_reset();
  init();
  var main = root_6$1();
  let classes;
  var section = sibling(child(main), 2);
  var p = child(section);
  var text = only_child(p, true);
  var node = sibling(p, 2);
  {
    var consequent = ($$anchor2) => {
      var p_1 = root$1();
      var text_1 = only_child(p_1);
      template_effect(() => set_text(text_1, `Profile: ${(deep_read_state(snapshot()), untrack(() => snapshot().account)) ?? ""}`));
      append($$anchor2, p_1);
    };
    if_block(node, ($$render) => {
      if (deep_read_state(snapshot()), untrack(() => snapshot().account)) $$render(consequent);
    });
  }
  var node_1 = sibling(node, 2);
  {
    var consequent_2 = ($$anchor2) => {
      var p_2 = root_2$1();
      var text_2 = child(p_2);
      var node_2 = sibling(text_2);
      {
        var consequent_1 = ($$anchor3) => {
          var span = root_1$1();
          append($$anchor3, span);
        };
        if_block(node_2, ($$render) => {
          if (get(working)) $$render(consequent_1);
        });
      }
      template_effect(() => set_text(text_2, get(status)));
      append($$anchor2, p_2);
    };
    if_block(node_1, ($$render) => {
      if (get(status)) $$render(consequent_2);
    });
  }
  var node_3 = sibling(node_1, 2);
  {
    var consequent_3 = ($$anchor2) => {
      var section_1 = root_3$1();
      var p_3 = sibling(child(section_1), 2);
      var text_3 = only_child(p_3, true);
      template_effect(() => {
        set_attribute(p_3, "aria-live", get(renderedState) === "speaking" ? "polite" : "off");
        set_text(text_3, get(visibleUserTranscript));
      });
      append($$anchor2, section_1);
    };
    if_block(node_3, ($$render) => {
      if (get(showUserTranscript)) $$render(consequent_3);
    });
  }
  var div = sibling(node_3, 2);
  let classes_1;
  var p_4 = child(div);
  var text_4 = only_child(p_4, true);
  bind_this(div, ($$value) => set(responseViewport, $$value), () => get(responseViewport));
  var node_4 = sibling(div, 2);
  {
    var consequent_4 = ($$anchor2) => {
      var section_2 = root_5$1();
      var h2 = child(section_2);
      var text_5 = only_child(h2, true);
      var p_5 = sibling(h2, 2);
      var text_6 = only_child(p_5, true);
      var ul = sibling(p_5, 2);
      each(
        ul,
        5,
        () => (deep_read_state(snapshot()), untrack(() => snapshot().prompt.options)),
        index,
        ($$anchor3, option) => {
          var li = root_4$1();
          var text_7 = only_child(li, true);
          template_effect(() => set_text(text_7, (get(option), untrack(() => get(option).label))));
          append($$anchor3, li);
        }
      );
      template_effect(() => {
        set_attribute(section_2, "aria-label", (deep_read_state(snapshot()), untrack(() => snapshot().prompt.title)));
        set_text(text_5, (deep_read_state(snapshot()), untrack(() => snapshot().prompt.title)));
        set_text(text_6, (deep_read_state(snapshot()), untrack(() => snapshot().prompt.body)));
      });
      append($$anchor2, section_2);
    };
    if_block(node_4, ($$render) => {
      if (get(renderedState), deep_read_state(snapshot()), untrack(() => get(renderedState) === "prompt" && snapshot().prompt)) $$render(consequent_4);
    });
  }
  template_effect(() => {
    classes = set_class(main, 1, "state-surface", null, classes, {
      "has-response": get(showResponse),
      "has-user-transcript": get(showUserTranscript),
      "accessible-only": accessibleOnly()
    });
    set_attribute(main, "data-state", get(renderedState));
    set_attribute(main, "aria-live", get(liveMode));
    set_attribute(section, "aria-label", (get(renderedState), untrack(() => labels[get(renderedState)])));
    set_text(text, (get(renderedState), untrack(() => labels[get(renderedState)])));
    classes_1 = set_class(div, 1, "response-viewport", null, classes_1, { visible: get(showResponse) });
    set_attribute(div, "data-response-phase", get(responsePhase));
    set_attribute(div, "aria-live", get(responseLiveMode));
    set_attribute(div, "aria-label", get(responsePhase) === "complete" ? "Completed Hermes response" : get(responsePhase) === "buffering" ? "Hermes response (audio unavailable)" : get(responsePhase) === "unavailable" ? "Unavailable Hermes response" : "Hermes response");
    set_text(text_4, (get(showResponse), deep_read_state(snapshot()), untrack(() => get(showResponse) ? snapshot().response_text : "")));
  });
  append($$anchor, main);
  pop();
}
const displayStates = [
  "idle",
  "heard",
  "listening",
  "thinking",
  "speaking",
  "buffering",
  "error",
  "disconnected",
  "prompt"
];
const displayActionNames = ["prompt.choose", "prompt.dismiss"];
const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);
function parsePromptOption(raw) {
  if (!isRecord(raw)) return null;
  const { id, label } = raw;
  if (typeof id !== "string" || !id) return null;
  if (id.length > 32) return null;
  if (typeof label !== "string" || !label || label.length > 48) return null;
  return { id, label };
}
function parseDisplayPrompt(raw) {
  if (!isRecord(raw)) return null;
  const { kind, title, body, options, action_id, timeout_seconds } = raw;
  if (typeof kind !== "string" || !kind || kind.length > 24) return null;
  if (typeof title !== "string" || !title || title.length > 64) return null;
  if (typeof body !== "string" || body.length > 192) return null;
  if (!Array.isArray(options) || options.length === 0 || options.length > 4) return null;
  const parsedOptions = [];
  for (const opt of options) {
    const parsed = parsePromptOption(opt);
    if (!parsed) return null;
    parsedOptions.push(parsed);
  }
  if (parsedOptions.length === 0) return null;
  if (typeof action_id !== "string" || !action_id || action_id.length > 64) return null;
  if (timeout_seconds === void 0) return null;
  if (timeout_seconds !== null && (typeof timeout_seconds !== "number" || !Number.isSafeInteger(timeout_seconds) || timeout_seconds <= 0)) {
    return null;
  }
  return {
    kind,
    title,
    body,
    options: parsedOptions,
    action_id,
    timeout_seconds
  };
}
function parseCapabilities(raw) {
  if (!isRecord(raw)) return null;
  const { actions, features } = raw;
  if (!Array.isArray(actions) || !Array.isArray(features)) return null;
  const parsedActions = [];
  for (const action of actions) {
    if (typeof action !== "string" || !displayActionNames.includes(action) || parsedActions.includes(action)) {
      return null;
    }
    parsedActions.push(action);
  }
  const parsedFeatures = [];
  for (const feature of features) {
    if (typeof feature !== "string" || !feature || parsedFeatures.includes(feature)) {
      return null;
    }
    parsedFeatures.push(feature);
  }
  let wakePhrases;
  if (raw.wake_phrases !== void 0) {
    if (!Array.isArray(raw.wake_phrases) || raw.wake_phrases.length > 8) return null;
    wakePhrases = [];
    for (const phrase of raw.wake_phrases) {
      if (typeof phrase !== "string" || !phrase.trim() || phrase.length > 128 || wakePhrases.some((existing) => existing === phrase)) {
        return null;
      }
      wakePhrases.push(phrase);
    }
  }
  const parseSeconds = (value) => {
    if (value === void 0) return void 0;
    if (typeof value !== "number" || !Number.isFinite(value) || value <= 0) return null;
    return value;
  };
  const wakeListenSeconds = parseSeconds(raw.wake_listen_seconds);
  const wakeFollowupSeconds = parseSeconds(raw.wake_followup_seconds);
  if (wakeListenSeconds === null || wakeFollowupSeconds === null) return null;
  const capabilities = {
    actions: parsedActions,
    features: parsedFeatures
  };
  if (wakePhrases !== void 0) capabilities.wake_phrases = wakePhrases;
  if (wakeListenSeconds !== void 0) capabilities.wake_listen_seconds = wakeListenSeconds;
  if (wakeFollowupSeconds !== void 0) {
    capabilities.wake_followup_seconds = wakeFollowupSeconds;
  }
  return capabilities;
}
function parseSnapshot(raw) {
  if (!isRecord(raw)) {
    return null;
  }
  const {
    type,
    schema,
    sequence,
    state: state2,
    response_text,
    status_text,
    media,
    prompt,
    account,
    capabilities
  } = raw;
  if (type !== "snapshot" || schema !== 1 || typeof sequence !== "number" || !Number.isSafeInteger(sequence) || sequence < 0 || sequence > 4294967295 || !displayStates.includes(state2) || typeof response_text !== "string" || status_text !== null && typeof status_text !== "string" || media !== null && !isRecord(media) || account !== void 0 && account !== null && typeof account !== "string") {
    return null;
  }
  let parsedPrompt = null;
  if (prompt !== null && prompt !== void 0) {
    parsedPrompt = parseDisplayPrompt(prompt);
    if (parsedPrompt === null) return null;
  }
  if (state2 === "prompt" && parsedPrompt === null) return null;
  if (state2 !== "prompt" && parsedPrompt !== null) return null;
  let parsedCapabilities;
  if (capabilities !== void 0) {
    const parsed = parseCapabilities(capabilities);
    if (parsed === null) return null;
    parsedCapabilities = parsed;
  }
  const snapshot = {
    type,
    schema,
    sequence,
    state: state2,
    response_text,
    status_text,
    media,
    prompt: parsedPrompt
  };
  if (account !== void 0) snapshot.account = account;
  if (parsedCapabilities !== void 0) snapshot.capabilities = parsedCapabilities;
  return snapshot;
}
function parseTurnId(raw) {
  return typeof raw === "string" && raw.length > 0 && raw.length <= 128 ? raw : null;
}
function parseAudioEvent(raw) {
  if (!isRecord(raw) || raw.schema !== 1 || typeof raw.type !== "string") {
    return null;
  }
  const turnId = parseTurnId(raw.turn_id);
  if (turnId === null) return null;
  if (raw.type === "audio_start") {
    const { sample_rate, channels, sample_width } = raw;
    if (typeof sample_rate !== "number" || !Number.isSafeInteger(sample_rate) || sample_rate <= 0 || typeof channels !== "number" || !Number.isSafeInteger(channels) || channels < 1 || channels > 8 || sample_width !== 2) {
      return null;
    }
    return {
      type: "audio_start",
      schema: 1,
      turn_id: turnId,
      sample_rate,
      channels,
      sample_width: 2
    };
  }
  if (raw.type === "audio_end") {
    return { type: "audio_end", schema: 1, turn_id: turnId };
  }
  if (raw.type === "audio_abort") {
    return typeof raw.reason === "string" && raw.reason.length > 0 ? { type: "audio_abort", schema: 1, turn_id: turnId, reason: raw.reason } : null;
  }
  return null;
}
const defaultSocketFactory = (url) => new WebSocket(url);
const RECONNECT_DELAYS_MS = [250, 500, 1e3, 2e3, 4e3];
class StateChannel {
  constructor(url, onSnapshot, onConnectionState, onProtocolError = () => {
  }, socketFactory = defaultSocketFactory, onValidSnapshot = () => {
  }, onAudioEvent = () => {
  }, onAudioChunk = () => {
  }) {
    __publicField(this, "socket", null);
    __publicField(this, "reconnectTimer", null);
    __publicField(this, "reconnectAttempt", 0);
    __publicField(this, "lastSequence", -1);
    __publicField(this, "hasHydratedSocket", false);
    __publicField(this, "socketOpen", false);
    __publicField(this, "running", false);
    this.url = url;
    this.onSnapshot = onSnapshot;
    this.onConnectionState = onConnectionState;
    this.onProtocolError = onProtocolError;
    this.socketFactory = socketFactory;
    this.onValidSnapshot = onValidSnapshot;
    this.onAudioEvent = onAudioEvent;
    this.onAudioChunk = onAudioChunk;
  }
  start() {
    if (this.running) {
      return;
    }
    this.running = true;
    this.connect();
  }
  stop() {
    this.running = false;
    this.socketOpen = false;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    const socket = this.socket;
    this.socket = null;
    if (socket !== null) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      socket.close();
    }
  }
  connect() {
    if (!this.running) {
      return;
    }
    this.deliver(() => this.onConnectionState("connecting"));
    let socket;
    try {
      socket = this.socketFactory(this.url);
    } catch {
      this.deliver(() => this.onConnectionState("disconnected"));
      this.scheduleReconnect();
      return;
    }
    socket.binaryType = "arraybuffer";
    this.socket = socket;
    this.hasHydratedSocket = false;
    socket.onopen = () => {
      if (!this.isCurrent(socket)) {
        return;
      }
      this.socketOpen = true;
      this.lastSequence = -1;
      this.reconnectAttempt = 0;
    };
    socket.onmessage = (event2) => {
      if (!this.isCurrent(socket)) {
        return;
      }
      this.handleMessage(event2.data);
    };
    socket.onerror = () => {
    };
    socket.onclose = () => {
      if (!this.isCurrent(socket)) {
        return;
      }
      this.socket = null;
      this.socketOpen = false;
      this.deliver(() => this.onConnectionState("disconnected"));
      this.scheduleReconnect();
    };
  }
  sendVoiceTurn(text) {
    const normalized = text.trim();
    if (!this.socketOpen || !this.hasHydratedSocket || !this.socket || !normalized || normalized.length > 4e3) {
      return false;
    }
    if (typeof this.socket.send !== "function") {
      return false;
    }
    try {
      this.socket.send(JSON.stringify({ type: "voice_turn", schema: 1, text: normalized }));
      return true;
    } catch {
      return false;
    }
  }
  handleMessage(data) {
    if (data instanceof ArrayBuffer) {
      this.deliver(() => this.onAudioChunk(data));
      return;
    }
    if (ArrayBuffer.isView(data)) {
      const view = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
      const copy = view.slice().buffer;
      this.deliver(() => this.onAudioChunk(copy));
      return;
    }
    if (typeof Blob !== "undefined" && data instanceof Blob) {
      void data.arrayBuffer().then((buffer) => {
        if (this.running) {
          this.deliver(() => this.onAudioChunk(buffer));
        }
      }).catch(() => this.reportProtocolError());
      return;
    }
    let raw;
    try {
      raw = typeof data === "string" ? JSON.parse(data) : null;
    } catch {
      this.reportProtocolError();
      return;
    }
    const audioEvent = parseAudioEvent(raw);
    if (audioEvent !== null) {
      this.deliver(() => this.onAudioEvent(audioEvent));
      return;
    }
    const snapshot = parseSnapshot(raw);
    if (snapshot === null) {
      this.reportProtocolError();
      return;
    }
    this.deliver(() => this.onValidSnapshot(snapshot));
    if (snapshot.sequence <= this.lastSequence) {
      return;
    }
    this.lastSequence = snapshot.sequence;
    this.deliver(() => this.onSnapshot(snapshot));
    if (!this.hasHydratedSocket) {
      this.hasHydratedSocket = true;
      this.deliver(() => this.onConnectionState("connected"));
    }
  }
  scheduleReconnect() {
    if (!this.running || this.reconnectTimer !== null) {
      return;
    }
    const delay = RECONNECT_DELAYS_MS[Math.min(this.reconnectAttempt, RECONNECT_DELAYS_MS.length - 1)];
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect();
    }, delay);
  }
  isCurrent(socket) {
    return this.running && this.socket === socket;
  }
  reportProtocolError() {
    this.deliver(() => this.onProtocolError("display data unavailable"));
  }
  deliver(callback) {
    try {
      callback();
    } catch {
    }
  }
}
const busyStates = /* @__PURE__ */ new Set(["listening", "thinking", "speaking", "buffering"]);
const allowedTransitions = {
  idle: /* @__PURE__ */ new Set(["idle", "heard", "listening", "thinking", "prompt"]),
  heard: /* @__PURE__ */ new Set(["heard", "listening", "thinking", "idle", "prompt"]),
  listening: /* @__PURE__ */ new Set(["listening", "thinking", "heard", "idle"]),
  thinking: /* @__PURE__ */ new Set(["thinking", "speaking", "buffering", "prompt", "idle"]),
  speaking: /* @__PURE__ */ new Set(["speaking", "buffering", "prompt", "idle"]),
  buffering: /* @__PURE__ */ new Set(["buffering", "speaking", "thinking", "prompt", "idle"]),
  error: /* @__PURE__ */ new Set(["error", "idle"]),
  disconnected: /* @__PURE__ */ new Set(["disconnected", "idle", "heard", "listening"]),
  prompt: /* @__PURE__ */ new Set(["prompt", "idle", "thinking"])
};
function connectionHealthy(state2) {
  return state2 !== "error" && state2 !== "disconnected";
}
function canPerformAction(snapshot, actionName) {
  var _a2;
  return ((_a2 = snapshot.capabilities) == null ? void 0 : _a2.actions.includes(actionName)) ?? false;
}
function toView(snapshot) {
  return {
    ...snapshot,
    is_busy: busyStates.has(snapshot.state),
    connection_healthy: connectionHealthy(snapshot.state),
    can_choose: snapshot.prompt !== null && canPerformAction(snapshot, "prompt.choose"),
    can_dismiss: snapshot.prompt !== null && canPerformAction(snapshot, "prompt.dismiss")
  };
}
class SnapshotReducer {
  constructor() {
    __publicField(this, "current", null);
  }
  reset() {
    this.current = null;
  }
  applySnapshot(snapshot) {
    if (this.current !== null && snapshot.sequence <= this.current.sequence) {
      return { kind: "stale" };
    }
    if (this.current !== null && snapshot.state !== "error" && snapshot.state !== "disconnected" && !allowedTransitions[this.current.state].has(snapshot.state)) {
      return { kind: "invalid_transition" };
    }
    const view = toView(snapshot);
    this.current = view;
    return { kind: "accepted", view };
  }
  validateAction(action) {
    if (action.type !== "action" || action.schema !== 1 || typeof action.action_id !== "string" || action.action_id.length === 0 || action.action_id.length > 64 || typeof action.choice !== "string" || action.choice.length === 0 || action.choice.length > 32) {
      return "invalid_argument";
    }
    if (this.current === null || this.current.state !== "prompt" || this.current.prompt === null) {
      return "prompt_not_active";
    }
    if (!this.current.can_choose) {
      return "action_not_allowed";
    }
    if (this.current.prompt.action_id !== action.action_id) {
      return "action_id_mismatch";
    }
    return this.current.prompt.options.some((option) => option.id === action.choice) ? "accepted" : "unknown_choice";
  }
}
function createDisplayReducer() {
  return new SnapshotReducer();
}
function createInitialDisplayView() {
  return toView({
    type: "snapshot",
    schema: 1,
    sequence: 0,
    state: "idle",
    response_text: "",
    status_text: null,
    media: null,
    prompt: null
  });
}
const DISPLAY_ACTION_TIMEOUT_MS = 1e4;
const postDisplayAction = async (action) => {
  const query = new URLSearchParams({
    action_id: action.action_id,
    choice: action.choice
  });
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), DISPLAY_ACTION_TIMEOUT_MS);
  try {
    const response = await fetch(`/action?${query.toString()}`, {
      method: "POST",
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`display action failed with HTTP ${response.status}`);
    }
  } finally {
    clearTimeout(timeoutId);
  }
};
class DisplayBridge {
  /**
   * Keep browser transport and action encoding at the edge. The reducer is an
   * injected port so a generated WebAssembly implementation can replace the
   * current browser reducer implementation without changing the kiosk
   * lifecycle or surfaces.
   */
  constructor(options) {
    __publicField(this, "reducer");
    __publicField(this, "actionTransport");
    __publicField(this, "onActionError");
    __publicField(this, "voiceTransport");
    __publicField(this, "onVoiceError");
    __publicField(this, "channel");
    this.reducer = options.reducer ?? createDisplayReducer();
    this.actionTransport = options.actionTransport ?? postDisplayAction;
    this.onActionError = options.onActionError ?? (() => {
    });
    this.voiceTransport = options.voiceTransport ?? null;
    this.onVoiceError = options.onVoiceError ?? (() => {
    });
    this.channel = new StateChannel(
      options.url,
      (snapshot) => {
        const result = this.reducer.applySnapshot(snapshot);
        if (result.kind === "accepted") {
          this.deliver(() => options.onView(result.view));
        } else if (result.kind === "invalid_transition" || result.kind === "invalid_snapshot") {
          this.deliver(() => {
            var _a2;
            return (_a2 = options.onProtocolError) == null ? void 0 : _a2.call(options, "display data unavailable");
          });
        }
      },
      (state2) => {
        var _a2, _b2;
        if (state2 === "connecting") {
          this.reducer.reset();
        } else if (state2 === "disconnected") {
          (_b2 = (_a2 = this.reducer).setConnectionState) == null ? void 0 : _b2.call(_a2, "disconnected");
        }
        this.deliver(() => options.onConnectionState(state2));
      },
      options.onProtocolError,
      options.socketFactory,
      options.onValidSnapshot,
      options.onAudioEvent,
      options.onAudioChunk
    );
  }
  start() {
    this.channel.start();
  }
  stop() {
    this.channel.stop();
  }
  async dispatchAction(action) {
    const validation = this.reducer.validateAction(action);
    if (validation !== "accepted") {
      this.deliver(() => this.onActionError(validation));
      return false;
    }
    try {
      await this.actionTransport(action);
      return true;
    } catch {
      this.deliver(() => this.onActionError("transport_error"));
      return false;
    }
  }
  async sendVoiceTurn(text) {
    const normalized = text.trim();
    if (!normalized || normalized.length > 4e3) {
      this.deliver(() => this.onVoiceError("transport_error"));
      return false;
    }
    try {
      if (this.voiceTransport !== null) {
        await this.voiceTransport(normalized);
        return true;
      }
      if (this.channel.sendVoiceTurn(normalized)) {
        return true;
      }
    } catch {
    }
    this.deliver(() => this.onVoiceError("transport_error"));
    return false;
  }
  deliver(callback) {
    try {
      callback();
    } catch {
    }
  }
}
function defaultRecognitionFactory() {
  const windowWithSpeech = window;
  const Constructor = windowWithSpeech.SpeechRecognition ?? windowWithSpeech.webkitSpeechRecognition;
  if (!Constructor) {
    throw new Error("Speech recognition is unavailable in this browser");
  }
  return new Constructor();
}
async function defaultRecognitionPreparer() {
  var _a2;
  if (typeof navigator === "undefined" || !((_a2 = navigator.mediaDevices) == null ? void 0 : _a2.getUserMedia)) return;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    for (const track of stream.getTracks()) track.stop();
  } catch {
  }
}
class BrowserVoiceController {
  constructor(options) {
    __publicField(this, "sendText");
    __publicField(this, "onState");
    __publicField(this, "onError");
    __publicField(this, "onTranscript");
    __publicField(this, "recognitionFactory");
    __publicField(this, "language");
    __publicField(this, "recognition", null);
    __publicField(this, "listening", false);
    __publicField(this, "submitting", false);
    this.sendText = options.sendText;
    this.onState = options.onState ?? (() => {
    });
    this.onError = options.onError ?? (() => {
    });
    this.onTranscript = options.onTranscript ?? (() => {
    });
    this.recognitionFactory = options.recognitionFactory ?? defaultRecognitionFactory;
    this.language = options.language ?? "en-US";
  }
  async start() {
    if (this.listening || this.submitting) return false;
    try {
      const recognition = this.recognitionFactory();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = this.language;
      recognition.onresult = (event2) => this.handleResult(event2);
      recognition.onerror = () => this.fail();
      recognition.onend = () => {
        if (this.recognition === recognition) this.recognition = null;
        if (!this.submitting) {
          this.listening = false;
          this.onTranscript("", true);
          this.emit("idle");
        }
      };
      this.recognition = recognition;
      this.listening = true;
      this.emit("listening");
      recognition.start();
      return true;
    } catch {
      this.fail();
      return false;
    }
  }
  stop() {
    if (!this.listening || this.recognition === null) return;
    this.listening = false;
    this.stopRecognition();
    this.onTranscript("", true);
    if (!this.submitting) this.emit("idle");
  }
  reset() {
    this.stopRecognition();
    this.listening = false;
    this.submitting = false;
    this.onTranscript("", true);
    this.emit("idle");
  }
  handleResult(event2) {
    if (!this.listening) return;
    const { liveText, finalText: text } = recognitionText(event2);
    const visibleText = text || liveText;
    this.onTranscript(visibleText, text.length > 0);
    if (!text) return;
    this.listening = false;
    this.submitting = true;
    this.emit("submitting");
    this.stopRecognition();
    let sendResult;
    try {
      sendResult = this.sendText(text);
    } catch {
      this.fail("Turn could not be sent");
      return;
    }
    Promise.resolve(sendResult).then((sent) => {
      if (!sent) this.fail("Turn could not be sent");
    }).catch(() => this.fail("Turn could not be sent"));
  }
  fail(message = "Microphone or speech recognition is unavailable") {
    this.stopRecognition();
    this.listening = false;
    this.submitting = false;
    this.onTranscript("", true);
    this.emit("error");
    this.onError(message);
  }
  stopRecognition() {
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition === null) return;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    try {
      recognition.stop();
    } catch {
    }
  }
  emit(state2) {
    this.onState(state2);
  }
}
const DEFAULT_HANDS_FREE_SECONDS = 8;
const MAX_HANDS_FREE_TIMER_SECONDS = 2147483647e-3;
const FOLLOW_UP_START_TIMEOUT_MS = 1e3;
const FOLLOW_UP_ACTIVITY_TIMEOUT_MS = 3500;
const FOLLOW_UP_RETRY_DELAYS_MS = [300, 1e3, 2e3, 3500];
function normaliseSpeech(text) {
  return text.trim().replace(/\s+/g, " ");
}
function isLocalStopCommand(text) {
  return normaliseSpeech(text).replace(/[.,!?;:…]+$/g, "").trim().toLocaleLowerCase() === "stop";
}
function wakeRemainder(text, wakePhrases) {
  const source2 = normaliseSpeech(text);
  const lowerSource = source2.toLocaleLowerCase();
  const phrases = wakePhrases.map(normaliseSpeech).filter(Boolean).sort((left, right) => right.length - left.length);
  for (const phrase of phrases) {
    const lowerPhrase = phrase.toLocaleLowerCase();
    if (lowerSource !== lowerPhrase && !lowerSource.startsWith(lowerPhrase)) continue;
    const next = lowerSource[lowerPhrase.length];
    if (next !== void 0 && !/^[\s,.:;!?;…-]$/.test(next)) continue;
    return normaliseSpeech(source2.slice(lowerPhrase.length).replace(/^[\s,.:;!?…-]+/, ""));
  }
  return null;
}
function recognitionText(event2) {
  var _a2;
  const liveParts = [];
  const finalParts = [];
  for (let index2 = event2.resultIndex; index2 < event2.results.length; index2 += 1) {
    const result = event2.results[index2];
    const transcript = (_a2 = result[0]) == null ? void 0 : _a2.transcript;
    if (!transcript) continue;
    const normalized = normaliseSpeech(transcript);
    if (!normalized) continue;
    liveParts.push(normalized);
    if (result.isFinal) finalParts.push(normalized);
  }
  return {
    liveText: normaliseSpeech(liveParts.join(" ")),
    finalText: normaliseSpeech(finalParts.join(" "))
  };
}
class BrowserHandsFreeController {
  constructor(options) {
    __publicField(this, "sendText");
    __publicField(this, "wakePhrases");
    __publicField(this, "wakeListenSeconds");
    __publicField(this, "followUpSeconds");
    __publicField(this, "onState");
    __publicField(this, "onError");
    __publicField(this, "onTranscript");
    __publicField(this, "recognitionFactory");
    __publicField(this, "prepareRecognition");
    __publicField(this, "language");
    __publicField(this, "phase", "off");
    __publicField(this, "armed", false);
    __publicField(this, "generation", 0);
    __publicField(this, "recognition", null);
    __publicField(this, "captureTimer", null);
    __publicField(this, "heardTimer", null);
    __publicField(this, "restartTimer", null);
    __publicField(this, "followUpRetryTimer", null);
    __publicField(this, "followUpWatchdogTimer", null);
    __publicField(this, "followUpAttempt", 0);
    __publicField(this, "turnInFlight", false);
    this.sendText = options.sendText;
    this.wakePhrases = options.wakePhrases.map(normaliseSpeech).filter(Boolean);
    this.wakeListenSeconds = positiveSeconds(options.wakeListenSeconds);
    this.followUpSeconds = positiveSeconds(options.followUpSeconds);
    this.onState = options.onState ?? (() => {
    });
    this.onError = options.onError ?? (() => {
    });
    this.onTranscript = options.onTranscript ?? (() => {
    });
    this.recognitionFactory = options.recognitionFactory ?? defaultRecognitionFactory;
    this.prepareRecognition = options.prepareRecognition ?? defaultRecognitionPreparer;
    this.language = options.language ?? "en-US";
  }
  configure(options) {
    const wakePhrases = options.wakePhrases.map(normaliseSpeech).filter(Boolean);
    const wakeListenSeconds = positiveSeconds(options.wakeListenSeconds);
    const followUpSeconds = positiveSeconds(options.followUpSeconds);
    if (this.armed) {
      const phrasesChanged = wakePhrases.length !== this.wakePhrases.length || wakePhrases.some((phrase, index2) => phrase !== this.wakePhrases[index2]);
      if (phrasesChanged || wakeListenSeconds !== this.wakeListenSeconds || followUpSeconds !== this.followUpSeconds) {
        this.abort("Display configuration changed — hands-free is off");
      }
      return;
    }
    this.wakePhrases = wakePhrases;
    this.wakeListenSeconds = wakeListenSeconds;
    this.followUpSeconds = followUpSeconds;
  }
  get isArmed() {
    return this.armed;
  }
  get state() {
    return this.stateForPhase();
  }
  async arm() {
    if (this.armed) return true;
    if (this.wakePhrases.length === 0) {
      this.fail("No wake phrase is configured for this display");
      return false;
    }
    this.generation += 1;
    const generation = this.generation;
    this.armed = true;
    this.phase = "wake_ready";
    this.turnInFlight = false;
    this.emit("arming");
    if (!this.startRecognition(generation)) {
      this.fail("Microphone or speech recognition is unavailable");
      return false;
    }
    this.emit("wake_ready");
    return true;
  }
  disarm() {
    this.generation += 1;
    this.armed = false;
    this.phase = "off";
    this.turnInFlight = false;
    this.clearTimers();
    this.stopRecognition();
    this.onTranscript("", true);
    this.emit("off");
  }
  abort(message = "Display disconnected — hands-free is off") {
    if (!this.armed && this.phase === "off") return;
    this.fail(message);
  }
  /** Called by the display after the current response has really finished. */
  turnFinished() {
    if (!this.armed || !this.turnInFlight || this.phase !== "submitting") return;
    const generation = this.generation;
    this.turnInFlight = false;
    this.clearCaptureTimer();
    this.beginFollowUp(generation);
  }
  stateForPhase() {
    switch (this.phase) {
      case "wake_ready":
        return "wake_ready";
      case "heard":
        return "heard";
      case "initial_capture":
        return "listening";
      case "follow_up":
        return "follow_up";
      case "submitting":
        return "submitting";
      default:
        return "off";
    }
  }
  startRecognition(generation) {
    if (!this.isCurrent(generation) || this.recognition !== null) return true;
    let recognition;
    try {
      recognition = this.recognitionFactory();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = this.language;
    } catch {
      return false;
    }
    let started = false;
    recognition.onstart = () => {
      if (!this.isCurrent(generation) || this.recognition !== recognition) return;
      started = true;
      if (this.phase === "follow_up") {
        this.scheduleFollowUpWatchdog(
          generation,
          recognition,
          FOLLOW_UP_ACTIVITY_TIMEOUT_MS
        );
      }
    };
    recognition.onresult = (event2) => {
      this.clearFollowUpWatchdog();
      this.handleResult(event2, generation);
    };
    recognition.onerror = (event2) => {
      var _a2;
      if (!this.isCurrent(generation) || this.recognition !== recognition) return;
      const code = (_a2 = event2.error) == null ? void 0 : _a2.toLocaleLowerCase();
      if (code === "no-speech" || code === "aborted") {
        if (this.phase === "follow_up") {
          this.stopRecognition();
          this.scheduleFollowUpRetry(generation);
        } else {
          this.scheduleRecognitionRestart(generation);
        }
        return;
      }
      this.fail("Microphone or speech recognition is unavailable");
    };
    recognition.onend = () => {
      if (!this.isCurrent(generation) || this.recognition !== recognition) return;
      this.recognition = null;
      this.clearFollowUpWatchdog();
      if (this.phase === "submitting") return;
      if (this.phase === "follow_up") {
        this.scheduleFollowUpRetry(generation);
      } else {
        this.scheduleRecognitionRestart(generation);
      }
    };
    this.recognition = recognition;
    try {
      recognition.start();
      if (this.phase === "follow_up" && !started && this.recognition === recognition) {
        this.scheduleFollowUpWatchdog(
          generation,
          recognition,
          FOLLOW_UP_START_TIMEOUT_MS
        );
      }
      return true;
    } catch {
      this.recognition = null;
      this.clearFollowUpWatchdog();
      return false;
    }
  }
  scheduleRecognitionRestart(generation) {
    if (!this.isCurrent(generation) || this.recognition !== null || this.restartTimer !== null || this.phase === "submitting") {
      return;
    }
    this.restartTimer = setTimeout(() => {
      this.restartTimer = null;
      if (!this.isCurrent(generation) || this.recognition !== null) return;
      if (!this.startRecognition(generation)) {
        this.fail("Microphone or speech recognition is unavailable");
      }
    }, 50);
  }
  handleResult(event2, generation) {
    if (!this.isCurrent(generation) || this.phase === "submitting") return;
    const { liveText, finalText: text } = recognitionText(event2);
    if (this.phase === "wake_ready") {
      if (!text) return;
      const remainder = wakeRemainder(text, this.wakePhrases);
      if (remainder === null) return;
      if (!remainder || isLocalStopCommand(remainder)) {
        if (remainder) this.finishCapture(generation);
        else this.beginInitialCapture(generation);
        return;
      }
      this.onTranscript(remainder, true);
      this.submit(remainder, generation);
      return;
    }
    if (this.phase !== "heard" && this.phase !== "initial_capture" && this.phase !== "follow_up") return;
    if (!text) {
      this.onTranscript(liveText, false);
      return;
    }
    if (isLocalStopCommand(text)) {
      this.finishCapture(generation);
      return;
    }
    this.onTranscript(text, true);
    this.submit(text, generation);
  }
  beginInitialCapture(generation) {
    if (!this.isCurrent(generation)) return;
    this.phase = "heard";
    this.emit("heard");
    this.startCaptureTimer(generation, this.wakeListenSeconds);
    this.clearHeardTimer();
    this.heardTimer = setTimeout(() => {
      this.heardTimer = null;
      if (!this.isCurrent(generation) || this.phase !== "heard") return;
      this.phase = "initial_capture";
      this.emit("listening");
    }, 150);
  }
  beginFollowUp(generation) {
    if (!this.isCurrent(generation)) return;
    this.phase = "follow_up";
    this.followUpAttempt = 0;
    this.emit("follow_up");
    this.startCaptureTimer(generation, this.followUpSeconds);
    void this.prepareAndStartFollowUp(generation);
  }
  async prepareAndStartFollowUp(generation) {
    try {
      await this.prepareRecognition();
    } catch {
    }
    if (!this.isCurrent(generation) || this.phase !== "follow_up") return;
    if (!this.startRecognition(generation)) this.scheduleFollowUpRetry(generation);
  }
  scheduleFollowUpRetry(generation) {
    if (!this.isCurrent(generation) || this.phase !== "follow_up" || this.followUpRetryTimer !== null) return;
    const nextAttempt = this.followUpAttempt + 1;
    const delay = FOLLOW_UP_RETRY_DELAYS_MS[nextAttempt - 1];
    if (delay === void 0) {
      this.fail("Speech recognition could not resume after playback");
      return;
    }
    this.followUpRetryTimer = setTimeout(() => {
      this.followUpRetryTimer = null;
      if (!this.isCurrent(generation) || this.phase !== "follow_up") return;
      this.followUpAttempt = nextAttempt;
      if (!this.startRecognition(generation)) {
        this.scheduleFollowUpRetry(generation);
      }
    }, delay);
  }
  scheduleFollowUpWatchdog(generation, recognition, delay) {
    this.clearFollowUpWatchdog();
    this.followUpWatchdogTimer = setTimeout(() => {
      this.followUpWatchdogTimer = null;
      if (!this.isCurrent(generation) || this.phase !== "follow_up" || this.recognition !== recognition) return;
      this.stopRecognition();
      this.scheduleFollowUpRetry(generation);
    }, delay);
  }
  enterWakeReady(generation, deferRecognition = false) {
    if (!this.isCurrent(generation)) return;
    this.clearFollowUpRetryTimer();
    this.phase = "wake_ready";
    this.clearHeardTimer();
    this.emit("wake_ready");
    if (deferRecognition || !this.startRecognition(generation)) {
      this.scheduleRecognitionRestart(generation);
    }
  }
  finishCapture(generation) {
    if (!this.isCurrent(generation)) return;
    this.onTranscript("", true);
    this.clearCaptureTimer();
    this.stopRecognition();
    this.enterWakeReady(generation, true);
  }
  startCaptureTimer(generation, seconds) {
    this.clearCaptureTimer();
    this.captureTimer = setTimeout(() => {
      this.captureTimer = null;
      if (!this.isCurrent(generation)) return;
      this.onTranscript("", true);
      this.stopRecognition();
      this.enterWakeReady(generation, true);
    }, Math.min(seconds, MAX_HANDS_FREE_TIMER_SECONDS) * 1e3);
  }
  submit(text, generation) {
    if (!this.isCurrent(generation)) return;
    this.clearCaptureTimer();
    this.clearHeardTimer();
    this.clearFollowUpRetryTimer();
    this.stopRecognition();
    this.phase = "submitting";
    this.turnInFlight = true;
    this.emit("submitting");
    let sendResult;
    try {
      sendResult = this.sendText(text);
    } catch {
      this.fail("Turn could not be sent");
      return;
    }
    Promise.resolve(sendResult).then((sent) => {
      if (!this.isCurrent(generation) || sent) return;
      this.fail("Turn could not be sent");
    }).catch(() => {
      if (this.isCurrent(generation)) this.fail("Turn could not be sent");
    });
  }
  fail(message) {
    this.generation += 1;
    this.armed = false;
    this.phase = "off";
    this.turnInFlight = false;
    this.clearTimers();
    this.stopRecognition();
    this.onTranscript("", true);
    this.emit("error");
    this.onError(message);
  }
  clearCaptureTimer() {
    if (this.captureTimer !== null) {
      clearTimeout(this.captureTimer);
      this.captureTimer = null;
    }
  }
  clearHeardTimer() {
    if (this.heardTimer !== null) {
      clearTimeout(this.heardTimer);
      this.heardTimer = null;
    }
  }
  clearTimers() {
    this.clearCaptureTimer();
    this.clearHeardTimer();
    if (this.restartTimer !== null) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    this.clearFollowUpRetryTimer();
    this.clearFollowUpWatchdog();
  }
  clearFollowUpRetryTimer() {
    if (this.followUpRetryTimer !== null) {
      clearTimeout(this.followUpRetryTimer);
      this.followUpRetryTimer = null;
    }
  }
  clearFollowUpWatchdog() {
    if (this.followUpWatchdogTimer !== null) {
      clearTimeout(this.followUpWatchdogTimer);
      this.followUpWatchdogTimer = null;
    }
  }
  stopRecognition() {
    this.clearFollowUpWatchdog();
    const recognition = this.recognition;
    this.recognition = null;
    if (recognition === null) return;
    recognition.onstart = null;
    recognition.onresult = null;
    recognition.onerror = null;
    recognition.onend = null;
    try {
      recognition.stop();
    } catch {
    }
  }
  isCurrent(generation) {
    return this.armed && this.generation === generation;
  }
  emit(state2) {
    this.onState(state2);
  }
}
function positiveSeconds(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : DEFAULT_HANDS_FREE_SECONDS;
}
function defaultAudioContextFactory() {
  const windowWithAudio = window;
  const Constructor = windowWithAudio.AudioContext ?? windowWithAudio.webkitAudioContext;
  if (!Constructor) {
    throw new Error("Web Audio is unavailable in this browser");
  }
  return new Constructor();
}
class PcmAudioPlayer {
  constructor(options = {}) {
    __publicField(this, "audioContextFactory");
    __publicField(this, "onError");
    __publicField(this, "onPlaybackFinished");
    __publicField(this, "context", null);
    __publicField(this, "activeTurnId", null);
    __publicField(this, "endedTurnId", null);
    __publicField(this, "sampleRate", 0);
    __publicField(this, "channels", 0);
    __publicField(this, "nextStartAt", 0);
    __publicField(this, "pendingBytes", new Uint8Array());
    __publicField(this, "sources", /* @__PURE__ */ new Set());
    this.audioContextFactory = options.audioContextFactory ?? defaultAudioContextFactory;
    this.onError = options.onError ?? (() => {
    });
    this.onPlaybackFinished = options.onPlaybackFinished ?? (() => {
    });
  }
  get hasPendingPlayback() {
    return this.sources.size > 0;
  }
  async resume() {
    try {
      const context = this.ensureContext();
      if (context.state === "suspended") {
        await context.resume();
      }
      return true;
    } catch {
      this.onError("Audio playback is unavailable in this browser");
      return false;
    }
  }
  start(event2) {
    this.stop();
    try {
      const context = this.ensureContext();
      this.activeTurnId = event2.turn_id;
      this.sampleRate = event2.sample_rate;
      this.channels = event2.channels;
      this.nextStartAt = context.currentTime;
    } catch {
      this.onError("Audio playback is unavailable in this browser");
    }
  }
  append(chunk) {
    if (this.activeTurnId === null || this.context === null || this.channels <= 0) return;
    const incoming = new Uint8Array(chunk);
    const bytesPerFrame = this.channels * 2;
    const combined = new Uint8Array(this.pendingBytes.byteLength + incoming.byteLength);
    combined.set(this.pendingBytes);
    combined.set(incoming, this.pendingBytes.byteLength);
    const completeByteLength = combined.byteLength - combined.byteLength % bytesPerFrame;
    this.pendingBytes = combined.slice(completeByteLength);
    if (completeByteLength === 0) return;
    const bytes = combined.subarray(0, completeByteLength);
    const frameCount = completeByteLength / bytesPerFrame;
    try {
      const buffer = this.context.createBuffer(this.channels, frameCount, this.sampleRate);
      for (let channel = 0; channel < this.channels; channel += 1) {
        const samples = new Float32Array(frameCount);
        for (let frame = 0; frame < frameCount; frame += 1) {
          const offset = (frame * this.channels + channel) * 2;
          const sample = bytes[offset] | bytes[offset + 1] << 8;
          const signed = sample & 32768 ? sample - 65536 : sample;
          samples[frame] = signed / 32768;
        }
        buffer.copyToChannel(samples, channel);
      }
      const source2 = this.context.createBufferSource();
      source2.buffer = buffer;
      source2.connect(this.context.destination);
      const startAt = Math.max(this.nextStartAt, this.context.currentTime);
      source2.start(startAt);
      this.nextStartAt = startAt + buffer.duration;
      this.sources.add(source2);
      source2.onended = () => {
        this.sources.delete(source2);
        this.notifyPlaybackFinished();
      };
    } catch {
      this.onError("Audio playback could not start");
      this.stop();
    }
  }
  end(turnId) {
    if (this.activeTurnId === turnId) {
      this.activeTurnId = null;
      this.pendingBytes = new Uint8Array();
      this.endedTurnId = turnId;
      this.notifyPlaybackFinished();
    }
  }
  abort(turnId) {
    if (this.activeTurnId !== turnId) return;
    this.stop();
  }
  stop() {
    for (const source2 of this.sources) {
      try {
        source2.stop();
      } catch {
      }
    }
    this.sources.clear();
    this.activeTurnId = null;
    this.endedTurnId = null;
    this.nextStartAt = 0;
    this.pendingBytes = new Uint8Array();
  }
  notifyPlaybackFinished() {
    if (this.endedTurnId === null || this.sources.size > 0) return;
    const turnId = this.endedTurnId;
    this.endedTurnId = null;
    try {
      this.onPlaybackFinished(turnId);
    } catch {
    }
  }
  ensureContext() {
    if (this.context === null) {
      this.context = this.audioContextFactory();
    }
    return this.context;
  }
}
var root = /* @__PURE__ */ from_html(`<button type="button" data-handsfree-button=""> </button>`);
var root_1 = /* @__PURE__ */ from_html(`<p data-voice-error="" role="alert"> </p>`);
var root_2 = /* @__PURE__ */ from_html(`<p data-voice-status="">Listening…</p>`);
var root_3 = /* @__PURE__ */ from_html(`<p data-voice-status="">Sending…</p>`);
var root_4 = /* @__PURE__ */ from_html(`<p data-handsfree-error="" role="alert"> </p>`);
var root_5 = /* @__PURE__ */ from_html(`<p data-handsfree-status=""> </p>`);
var root_6 = /* @__PURE__ */ from_html(`<p data-handsfree-status="">Heard you</p>`);
var root_7 = /* @__PURE__ */ from_html(`<p data-handsfree-status="">Listening…</p>`);
var root_8 = /* @__PURE__ */ from_html(`<p data-handsfree-status="">Listening for a follow-up…</p>`);
var root_9 = /* @__PURE__ */ from_html(`<p data-handsfree-status="">Sending…</p>`);
var root_10 = /* @__PURE__ */ from_html(`<section class="browser-voice-controls" aria-label="Browser voice"><button type="button" data-voice-button=""> </button> <!> <!> <!></section>`);
var root_11 = /* @__PURE__ */ from_html(`<div><!></div> <!> <!>`, 1);
function App($$anchor, $$props) {
  push($$props, false);
  const browserVoiceEnabled = /* @__PURE__ */ mutable_source();
  const browserHandsFreeEnabled = /* @__PURE__ */ mutable_source();
  const handsFreeArmed = /* @__PURE__ */ mutable_source();
  const displayReady = /* @__PURE__ */ mutable_source();
  const wakePhraseLabel = /* @__PURE__ */ mutable_source();
  const promptVisible = /* @__PURE__ */ mutable_source();
  const promptKey = /* @__PURE__ */ mutable_source();
  const localHandsFreeState = /* @__PURE__ */ mutable_source();
  const surfaceView = /* @__PURE__ */ mutable_source();
  let protocolError = /* @__PURE__ */ mutable_source(null);
  let displayView = /* @__PURE__ */ mutable_source(createInitialDisplayView());
  let connectionState = /* @__PURE__ */ mutable_source("connecting");
  let voiceState = /* @__PURE__ */ mutable_source("idle");
  let voiceError = /* @__PURE__ */ mutable_source(null);
  let handsFreeState = /* @__PURE__ */ mutable_source("off");
  let handsFreeError = /* @__PURE__ */ mutable_source(null);
  let voiceController = null;
  let handsFreeController = null;
  let audioPlayer = null;
  let dispatchAction = /* @__PURE__ */ mutable_source(async () => false);
  let responseHasAudio = false;
  let playbackFinished = false;
  let pendingAudioTurnId = null;
  let audioPlaybackFailed = /* @__PURE__ */ mutable_source(false);
  let userTranscript = /* @__PURE__ */ mutable_source("");
  let responseVisible = /* @__PURE__ */ mutable_source(false);
  let responseRetentionTimer = null;
  let responseRetentionGeneration = 0;
  let trackedResponseText = "";
  let responseTurnActive = false;
  let responseRetentionExpired = false;
  const responseActiveStates = /* @__PURE__ */ new Set(["heard", "listening", "thinking", "buffering", "speaking"]);
  const RESPONSE_RETENTION_MS = 6e4;
  function isDisplayReady() {
    return get(protocolError) === null && get(connectionState) === "connected" && get(displayView).state === "idle" && get(displayView).connection_healthy && !get(displayView).is_busy;
  }
  function handsFreeSurfaceState(state2) {
    if (state2 === "heard") return "heard";
    if (state2 === "listening" || state2 === "follow_up") return "listening";
    if (state2 === "submitting") return "thinking";
    return null;
  }
  function clearResponseRetentionTimer() {
    responseRetentionGeneration += 1;
    if (responseRetentionTimer !== null) {
      clearTimeout(responseRetentionTimer);
      responseRetentionTimer = null;
    }
  }
  function clearConversationPresentation() {
    clearResponseRetentionTimer();
    set(userTranscript, "");
    set(responseVisible, false);
    trackedResponseText = "";
    responseTurnActive = false;
    responseRetentionExpired = false;
  }
  function beginCapturePresentation() {
    clearConversationPresentation();
  }
  function scheduleResponseRetention(view) {
    if (view.state !== "idle" || responseHasAudio && !playbackFinished || trackedResponseText.length === 0 || !get(responseVisible) || responseRetentionExpired || responseRetentionTimer !== null) return;
    const generation = responseRetentionGeneration;
    responseRetentionTimer = setTimeout(
      () => {
        if (generation !== responseRetentionGeneration) return;
        responseRetentionTimer = null;
        set(responseVisible, false);
        responseRetentionExpired = true;
        set(userTranscript, "");
      },
      RESPONSE_RETENTION_MS
    );
  }
  function updateResponsePresentation(view) {
    const activeTurn = responseActiveStates.has(view.state);
    if (activeTurn) responseTurnActive = true;
    if (view.response_text.length === 0) {
      trackedResponseText = "";
      set(responseVisible, false);
      responseRetentionExpired = false;
      clearResponseRetentionTimer();
      if (view.state === "idle" || view.state === "prompt") responseTurnActive = false;
    } else if (view.response_text !== trackedResponseText && (activeTurn || responseTurnActive)) {
      trackedResponseText = view.response_text;
      set(responseVisible, true);
      responseRetentionExpired = false;
      clearResponseRetentionTimer();
    }
    scheduleResponseRetention(view);
  }
  function setUserTranscript(text) {
    set(userTranscript, text.trim());
  }
  function handleHandsFreeTranscript(text) {
    if (text && get(handsFreeState) === "wake_ready") beginCapturePresentation();
    setUserTranscript(text);
  }
  const stateChannelUrl = () => {
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${scheme}//${window.location.host}/state`;
  };
  onMount(() => {
    let bridge = null;
    bridge = new DisplayBridge({
      url: stateChannelUrl(),
      onView: (view) => {
        var _a2, _b2, _c;
        set(displayView, view);
        set(protocolError, null);
        if (view.state === "error" || view.state === "disconnected") {
          clearConversationPresentation();
        } else {
          updateResponsePresentation(view);
        }
        handsFreeController == null ? void 0 : handsFreeController.configure({
          wakePhrases: ((_a2 = view.capabilities) == null ? void 0 : _a2.wake_phrases) ?? [],
          wakeListenSeconds: (_b2 = view.capabilities) == null ? void 0 : _b2.wake_listen_seconds,
          followUpSeconds: (_c = view.capabilities) == null ? void 0 : _c.wake_followup_seconds
        });
        if (view.state === "prompt" || view.state !== "idle" && view.state !== "error" && view.state !== "disconnected" && (handsFreeController == null ? void 0 : handsFreeController.state) !== "submitting") {
          handsFreeController == null ? void 0 : handsFreeController.abort("Display is busy — hands-free is off");
        }
        if ([
          "heard",
          "listening",
          "thinking",
          "error",
          "disconnected",
          "prompt"
        ].includes(view.state)) {
          resetPlayback();
        }
        if (get(voiceState) === "listening" && view.state !== "idle") {
          voiceController == null ? void 0 : voiceController.reset();
        }
        if (view.state === "error") {
          voiceController == null ? void 0 : voiceController.reset();
          handsFreeController == null ? void 0 : handsFreeController.abort(view.status_text ?? "Turn could not be completed");
        } else if (view.state === "disconnected") {
          voiceController == null ? void 0 : voiceController.reset();
          handsFreeController == null ? void 0 : handsFreeController.abort("Display disconnected — hands-free is off");
        } else if (view.state === "idle") {
          if (get(voiceState) === "submitting") voiceController == null ? void 0 : voiceController.reset();
          maybeCompleteHandsFreeTurn();
        }
      },
      onConnectionState: (state2) => {
        set(connectionState, state2);
        if (state2 !== "connected") clearConversationPresentation();
        if (state2 === "disconnected") {
          resetPlayback();
          voiceController == null ? void 0 : voiceController.reset();
          handsFreeController == null ? void 0 : handsFreeController.abort("Display disconnected — hands-free is off");
        } else if (state2 === "connecting") {
          handsFreeController == null ? void 0 : handsFreeController.abort("Display disconnected — hands-free is off");
        }
      },
      onProtocolError: (message) => {
        set(protocolError, message);
        clearConversationPresentation();
        resetPlayback();
        voiceController == null ? void 0 : voiceController.reset();
        handsFreeController == null ? void 0 : handsFreeController.abort("Display data unavailable — hands-free is off");
      },
      onAudioEvent: (event2) => {
        if (event2.type === "audio_start") {
          responseHasAudio = true;
          playbackFinished = false;
          pendingAudioTurnId = event2.turn_id;
          set(audioPlaybackFailed, false);
          clearResponseRetentionTimer();
          audioPlayer == null ? void 0 : audioPlayer.start(event2);
        } else if (event2.type === "audio_end") {
          audioPlayer == null ? void 0 : audioPlayer.end(event2.turn_id);
          if (pendingAudioTurnId === event2.turn_id && !(audioPlayer == null ? void 0 : audioPlayer.hasPendingPlayback)) {
            playbackFinished = true;
          }
          maybeCompleteHandsFreeTurn();
        } else {
          audioPlayer == null ? void 0 : audioPlayer.abort(event2.turn_id);
          if (pendingAudioTurnId !== event2.turn_id) return;
          clearConversationPresentation();
          resetPlayback();
          handsFreeController == null ? void 0 : handsFreeController.abort("Response interrupted — hands-free is off");
        }
      },
      onAudioChunk: (chunk) => audioPlayer == null ? void 0 : audioPlayer.append(chunk),
      onVoiceError: () => {
        clearConversationPresentation();
        set(voiceError, "Turn could not be sent");
        set(voiceState, "error");
      }
    });
    set(dispatchAction, (action) => {
      if (get(connectionState) !== "connected" || get(displayView).state !== "prompt" || !get(displayView).can_choose) {
        return Promise.resolve(false);
      }
      return (bridge == null ? void 0 : bridge.dispatchAction(action)) ?? Promise.resolve(false);
    });
    audioPlayer = new PcmAudioPlayer({
      onError: (message) => {
        resetPlayback();
        set(audioPlaybackFailed, true);
        handsFreeController == null ? void 0 : handsFreeController.abort("Audio playback is unavailable — hands-free is off");
        clearConversationPresentation();
        set(voiceError, message);
        set(voiceState, "error");
      },
      onPlaybackFinished: (turnId) => {
        if (pendingAudioTurnId !== turnId) return;
        playbackFinished = true;
        updateResponsePresentation(get(displayView));
        maybeCompleteHandsFreeTurn();
      }
    });
    voiceController = new BrowserVoiceController({
      sendText: (text) => (bridge == null ? void 0 : bridge.sendVoiceTurn(text)) ?? false,
      onState: (state2) => {
        set(voiceState, state2);
        if (state2 !== "error") set(voiceError, null);
      },
      onError: (message) => {
        clearConversationPresentation();
        set(voiceError, message);
      },
      onTranscript: (text) => setUserTranscript(text)
    });
    handsFreeController = new BrowserHandsFreeController({
      sendText: (text) => (bridge == null ? void 0 : bridge.sendVoiceTurn(text)) ?? false,
      wakePhrases: [],
      onState: (state2) => {
        const previousState = get(handsFreeState);
        set(handsFreeState, state2);
        if (state2 === "heard" || state2 === "follow_up" || state2 === "listening" && previousState !== "heard") {
          beginCapturePresentation();
        }
        if (state2 !== "error") set(handsFreeError, null);
      },
      onError: (message) => {
        clearConversationPresentation();
        set(handsFreeError, message);
      },
      onTranscript: (text) => handleHandsFreeTranscript(text)
    });
    bridge.start();
    return () => {
      voiceController == null ? void 0 : voiceController.reset();
      handsFreeController == null ? void 0 : handsFreeController.disarm();
      clearResponseRetentionTimer();
      resetPlayback();
      bridge == null ? void 0 : bridge.stop();
    };
  });
  function resetPlayback() {
    audioPlayer == null ? void 0 : audioPlayer.stop();
    responseHasAudio = false;
    playbackFinished = false;
    pendingAudioTurnId = null;
    set(audioPlaybackFailed, false);
  }
  async function toggleVoice() {
    if (voiceController === null || get(voiceState) === "submitting" || get(handsFreeArmed)) return;
    if (get(voiceState) === "listening") {
      voiceController.stop();
      return;
    }
    if (!get(displayReady) || !get(browserVoiceEnabled)) return;
    set(voiceError, null);
    if (audioPlayer !== null && !await audioPlayer.resume()) return;
    if (!isDisplayReady() || (handsFreeController == null ? void 0 : handsFreeController.isArmed)) return;
    beginCapturePresentation();
    await voiceController.start();
  }
  async function toggleHandsFree() {
    if (handsFreeController === null) return;
    if (get(handsFreeArmed)) {
      handsFreeController.disarm();
      return;
    }
    if (!get(displayReady) || !get(browserHandsFreeEnabled)) return;
    set(handsFreeError, null);
    if (audioPlayer !== null && !await audioPlayer.resume()) return;
    if (!isDisplayReady() || !get(browserHandsFreeEnabled)) return;
    await handsFreeController.arm();
  }
  function maybeCompleteHandsFreeTurn() {
    if (get(displayView).state !== "idle" || get(connectionState) !== "connected" || responseHasAudio && !playbackFinished) {
      return;
    }
    responseHasAudio = false;
    playbackFinished = false;
    pendingAudioTurnId = null;
    handsFreeController == null ? void 0 : handsFreeController.turnFinished();
  }
  legacy_pre_effect(() => get(displayView), () => {
    var _a2;
    set(browserVoiceEnabled, ((_a2 = get(displayView).capabilities) == null ? void 0 : _a2.features.includes("browser_voice")) ?? false);
  });
  legacy_pre_effect(() => get(displayView), () => {
    var _a2;
    set(browserHandsFreeEnabled, ((_a2 = get(displayView).capabilities) == null ? void 0 : _a2.features.includes("browser_hands_free")) ?? false);
  });
  legacy_pre_effect(() => get(handsFreeState), () => {
    set(handsFreeArmed, get(handsFreeState) !== "off" && get(handsFreeState) !== "error");
  });
  legacy_pre_effect(
    () => (get(protocolError), get(connectionState), get(displayView)),
    () => {
      set(displayReady, get(protocolError) === null && get(connectionState) === "connected" && get(displayView).state === "idle" && get(displayView).connection_healthy && !get(displayView).is_busy);
    }
  );
  legacy_pre_effect(() => get(displayView), () => {
    var _a2, _b2;
    set(wakePhraseLabel, ((_b2 = (_a2 = get(displayView).capabilities) == null ? void 0 : _a2.wake_phrases) == null ? void 0 : _b2.join(" or ")) ?? "the wake phrase");
  });
  legacy_pre_effect(
    () => (get(protocolError), get(connectionState), get(displayView)),
    () => {
      set(promptVisible, get(protocolError) === null && get(connectionState) === "connected" && get(displayView).state === "prompt" && get(displayView).prompt !== null && get(displayView).can_choose);
    }
  );
  legacy_pre_effect(() => get(displayView), () => {
    set(promptKey, get(displayView).prompt === null ? "" : JSON.stringify(get(displayView).prompt));
  });
  legacy_pre_effect(() => get(handsFreeState), () => {
    set(localHandsFreeState, handsFreeSurfaceState(get(handsFreeState)));
  });
  legacy_pre_effect(() => (get(localHandsFreeState), get(displayView)), () => {
    set(surfaceView, get(localHandsFreeState) !== null && get(displayView).state === "idle" ? {
      ...get(displayView),
      state: get(localHandsFreeState),
      status_text: null
    } : get(displayView));
  });
  legacy_pre_effect_reset();
  init();
  var fragment = root_11();
  var div = first_child(fragment);
  var node = child(div);
  StateSurface(node, {
    get snapshot() {
      return get(surfaceView);
    },
    get connectionState() {
      return get(connectionState);
    },
    get protocolError() {
      return get(protocolError);
    },
    get userTranscript() {
      return get(userTranscript);
    },
    get responseVisible() {
      return get(responseVisible);
    },
    get audioPlaybackFailed() {
      return get(audioPlaybackFailed);
    }
  });
  var node_1 = sibling(div, 2);
  {
    var consequent = ($$anchor2) => {
      var fragment_1 = comment();
      var node_2 = first_child(fragment_1);
      key(node_2, () => get(promptKey), ($$anchor3) => {
        {
          let $0 = /* @__PURE__ */ derived_safe_equal(() => (get(displayView), untrack(() => get(displayView).account ?? null)));
          PromptOverlay($$anchor3, {
            get prompt() {
              return get(displayView), untrack(() => get(displayView).prompt);
            },
            get account() {
              return get($0);
            },
            get onAction() {
              return get(dispatchAction);
            }
          });
        }
      });
      append($$anchor2, fragment_1);
    };
    if_block(node_1, ($$render) => {
      if (get(promptVisible), get(displayView), untrack(() => get(promptVisible) && get(displayView).prompt)) $$render(consequent);
    });
  }
  var node_3 = sibling(node_1, 2);
  {
    var consequent_11 = ($$anchor2) => {
      var section = root_10();
      var button = child(section);
      var text_1 = only_child(button, true);
      var node_4 = sibling(button, 2);
      {
        var consequent_1 = ($$anchor3) => {
          var button_1 = root();
          var text_2 = only_child(button_1, true);
          template_effect(() => {
            set_attribute(button_1, "aria-pressed", get(handsFreeArmed));
            button_1.disabled = !get(handsFreeArmed) && !get(displayReady);
            set_text(text_2, get(handsFreeArmed) ? "Disable hands-free" : "Enable hands-free");
          });
          event("click", button_1, toggleHandsFree);
          append($$anchor3, button_1);
        };
        if_block(node_4, ($$render) => {
          if (get(browserHandsFreeEnabled)) $$render(consequent_1);
        });
      }
      var node_5 = sibling(node_4, 2);
      {
        var consequent_2 = ($$anchor3) => {
          var p = root_1();
          var text_3 = only_child(p, true);
          template_effect(() => set_text(text_3, get(voiceError)));
          append($$anchor3, p);
        };
        var consequent_3 = ($$anchor3) => {
          var p_1 = root_2();
          append($$anchor3, p_1);
        };
        var consequent_4 = ($$anchor3) => {
          var p_2 = root_3();
          append($$anchor3, p_2);
        };
        if_block(node_5, ($$render) => {
          if (get(voiceError)) $$render(consequent_2);
          else if (get(voiceState) === "listening") $$render(consequent_3, 1);
          else if (get(voiceState) === "submitting") $$render(consequent_4, 2);
        });
      }
      var node_6 = sibling(node_5, 2);
      {
        var consequent_5 = ($$anchor3) => {
          var p_3 = root_4();
          var text_4 = only_child(p_3, true);
          template_effect(() => set_text(text_4, get(handsFreeError)));
          append($$anchor3, p_3);
        };
        var consequent_6 = ($$anchor3) => {
          var p_4 = root_5();
          var text_5 = only_child(p_4);
          template_effect(() => set_text(text_5, `Say ${get(wakePhraseLabel) ?? ""}`));
          append($$anchor3, p_4);
        };
        var consequent_7 = ($$anchor3) => {
          var p_5 = root_6();
          append($$anchor3, p_5);
        };
        var consequent_8 = ($$anchor3) => {
          var p_6 = root_7();
          append($$anchor3, p_6);
        };
        var consequent_9 = ($$anchor3) => {
          var p_7 = root_8();
          append($$anchor3, p_7);
        };
        var consequent_10 = ($$anchor3) => {
          var p_8 = root_9();
          append($$anchor3, p_8);
        };
        if_block(node_6, ($$render) => {
          if (get(handsFreeError)) $$render(consequent_5);
          else if (get(handsFreeState) === "wake_ready") $$render(consequent_6, 1);
          else if (get(handsFreeState) === "heard") $$render(consequent_7, 2);
          else if (get(handsFreeState) === "listening") $$render(consequent_8, 3);
          else if (get(handsFreeState) === "follow_up") $$render(consequent_9, 4);
          else if (get(handsFreeState) === "submitting") $$render(consequent_10, 5);
        });
      }
      template_effect(() => {
        set_attribute(section, "data-voice-state", get(voiceState));
        set_attribute(button, "aria-pressed", get(voiceState) === "listening");
        button.disabled = !get(displayReady) || get(voiceState) === "submitting" || get(handsFreeArmed);
        set_text(text_1, get(voiceState) === "listening" ? "Stop listening" : "Tap to talk");
      });
      event("click", button, toggleVoice);
      append($$anchor2, section);
    };
    if_block(node_3, ($$render) => {
      if (get(browserVoiceEnabled)) $$render(consequent_11);
    });
  }
  template_effect(() => set_attribute(div, "aria-hidden", get(promptVisible) ? "true" : void 0));
  append($$anchor, fragment);
  pop();
}
const target = document.getElementById("app");
if (target === null) {
  throw new Error("Home display mount point is missing");
}
mount(App, { target });
