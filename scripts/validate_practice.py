"""Validate official MineDojo practice output before CI reports success.

Why this exists: the previous inline CI check only looped over whatever
``world-*/result.json`` files happened to exist. With no result file, or a
result document with an empty ``episodes`` list, the loop body never ran and
the step exited 0, so a broken/empty practice run was reported as passed.

Official result contract (verified against the downloaded developer package,
not guessed):

* ``practice.py`` writes ``<output>/world-*/result.json`` as
  ``{"episodes": [...], "summary": aggregate(episodes)}``.
* Each episode is built by ``evaluation_adapters/pdf_runner.py`` ``outcome()``
  with ``scenario``, ``status``, ``termination``, ``scoring``, ``metrics``,
  ``objectives``, ``api``, ``scored`` and ``note``.
* A tutorial (woodcraft) world succeeds with ``status == "completed"``,
  ``termination == "tutorial_goals"`` and ``metrics.task_success is True``.

The validator needs no MineDojo, Docker, network access or API key, so it can
be unit tested offline. Exit code 0 means: at least one result file, at least
one episode, and every episode is a completed woodcraft tutorial success.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RESULT_GLOB = "world-*/result.json"


def _episode_errors(path, index, episode):
    where = f"{path} episodes[{index}]"
    if not isinstance(episode, dict):
        return [f"{where} is not a JSON object"]
    errors = []
    status = episode.get("status")
    if status != "completed":
        errors.append(f"{where}.status is {status!r}, expected 'completed'")
    termination = episode.get("termination")
    if termination != "tutorial_goals":
        errors.append(f"{where}.termination is {termination!r}, expected 'tutorial_goals'")
    metrics = episode.get("metrics")
    if not isinstance(metrics, dict):
        errors.append(f"{where}.metrics is missing or not a JSON object")
    elif metrics.get("task_success") is not True:
        errors.append(
            f"{where}.metrics.task_success is {metrics.get('task_success')!r}, expected true")
    return errors


def validate_directory(output):
    """Return a list of human-readable problems; an empty list means valid."""
    output = Path(output)
    if not output.is_dir():
        return [f"practice output directory not found: {output}"]
    results = sorted(output.glob(RESULT_GLOB))
    if not results:
        return [f"no practice result files matching {RESULT_GLOB} under {output}"]
    errors = []
    for path in results:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            errors.append(f"{path} cannot be read as JSON: {error}")
            continue
        if not isinstance(document, dict):
            errors.append(f"{path} is not a JSON object")
            continue
        episodes = document.get("episodes")
        if not isinstance(episodes, list) or not episodes:
            errors.append(f"{path} must contain a non-empty 'episodes' list")
            continue
        if not isinstance(document.get("summary"), dict):
            errors.append(f"{path} must contain a 'summary' JSON object")
        for index, episode in enumerate(episodes):
            errors.extend(_episode_errors(path, index, episode))
    return errors


def _print_results(output):
    """Print the official summary/episode fields for the CI log."""
    results = sorted(Path(output).glob(RESULT_GLOB))
    episode_count = 0
    for path in results:
        document = json.loads(path.read_text(encoding="utf-8"))
        episodes = document["episodes"]
        episode_count += len(episodes)
        print("PRACTICE_SUMMARY", json.dumps(document.get("summary"), ensure_ascii=False))
        for episode in episodes:
            scenario = episode.get("scenario")
            print("PRACTICE_EPISODE", json.dumps({
                "result": path.as_posix(),
                "scenario_id": scenario.get("id") if isinstance(scenario, dict) else None,
                "status": episode.get("status"),
                "termination": episode.get("termination"),
                "task_success": episode.get("metrics", {}).get("task_success"),
            }, ensure_ascii=False))
    return len(results), episode_count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("practice-output"),
                        help="directory containing the official world-*/result.json files")
    args = parser.parse_args(argv)
    errors = validate_directory(args.output)
    if errors:
        for error in errors:
            print(f"PRACTICE_VALIDATION_ERROR: {error}", file=sys.stderr)
        print(f"PRACTICE_VALIDATION_FAILED errors={len(errors)}", file=sys.stderr)
        return 1
    results, episodes = _print_results(args.output)
    print(f"PRACTICE_VALIDATION_OK results={results} episodes={episodes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
