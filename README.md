![](banner.jpg)

# DAZ-CAD

A browser-based parametric CAD editor with 3D text support and multi-material 3MF export for Bambu Lab printers.

## Purpose

DAZ-CAD is a web-based CAD application that allows you to create and edit 3D models directly in your browser. It features:

- Parametric modeling with numeric variable sliders
- 3D text creation
- Multi-material support with automatic filament assignment
- Export to Bambu Lab-compatible 3MF files for direct printing
- Global opacity controls for visualization
- Built-in Gridfinity bin and insert generator

## Documentation

- **[User Guide](docs/user-guide.md)** - Complete walkthrough of the interface, navigation, and features
- **[Library Reference](docs/library-reference.md)** - API documentation for all CAD operations

## Installation

```bash
# Clone the repository
git clone https://github.com/darrenoakey/daz-cad.git
cd daz-cad

# Install dependencies
./run install
```

This installs Python dependencies, development tools, and the Playwright browser for testing.

## Usage

### Starting the Server

```bash
./run serve
```

The server starts at `http://127.0.0.1:8766`. Open this URL in your browser to access the CAD editor.

### Running Tests

Run a specific test:

```bash
./run test src/server_test.py::test_health
```

Run the full test suite:

```bash
./run check
```

### Linting

```bash
./run lint
```

### Building Custom OpenCascade (Optional)

If you need to rebuild the OpenCascade.js library with FreeType support:

```bash
./run build-opencascade
```

This requires Docker to be installed and running.

## Examples

### Creating a Simple Model

1. Start the server with `./run serve`
2. Open `http://127.0.0.1:8766` in your browser
3. Use the editor interface to create shapes
4. Adjust parameters using the properties panel sliders
5. Export to 3MF for printing

### Multi-Material Export

The editor supports assigning different colors/materials to different parts of your model. When exporting to 3MF format, these assignments are preserved in a format compatible with Bambu Lab slicers (Bambu Studio, Orca Slicer), allowing automatic filament mapping to your AMS.

### Using Demo Files

Click the reset button to load template demo files and explore the editor's capabilities.

## Commands Reference

| Command | Description |
|---------|-------------|
| `./run serve` | Start the development server |
| `./run test <target>` | Run a specific test |
| `./run check` | Run full test suite |
| `./run lint` | Run code linter |
| `./run install` | Install all dependencies |
| `./run build-opencascade` | Build custom OpenCascade.js |

## License

This project is licensed under [CC BY-NC 4.0](https://darren-static.waft.dev/license) - free to use and modify, but no commercial use without permission.
