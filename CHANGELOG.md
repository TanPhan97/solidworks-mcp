# Changelog

Versioning follows **MAJOR.MINOR.PATCH**: a new group of tools raises MINOR, fixes only raise PATCH.
Numbering continues from the original project (server 4.0.0 by Samsaam Ali Baig).

| Version | Date | Tools | Summary |
|---|---|---|---|
| 4.4.0 | 2026-10-26 | 132 | Surface, sheet metal, multi-body, mold/3D-print tools, advanced mates, BOM CSV, Pack and Go, drawing tables |
| 4.3.1 | 2026-10-26 | 105 | Audit fixes: COM signatures, `close_document` safety |
| 4.3.0 | 2026-10-26 | 105 | Single tool registry; part / assembly / drawing additions; many fixes |
| 4.2.0 | 2026-10-26 | 76 | Drawing, loft/sweep, batch export/import, feature editing, rib/draft/Hole Wizard |
| 4.1.0 | 2026-10-25 | 58 | Selection & topology, parametric edit, patterns, export, basic assembly; installer |
| 4.0.0 | 2026-03-22 | 25 | Original server, fixed for SolidWorks 2025 (Samsaam Ali Baig) |
| 3.0.0 | 2026-03-22 | 22 | Original package release (Samsaam Ali Baig) |

## 4.4.0 — 2026-10-26 (132 tools, +27)

**New tools**
- Surface (9): `surface_extrude`, `surface_revolve`, `planar_surface`, `offset_surface`, `loft_surface`,
  `knit_surfaces` (optionally to a solid), `thicken_surface`, `cut_with_surface`, `delete_face` (delete / patch / fill).
- Sheet metal (4): `base_flange`, `edge_flange`, `flatten`, `export_flat_pattern` (DXF/DWG with bend lines).
- Multi-body (4): `list_bodies` (solid / surface), `combine_bodies`, `split_body`, `delete_body`.
- Part (3): `sketch_text`, `scale_part` (shrinkage), `cosmetic_thread` (metric size → diameter).
- Assembly (3): `add_advanced_mate` (symmetric, width, gear, slot, hinge, limit distance/angle),
  `export_bom` (CSV: parts only / top level / indented), `pack_and_go`.
- Drawing (4): `add_revision`, `insert_hole_table`, `add_auxiliary_view`, `add_broken_out_section`.

**Fixes**
- `list_edges`: wrong midpoint on reversed straight edges (Curve.Evaluate2 vs GetCurveParams2).
- Zero-argument COM members (`EditRebuild3`, `GetType`, `GetFirstDocument`, `EditSuppress2`, `SketchMirror`,
  `EditSketch`…) are now called through `cu.call`: depending on how pywin32 bound the object they are
  methods or properties. `rebuild` used to report failure after a successful rebuild.
- `list_faces` / `list_edges` include surface bodies (after the solids, so solid indices are unchanged).
- Table templates (BOM / revision / hole): company template folders are searched first.
- Package and server versions unified (`solidworks_mcp.__version__` was still 3.0.0).

**Notes verified on SolidWorks 2026**
- Knit and thicken need the surface body selected with mark 1; knit's "form solid" is set through the feature definition.
- Edge flange needs `InsertSketchForEdgeFlange`; its length is `OffsetDistance`.
- Hinge mate entities are a parameterised property (concentric pair, coincident pair).
- `GetPackAndGo` fails through late-bound COM, so Pack and Go copies the files and re-points references with
  `ReplaceReferencedDocument`.
- `insert_component` centres the component's bounding box on the given point.

**Tests**: 51 offline unit tests; live smoke test 216/216 checks in 13 sections.

## 4.3.1 — 2026-10-26

- All 236 COM calls checked against the SolidWorks 2026 type library; dead fallbacks with wrong signatures removed.
- `close_document` no longer drops unsaved changes silently (needs `save` or `discard_changes`).

## 4.3.0 — 2026-10-26 (105 tools, +29)

- Architecture: `server.py` reduced from 915 to 84 lines; one registry (`TOOL_TABLE`) generates schemas and dispatch.
- Part: full-option `extrude`, spline, ellipse, convert/offset entities, sketch mirror/pattern, construction
  geometry, reference axis, configurations, equations, measure, delete/rename feature.
- Assembly: move / fix / suppress / replace component, component pattern, list mates, interference, exploded view.
- Drawing: center marks, notes, multiple sheets, activate sheet; section/detail placement; no overlapping views.
- Fixes: silent save (no dialog), rebuild no longer exits a sketch, STEP/STL export clears the selection, PDF not
  locked by the viewer, import of a file named like an open document, `add_sheet` with a missing sheet-format
  file, center-mark duplicates, mate WIDTH constant.

## 4.2.0 — 2026-10-26 (76 tools, +18)

Feature groups from a comparison with other SolidWorks MCP servers: drawing creation (views, section, detail,
annotations, BOM, balloons), loft / sweep, batch export, neutral-format import, feature editing
(`get_feature_info`, `edit_feature`), rib / draft / Hole Wizard.

## 4.1.0 — 2026-10-25 (58 tools, +33)

Selection and topology (`list_edges`, `select_faces`…), sketch centerline / slot / fillet / dimensions / relations,
revolve, shell, patterns, mirror, reference planes, dimensions and suppression, undo, mass properties, materials,
custom properties, export, view / capture, basic assembly (insert, mate, list). Template resolver, dimension
kinds, Claude Desktop registration script.

## 4.0.0 / 3.0.0 — 2026-03-22

Original project by Samsaam Ali Baig ([alisamsam/solidworks-mcp](https://github.com/alisamsam/solidworks-mcp)).
