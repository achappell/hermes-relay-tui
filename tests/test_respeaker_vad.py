"""Native regressions for the same progress/publication helpers used by MWW.

Synthetic numerical inputs only: no model tuning, recordings, or device access.
The production StreamingModel calls StreamingInferenceProgress at its actual
Invoke site; MicroWakeWord publishes/reads through VADSnapshotStore.
"""

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "firmware/respeaker-lite/components/micro_wake_word"


def _run_native(tmp_path, body):
    compiler = shutil.which("clang++") or shutil.which("c++")
    if compiler is None:
        pytest.skip("native C++ compiler unavailable")
    source = tmp_path / "vad.cpp"
    source.write_text(
        '#include "vad_snapshot.h"\n'
        "#include <cassert>\n#include <cmath>\n#include <mutex>\n"
        "#include <atomic>\n#include <thread>\n#include <condition_variable>\n"
        "#include <vector>\n"
        "using namespace esphome::micro_wake_word;\n"
        + body
    )
    executable = tmp_path / "vad"
    compiled = subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-I", str(COMPONENT), str(source), "-o", str(executable)],
        capture_output=True, text=True, timeout=60,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_actual_invoke_progress_full_window_reset_and_no_new_invoke(tmp_path):
    _run_native(tmp_path, r'''
        int main() {
          StreamingInferenceProgress progress;
          VADSnapshotStore<std::mutex> store;
          uint32_t epoch = store.start();
          constexpr size_t stride = 3, window = 4;
          uint32_t now = 100;
          auto feature = [&](bool successful, uint8_t probability) {
            const size_t slot = progress.next_feature_slot(stride);
            assert(slot < stride);
            now += 10;
            if (!progress.ready(stride)) return false;
            progress.invoked(successful, window);
            if (successful) {
              store.publish(epoch, progress.generation(), now, progress.full_window(window),
                            probability > 12, probability, probability, 30);
            } else {
              store.invalidate();
            }
            return true;
          };
          assert(!store.snapshot(now).valid);
          // Nine feature steps are only three actual invocations, not a window.
          for (unsigned i = 0; i < 9; ++i) feature(true, 255);
          assert(progress.generation() == 3);
          assert(!store.snapshot(now).valid && !store.snapshot(now).detected);
          feature(true, 255);
          const auto before = store.snapshot(now);
          assert(before.generation == 3 && !before.valid);
          feature(true, 255);
          feature(true, 255);
          auto snapshot = store.snapshot(now);
          assert(progress.generation() == 4 && snapshot.generation == 4);
          assert(snapshot.valid && snapshot.detected);
          assert(snapshot.average_probability == 1.0f && snapshot.maximum_probability == 1.0f);
          // A partial next tensor never refreshes timestamp or generation.
          assert(!feature(true, 0));
          assert(!feature(true, 0));
          snapshot = store.snapshot(now);
          assert(snapshot.generation == 4 && snapshot.timestamp_ms == before.timestamp_ms + 30);
          assert(feature(true, 0));
          snapshot = store.snapshot(now);
          assert(snapshot.valid && !snapshot.detected && snapshot.generation == 5);
          // Stop invalidates cached true immediately; restart needs a full window.
          feature(true, 255); // leave a partial tensor behind
          store.invalidate();
          progress.reset();
          assert(progress.generation() == 5);
          epoch = store.start();
          for (unsigned i = 0; i < 11; ++i) {
            feature(true, 255);
            assert(!store.snapshot(now).valid);
          }
          feature(true, 255);
          assert(store.snapshot(now).valid && store.snapshot(now).detected);
          assert(store.snapshot(now).generation == 9);
          // Failed Invoke still counts as an invocation, but cannot be a result.
          feature(true, 255);
          feature(true, 255);
          feature(false, 255);
          assert(progress.generation() == 10 && !progress.full_window(window));
          assert(!store.snapshot(now).valid);
        }
    ''')


def test_stale_true_stop_and_inflight_result_cannot_revalidate(tmp_path):
    _run_native(tmp_path, r'''
        int main() {
          VADSnapshotStore<std::mutex> store;
          auto epoch = store.start();
          store.publish(epoch, 1, 100, true, true, 200, 250, 30);
          assert(store.snapshot(190).valid); // exactly 3 * cadence
          assert(!store.snapshot(191).valid && !store.snapshot(191).detected);
          // Repeated processing of features without Invoke is not progress.
          store.publish(epoch, 1, 190, true, true, 200, 250, 30);
          assert(store.snapshot(190).timestamp_ms == 100);
          assert(!store.snapshot(191).valid);
          std::mutex mutex;
          std::condition_variable cv;
          bool invoking = false, complete = false;
          std::thread worker([&] {
            const auto invocation_epoch = store.epoch();
            {
              std::unique_lock<std::mutex> lock(mutex);
              invoking = true;
              cv.notify_one();
              cv.wait(lock, [&] { return complete; });
            }
            store.publish(invocation_epoch, 2, 200, true, true, 255, 255, 30);
          });
          {
            std::unique_lock<std::mutex> lock(mutex);
            cv.wait(lock, [&] { return invoking; });
          }
          store.invalidate(); // synchronous stop, including a repeated STOPPING stop
          store.invalidate();
          const auto new_epoch = store.start();
          {
            std::lock_guard<std::mutex> lock(mutex);
            complete = true;
          }
          cv.notify_one();
          worker.join();
          auto snapshot = store.snapshot(200);
          assert(!snapshot.valid && !snapshot.detected && snapshot.generation == 1);
          store.publish(new_epoch, 3, 210, false, true, 255, 255, 30);
          assert(!store.snapshot(210).valid && !store.snapshot(210).detected);
          store.publish(new_epoch, 4, 240, true, false, 0, 0, 30);
          assert(store.snapshot(240).valid && !store.snapshot(240).detected);
          // Unsigned elapsed arithmetic remains correct across millis wrap.
          store.publish(new_epoch, 5, UINT32_MAX - 20, true, true, 255, 255, 30);
          assert(store.snapshot(30).valid);
          assert(!store.snapshot(71).valid);
        }
    ''')


def test_snapshot_fields_share_one_synchronization_boundary(tmp_path):
    _run_native(tmp_path, r'''
        int main() {
          VADSnapshotStore<std::mutex> store;
          const auto epoch = store.start();
          std::atomic<bool> done{false};
          std::thread worker([&] {
            for (uint32_t i = 1; i <= 20000; ++i)
              store.publish(epoch, i, i + 1000, true, (i % 2) != 0,
                            uint8_t(i % 256), uint8_t((i * 3) % 256), 100000);
            done = true;
          });
          do {
            const auto s = store.snapshot(21000);
            if (!s.valid) continue;
            assert(s.timestamp_ms == s.generation + 1000);
            assert(s.detected == ((s.generation % 2) != 0));
            assert(s.average_probability == uint8_t(s.generation % 256) / 255.0f);
            assert(s.maximum_probability == uint8_t((s.generation * 3) % 256) / 255.0f);
          } while (!done);
          worker.join();
          assert(store.snapshot(21000).generation == 20000);
        }
    ''')


def test_capture_diagnostics_unique_fresh_results_and_selected_s16_rails(tmp_path):
    _run_native(tmp_path, r'''
        int main() {
          VADSnapshotStore<std::mutex> store;
          const auto epoch = store.start();
          VADCaptureDiagnostics summary;
          assert(!store.finish_capture(summary));
          // Before the capture neither probabilities nor samples are counted.
          store.publish(epoch, 1, 100, true, true, 255, 255, 30);
          const int16_t pcm[] = {INT16_MIN, -1, 0, 1, INT16_MAX, 32766};
          store.record_selected_pcm(reinterpret_cast<const uint8_t *>(pcm), sizeof(pcm));
          store.begin_capture();
          store.publish(epoch, 2, 110, false, true, 255, 255, 30); // partial window
          store.publish(epoch, 3, 120, true, true, 128, 200, 30);
          store.publish(epoch, 3, 130, true, true, 255, 255, 30); // duplicate generation
          store.begin_capture(); // repeated begin cannot erase the current summary
          for (unsigned i = 0; i < 100; ++i) store.snapshot(140);
          store.publish(epoch, 4, 150, true, false, 0, 0, 30);
          // The production helper accepts byte-aligned S16 callback data.
          std::vector<uint8_t> unaligned(sizeof(pcm) + 2, 0);
          std::memcpy(unaligned.data() + 1, pcm, sizeof(pcm));
          store.record_selected_pcm(unaligned.data() + 1, sizeof(pcm) + 1);
          assert(store.finish_capture(summary));
          assert(summary.fresh_generations == 2);
          assert(std::abs(summary.probability_sum - 128 / 255.0f) < 0.00001);
          assert(summary.maximum_probability == 200 / 255.0f);
          assert(summary.selected_samples == 6 && summary.selected_rail_samples == 2);
          assert(!store.finish_capture(summary)); // at most one summary/capture
          store.record_selected_pcm(unaligned.data() + 1, sizeof(pcm));
          store.begin_capture();
          store.publish(epoch, 4, 200, true, true, 255, 255, 30); // no new Invoke
          assert(store.finish_capture(summary));
          assert(summary.fresh_generations == 0 && summary.probability_sum == 0);
          assert(summary.selected_samples == 0 && summary.selected_rail_samples == 0);
          // Measured zero differs from unavailable zero by the availability
          // counts used in the single production DEBUG summary.
          store.begin_capture();
          store.publish(epoch, 5, 230, true, false, 0, 0, 30);
          const int16_t quiet[] = {0, 0, 0};
          store.record_selected_pcm(reinterpret_cast<const uint8_t *>(quiet), sizeof(quiet));
          assert(store.finish_capture(summary));
          assert(summary.fresh_generations > 0 && summary.probability_sum == 0);
          assert(summary.maximum_probability == 0);
          assert(summary.selected_samples > 0 && summary.selected_rail_samples == 0);
        }
    ''')


def test_pcm_callback_crossing_capture_boundary_cannot_contaminate_next(tmp_path):
    _run_native(tmp_path, r'''
        // Pause the real helper just before its final PCM publication lock.
        struct BoundaryMutex {
          std::mutex mutex;
          static inline std::mutex gate;
          static inline std::condition_variable cv;
          static inline bool waiting = false, released = false;
          static inline thread_local bool intercept = false;
          static inline thread_local unsigned locks = 0;
          void lock() {
            if (intercept && ++locks == 2) {
              std::unique_lock<std::mutex> lock(gate);
              waiting = true;
              cv.notify_one();
              cv.wait(lock, [] { return released; });
            }
            mutex.lock();
          }
          void unlock() { mutex.unlock(); }
        };
        int main() {
          VADSnapshotStore<BoundaryMutex> store;
          store.begin_capture();
          std::thread callback([&] {
            BoundaryMutex::intercept = true;
            const int16_t pcm[] = {INT16_MIN, INT16_MAX};
            store.record_selected_pcm(reinterpret_cast<const uint8_t *>(pcm), sizeof(pcm));
          });
          {
            std::unique_lock<std::mutex> lock(BoundaryMutex::gate);
            BoundaryMutex::cv.wait(lock, [] { return BoundaryMutex::waiting; });
          }
          VADCaptureDiagnostics summary;
          assert(store.finish_capture(summary));
          assert(summary.selected_samples == 0);
          store.begin_capture();
          {
            std::lock_guard<std::mutex> lock(BoundaryMutex::gate);
            BoundaryMutex::released = true;
          }
          BoundaryMutex::cv.notify_one();
          callback.join();
          assert(store.finish_capture(summary));
          assert(summary.selected_samples == 0 && summary.selected_rail_samples == 0);
        }
    ''')


def test_production_window_math_fresh_true_and_fresh_false(tmp_path):
    _run_native(tmp_path, r'''
        int main() {
          constexpr uint8_t cutoff = 12;
          uint8_t probabilities[4] = {};
          StreamingInferenceProgress progress;
          VADSnapshotStore<std::mutex> store;
          const auto epoch = store.start();
          size_t slot = 0;
          uint32_t now = 0;
          auto invoke = [&](uint8_t probability) {
            probabilities[slot++ % 4] = probability;
            progress.invoked(true, 4);
            const auto result = summarize_vad_window(probabilities, 4, cutoff);
            store.publish(epoch, progress.generation(), now += 30, progress.full_window(4),
                          result.detected, result.average_probability, result.maximum_probability, 30);
          };
          for (unsigned i = 0; i < 3; ++i) {
            invoke(255);
            assert(!store.snapshot(now).valid); // high partial history cannot latch
          }
          invoke(255);
          auto snapshot = store.snapshot(now);
          assert(snapshot.valid && snapshot.detected);
          assert(snapshot.average_probability == 1.0f && snapshot.maximum_probability == 1.0f);
          for (unsigned i = 0; i < 3; ++i) {
            invoke(0);
            assert(store.snapshot(now).detected); // rolling threshold unchanged
          }
          invoke(0);
          snapshot = store.snapshot(now);
          assert(snapshot.valid && !snapshot.detected);
          assert(snapshot.average_probability == 0.0f && snapshot.maximum_probability == 0.0f);
          // Equality to the configured quantized cutoff remains NOT detected.
          for (auto &value : probabilities) value = cutoff;
          const auto equality = summarize_vad_window(probabilities, 4, cutoff);
          assert(!equality.detected && equality.average_probability == cutoff);
          probabilities[3] = cutoff + 1;
          const auto above = summarize_vad_window(probabilities, 4, cutoff);
          assert(above.detected && above.average_probability == cutoff);
          assert(above.maximum_probability == cutoff + 1);
        }
    ''')
