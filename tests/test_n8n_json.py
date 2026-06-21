from __future__ import annotations

import glob
import json
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
# Mirror the scripts-on-path pattern used by the other tests (e.g. test_clean_leads).
sys.path.insert(0, str(ROOT / "scripts"))

WORKFLOW_GLOB = str(ROOT / "n8n-workflows" / "*.json")


def _discover_workflow_paths() -> list[str]:
    # Spec §3 case 10: discover every n8n-workflows/*.json via glob.
    return sorted(glob.glob(WORKFLOW_GLOB))


class N8nJsonTests(unittest.TestCase):
    # --- Case 10: every n8n workflow is valid JSON with nodes + connections

    def test_discovers_at_least_one_workflow_file(self):
        # Guard: if the glob finds nothing (e.g. files were deleted) the per-file
        # assertions below would vacuously pass, so assert we actually found files.
        paths = _discover_workflow_paths()
        self.assertTrue(paths, f"No n8n workflow JSON found under {WORKFLOW_GLOB}")

    def test_each_workflow_parses_and_has_nodes_and_connections(self):
        # Spec §4 acceptance: each workflow MUST pass json.loads and expose a
        # non-empty "nodes" list plus a "connections" object.
        paths = _discover_workflow_paths()
        self.assertTrue(paths, f"No n8n workflow JSON found under {WORKFLOW_GLOB}")

        for path in paths:
            with self.subTest(workflow=Path(path).name):
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read()

                # Must be strictly valid JSON (mirrors `python3 -m json.tool`).
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError as exc:
                    self.fail(f"{path} is not valid JSON: {exc}")

                # n8n exports the workflow as a single JSON object.
                self.assertIsInstance(
                    data,
                    dict,
                    f"{path}: top-level JSON must be an object, got {type(data).__name__}",
                )

                # nodes must be present and non-empty.
                self.assertIn(
                    "nodes",
                    data,
                    f"{path}: missing top-level 'nodes' key",
                )
                self.assertIsInstance(
                    data["nodes"],
                    list,
                    f"{path}: 'nodes' must be a list, got {type(data['nodes']).__name__}",
                )
                self.assertTrue(
                    data["nodes"],
                    f"{path}: 'nodes' list must not be empty",
                )

                # connections must be present (may be {} for a single-node workflow,
                # but the key must exist per the n8n export contract).
                self.assertIn(
                    "connections",
                    data,
                    f"{path}: missing top-level 'connections' key",
                )
                self.assertIsInstance(
                    data["connections"],
                    dict,
                    f"{path}: 'connections' must be an object, got {type(data['connections']).__name__}",
                )

    def test_each_workflow_node_has_name_and_type(self):
        # Lightweight structural sanity: every node entry should at least carry a
        # name and type so downstream connections can reference it. This catches
        # half-authored node objects without over-constraining n8n's schema.
        paths = _discover_workflow_paths()
        self.assertTrue(paths, f"No n8n workflow JSON found under {WORKFLOW_GLOB}")

        for path in paths:
            with self.subTest(workflow=Path(path).name):
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for idx, node in enumerate(data["nodes"]):
                    with self.subTest(node_index=idx):
                        self.assertIsInstance(
                            node,
                            dict,
                            f"{path}: node[{idx}] must be an object",
                        )
                        self.assertIn(
                            "name",
                            node,
                            f"{path}: node[{idx}] missing 'name'",
                        )
                        self.assertIn(
                            "type",
                            node,
                            f"{path}: node[{idx}] missing 'type'",
                        )


if __name__ == "__main__":
    unittest.main()
