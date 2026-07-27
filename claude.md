# daz-cad Project Guide

## Overview
Browser-based CAD application using OpenCascade.js for 3D modeling. JavaScript CAD library with CadQuery-like API.

## Key Files
- `static/patterns.js` - cutPattern() API for cutting shapes into faces
- `static/cad.js` - Core Workplane class and CAD operations
- `static/naming.js` - Named references system (semantic face/edge names, relative operations)
- `static/viewer.js` - Three.js 3D viewer
- `static/editor.js` - Monaco editor integration
- `static/gridfinity.js` - Gridfinity module (bin, plug, baseplate, fitBin, cutRectGrid, cutCircleGrid)
- `static/cad-library-spec.md` - **CRITICAL: sole API doc sent to AI agent** — any API not documented here is invisible to the in-app assistant
- `src/server_test.py` - Playwright-based E2E tests

## Testing
- Run tests: `python -m pytest src/server_test.py -v`
- Smoketest: `./smoketest` (connects to localhost:8766, waits for OC.js ready)
- Tests use Playwright and require a running server (pytest fixture handles this)
- Tests use `page.evaluate()` to run JavaScript in browser context
- Pattern tests verify cutting by comparing mesh vertex counts before/after
- **Mesh format:** `toMesh()` returns `{ vertices, indices, color, isModifier }` (not `position`)
- **Shared fixtures** (conftest.py): `shared_browser` (session-scoped Chromium), `cad_page` (editor with OC.js ready), `init_page` (/init-test page). Reuse these — don't create new browsers per test (WASM compile = 30s per browser)
- **Server fixture**: DO NOT use `--reload` with uvicorn in `run serve` — it creates multiprocessing parent/child that hangs after extended runtime. The in-app FileWatcher + SSE handles browser hot-reload

## cutPattern() Architecture
- Cutters are created at Z=0 extending in +Z direction
- `_createFaceTransform()` rotates/translates cutters to align with any face
- For non-Z faces, rotation maps +Z to the face's inward normal direction
- X-aligned faces need extra 90° pre-rotation for lines (so length runs in Y)
- `spacing` parameter = gap between shapes (not center-to-center)
- Default spacing = width (50% solid, 50% cut)
- **Cutters are fused before cutting** - eliminates internal faces when shapes overlap
- This fixes hexagon patterns with thin wallThickness that would otherwise fail
- **Clipping for non-rectangular faces:**
  - `clip: 'partial'` - clips shapes at face boundary (partial shapes at edges)
  - `clip: 'whole'` - only keeps shapes fully inside (volume comparison check)
  - `_createOffsetFace()` handles border inset:
    - Circles: shrinks radius by border distance
    - Polygons: edge-based offset using `BRepTools_WireExplorer` for vertex ordering,
      computes inward normals per edge, finds intersections of adjacent offset edges
  - Clip solid extends both above and below face to fully contain cutters

## Geometry Optimization
- `clean()` method merges coplanar faces and collinear edges
- Uses `ShapeUpgrade_UnifySameDomain` and `ShapeFix_Shape`
- Call after complex boolean operations to simplify geometry
- Options: `{ unifyFaces, unifyEdges, fix, rebuildSolid }`

## Edge Selectors
- Simple: `|Z` (parallel to Z), `<X` (min X), `>Y` (max Y)
- Compound with "and": `edges("<X and <Y")` - intersection (edges matching ALL)
- Compound with "or": `edges("<X or |Z")` - union (edges matching ANY)
- Use `edgesNot()` to exclude: `edgesNot("|Z")` gets all non-vertical edges
- Chain operations: `box.edges("|Z").fillet(3).edgesNot("|Z").fillet(1)`

## Non-Uniform Scaling (Ellipsoid Pattern)
- `gp_GTrsf` + `BRepBuilderAPI_GTransform` for non-uniform scaling of shapes
- Used by `ellipsoid()`: creates unit sphere, scales by (rx, ry, rz)
- This pattern works for any shape that needs independent axis scaling

## Common Issues
- Face normal detection uses `BRepAdaptor_Surface.D1()` with cross product
- Check `face.Orientation_1()` for reversed faces that need normal flip
- Boolean cuts can fail silently - verify by checking mesh vertex counts
- Browser caching: NoCacheMiddleware adds no-cache headers to all /static/* files

## Version Control
- `local/models/` directory is auto-initialized as a git repo on server startup
- Every successful model save auto-commits with AI-generated message (Claude Haiku)
- Commits run in background task to not block save response
- Uses `claude-agent-sdk` with `model="haiku"` for commit message generation
- Error handling: falls back to simple "Update filename" message if Claude SDK fails

## Marketing Website (site/)
- Static site at `dazcad.insidemind.com.au` (S3 + CloudFront)
- Generator: `site/src/sitegen/` - Python modules producing HTML/CSS/JS
- CLI: `site/run generate|deploy|setup|publish|test|screenshots`
- Standalone editor: `site/src/standalone/bundler.py` packages editor.js for serverless use
- AWS infra: uses `~/src/aws-web/` shared library (S3Manager, CloudFrontManager, ACMManager)
- Config: `site/local/config.json` (subdomain, domain, bucket_suffix)
- Output: `site/local/web/` (gitignored, has its own git repo for delta deploy)
- Images: `~/bin/generate_image` outputs JPG not PNG despite --output extension

## Standalone Editor Mode
- `window.DAZ_CAD_STANDALONE = true` flag in editor.js
- **CRITICAL**: ALL methods that access chat DOM elements (`chat-input`, `chat-send-btn`, `chat-messages`) MUST have `if (STANDALONE) return;` guards — these elements don't exist in standalone HTML (replaced with "AI not available" image). Missing guards crash the entire async `_init()` chain, silently killing Monaco and worker initialization.
- File storage: localStorage instead of server API
- Chat pane: replaced with sad android "AI not available" image in standalone
- File watchers and hot reload: disabled
- Bundled examples via `window.DAZ_CAD_EXAMPLES` object
- URL params: `?file=demo_patterns.js` to select example (standalone mode only)
- Server mode uses URL path for file selection: `/model_name` (not `?file=`)

## Site Deployment
- S3 bucket: `dazcad-insidemind-com-au-site` (ap-southeast-2)
- CloudFront: `d36vius0luszvk.cloudfront.net` with URL rewrite function
- Links use `.html` extensions (S3 compatible), CloudFront rewrites extensionless URLs
- Screenshots: Playwright capture requires fresh browser per model (OC.js memory leak crashes shared browser)
- Screenshots wait: 20s for simple models, 35s for complex (clip-demo, baseplate-on-surface)
- After S3 upload, must invalidate CloudFront cache for changes to appear on custom domain
- Hero section has dark background always — force light text for buttons regardless of theme

## Named References System (naming.js)
- Extends `Workplane.prototype` like patterns.js — zero modifications to cad.js
- Convention: Front=+Y, Back=-Y, Right=+X, Left=-X, Top=+Z, Bottom=-Z
- `box()` auto-names 6 faces; `cylinder()` gets top/bottom/side
- Edges auto-named as "face1-face2" (alphabetical, e.g. "front-top")
- Names survive `translate()` (centroids shift) and `rotate()` (normals rotate via Rodrigues)
- Boolean ops re-match faces by similarity scoring (50% normal, 35% centroid, 15% area)
- `_isFacePlanar()` uses dual-point normal comparison (OC enum comparison unreliable in JS bindings)
- `_resolveNamedFace()` uses best-match scoring with distance tolerance = 10% of shape diagonal
- `name("part")` + `.union()` creates `_subParts` for dotted access: `faces("part.front")`
- Relative ops: `extrudeOn`, `cutInto`, `centerOn`, `alignTo`, `attachTo`
- Extrusion/cutting use Rodrigues rotation to align box +Z with face normal
- **Face name selectors**: `face("top")` is a selector (returns Workplane with `_selectedFaces`), NOT inspection — use `faceInfo("top")` for `{ normal, centroid, area }`
- **edges by face name**: `edges("top")` selects all edges of the top face — enables `box.edges("top").chamfer(2)`
- **fillet/chamfer from face**: `face("top").fillet(2)` works — `fillet()`/`chamfer()` in cad.js derive edges via `_edgesFromSelectedFaces()` when `_selectedFaces` is set and `_selectedEdges` is empty

## Adding New Primitives (Checklist)
When adding a new primitive to the CAD library, ALL four locations must be updated:
1. `static/cad.js` — Implementation in `Workplane` class (wire/face/extrude pattern via `BRepBuilderAPI_MakeWire` + `BRepBuilderAPI_MakeFace` + `BRepPrimAPI_MakePrism`)
2. `static/editor.js` — Monaco type definitions (JSDoc + TypeScript signature for autocomplete)
3. `static/cad-library-spec.md` — API reference + usage examples (this is the AI agent's sole API doc)
4. `src/server_test.py` — Tests AND add to `expectedWorkplaneMethods` list (type-sync test catches missing entries)

## Conventions
- Dimensions in millimeters
- Result variable must be defined in CAD scripts
- Colors as hex strings: `.color("#3498db")`
