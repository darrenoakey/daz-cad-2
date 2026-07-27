#!/usr/bin/env python3
# ##################################################################
# performance test runner
# runs browser-based opencascade performance tests and captures results

import json
import subprocess
import time
import sys
import socket
from playwright.sync_api import sync_playwright


# ##################################################################
# run performance tests
# launches browser, runs perf tests, returns JSON results
def run_perf_tests():
    # check if server already running
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_running = sock.connect_ex(('127.0.0.1', 8766)) == 0
    sock.close()

    server = None
    if not server_running:
        print("Starting server...")
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "src.server:app", "--host", "127.0.0.1", "--port", "8766"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(5)  # wait for server to start
    else:
        print("Server already running on port 8766")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(600000)  # 10 min timeout

            # capture console messages
            page.on("console", lambda msg: print(f"[Browser] {msg.text}"))

            # navigate to perf test page
            print("Loading perf test page...")
            page.goto("http://localhost:8766/perf-test", timeout=120000)

            # wait for OpenCascade to load - check status text
            print("Waiting for OpenCascade to initialize...")
            for _ in range(120):  # 6 minutes max
                status = page.evaluate("document.getElementById('status').textContent")
                print(f"  Status: {status}")
                if "ready" in status.lower():
                    break
                time.sleep(3)

            print("OpenCascade loaded, running benchmark...")

            # click run benchmark button
            page.click("#run-benchmark")

            # wait for benchmark to complete - check for "Benchmark Complete"
            print("Running benchmark (this may take several minutes)...")
            page.wait_for_function(
                """() => {
                    const results = document.getElementById('results').innerHTML;
                    return results.includes('Benchmark Complete');
                }""",
                timeout=600000  # 10 minutes for all tests
            )

            print("Benchmark complete, extracting results...")

            # get JSON results
            results_json = page.evaluate("JSON.stringify(window.results || {}, null, 2)")

            browser.close()

            return json.loads(results_json)

    finally:
        if server is not None:
            server.terminate()
            server.wait()


# ##################################################################
# format results
# prints results in a readable table format
def format_results(results):
    print("\n" + "=" * 80)
    print("OPENCASCADE PATTERN CUTTING BENCHMARK RESULTS")
    print("=" * 80)

    if "testConfig" in results:
        config = results["testConfig"]
        print("\nConfiguration:")
        print(f"  Base: {config.get('baseSize', '?')}x{config.get('baseSize', '?')/2}x{config.get('baseThickness', '?')}mm")
        print(f"  Hex size: {config.get('hexSize', '?'):.2f}mm")
        print(f"  Wall thickness: {config.get('wallThickness', '?')}mm")
        print(f"  Number of holes: {config.get('holeCount', '?')}")

    if "techniques" in results:
        print(f"\n{'Technique':<50} {'Time (ms)':>12} {'Notes':>20}")
        print("-" * 85)

        for name, data in results["techniques"].items():
            if isinstance(data, dict):
                if data.get("skipped"):
                    print(f"{name:<50} {'SKIPPED':>12} {data.get('reason', '')[:20]:>20}")
                elif data.get("error"):
                    print(f"{name:<50} {'ERROR':>12} {data.get('error', '')[:20]:>20}")
                else:
                    time_ms = data.get("time_ms", 0)
                    print(f"{name:<50} {time_ms:>12.0f}")

    if "summary" in results:
        print("\n" + "-" * 85)
        print("RANKED BY SPEED:")
        print("-" * 85)
        for i, item in enumerate(results["summary"], 1):
            name = item["name"]
            time_ms = item["time_ms"]
            ratio = time_ms / results["summary"][0]["time_ms"] if results["summary"] else 1
            marker = " <<< WINNER" if i == 1 else ""
            print(f"  {i}. {name:<45} {time_ms:>8.0f}ms ({ratio:.1f}x){marker}")

    print("\n" + "=" * 80)


# ##################################################################
# main
# entry point for performance test runner
def main():
    print("Starting performance benchmark...")
    results = run_perf_tests()
    format_results(results)

    # save raw JSON
    output_path = "output/testing/perf_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nRaw JSON saved to: {output_path}")

    return results


# ##################################################################
# entry point
if __name__ == "__main__":
    main()
