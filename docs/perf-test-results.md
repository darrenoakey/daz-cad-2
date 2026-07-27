# OpenCascade CAD Performance Test Results

## Overview

This document tracks performance test results for the CAD editor, focusing on pattern cutting operations which are the most computationally expensive.

## How to Run Tests

1. Start the server: `./run serve`
2. Navigate to: `http://localhost:8766/perf-test`
3. Click "Run All Tests" or individual test categories
4. Copy the JSON results from the bottom of the page

## Test Categories

### Primitives
- Box creation
- Cylinder creation
- Hexagonal prism (wire -> face -> extrude)
- Wire-only creation
- Face-from-wire creation

### Boolean Operations
- Single cut (box - box)
- Single fuse (box + box)
- Sequential cuts (10x, 50x)
- Compound + single cut (10x, 50x)

### Pattern Approaches

**APPROACH 1: 3D Compound Cut (Current Implementation)**
- Create 3D hexagonal prisms
- Add all to compound
- Single cut operation

**APPROACH 2: 2D Faces -> Extrude -> Cut**
- Create 2D hexagonal faces
- Add all faces to compound
- Extrude compound
- Cut from base

**APPROACH 3: BRepAlgoAPI_Cut with ListOfShape**
- Create 3D prisms
- Use SetTools API with TopTools_ListOfShape
- Alternative API that may have different performance

### Breakdown Tests
- Prism creation time only
- Compound building time only
- Boolean cut time only (pre-built compound)
- Mesh tessellation time

## Results Template

```json
{
  "timestamp": "2025-01-09T...",
  "system": "Mozilla/5.0 ...",
  "tests": {
    "primitives": [
      {"name": "Create box (10x10x10)", "avg_ms": X, "min_ms": X, "max_ms": X, "iterations": 5}
    ],
    "booleans": [
      {"name": "Single cut (box - box)", "avg_ms": X, "min_ms": X, "max_ms": X, "iterations": 5}
    ],
    "patterns": [
      {"name": "APPROACH 1: 3D compound cut", "avg_ms": X, "min_ms": X, "max_ms": X, "iterations": 1}
    ]
  }
}
```

## Key Findings

### Performance Scaling

The boolean cut operation complexity scales with the number of faces in the cutting tool.
More holes = more faces = exponentially slower.

| Pattern Size | Approx Holes | Performance |
|-------------|--------------|-------------|
| 5mm (auto)  | ~50 holes    | Very slow (>15s) - test timeout |
| 10mm        | ~15 holes    | Acceptable (<5s) |
| 15mm        | ~8 holes     | Fast (<2s) |

### Implemented Optimizations

1. **2D extrusion approach** - Create 2D faces, compound them, extrude once, then cut
   - Faster than creating individual 3D prisms
   - Single extrusion of compound vs n individual extrusions

2. **Compound cut** - Single boolean with compound vs sequential cuts
   - O(1) vs O(n) boolean operations
   - Major speedup for >5 holes

3. **`size` parameter** - Control polygon size to reduce hole count
   - Larger size = fewer holes = faster
   - User can trade detail for performance

4. **Worker cancellation** - Changes during render cancel immediately
   - `worker.terminate()` kills in-progress render
   - Fresh worker created for new render

### Current Bottleneck

The boolean cut operation (`BRepAlgoAPI_Cut`) is the fundamental bottleneck.
OpenCascade's boolean operations are O(n*m) where n and m are face counts.
With ~50 hexagonal holes (each with 8 faces including top/bottom), that's 400+ faces.

### Optimization Recommendations

1. **Use `size` parameter** - Set larger polygon size for faster preview
2. **Reduce hole count** - Increase wallThickness or border
3. **Worker cancellation** - User edits cancel in-progress renders
4. **Progressive rendering** - Show base first, add pattern after (not yet implemented)
5. **Mesh caching** - Cache mesh for unchanged patterns (not yet implemented)

## Historical Results

### Run 1: [DATE]
```json
// Paste full JSON here
```

---

## Notes for Future Optimization

Potential areas to explore:
1. **Mesh caching** - If pattern is the same, cache the mesh data
2. **Level of detail** - Simpler tessellation during editing, full quality for export
3. **Progressive rendering** - Show base shape immediately, add pattern after
4. **WebGPU** - Future: GPU-accelerated boolean operations
5. **Pattern presets** - Pre-computed common pattern sizes
