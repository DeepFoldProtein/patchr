# Patchr Studio

> **Local GUI Application for Molecular Structure Editing and Inpainting**

Patchr Studio is an Electron-based desktop application designed for molecular structure visualization, editing, and inpainting. It combines a modern UI with powerful molecular modeling capabilities, supporting multimer structures, DNA, and ligands.

## 🎯 Features

- **Visual Workflow Editor**: Photoshop/ComfyUI-style interface for molecular structure editing
- **Mol\* 3D Viewer**: High-performance molecular structure visualization
- **Mask-based Editing**: Select and mask regions for targeted modifications
- **Missing Region Detection & Visualization**: Automatic detection of missing residues with interactive visualization
- **Inpainting Pipeline**: AI-powered structure generation for masked regions
- **Structure Refinement**: Post-processing tools including OpenMM integration
- **MolViewSpec Integration**: Standard format for view state serialization and sharing
- **Dark/Light Theme**: Customizable UI with theme switching

## 🏗️ Architecture

### Tech Stack

- **Framework**: Electron + React + TypeScript + Vite
- **UI Components**:
  - Radix UI + shadcn/ui (accessible, headless components)
  - TailwindCSS (styling)
  - react-resizable-panels (layout)
  - lucide-react (icons)
- **State Management**:
  - Jotai (component-level state)
  - **Zustand (global state for preview streaming)**
  - TanStack Query (server data caching)
  - mitt (event bus for cross-component communication)
- **Forms**: React Hook Form + Zod (validation)
- **3D Viewer**:
  - **molstar** ^5.0.0 (high-performance molecular visualization)
  - **PluginUIContext** for full UI integration with React
  - **Sequence viewer** in separate panel (chain/entity breakdown)
    - **✨ Chain Auto-Selection**: When missing region is clicked, sequence panel automatically shows the relevant chain
    - **🔗 Linked Selection**: 3D viewer selection syncs with sequence panel
    - **📝 Reference-based Integration**: Uses Mol\* SequenceView ref for programmatic control
  - **Missing region detection** with automatic missing residue identification
    - **DNA/RNA Support**: Robust detection for nucleotide structures (O1P/O2P vs OP1/OP2 naming handling)
    - **Terminal Residue Handling**: Correctly identifies terminal residues without phosphate atoms
    - **Multi-chain Analysis**: Detects missing regions across entire structure
  - **Missing region visualization** with distance lines and interactive focus
    - **Interactive**: Click missing region to focus camera, highlight residues, and show chain in sequence panel
  - See [mol-viewer-integration.md](docs/mol-viewer-integration.md) for architecture
  - See [gap-visualization-complete.md](docs/gap-visualization-complete.md) for missing region features
  - See [ROBUST-DNA-RNA-DETECTION.md](docs/ROBUST-DNA-RNA-DETECTION.md) for DNA/RNA detection details
  - See [IMPLEMENTATION_NOTES.md](docs/IMPLEMENTATION_NOTES.md) for implementation details

### Project Structure

```
patchr-studio/
├── src/
│   ├── main/           # Electron main process
│   ├── preload/        # Preload scripts
│   └── renderer/       # React application
│       └── src/
│           ├── components/   # UI components
│           │   ├── ui/       # shadcn/ui components
│           │   ├── AppLayout.tsx
│           │   ├── Toolbar.tsx
│           │   ├── StatusBar.tsx
│           │   ├── MolViewerPanel.tsx
│           │   └── ControlPanel.tsx
│           ├── store/        # State management
│           │   ├── app-atoms.ts
│           │   ├── project-atoms.ts
│           │   └── ProjectProvider.tsx
│           ├── lib/          # Utilities
│           │   ├── utils.ts
│           │   └── event-bus.ts
│           ├── mocks/        # Mock API handlers
│           ├── types/        # TypeScript definitions
│           └── assets/       # CSS and static files
├── docs/             # Documentation
└── build/            # Build resources
```

## 🚀 Getting Started

### Prerequisites

- Node.js >= 18
- npm >= 9

### Installation

```bash
# Clone the repository
git clone https://github.com/DeepFoldProtein/patchr-studio.git
cd patchr-studio

# Install dependencies
npm install
```

### Development

```bash
# Start development server
npm run dev

# Build for production
npm run build

# Build platform-specific packages
npm run build:mac     # macOS
npm run build:win     # Windows
npm run build:linux   # Linux
```

### Scripts

- `npm run dev` - Start development mode with hot reload
- `npm run build` - Build the application
- `npm run lint` - Run ESLint
- `npm run format` - Format code with Prettier
- `npm run typecheck` - Run TypeScript type checking

### ⚠️ Development Notes

See [IMPLEMENTATION_NOTES.md](docs/IMPLEMENTATION_NOTES.md) for important development guidelines, especially:

- **React 18 Integration**: HMR stability and ref callback patterns
- **Mol\* Canvas3D**: Using `createPluginUI()` vs manual PluginContext
- **DOM Isolation**: Preventing React reconciliation conflicts
- **Performance**: Memory optimization and structure loading

## 📐 State Management Philosophy

Patchr Studio follows a **layered state management** approach:

### Component-Level State (Jotai)

- UI input values (seeds, temperature, confidence_threshold)
- Tab selection
- Local UI interactions
- Mask specifications

### Global State (Zustand)

- Preview streaming (isRunning, progress, elapsed_s, remaining_s)
- Generated frames cache
- Run IDs and error states
- **Independent interval management** (React lifecycle-agnostic)

### Why Zustand for Preview State?

When switching tabs in React, component-level state management (Jotai, useState) causes intervals to pause because the component unmounts. Zustand manages state and intervals at the window level, ensuring:

- ✅ Progress continues updating when tab is not visible
- ✅ Automatic cleanup on completion/cancellation
- ✅ Multiple components can subscribe to the same global state
- ✅ Simpler code without useEffect/useRef complexity

## 🎨 UI Components

### Layout Structure

```
┌─────────────────────────────────────────────────┐
│  Toolbar (Open, Save, Undo/Redo, Theme, etc.)  │
├──────────────────────┬──────────────────────────┤
│  Sequence Viewer     │   Control Panel          │
│  (Chain/Entity view) │   ┌──────────────────┐   │
├──────────────────────┤   │ Tabs:            │   │
│                      │   │ • Mask           │   │
│   Mol* 3D Viewer     │   │ • Inpaint        │   │
│                      │   │ • Refine         │   │
│   (Resizable)        │   │ • Export         │   │
│                      │   └──────────────────┘   │
│                      │                          │
├──────────────────────┴──────────────────────────┤
│  Status Bar (FPS, GPU, Progress, Project Info)  │
└─────────────────────────────────────────────────┘
```

### Control Panel Tabs

1. **Mask Tab**: Region selection, auto-detection of missing regions
2. **Inpaint Tab**: Parameter configuration (steps, tau, seeds)
3. **Refine Tab**: Structure post-processing and metrics
4. **Export Tab**: Save structures in PDB, mmCIF, or project format

## 🔌 API Integration

### Mock API (Development)

The application uses MSW (Mock Service Worker) during development to simulate backend API responses:

- `/api/inpaint/run` - Start inpainting job
- `/api/inpaint/status/:runId` - Get job status
- `/api/preview/:runId` - Get preview frames
- `/api/view/export` - Export MVS view state
- `/api/view/import` - Import MVS view state
- `/api/mask/detect` - Auto-detect missing regions
- `/api/refine/run` - Run structure refinement

### Backend Integration

To connect to a real backend:

1. Set `DEV_MOCK=false` in environment
2. Configure backend URL in app settings
3. Ensure FastAPI backend implements the same endpoints

## 📊 MolViewSpec (MVS) Integration

Patchr Studio uses MolViewSpec for view state management:

- **Standard Format**: JSON-based view state serialization
- **Reproducibility**: Save and restore exact visual scenes
- **Sharing**: Exchange view states with collaborators
- **Versioning**: Track view state changes in project history

### MVS File Structure

```json
{
  "version": "1.0",
  "_molviewspec_version": "1.0.0",
  "nodes": [
    {
      "type": "data",
      "id": "structure-1",
      "params": { "source": "file://structure.pdb", "format": "pdb" }
    },
    {
      "type": "representation",
      "id": "repr-1",
      "params": { "style": "cartoon", "colorTheme": "chain" }
    }
  ],
  "metadata": {
    "timestamp": "2025-10-25T00:00:00Z",
    "description": "Project view state",
    "author": "Patchr Studio"
  }
}
```

## 🧪 Testing

```bash
# Run tests (when implemented)
npm test

# Type checking
npm run typecheck
```

## 📝 Project File Format

### .patchrproj

Project files contain:

- Structure data
- Mask specifications
- Inpainting parameters
- View state (MVS)
- History/logs

### .msvj

Separate view state files for sharing visual configurations without full project data.

## 🎓 Development Guidelines

### Code Style

- ESLint + Prettier for consistency
- TypeScript strict mode
- Functional components with hooks
- Props validation with TypeScript

### State Management Best Practices

1. Keep global state minimal
2. Use project-scope providers for document data
3. Leverage TanStack Query for server data
4. Event bus for cross-component communication
5. Avoid prop drilling with composition

### Component Organization

- `/ui`: Reusable, generic UI components
- `/components`: Feature-specific components
- Co-locate tests with components
- Use TypeScript for prop types

## 🗺️ Roadmap

### Phase 1: Core Viewer (✅ COMPLETED)

- [x] Mol\* viewer integration with canvas3d
- [x] Structure loading (PDB, mmCIF formats)
- [x] React 18 HMR stability
- [x] DOM isolation for Mol\* integration
- [x] **Sequence viewer integration** - Separate panel for chain/entity visualization
- [x] **Missing region detection** - Automatic detection of missing residues/atoms
- [x] **Missing region visualization** - Interactive visualization with distance lines and camera focus
- [x] **Dark/Light theme** - Dynamic Mol\* CSS loading with theme switching

### Phase 2: Real-time Inpainting Preview (Boltz-based)

- [x] Zustand global state for preview streaming
- [x] Time-based progress bar with interval management
- [x] Multi-seed sample gallery with pLDDT confidence scores
- [ ] WebSocket streaming with binary frame parsing
- [ ] Boltz-Inpainting inference integration (single forward pass)
- [ ] See [phase-2-boltz-inpainting.md](docs/phase-2-boltz-inpainting.md) for design details

### Phase 3: UI & Features

- [ ] Multiple project tabs
- [ ] Command palette (⌘K)
- [ ] Undo/redo system
- [ ] AG Grid for data tables
- [ ] ECharts for analytics

### Phase 4: Backend Integration

- [ ] FastAPI backend implementation
- [ ] Structure refinement with OpenMM
- [ ] Project persistence
- [ ] i18n support

## 📄 License

MIT

## 👥 Contributors

- DeepFoldProtein Team

## 🔗 Links

- [Electron](https://www.electronjs.org/)
- [React](https://react.dev/)
- [Mol\* Viewer](https://molstar.org/)
- [MolViewSpec](https://molstar.org/viewer-docs/extensions/mvs/)
- [Radix UI](https://www.radix-ui.com/)
- [shadcn/ui](https://ui.shadcn.com/)
- [TailwindCSS](https://tailwindcss.com/)

---

**Note**: This project is under active development. The UI is functional, and backend integration is planned for the next phase.

## To Do

- molprobability (sorting)
- hide 관리 로직 이상?
