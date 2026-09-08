"""Checks for the reproducible shared-display WebAssembly target."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_display_wasm.sh"
DISPLAY_DIR = REPO_ROOT / "shared" / "display"
WASM_DIR = DISPLAY_DIR / "wasm"
WASM_ARTIFACT_DIR = REPO_ROOT / "home_display" / "web" / "public" / "wasm"


def test_wasm_build_script_declares_versioned_artifact_and_reducer_exports() -> None:
    source = BUILD_SCRIPT.read_text()

    assert 'EMSCRIPTEN_VERSION="6.0.5"' in source
    assert 'LVGL_VERSION="8.3.11"' in source
    assert 'display_core.js' in source
    assert 'display_core.wasm' in source
    assert "display_wasm_apply_snapshot" in source
    assert "display_wasm_validate_choice" in source
    assert "-sMODULARIZE=1" in source
    assert "-sEXPORT_ES6=1" in source


def _compile_and_run(source: str) -> subprocess.CompletedProcess[str]:
    harness = Path(__file__).with_name("_display_wasm_harness.c")
    binary = Path(__file__).with_name("_display_wasm_harness")
    harness.write_text(source, encoding="utf-8")
    try:
        compile_result = subprocess.run(
            [
                "cc",
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(DISPLAY_DIR),
                str(harness),
                str(DISPLAY_DIR / "display_wasm.c"),
                str(DISPLAY_DIR / "display_rules.c"),
                "-o",
                str(binary),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert compile_result.returncode == 0, compile_result.stderr
        return subprocess.run([str(binary)], check=False, capture_output=True, text=True)
    finally:
        harness.unlink(missing_ok=True)
        binary.unlink(missing_ok=True)


def test_wasm_abi_matches_native_reducer_for_prompt_and_stale_snapshots() -> None:
    result = _compile_and_run(
        r'''
        #include <assert.h>
        #include "display_wasm.h"

        int main(void) {
            assert(display_wasm_abi_version() == 2);
            assert(display_wasm_init() == DISPLAY_RULES_ACCEPTED);
            assert(display_wasm_apply_snapshot(
                10, "prompt", "", "", "", "confirm", "Set home?", "Use this display?",
                "sethome", -1, 1, 1, 2,
                "yes", "Yes", "no", "No", "", "", "", "") == DISPLAY_RULES_ACCEPTED);
            assert(display_wasm_view_state() == DISPLAY_RULES_PROMPT);
            assert(display_wasm_view_sequence() == 10);
            assert(display_wasm_view_can_choose());
            assert(display_wasm_view_can_dismiss());
            assert(display_wasm_validate_choice("sethome", "yes") == DISPLAY_RULES_ACCEPTED);
            assert(display_wasm_validate_choice("sethome", "later") == DISPLAY_RULES_UNKNOWN_CHOICE);
            assert(display_wasm_apply_snapshot(
                9, "idle", "", "", "", "", "", "", "", -1, 0, 0, 0,
                "", "", "", "", "", "", "", "") == DISPLAY_RULES_STALE);
            assert(display_wasm_view_state() == DISPLAY_RULES_PROMPT);
            assert(display_wasm_apply_snapshot(
                11, "prompt", "", "", "", "confirm", "Bad timeout", "Reject this",
                "bad-timeout", 0, 1, 0, 1,
                "yes", "Yes", "", "", "", "", "", "") == DISPLAY_RULES_INVALID_SNAPSHOT);
            return 0;
        }
        '''
    )

    assert result.returncode == 0, result.stderr


def test_wasm_build_reports_an_actionable_missing_toolchain(tmp_path: Path) -> None:
    empty_path = tmp_path / "bin"
    empty_path.mkdir()
    result = subprocess.run(
        ["/bin/bash", str(BUILD_SCRIPT), "--check"],
        check=False,
        capture_output=True,
        text=True,
        env={"PATH": str(empty_path)},
    )

    assert result.returncode != 0
    assert "Emscripten 6.0.5 is required" in result.stderr


def test_wasm_build_invokes_pinned_sources_and_emits_both_artifacts(tmp_path: Path) -> None:
    fake_emcc = tmp_path / "emcc"
    fake_emcc.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'if [ "$1" = "--version" ]; then',
                "  echo 'emcc (Emscripten gcc/clang-like replacement) 6.0.5'",
                "  exit 0",
                "fi",
                "log_file=${FAKE_EMCC_LOG:?}",
                "output=''",
                'while [ "$#" -gt 0 ]; do',
                '  if [ "$1" = "-o" ]; then',
                "    output=$2",
                "    shift 2",
                "  else",
                '    printf \'%s\\n\' "$1" >> "$log_file"',
                "    shift",
                "  fi",
                "done",
                'mkdir -p "$(dirname "$output")"',
                "printf 'js\\n' > \"$output\"",
                "printf 'wasm\\n' > \"${output%.js}.wasm\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    fake_emcc.chmod(0o755)
    lvgl_dir = tmp_path / "lvgl"
    (lvgl_dir / "src").mkdir(parents=True)
    (lvgl_dir / "lvgl.h").write_text("/* fake LVGL header */\n", encoding="utf-8")
    (lvgl_dir / "src" / "lv_fake.c").write_text("", encoding="utf-8")
    output_dir = tmp_path / "output"
    log_file = tmp_path / "emcc.log"

    environment = os.environ.copy()
    environment.update(
        {
            "EMCC": str(fake_emcc),
            "FAKE_EMCC_LOG": str(log_file),
            "LVGL_DIR": str(lvgl_dir),
            "DISPLAY_WASM_OUTPUT_DIR": str(output_dir),
            "DISPLAY_WASM_BUILD_DIR": str(tmp_path / "build"),
        }
    )
    result = subprocess.run(
        ["/bin/bash", str(BUILD_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "display_core.js").is_file()
    assert (output_dir / "display_core.wasm").is_file()
    invocation = log_file.read_text(encoding="utf-8")
    assert "-DDISPLAY_WASM=1" in invocation
    assert "-sMODULARIZE=1" in invocation
    assert "-sEXPORT_ES6=1" in invocation
    assert str(DISPLAY_DIR / "display_wasm.c") in invocation
    assert str(lvgl_dir / "src" / "lv_fake.c") in invocation


def test_wasm_target_reuses_the_lvgl_surface_with_browser_platform_shims() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    board_config = (WASM_DIR / "board_config.h").read_text(encoding="utf-8")
    lv_conf = (WASM_DIR / "lv_conf.h").read_text(encoding="utf-8")

    assert "main/src/ui_snapshot.c" in source
    assert "main/src/ui_display.c" in source
    assert "-DDISPLAY_WASM=1" in source
    assert "BOARD_LCD_H_RES 1024" in board_config
    assert "BOARD_LCD_V_RES 600" in board_config
    assert "#define LV_CONF_H" in lv_conf
    assert "LV_MEM_CUSTOM 0" in lv_conf
    assert "LV_TICK_CUSTOM 0" in lv_conf


def test_wasm_target_exports_the_lvgl_framebuffer_and_tick_pump() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    runtime = (DISPLAY_DIR / "display_wasm.c").read_text(encoding="utf-8")

    assert "-DDISPLAY_WASM_WITH_LVGL=1" in source
    assert "_display_wasm_framebuffer" in source
    assert "_display_wasm_tick" in source
    assert "DISPLAY_WASM_WITH_LVGL" in runtime
    assert "ui_display_init" in runtime
    assert "lv_disp_drv_register" in runtime


def test_wasm_target_exports_browser_pointer_and_action_bridge() -> None:
    source = BUILD_SCRIPT.read_text(encoding="utf-8")
    header = (DISPLAY_DIR / "display_wasm.h").read_text(encoding="utf-8")
    runtime = (DISPLAY_DIR / "display_wasm.c").read_text(encoding="utf-8")

    for export in (
        "_display_wasm_set_pointer",
        "_display_wasm_action_pending",
        "_display_wasm_action_id",
        "_display_wasm_action_choice",
        "_display_wasm_action_clear",
    ):
        assert export in source
    for symbol in (
        "display_wasm_set_pointer",
        "display_wasm_action_pending",
        "display_wasm_action_id",
        "display_wasm_action_choice",
        "display_wasm_action_clear",
    ):
        assert symbol in header
        assert symbol in runtime


def _fixture_c_arguments(snapshot: dict[str, object]) -> list[str]:
    raw_prompt = snapshot.get("prompt")
    prompt = raw_prompt if isinstance(raw_prompt, dict) else {}
    raw_options = prompt.get("options", [])
    options = raw_options if isinstance(raw_options, list) else []
    raw_capabilities = snapshot.get("capabilities")
    capabilities = raw_capabilities if isinstance(raw_capabilities, dict) else {}
    raw_actions = capabilities.get("actions", [])
    actions = raw_actions if isinstance(raw_actions, list) else []
    timeout = prompt.get("timeout_seconds")

    def text(value: object) -> str:
        return "" if value is None else str(value)

    arguments = [
        str(snapshot.get("sequence", 0)),
        text(snapshot.get("state")),
        text(snapshot.get("response_text")),
        text(snapshot.get("status_text")),
        text(snapshot.get("account")),
        text(prompt.get("kind")),
        text(prompt.get("title")),
        text(prompt.get("body")),
        text(prompt.get("action_id")),
        str(-1 if timeout is None else int(timeout)),
        "1" if "prompt.choose" in actions else "0",
        "1" if "prompt.dismiss" in actions else "0",
        str(len(options)),
    ]
    for index in range(4):
        option = options[index] if index < len(options) else {}
        option = option if isinstance(option, dict) else {}
        arguments.extend([text(option.get("id")), text(option.get("label"))])
    return [json.dumps(argument) if index != 0 and index != 9 and index not in {10, 11, 12} else argument
            for index, argument in enumerate(arguments)]


def _run_native_fixture_abi(
    tmp_path: Path,
    valid_snapshots: list[dict[str, object]],
    invalid_snapshots: list[dict[str, object]],
) -> list[str]:
    statements: list[str] = []
    for index, snapshot in enumerate(valid_snapshots):
        arguments = ", ".join(_fixture_c_arguments(snapshot))
        statements.append(
            f'''    display_wasm_reset();
    result = display_wasm_apply_snapshot({arguments});
    printf("valid,{index},%d,%d,%u,%d,%d,%d,%d\\n", result,
           display_wasm_view_state(), display_wasm_view_sequence(),
           display_wasm_view_is_busy(), display_wasm_view_connection_healthy(),
           display_wasm_view_can_choose(), display_wasm_view_can_dismiss());'''
        )
    for index, snapshot in enumerate(invalid_snapshots):
        arguments = ", ".join(_fixture_c_arguments(snapshot))
        statements.append(
            f'''    display_wasm_reset();
    result = display_wasm_apply_snapshot({arguments});
    printf("invalid,{index},%d\\n", result);'''
        )

    empty_idle = ', '.join([
        '20', '"idle"', '""', '""', '""', '""', '""', '""', '""',
        '-1', '0', '0', '0', '""', '""', '""', '""', '""', '""', '""', '""',
    ])
    stale_idle = empty_idle.replace('20,', '19,', 1)
    statements.append(
        f'''    display_wasm_reset();
    display_wasm_apply_snapshot({empty_idle});
    result = display_wasm_apply_snapshot({stale_idle});
    printf("stale,%d,%d,%u\\n", result, display_wasm_view_state(), display_wasm_view_sequence());'''
    )

    capability_snapshot = next(
        snapshot
        for snapshot in valid_snapshots
        if snapshot.get("state") == "prompt"
        and isinstance(snapshot.get("capabilities"), dict)
        and snapshot["capabilities"].get("actions") == ["prompt.choose"]
    )
    capability_arguments = ", ".join(_fixture_c_arguments(capability_snapshot))
    statements.append(
        f'''    display_wasm_reset();
    display_wasm_apply_snapshot({capability_arguments});
    printf("cap,%d,%d,%d,%d\\n", display_wasm_view_can_choose(),
           display_wasm_view_can_dismiss(),
           display_wasm_validate_choice("approval-1", "yes"),
           display_wasm_validate_dismiss());'''
    )

    source = f'''
        #include <stdio.h>
        #include "display_wasm.h"

        int main(void) {{
            int result;
            if (display_wasm_init() != DISPLAY_RULES_ACCEPTED) return 2;
{chr(10).join(statements)}
            return 0;
        }}
    '''
    harness = tmp_path / "display_wasm_fixture_harness.c"
    binary = tmp_path / "display_wasm_fixture_harness"
    harness.write_text(source, encoding="utf-8")
    compile_result = subprocess.run(
        [
            "cc",
            "-std=c11",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(DISPLAY_DIR),
            str(harness),
            str(DISPLAY_DIR / "display_wasm.c"),
            str(DISPLAY_DIR / "display_rules.c"),
            "-o",
            str(binary),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compile_result.returncode == 0, compile_result.stderr
    result = subprocess.run([str(binary)], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


def _run_generated_wasm_fixtures(
    valid_snapshots: list[dict[str, object]],
    invalid_snapshots: list[dict[str, object]],
) -> list[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the generated WebAssembly parity check")
    wasm_js = WASM_ARTIFACT_DIR / "display_core.js"
    wasm_binary = WASM_ARTIFACT_DIR / "display_core.wasm"
    if not wasm_js.is_file() or not wasm_binary.is_file():
        pytest.skip("run scripts/build_display_wasm.sh before the generated parity check")

    snapshot_types = [
        "number",
        *(["string"] * 8),
        *(["number"] * 4),
        *(["string"] * 8),
    ]
    node_script = f'''
        import fs from "node:fs";
        import {{ createServer }} from "node:http";
        import {{ pathToFileURL }} from "node:url";

        const snapshots = {json.dumps(valid_snapshots)};
        const invalidSnapshots = {json.dumps(invalid_snapshots)};
        const wasmPath = {json.dumps(str(wasm_binary))};
        const modulePath = {json.dumps(str(wasm_js))};
        const wasmBytes = fs.readFileSync(wasmPath);
        const server = createServer((_request, response) => {{
            response.writeHead(200, {{ "Content-Type": "application/wasm" }});
            response.end(wasmBytes);
        }});
        await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
        const address = server.address();
        const port = typeof address === "object" && address !== null ? address.port : 0;

        try {{
            const factory = (await import(pathToFileURL(modulePath).href)).default;
            const module = await factory({{ locateFile: (path) => `http://127.0.0.1:${{port}}/${{path}}` }});
            const wrap = (name, argumentTypes = []) => module.cwrap(name, "number", argumentTypes);
            const init = wrap("display_wasm_init")();
            const reset = wrap("display_wasm_reset");
            const apply = wrap("display_wasm_apply_snapshot", {json.dumps(snapshot_types)});
            const viewState = wrap("display_wasm_view_state");
            const viewSequence = wrap("display_wasm_view_sequence");
            const viewBusy = wrap("display_wasm_view_is_busy");
            const viewHealthy = wrap("display_wasm_view_connection_healthy");
            const viewChoose = wrap("display_wasm_view_can_choose");
            const viewDismiss = wrap("display_wasm_view_can_dismiss");
            const validateChoice = wrap("display_wasm_validate_choice", ["string", "string"]);
            const validateDismiss = wrap("display_wasm_validate_dismiss");
            const args = (snapshot) => {{
                const prompt = snapshot.prompt ?? {{}};
                const options = Array.isArray(prompt.options) ? prompt.options : [];
                const flatOptions = [0, 1, 2, 3].flatMap((index) => [
                    options[index]?.id ?? "", options[index]?.label ?? "",
                ]);
                const actions = snapshot.capabilities?.actions ?? [];
                return [
                    snapshot.sequence ?? 0, snapshot.state ?? "", snapshot.response_text ?? "",
                    snapshot.status_text ?? "", snapshot.account ?? "", prompt.kind ?? "",
                    prompt.title ?? "", prompt.body ?? "", prompt.action_id ?? "",
                    prompt.timeout_seconds ?? -1,
                    prompt.options ? (actions.includes("prompt.choose") ? 1 : 0) : 0,
                    prompt.options ? (actions.includes("prompt.dismiss") ? 1 : 0) : 0,
                    options.length, ...flatOptions,
                ];
            }};
            const output = [];
            if (init !== 0) throw new Error(`init ${{init}}`);
            for (const [index, snapshot] of snapshots.entries()) {{
                reset();
                const result = apply(...args(snapshot));
                output.push(`valid,${{index}},${{result}},${{viewState()}},${{viewSequence()}},${{viewBusy()}},${{viewHealthy()}},${{viewChoose()}},${{viewDismiss()}}`);
            }}
            for (const [index, snapshot] of invalidSnapshots.entries()) {{
                reset();
                output.push(`invalid,${{index}},${{apply(...args(snapshot))}}`);
            }}
            reset();
            apply(20, "idle", "", "", "", "", "", "", "", -1, 0, 0, 0, "", "", "", "", "", "", "", "");
            const staleResult = apply(19, "idle", "", "", "", "", "", "", "", -1, 0, 0, 0, "", "", "", "", "", "", "", "");
            output.push(`stale,${{staleResult}},${{viewState()}},${{viewSequence()}}`);
            const capabilitySnapshot = snapshots.find((snapshot) => snapshot.state === "prompt" && snapshot.capabilities?.actions?.length === 1);
            reset();
            apply(...args(capabilitySnapshot));
            output.push(`cap,${{viewChoose()}},${{viewDismiss()}},${{validateChoice("approval-1", "yes")}},${{validateDismiss()}}`);
            process.stdout.write(output.join("\\n") + "\\n");
        }} finally {{
            server.close();
        }}
    '''
    result = subprocess.run(
        [node, "--input-type=module"],
        input=node_script,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().splitlines()


def _run_generated_wasm_canvas_input_smoke() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required for the generated WebAssembly canvas check")
    wasm_js = WASM_ARTIFACT_DIR / "display_core.js"
    wasm_binary = WASM_ARTIFACT_DIR / "display_core.wasm"
    if not wasm_js.is_file() or not wasm_binary.is_file():
        pytest.skip("run scripts/build_display_wasm.sh before the generated canvas check")

    snapshot_types = [
        "number",
        *(["string"] * 8),
        *(["number"] * 4),
        *(["string"] * 8),
    ]
    node_script = f'''
        import fs from "node:fs";
        import {{ createServer }} from "node:http";
        import {{ pathToFileURL }} from "node:url";

        const wasmPath = {json.dumps(str(wasm_binary))};
        const modulePath = {json.dumps(str(wasm_js))};
        const wasmBytes = fs.readFileSync(wasmPath);
        const server = createServer((_request, response) => {{
            response.writeHead(200, {{ "Content-Type": "application/wasm" }});
            response.end(wasmBytes);
        }});
        await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
        const address = server.address();
        const port = typeof address === "object" && address !== null ? address.port : 0;

        try {{
            const factory = (await import(pathToFileURL(modulePath).href)).default;
            const module = await factory({{ locateFile: (path) => `http://127.0.0.1:${{port}}/${{path}}` }});
            const wrap = (name, returnType = "number", argumentTypes = []) =>
                module.cwrap(name, returnType, argumentTypes);
            const init = wrap("display_wasm_init")();
            const apply = wrap("display_wasm_apply_snapshot", "number", {json.dumps(snapshot_types)});
            const setPointer = wrap("display_wasm_set_pointer", "number", ["number", "number", "number"]);
            const tick = wrap("display_wasm_tick", "number", ["number"]);
            const framebuffer = wrap("display_wasm_framebuffer");
            const width = wrap("display_wasm_framebuffer_width");
            const height = wrap("display_wasm_framebuffer_height");
            const pending = wrap("display_wasm_action_pending");
            const actionId = wrap("display_wasm_action_id", "string");
            const choice = wrap("display_wasm_action_choice", "string");
            const clear = wrap("display_wasm_action_clear");
            const snapshot = [
                10, "prompt", "", "", "", "confirm", "Set home?", "Use this display?",
                "sethome", -1, 1, 0, 1, "yes", "Yes", "", "", "", "", "", "",
            ];
            if (init !== 0) throw new Error(`init ${{init}}`);
            if (apply(...snapshot) !== 0) throw new Error("prompt snapshot was rejected");
            if (tick(100) !== 0) throw new Error("initial render tick was rejected");
            const framePointer = framebuffer();
            const frameBytes = module.HEAPU8.subarray(framePointer, framePointer + width() * height() * 4);
            const rendered = frameBytes.some((byte) => byte !== 0);
            if (setPointer(200, 338, 1) !== 0) throw new Error("pointer press was rejected");
            if (setPointer(200, 338, 0) !== 0) throw new Error("pointer release was rejected");
            if (tick(16) !== 0) throw new Error("release tick was rejected");
            const result = {{
                width: width(), height: height(), framebuffer: framePointer > 0, rendered,
                pending: pending(), actionId: actionId(), choice: choice(), clear: clear(),
                pendingAfterClear: pending(),
            }};
            process.stdout.write(JSON.stringify(result));
        }} finally {{
            server.close();
        }}
    '''
    result = subprocess.run(
        [node, "--input-type=module"],
        input=node_script,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_generated_wasm_canvas_input_emits_the_normalized_prompt_action() -> None:
    assert _run_generated_wasm_canvas_input_smoke() == {
        "width": 1024,
        "height": 600,
        "framebuffer": True,
        "rendered": True,
        "pending": 1,
        "actionId": "sethome",
        "choice": "yes",
        "clear": 0,
        "pendingAfterClear": 0,
    }


def test_generated_wasm_matches_native_fixture_normalization(tmp_path: Path) -> None:
    valid_snapshots = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((DISPLAY_DIR / "fixtures" / "snapshots").glob("*.json"))
    ]
    invalid_snapshots = [
        json.loads((DISPLAY_DIR / "fixtures" / "invalid" / name).read_text(encoding="utf-8"))
        for name in ("bad_timeout.json", "unknown_state.json", "prompt_missing.json")
    ]

    native = _run_native_fixture_abi(tmp_path, valid_snapshots, invalid_snapshots)
    wasm = _run_generated_wasm_fixtures(valid_snapshots, invalid_snapshots)

    assert wasm == native
