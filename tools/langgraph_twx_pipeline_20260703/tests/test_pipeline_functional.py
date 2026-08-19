from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import sys

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from extractor import parse_manifest, parse_xml_artifacts_recursive  # noqa: E402
from graph_builder import build_execution_graph  # noqa: E402
from functional_model_builder import build_functional_model  # noqa: E402
from html_fallback import render_html  # noqa: E402


ROOT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<teamworks>
  <bpd id="25.root-proc" name="Proceso Principal">
    <BusinessProcessDiagram id="diag-main">
      <flow id="f1" connectionType="SequenceFlow"><connection><condition id="c1"/></connection></flow>
      <flow id="f2" connectionType="SequenceFlow"><connection><condition id="c2"><expression>tw.local.route == 1</expression></condition></connection></flow>
      <flow id="f3" connectionType="SequenceFlow"><connection><condition id="c3"/></connection></flow>
      <flow id="f4" connectionType="SequenceFlow"><connection><condition id="c4"/></connection></flow>
      <flow id="f5" connectionType="SequenceFlow"><connection><condition id="c5"/></connection></flow>
      <flow id="f6" connectionType="SequenceFlow"><connection><condition id="c6"/></connection></flow>
      <flow id="f7" connectionType="SequenceFlow"><connection><condition id="c7"/></connection></flow>
      <flow id="f8" connectionType="SequenceFlow"><connection><condition id="c8"/></connection></flow>
      <flow id="f9" connectionType="SequenceFlow"><connection><condition id="c9"/></connection></flow>
      <flow id="f10" connectionType="SequenceFlow"><connection><condition id="c10"><expression>tw.local.route != 1</expression></condition></connection></flow>

      <flowObject id="n-start" componentType="Activity">
        <name>Inicio</name>
        <component>
          <implementationType>3</implementationType>
          <implementation><script>tw.local.route=1; tw.local.stateId=100;</script></implementation>
        </component>
        <outputPort><flow ref="f1"/></outputPort>
      </flowObject>

      <flowObject id="n-gw-alt" componentType="Gateway">
        <name>Decision Ruta</name>
        <component><gatewayType>1</gatewayType><splitJoinType>0</splitJoinType></component>
        <inputPort><flow ref="f1"/></inputPort>
        <inputPort><flow ref="f3"/></inputPort>
        <outputPort><flow ref="f2"/></outputPort>
        <outputPort><flow ref="f10"/></outputPort>
      </flowObject>

      <flowObject id="n-user" componentType="Activity">
        <name>Confirmar</name>
        <component>
          <implementationType>1</implementationType>
          <implementation>
            <attachedActivityId>/1.user-coach</attachedActivityId>
            <script>
              tw.local.action=2;
              var x="{&quot;VisibilityRules&quot;:{&quot;rules&quot;:[{&quot;var&quot;:&quot;tw.local.ready&quot;,&quot;operand&quot;:&quot;true&quot;,&quot;action&quot;:&quot;DISABLE&quot;}]}}";
            </script>
          </implementation>
        </component>
        <inputPort><flow ref="f2"/></inputPort>
        <outputPort><flow ref="f4"/></outputPort>
      </flowObject>

      <flowObject id="n-call" componentType="Activity">
        <name>Llamar Subproceso</name>
        <component>
          <implementationType>2</implementationType>
          <implementation>
            <attachedProcessId>/25.child-proc</attachedProcessId>
            <inputProcessParameterMapping><name>entrada</name><value>tw.local.action</value></inputProcessParameterMapping>
            <outputProcessParameterMapping><name>salida</name><value>tw.local.childResult</value></outputProcessParameterMapping>
          </implementation>
        </component>
        <inputPort><flow ref="f4"/></inputPort>
        <outputPort><flow ref="f5"/></outputPort>
      </flowObject>

      <flowObject id="n-gw-par" componentType="Gateway">
        <name>Fork paralelo</name>
        <component><gatewayType>0</gatewayType><splitJoinType>0</splitJoinType></component>
        <inputPort><flow ref="f5"/></inputPort>
        <outputPort><flow ref="f6"/></outputPort>
        <outputPort><flow ref="f7"/></outputPort>
      </flowObject>

      <flowObject id="n-a" componentType="Activity">
        <name>Servicio A</name>
        <component><implementationType>2</implementationType><implementation><script>tw.local.flag=true;</script></implementation></component>
        <inputPort><flow ref="f6"/></inputPort>
        <outputPort><flow ref="f8"/></outputPort>
      </flowObject>

      <flowObject id="n-b" componentType="Activity">
        <name>Servicio B</name>
        <component><implementationType>2</implementationType><implementation><script>if(tw.local.flag){tw.local.retry=1;}</script></implementation></component>
        <inputPort><flow ref="f7"/></inputPort>
        <inputPort><flow ref="f10"/></inputPort>
        <outputPort><flow ref="f9"/></outputPort>
      </flowObject>

      <flowObject id="n-loop-gw" componentType="Gateway">
        <name>Loop GW</name>
        <component><gatewayType>1</gatewayType><splitJoinType>0</splitJoinType></component>
        <inputPort><flow ref="f9"/></inputPort>
        <outputPort><flow ref="f3"/></outputPort>
      </flowObject>

      <flowObject id="n-end" componentType="Event">
        <name>Fin</name>
        <component><eventType>2</eventType></component>
        <inputPort><flow ref="f8"/></inputPort>
      </flowObject>
    </BusinessProcessDiagram>
  </bpd>
</teamworks>
"""


CHILD_XML = """<?xml version="1.0" encoding="UTF-8"?>
<teamworks>
  <bpd id="25.child-proc" name="Subproceso Hijo">
    <BusinessProcessDiagram id="diag-child">
      <flow id="cf1" connectionType="SequenceFlow"><connection><condition id="cc1"/></connection></flow>
      <flow id="cf2" connectionType="SequenceFlow"><connection><condition id="cc2"><expression>tw.local.childResult == 999</expression></condition></connection></flow>
      <flowObject id="c-start" componentType="Activity">
        <name>Child Start</name>
        <component>
          <implementationType>3</implementationType>
          <implementation><script>tw.local.childResult=999;</script></implementation>
        </component>
        <outputPort><flow ref="cf1"/></outputPort>
      </flowObject>
      <flowObject id="c-user" componentType="Activity">
        <name>Aprobar</name>
        <component>
          <implementationType>1</implementationType>
          <implementation>
            <attachedActivityId>/1.child-coach</attachedActivityId>
            <script>
              tw.local.salida=100;
              var y="{&amp;quot;VisibilityRules&amp;quot;:{&amp;quot;rules&amp;quot;:[{&amp;quot;var&amp;quot;:&amp;quot;tw.local.childResult&amp;quot;,&amp;quot;operand&amp;quot;:&amp;quot;999&amp;quot;,&amp;quot;action&amp;quot;:&amp;quot;SHOW&amp;quot;}]}}";
            </script>
          </implementation>
        </component>
        <inputPort><flow ref="cf1"/></inputPort>
        <outputPort><flow ref="cf2"/></outputPort>
      </flowObject>
      <flowObject id="c-end" componentType="Event">
        <name>Child End</name>
        <component><eventType>2</eventType></component>
        <inputPort><flow ref="cf2"/></inputPort>
      </flowObject>
    </BusinessProcessDiagram>
  </bpd>
</teamworks>
"""


MANIFEST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <name>Proceso Principal</name>
  <environmentVariable>
    <name>ID_SUBETAPA_X</name>
    <defaultValue>200</defaultValue>
  </environmentVariable>
</manifest>
"""


class PipelineFunctionalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="twx_test_")
        base = Path(self.tmp.name)
        (base / "manifest.xml").write_text(MANIFEST_XML, encoding="utf-8")
        objects = base / "objects"
        objects.mkdir(parents=True, exist_ok=True)
        (objects / "25.root-proc.xml").write_text(ROOT_XML, encoding="utf-8")
        (objects / "25.child-proc.xml").write_text(CHILD_XML, encoding="utf-8")
        self.base = base

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_extractor_parses_process_model(self) -> None:
        manifest, mw = parse_manifest(str(self.base))
        self.assertEqual(mw, [])
        self.assertEqual(manifest.get("process_name"), "Proceso Principal")
        artifacts, aw = parse_xml_artifacts_recursive(str(self.base))
        self.assertEqual(aw, [])
        root = artifacts["25.root-proc"]
        self.assertEqual(root["artifact_type"], "process")
        pm = root["process_model"]
        self.assertTrue(pm["nodes"])
        self.assertTrue(pm["flows"])
        call_nodes = [n for n in pm["nodes"] if n.get("attached_process_id")]
        self.assertEqual(len(call_nodes), 1)
        self.assertEqual(call_nodes[0]["attached_process_id"], "25.child-proc")
        self.assertTrue(call_nodes[0]["mappings"])
        # condition_ref -> condition_expression resuelto desde flow XML
        f2 = next(x for x in pm["flows"] if x["flow_id"] == "f2")
        self.assertEqual(f2.get("condition_expression"), "tw.local.route == 1")

    def test_graph_builder_creates_cfg_and_call_graph(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        self.assertFalse(warnings)
        self.assertEqual(root_id, "25.root-proc")
        self.assertTrue(nodes)
        self.assertTrue(edges)
        self.assertTrue(call_graph["edges"])
        self.assertIn("25.root-proc", cfgs)
        self.assertIn("nodes", technical_graph)
        self.assertIsInstance(unresolved, list)

    def test_functional_model_contains_context_lineage_and_decisions(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        state = {
            "manifest": manifest,
            "artifacts": artifacts,
            "graph_nodes": nodes,
            "graph_edges": edges,
            "root_id": root_id,
            "technical_graph": technical_graph,
            "call_graph": call_graph,
            "control_flow_graphs": cfgs,
            "unresolved_references": unresolved,
            "warnings": warnings,
        }
        fm = build_functional_model(state)
        self.assertTrue(fm["functional_stages"])
        self.assertTrue(fm["transitions"])
        self.assertTrue(fm["traversal_traces"])
        self.assertIn("nodes", fm["lineage_graph"])
        self.assertIn("edges", fm["lineage_graph"])
        self.assertTrue(any(d.get("decision_type") in {"alternative", "parallel"} for d in fm["decisions"]))
        self.assertTrue(any(lp.get("loop_kind") for lp in fm["loop_patterns"]))
        self.assertTrue(any(c.get("label") for c in fm["contexts"]))
        # sin fuga de condition_ref técnico
        self.assertFalse(any("condition_ref" in (t.get("trigger", {}).get("condition", "")) for t in fm["transitions"]))

    def test_ids_and_scope_are_resolved(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        fm = build_functional_model(
            {
                "manifest": manifest,
                "artifacts": artifacts,
                "graph_nodes": nodes,
                "graph_edges": edges,
                "root_id": root_id,
                "technical_graph": technical_graph,
                "call_graph": call_graph,
                "control_flow_graphs": cfgs,
                "unresolved_references": unresolved,
                "warnings": warnings,
            }
        )
        self.assertIn("id_resolutions", fm)
        self.assertTrue(any(s.get("scope_class") == "A" for s in fm["functional_stages"]))
        # ID funcional por uso: stateId=100 participa como candidato funcional.
        vals = {x.get("id_value") for x in fm["id_resolutions"]}
        self.assertTrue("100" in vals or "200" in vals)
        self.assertFalse("777" in vals)

    def test_nested_subprocess_return_and_internal_end_filtering(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        fm = build_functional_model(
            {
                "manifest": manifest,
                "artifacts": artifacts,
                "graph_nodes": nodes,
                "graph_edges": edges,
                "root_id": root_id,
                "technical_graph": technical_graph,
                "call_graph": call_graph,
                "control_flow_graphs": cfgs,
                "unresolved_references": unresolved,
                "warnings": warnings,
            }
        )
        child_traces = [t for t in fm["traversal_traces"] if not t.get("edge") and t.get("caller_process_id")]
        self.assertTrue(child_traces)
        self.assertTrue(any(t.get("return_node_id") for t in child_traces))
        # End event interno no se promueve como stage funcional
        names = {_n(st.get("functional_name", "")) for st in fm["functional_stages"]}
        self.assertFalse("child end" in names)

    def test_stage_eligibility_action_chain_visibility_and_ui_signatures(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        fm = build_functional_model(
            {
                "manifest": manifest,
                "artifacts": artifacts,
                "graph_nodes": nodes,
                "graph_edges": edges,
                "root_id": root_id,
                "technical_graph": technical_graph,
                "call_graph": call_graph,
                "control_flow_graphs": cfgs,
                "unresolved_references": unresolved,
                "warnings": warnings,
            }
        )
        self.assertTrue(any(s.get("scope_class") == "A" for s in fm["functional_stages"]))
        visited_nodes = {(t.get("process_id"), t.get("node_id")) for t in fm["traversal_traces"] if not t.get("edge")}
        self.assertTrue(len(visited_nodes) > len(fm["functional_stages"]))
        actions = [a for s in fm["functional_stages"] for a in s.get("actions", [])]
        self.assertTrue(actions)
        self.assertTrue(any(a.get("resulting_paths") for a in actions))
        self.assertTrue(any(a.get("validations", {}).get("visible_if") for a in actions))
        self.assertTrue(any(a.get("ui_state_signatures") for a in actions))

    def test_alternative_parallel_retry_and_context_dedupe(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        fm = build_functional_model(
            {
                "manifest": manifest,
                "artifacts": artifacts,
                "graph_nodes": nodes,
                "graph_edges": edges,
                "root_id": root_id,
                "technical_graph": technical_graph,
                "call_graph": call_graph,
                "control_flow_graphs": cfgs,
                "unresolved_references": unresolved,
                "warnings": warnings,
            }
        )
        dtypes = {d.get("decision_type") for d in fm["decisions"]}
        self.assertTrue("alternative" in dtypes or "parallel" in dtypes)
        ttypes = {t.get("transition_kind") for t in fm["transitions"]}
        self.assertTrue(any(x in ttypes for x in {"retry", "reprocess", "loop_back", "parallel"}))
        ctx_keys = [c.get("context_key") for c in fm["contexts"]]
        self.assertEqual(len(ctx_keys), len(set(ctx_keys)))

    def test_renderer_snapshot_without_technical_tokens(self) -> None:
        manifest, _ = parse_manifest(str(self.base))
        artifacts, _ = parse_xml_artifacts_recursive(str(self.base))
        nodes, edges, root_id, unresolved, warnings, technical_graph, call_graph, cfgs = build_execution_graph(artifacts, manifest)
        fm = build_functional_model(
            {
                "manifest": manifest,
                "artifacts": artifacts,
                "graph_nodes": nodes,
                "graph_edges": edges,
                "root_id": root_id,
                "technical_graph": technical_graph,
                "call_graph": call_graph,
                "control_flow_graphs": cfgs,
                "unresolved_references": unresolved,
                "warnings": warnings,
            }
        )
        html = render_html(fm)
        low = html.lower()
        self.assertNotIn("condition_ref", low)
        self.assertNotIn("bpdid", low)
        self.assertNotIn("guid", low)
        self.assertNotIn("caller_node_id", low)


def _n(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


if __name__ == "__main__":
    unittest.main()
