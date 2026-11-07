#!/usr/bin/env python3
"""Mutation gate for the update checker's decision logic.

Applies each mutant to a temporary export of a commit and runs the tests. In gate
mode a mutant passes only if every named test fails with an AssertionError, so a
mutant that dies by a crash in a mock does not count. Manual tool, not run in CI.

    venv/bin/python scripts/mutation/update_checker.py              # gate on HEAD
    venv/bin/python scripts/mutation/update_checker.py --baseline --ref <commit> --tests tests/unit
    venv/bin/python scripts/mutation/update_checker.py --only M3,M3t
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHECKER = "backend/updates/update_checker.py"
ADAPTER = "backend/updates/registry_adapter.py"
IMAGE_REF = "backend/utils/image_ref.py"

DECISION = "tests/unit/updates/test_update_decision.py::"
PROVENANCE = "tests/unit/updates/test_update_provenance.py::"
SOURCES = "tests/unit/updates/test_update_digest_sources.py::"
EVENTS = "tests/unit/updates/test_update_events.py::"
CONFIG = "tests/unit/updates/test_registry_config_fetch.py::"
TAGS = "tests/unit/updates/test_registry_tag_logic.py::"
STORAGE = "tests/unit/updates/test_update_storage_and_loop.py::"

DEFAULT_TESTS = ["tests/unit/updates"]
MUTANT_TIMEOUT_SECONDS = 900

OUTCOME_PLUGIN = """
import json, os
import pytest

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.failed:
        exception = call.excinfo.type.__name__ if call.excinfo else "unknown"
        with open(os.environ["MUTATION_OUTCOMES"], "a") as handle:
            handle.write(json.dumps({"nodeid": item.nodeid, "exception": exception}) + "\\n")
"""


@dataclass(frozen=True)
class Mutant:
    id: str
    path: str
    old: str
    new: str
    killers: tuple


M = Mutant
MUTANTS = [
    M("M1", CHECKER, "self._has_digest(container, latest_digest) or bool(", "False or bool(",
      (DECISION + "test_latest_index_digest_in_any_repo_digest_means_no_update",)),
    M("M1t", CHECKER, "self._has_digest(container, latest_digest) or bool(", "True or bool(",
      (DECISION + "test_index_and_child_missing_from_repo_digests_means_update",)),
    M("M2", CHECKER, "bool(platform_digest and self._has_digest(container, platform_digest))", "False",
      (DECISION + "test_platform_child_digest_in_repo_digests_means_no_update",)),
    M("M2t", CHECKER, "bool(platform_digest and self._has_digest(container, platform_digest))", "True",
      (DECISION + "test_index_and_child_missing_from_repo_digests_means_update",)),
    M("M3", CHECKER, "update_available = current_digest != latest_digest", "update_available = False",
      (DECISION + "test_different_digests_mean_update",)),
    M("M3t", CHECKER, "update_available = current_digest != latest_digest", "update_available = True",
      (DECISION + "test_fresh_image_without_local_record_reports_no_update",)),
    M("M4", CHECKER, 'current_digest = current_result["digest"]', "current_digest = None",
      (DECISION + "test_fallback_uses_registry_digest_of_current_tag",)),
    M("M5", CHECKER, "if current_ver and latest_ver and self._is_downgrade(current_ver, latest_ver):", "if False:",
      (DECISION + "test_older_latest_label_suppresses_update",
       DECISION + "test_frozen_floating_tag_suppresses_update")),
    M("M5b", CHECKER, "return latest_ver < current_ver", "return latest_ver <= current_ver",
      (DECISION + "test_same_label_new_digest_is_still_an_update",)),
    M("M6", CHECKER, "current_version = self._extract_version_from_tag(image)", "current_version = None",
      (DECISION + "test_versions_fall_back_to_tags",)),
    M("M7", CHECKER, "latest_version = self._extract_version_from_tag(floating_tag)", "latest_version = None",
      (DECISION + "test_versions_fall_back_to_tags",)),
    M("M8", CHECKER, "current_version = await self._get_container_image_version(container)", "current_version = None",
      (DECISION + "test_current_version_comes_from_container_label",)),
    M("M9", CHECKER, "if not bypass_cache:", "if True:",
      (DECISION + "test_bypass_cache_skips_db_cache",)),
    M("M10a", CHECKER, "# First time checking this container - emit event\n            should_emit_event = True",
      "should_emit_event = False",
      (EVENTS + "test_first_check_emits_event",)),
    M("M10b", CHECKER, "# Digest changed (new update available) - emit event\n            should_emit_event = True",
      "should_emit_event = False",
      (EVENTS + "test_changed_latest_digest_emits_event",)),
    M("M10c", CHECKER, "should_emit_event = False\n\n        if previous_digest is None:",
      "should_emit_event = True\n\n        if previous_digest is None:",
      (EVENTS + "test_repeated_latest_digest_emits_nothing",)),
    M("M11", CHECKER, "if repo_digests and isinstance(repo_digests, list) and len(repo_digests) > 0:", "if False:",
      (SOURCES + "test_agent_repo_digests_take_priority_over_docker",)),
    M("M12", ADAPTER, "config = await response.json(content_type=None)", "config = await response.json()",
      (CONFIG + "test_single_manifest_octet_stream_config_blob_yields_labels",)),
    M("M13", ADAPTER, "config = await blob_response.json(content_type=None)", "config = await blob_response.json()",
      (CONFIG + "test_index_traverses_to_platform_manifest_and_blob",)),
    M("M14", ADAPTER,
      "return await self._fetch_config_from_manifest_list(\n"
      "                    registry, repository, manifest, token, platform\n"
      "                )",
      "return None, None",
      (CONFIG + "test_index_traverses_to_platform_manifest_and_blob",)),
    M("M15", ADAPTER,
      "config_data, config_digest = await self._fetch_config_blob(\n"
      "                    registry, repository, manifest, token, platform\n"
      "                )",
      "config_data, config_digest = None, None",
      (CONFIG + "test_single_manifest_octet_stream_config_blob_yields_labels",)),
    M("M16", ADAPTER, 'if mode == "exact":', "if True:",
      (TAGS + "test_floating_tag_table",
       DECISION + "test_tracking_mode_from_record_selects_floating_tag")),
    M("M17", CHECKER, "latest_result = await self.registry.resolve_tag(floating_tag, platform=platform, auth=auth)",
      "latest_result = await self.registry.resolve_tag(floating_tag, platform=platform, auth=None)",
      (DECISION + "test_credentials_reach_both_registry_calls",)),
    M("M17b", CHECKER, "current_result = await self.registry.resolve_tag(current_image, platform=platform, auth=auth)",
      "current_result = await self.registry.resolve_tag(current_image, platform=platform, auth=None)",
      (DECISION + "test_credentials_reach_both_registry_calls",)),
    M("M18", CHECKER, "if skip_compose and self._is_compose_container(container):", "if False:",
      (STORAGE + "test_loop_skips_compose_containers_when_configured",)),
    M("M19a", CHECKER, 'update_available=update_info["update_available"],', "update_available=False,",
      (STORAGE + "test_store_creates_record_with_every_field",)),
    M("M19b", CHECKER, '\n                record.update_available = update_info["update_available"]',
      "\n                record.update_available = record.update_available",
      (STORAGE + "test_store_updates_existing_record_and_keeps_tracking_mode",)),
    M("M19c", CHECKER, '\n                    record.update_available = update_info["update_available"]',
      "\n                    record.update_available = record.update_available",
      (STORAGE + "test_store_retry_updates_concurrently_inserted_row",)),
    M("M20", CHECKER,
      'if update_info["update_available"]:\n                logger.info(f"Update available for {container[\'name\']}")',
      'if True:\n                logger.info(f"Update available for {container[\'name\']}")',
      (STORAGE + "test_single_check_without_update_stores_and_emits_nothing",)),
    M("M21", CHECKER, 'if update_info["update_available"]:\n                        stats["updates_found"] += 1',
      'if True:\n                        stats["updates_found"] += 1',
      (STORAGE + "test_loop_without_update_stores_and_emits_nothing",)),
    M("M32", CHECKER, "elif current_digest_from_registry and config_digest and stored_evidence == evidence:",
      "elif current_digest_from_registry and config_digest:",
      (PROVENANCE + "test_local_build_never_matched_is_left_alone",
       PROVENANCE + "test_container_recreated_on_a_new_local_build_is_left_alone",
       PROVENANCE + "test_evidence_for_another_reference_does_not_count",
       PROVENANCE + "test_evidence_for_another_platform_does_not_count")),
    M("M33", CHECKER, "elif current_digest_from_registry and config_digest and stored_evidence == evidence:",
      "elif current_digest_from_registry and stored_evidence == evidence:",
      (PROVENANCE + "test_no_usable_config_digest_means_no_stale",)),
    M("M34", CHECKER, "elif current_digest_from_registry and config_digest and stored_evidence == evidence:",
      "elif False:",
      (PROVENANCE + "test_stale_when_registry_moved_after_a_match_and_record_is_gone",
       STORAGE + "test_stale_running_image_end_to_end")),
    M("M35", CHECKER, "                current_digest = running.image_id\n", "",
      (PROVENANCE + "test_stale_when_registry_moved_after_a_match_and_record_is_gone",)),
    M("M36", CHECKER, "if running and running.image_id and platform_verified:", "if running and running.image_id:",
      (PROVENANCE + "test_no_evidence_written_without_a_verified_platform",)),
    M("M37", CHECKER, "registry_digests = {latest_digest, platform_digest, config_digest}",
      "registry_digests = {platform_digest, config_digest}",
      (PROVENANCE + "test_any_digest_match_means_current",)),
    M("M38", CHECKER, "registry_digests = {latest_digest, platform_digest, config_digest}",
      "registry_digests = {latest_digest, config_digest}",
      (PROVENANCE + "test_any_digest_match_means_current",)),
    M("M39", CHECKER, "registry_digests = {latest_digest, platform_digest, config_digest}",
      "registry_digests = {latest_digest, platform_digest}",
      (PROVENANCE + "test_any_digest_match_means_current",)),
    M("M40", CHECKER, "and SHA256_DIGEST.fullmatch(config_digest)", "",
      (PROVENANCE + "test_no_usable_config_digest_means_no_stale",)),
    M("M41", CHECKER, "current_result = await self.registry.resolve_tag(current_image, platform=platform, auth=auth)",
      "current_result = await self.registry.resolve_tag(current_image, auth=auth)",
      (PROVENANCE + "test_platform_comes_from_the_image",)),
    M("M42", CHECKER, "latest_result = await self.registry.resolve_tag(floating_tag, platform=platform, auth=auth)",
      "latest_result = await self.registry.resolve_tag(floating_tag, auth=auth)",
      (PROVENANCE + "test_platform_comes_from_the_image",)),
    M("M50", CHECKER, '"ref": floating_tag}', '"ref": image}',
      (PROVENANCE + "test_evidence_written_with_a_tag_still_counts_for_the_untagged_name",
       PROVENANCE + "test_evidence_names_the_tag_that_was_compared")),
    M("M51", CHECKER, """            if running.image_id in registry_digests:
                update_available = False
""", "",
      (PROVENANCE + "test_image_id_match_clears_an_update_when_only_the_index_changed",)),
    M("M52", CHECKER, '(attrs.get("Config") or {}).get("Labels")', 'attrs.get("Config", {}).get("Labels")',
      (PROVENANCE + "test_image_with_null_config_keeps_its_repo_digests",)),
    M("M43", CHECKER, "            and not running.record_exists\n", "",
      (PROVENANCE + "test_non_linux_images_are_never_stale",)),
    M("M44", CHECKER, '''                if update_info.get("verified_image"):
                    record.verified_image = update_info["verified_image"]
                record.check_status = None''', "                record.check_status = None",
      (STORAGE + "test_store_update_sets_verified_image",)),
    M("M45", CHECKER, '''                    if update_info.get("verified_image"):
                        record.verified_image = update_info["verified_image"]
''', "",
      (STORAGE + "test_store_retry_sets_verified_image",)),
    M("M46", CHECKER, 'verified_image=update_info.get("verified_image"),', "verified_image=None,",
      (STORAGE + "test_store_create_sets_verified_image",)),
    M("M47", ADAPTER, '''logger.warning(f"Failed to fetch config blob: {response.status}")
                        return None, config_digest''', '''logger.warning(f"Failed to fetch config blob: {response.status}")
                        return None, None''',
      (CONFIG + "test_config_digest_kept_when_the_single_manifest_blob_fails",)),
    M("M48", ADAPTER, '''logger.warning(f"Failed to fetch config blob: {blob_response.status}")
                                return None, config_digest''', '''logger.warning(f"Failed to fetch config blob: {blob_response.status}")
                                return None, None''',
      (CONFIG + "test_config_digest_kept_when_the_index_child_blob_fails",)),
    M("M49", ADAPTER, '"config_digest": config_digest,', '"config_digest": None,',
      (CONFIG + "test_config_digest_reported_for_a_single_manifest",
       CONFIG + "test_config_digest_reported_for_an_index")),
    M("M22", CHECKER,
      "container_id=composite_key\n            ).first()\n\n            if record:\n"
      "                return record.floating_tag_mode",
      'container_id=composite_key.split(":")[1]\n            ).first()\n\n            if record:\n'
      "                return record.floating_tag_mode",
      (STORAGE + "test_stored_tracking_mode_is_read_by_composite_key",)),
    M("M23", IMAGE_REF, 'return image_ref.rfind(":") > image_ref.rfind("/")', 'return ":" in image_ref',
      (TAGS + "test_floating_tag_table",
       CONFIG + "test_credentials_stay_on_any_other_registry",
       DECISION + "test_untagged_registry_with_port_stays_on_its_own_registry")),
    M("M24", ADAPTER, "return _canonical_registry_host(registry) in DOCKER_HUB_HOSTS",
      'return "docker.io" in _canonical_registry_host(registry)',
      (CONFIG + "test_credentials_stay_on_any_other_registry",)),
    M("M25", ADAPTER, 'return _canonical_registry_host(registry) == "ghcr.io"',
      'return "ghcr.io" in _canonical_registry_host(registry)',
      (CONFIG + "test_credentials_stay_on_any_other_registry",)),
    M("M26", ADAPTER, 'return host.removesuffix(":443")', "return host",
      (CONFIG + "test_docker_hub_credentials_go_only_to_docker_hub",)),
    M("M27", ADAPTER, 'host = registry.lower().split("://", 1)[-1].rstrip("/")',
      'host = registry.split("://", 1)[-1].rstrip("/")',
      (CONFIG + "test_docker_hub_credentials_go_only_to_docker_hub",)),
    M("M28", IMAGE_REF, ' or segment == "localhost"', "",
      (TAGS + "test_parse_image_ref",
       CONFIG + "test_credentials_stay_on_any_other_registry")),
    M("M31", IMAGE_REF, " or segment.lower() != segment", "",
      (TAGS + "test_parse_image_ref",)),
    M("M29", CHECKER, 'elif "/" in tag:\n            return None', 'elif "/" in tag:\n            tag = tag.rsplit(":", 1)[-1]',
      (DECISION + "test_registry_port_is_not_read_as_a_version",)),
    M("M30", ADAPTER, 'if _is_docker_hub(registry) and "/" not in repository:', 'if registry == "docker.io" and "/" not in repository:',
      (TAGS + "test_parse_image_ref",)),
]


def cap_prefix():
    scope = ["systemd-run"]
    if os.environ.get("XDG_RUNTIME_DIR"):
        scope.append("--user")
    return scope + ["--scope", "-q", "-p", "MemoryMax=4G", "-p", "MemorySwapMax=0"]


def export_commit(ref, destination):
    archive = subprocess.run(["git", "-C", str(REPO), "archive", ref, "backend", "scripts"],
                             check=True, capture_output=True)
    subprocess.run(["tar", "-x", "-C", str(destination)], input=archive.stdout, check=True)


def check_anchors(tree, mutants):
    problems = []
    for mutant in mutants:
        count = (tree / mutant.path).read_text().count(mutant.old)
        if count != 1:
            problems.append(f"{mutant.id}: expected 1 match in {mutant.path}, found {count}: {mutant.old!r}")
    return problems


def run_tests(tree, plugin_dir, outcomes, tests):
    outcomes.write_text("")
    env = dict(os.environ, PYTHONPATH=str(plugin_dir), PYTHONDONTWRITEBYTECODE="1", MUTATION_OUTCOMES=str(outcomes))
    command = cap_prefix() + [sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=no",
                              "-p", "no:cacheprovider", "-p", "mutation_outcomes", *tests]
    try:
        result = subprocess.run(command, cwd=tree / "backend", env=env, capture_output=True, text=True,
                                timeout=MUTANT_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None, []
    failures = [json.loads(line) for line in outcomes.read_text().splitlines()]
    return result, failures


def judge(mutant, failures, baseline):
    if not failures:
        return "SURVIVED"
    if baseline:
        return "KILLED" if any(f["exception"] == "AssertionError" for f in failures) else "CRASH-ONLY"
    for killer in mutant.killers:
        named = [f for f in failures if f["nodeid"] == killer or f["nodeid"].startswith(killer + "[")]
        if not named or any(f["exception"] != "AssertionError" for f in named):
            return "WRONG-KILLER"
    return "KILLED"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ref", default="HEAD", help="commit to export")
    parser.add_argument("--baseline", action="store_true", help="report survivors, without requiring the named tests")
    parser.add_argument("--tests", nargs="+", default=DEFAULT_TESTS, help="pytest paths, relative to backend/")
    parser.add_argument("--only", help="comma-separated mutant ids")
    args = parser.parse_args()

    mutants = MUTANTS
    if args.only:
        wanted = set(args.only.split(","))
        unknown = wanted - {mutant.id for mutant in MUTANTS}
        if unknown:
            print(f"Unknown mutant ids: {', '.join(sorted(unknown))}")
            return 2
        mutants = [mutant for mutant in MUTANTS if mutant.id in wanted]

    work = Path(tempfile.mkdtemp(prefix="dockmon-mutation-"))
    try:
        tree = work / "tree"
        tree.mkdir()
        export_commit(args.ref, tree)
        (work / "mutation_outcomes.py").write_text(OUTCOME_PLUGIN)
        outcomes = work / "outcomes.jsonl"

        problems = check_anchors(tree, mutants)
        if problems:
            print("Mutant anchors no longer match, update the mutant list:", *problems, sep="\n  ")
            return 2

        result, failures = run_tests(tree, work, outcomes, args.tests)
        if result is None or result.returncode != 0:
            print("Unmutated tests do not pass:", *(f["nodeid"] for f in failures), sep="\n  ")
            print(result.stdout[-2000:] if result else "timed out")
            return 2
        print(f"unmutated: {result.stdout.strip().splitlines()[-1]}", flush=True)

        passed = True
        for mutant in mutants:
            source = tree / mutant.path
            original = source.read_text()
            source.write_text(original.replace(mutant.old, mutant.new))
            result, failures = run_tests(tree, work, outcomes, args.tests)
            source.write_text(original)

            if result is None:
                verdict = "TIMEOUT"
            elif result.returncode != 0 and not failures:
                # Collection errors and an OOM kill record no test failure; that is not a survivor.
                verdict = "NO-RESULT"
            else:
                verdict = judge(mutant, failures, args.baseline)
            passed = passed and verdict == "KILLED"
            kinds = sorted({f["exception"] for f in failures})
            print(f"{mutant.id:<5} {verdict:<13} failures={len(failures):<4} {','.join(kinds)}", flush=True)
            if verdict == "WRONG-KILLER":
                for failure in failures[:8]:
                    print(f"        {failure['exception']}: {failure['nodeid']}", flush=True)
        return 0 if passed or args.baseline else 1
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
