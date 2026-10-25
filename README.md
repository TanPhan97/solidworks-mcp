# SolidWorks MCP Server 🔧

> Automate SolidWorks using natural language through Claude AI and the Model Context Protocol (MCP)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![SolidWorks 2025](https://img.shields.io/badge/SolidWorks-2023--2025-red.svg)](https://www.solidworks.com/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green.svg)](https://modelcontextprotocol.io/)

---

## 🎯 What is This?

**SolidWorks MCP Server** is a production-ready [Model Context Protocol](https://modelcontextprotocol.io/) server that lets Claude AI control SolidWorks through natural language. Instead of manually clicking through menus, you simply tell Claude what to design — and it builds it for you.

**Example prompts you can use:**
- *"Create a new part, draw a circle with radius 30mm and extrude it 15mm"*
- *"Add a fillet of 2mm to all edges"*
- *"Draw a hexagon and cut extrude it 10mm"*
- *"List all features in the current part"*

---

## ✨ Features

- ✅ **58 Tools** covering parts, sketches, features, selection, parametric edit, properties, export and assemblies
- ✅ **SolidWorks 2023–2025 Compatible** with version-aware API fallbacks
- ✅ **Auto-detects SolidWorks** installation via Windows registry
- ✅ **Multi-unit support** — mm, cm, inch, meter, foot
- ✅ **Modular architecture** — clean, extensible Python package
- ✅ **Robust error handling** — cascading fallback chains for COM API
- ✅ **JSON configuration** — easy to customize without touching code
- ✅ **Comprehensive logging** — full debug output for troubleshooting

---

## 🛠️ Available Tools

| Category | Tool | Description |
|----------|------|-------------|
| **Connection** | `connect_solidworks` | Connect to running SolidWorks instance |
| **Connection** | `get_solidworks_info` | Get version and installation info |
| **Documents** | `create_new_part` | Create a new part document |
| **Documents** | `create_new_assembly` | Create a new assembly document |
| **Documents** | `open_document` | Open an existing SolidWorks file |
| **Documents** | `close_document` | Close the active document |
| **Documents** | `save_document` | Save the active document |
| **Documents** | `list_open_documents` | List all open documents |
| **Sketches** | `create_sketch` | Create a sketch on a plane (Front/Top/Right) |
| **Sketches** | `close_sketch` | Exit the active sketch |
| **Sketches** | `draw_circle` | Draw a circle by center and radius |
| **Sketches** | `draw_rectangle` | Draw a rectangle by two corners |
| **Sketches** | `draw_line` | Draw a line between two points |
| **Sketches** | `draw_arc` | Draw an arc by center and angles |
| **Sketches** | `draw_polygon` | Draw a regular polygon (triangle, hex, etc.) |
| **Features** | `extrude_sketch` | Boss-extrude the active sketch |
| **Features** | `cut_extrude` | Cut-extrude to remove material |
| **Features** | `fillet_edges` | Add fillets to selected edges |
| **Features** | `chamfer_edges` | Add chamfers to selected edges |
| **Features** | `list_features` | List all features in the model |
| **Utilities** | `set_units` | Change default unit (mm/inch/cm/m/ft) |
| **Utilities** | `execute_python` | Execute custom Python code in SW context |

---

## 🧩 Extended Tools (v4.1) — +33 tools

Registered from `solidworks_mcp/tools_ext.py` (declarative table, one line per tool → automation method).

| Group | Tool | Purpose |
|---|---|---|
| **Selection** | `list_edges` | Edges with stable index: type (line/circle/arc), length, midpoint, direction, radius |
| | `list_faces` | Faces: type, area, normal / radius, point on face |
| | `select_edges` | By index or filter: `parallel_to`, `axis_parallel_to`, `radius`, `min/max_length`, `on_face_index` |
| | `select_faces` | By index or filter: `face_type`, `normal` (`z`, `+z`, `-z`…), `radius`, `min_area` |
| | `select_entity` | Generic SelectByID2 by name / model point / sketch point |
| | `clear_selection`, `get_selection` | Selection housekeeping / inspection |
| **Sketch** | `draw_centerline`, `draw_slot`, `sketch_fillet` | Geometry |
| | `add_sketch_dimension` | Smart dimension (length / diameter / radius / distance / angle) with driving value |
| | `add_sketch_relation` | horizontal, vertical, coincident, concentric, tangent, parallel, perpendicular, collinear, equal, midpoint, symmetric, fixed |
| **Features** | `revolve` | Boss / cut revolve, mid-plane, thin |
| | `shell` | Remove faces by index or normal |
| | `linear_pattern`, `circular_pattern` | Direction / axis as edge, face, axis or plane reference |
| | `mirror` | Features or bodies about plane / planar face |
| | `create_ref_plane` | Offset, angle-through-axis, mid-plane |
| **Parametric** | `list_dimensions`, `set_dimension` | Edit `D1@Sketch1` etc., rebuild, report rebuild errors |
| | `suppress_feature`, `rebuild`, `undo` | Feature state / recovery |
| **Properties** | `get_mass_properties` | Mass, volume, area, density, CoM, principal MOI |
| | `set_material` | Library material by exact name |
| | `set_custom_property`, `get_custom_properties` | PartNo / Description / Revision … |
| **Output** | `export_document` | STEP, IGES, Parasolid, STL, 3MF, eDrawings, PDF/DXF (copy; active file unchanged) |
| | `set_view`, `capture_view` | Standard views; viewport returned **as an image** for visual checks |
| **Assembly** | `insert_component`, `add_mate`, `list_components` | Coincident / concentric / parallel / perpendicular / tangent / distance / angle / lock |

**Reference spec** (used by patterns, mirror, planes, revolve axis):
`{"plane": "Front"}` · `{"edge_index": 12}` · `{"face_index": 6}` · `{"name": "Axis1", "type": "AXIS"}` · `{"point": [x, y, z], "type": "FACE"}`

**Typical flow**
```
list_edges(parallel_to="z")          → see vertical edges
select_edges(parallel_to="z")        → select them
fillet_edges(radius=3)
list_faces(face_type="cylinder")     → hole face index 6
circular_pattern(features=["Cut-Extrude1"], axis={"face_index": 6}, count=6)
set_material("6061-T6 (SS)"); get_mass_properties()
export_document("C:/out/part.step"); capture_view("isometric")
```

**Fixes in v4.1**
- `fillet_edges`: `FeatureFillet3` now called with its 14 parameters (was 15 → always failed, silently falling back).
- `chamfer_edges`: `InsertFeatureChamfer` now called with 8 parameters in documented order (was 7, wrong order).
- `requirements.txt`: `mcp<2` — the server uses the 1.x low-level decorator API, which mcp 2.x removed.

**Tests**
- Offline (any OS, fake COM): `python -m pytest solidworks_mcp/tests -q`
- Live (Windows + SolidWorks running): `python scripts\smoke_test_ext.py C:\temp\swmcp_out`

---

## 📋 Requirements

- **OS:** Windows 10 or Windows 11
- **SolidWorks:** 2023, 2024, or 2025 (must be installed and licensed)
- **Python:** 3.10 or higher
- **Claude:** Claude Desktop app or Claude Code

---

## ⚡ Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/alisamsam/solidworks-mcp.git
cd solidworks-mcp
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Claude Desktop

Add the following to your `claude_desktop_config.json`:

**Location:** `C:\Users\YOUR_NAME\AppData\Roaming\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "solidworks": {
      "command": "python",
      "args": ["C:\\path\\to\\solidworks-mcp\\solidworks_mcp_server.py"]
    }
  }
}
```

### 4. Launch

1. Open **SolidWorks** first
2. Restart **Claude Desktop**
3. In Claude, type: *"Connect to SolidWorks"*
4. Start designing! 🎉

---

## 📁 Project Structure

```
solidworks-mcp/
├── solidworks_mcp_server.py      # Entry point
├── solidworks_mcp/               # Main package
│   ├── __init__.py              # Package exports (v3.0.0)
│   ├── server.py                # MCP server & tool definitions
│   ├── config.py                # Configuration management
│   ├── config.json              # Default settings
│   ├── constants.py             # SolidWorks constants & enums
│   ├── automation/              # Core automation modules
│   │   ├── base.py             # Connection management
│   │   ├── documents.py        # Document operations
│   │   ├── sketches.py         # Sketch operations
│   │   └── features.py         # Feature operations (SW 2025 fixed)
│   └── utils/                   # Utility modules
│       ├── units.py            # Unit conversion system
│       └── sw_finder.py        # Auto-detect SolidWorks
├── requirements.txt
├── .gitignore
└── DEVELOPMENT_ROADMAP.md       # Future development plan
```

---

## ⚙️ Configuration

Edit `solidworks_mcp/config.json` to customize behavior:

```json
{
  "exe_path": "auto",
  "default_unit": "mm",
  "startup_timeout": 120,
  "log_level": "INFO",
  "default_extrude_depth": 10.0,
  "default_fillet_radius": 2.0
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `exe_path` | `"auto"` | Path to SLDWORKS.exe or auto-detect |
| `default_unit` | `"mm"` | Default unit for all dimensions |
| `startup_timeout` | `120` | Seconds to wait for SW startup |
| `log_level` | `"INFO"` | Logging verbosity |

---

## 🔧 SolidWorks 2025 Compatibility

This server includes special handling for SolidWorks 2025 API changes:

- **Extrusion fallback chain:** `FeatureExtrusion3` → `FeatureExtrusion2` → `FeatureBossSimple`
- **Safe property access** for `feat.Name`, `feat.GetTypeName2()`, `IsSuppressed2()`
- **stdout capture** fix for `execute_python` tool
- **Registry-based** SolidWorks auto-detection

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Commit your changes: `git commit -m "Add my feature"`
4. Push to the branch: `git push origin feature/my-feature`
5. Open a Pull Request

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Samsaam Ali Baig**
- GitHub: [@alisamsam](https://github.com/alisamsam)

---

## 🙏 Acknowledgements

- [Anthropic](https://anthropic.com) for Claude AI and the MCP framework
- [SolidWorks](https://www.solidworks.com) COM API documentation
- Inspired by [ros2-claude-code-template](https://github.com/harunkurt/ros2-claude-code-template) by Harun KURT

---

⭐ **If this project helps you, please give it a star!**
