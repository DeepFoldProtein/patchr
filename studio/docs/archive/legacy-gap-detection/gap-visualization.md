# Missing Region Visualization Implementation

## Overview

Missing region visualization system provides visual feedback for detected missing regions in protein structures:

- **Partial residues** (missing sidechain atoms): Yellow highlighting
- **Complete missing regions** (missing entire residues): Orange distance lines between missing region boundaries
- **Interactive focus**: Click on missing regions to zoom camera to that location

## Implementation Status

### ✅ Completed

1. **Event Bus Integration** (`src/renderer/src/lib/event-bus.ts`)
   - Added `missing-region:focus` event type for camera focusing

2. **Gap Visuals Hook** (`src/renderer/src/components/mol-viewer/useMissingRegionVisuals.ts`)
   - React hook for managing missing region visualizations
   - Listens to missing region detection results
   - Handles missing region click events for camera focusing
   - Distance calculation between missing region boundaries (C-terminus to N-terminus)

3. **Gap Click Handler** (`src/renderer/src/components/repair/MissingRegionReviewSection.tsx`)
   - Added click handlers to missing region items in review section
   - Emits `missing-region:focus` event when missing region is clicked
   - Visual feedback with hover effects

4. **Integration** (`src/renderer/src/components/MolViewerPanel.tsx`)
   - useMissingRegionVisuals hook integrated into viewer panel
   - Auto-enables after structure loading

### 🚧 To Do

1. **Partial Residue Highlighting** (Yellow Color)
   - Current implementation: Placeholder with console logging
   - Requires: Molstar overpaint/color theme API
   - Approach options:
     - `plugin.managers.structure.overpaint` for coloring specific residues
     - Create custom color theme for partial residues
     - Use structure selection with color override

2. **Distance Line Visualization** (Orange Lines)
   - Current implementation: Console logging with coordinates
   - Requires: Molstar shape/measurement API
   - Approach options:
     - **Option A**: Use `plugin.managers.structure.measurement.addDistance(lociA, lociB)`
       - Pros: Built-in, handles labels automatically
       - Cons: Requires creating proper Loci objects from coordinates
     - **Option B**: Create custom Shape with Lines geometry
       - Pros: Full control over appearance
       - Cons: More complex, requires understanding Shape API
     - **Option C**: Use `StateTransforms.Representation.StructureSelectionsDistance3D`
       - Pros: Built for this purpose
       - Cons: Requires selections, not just coordinates

## Current Behavior

When missing regions are detected:

1. Console logs show distance calculations for complete missing regions
2. Camera can focus on missing regions when clicked (implementation ready)
3. Partial residues are identified but not yet visually highlighted

Example console output:

```
[Missing Region Visuals] Distance line for chain_A_gap_1_5:
  23.5 Å (4 residues)
  from [12.3, 45.6, 78.9] to [15.2, 48.3, 81.2]
```

## API References

### Molstar Distance Measurement

- File: `molstar/lib/mol-plugin-state/manager/structure/measurement.ts`
- Method: `addDistance(lociA: StructureElement.Loci, lociB: StructureElement.Loci)`
- Example: See molstar examples at `mol-plugin-ui/structure/measurements.tsx`

### Shape Creation

- File: `molstar/lib/mol-model/shape/shape.ts`
- Method: `Shape.create(name, data, geometry, getColor, getSize, getLabel)`
- Geometry: Use `LinesBuilder` from `molstar/lib/mol-geo/geometry/lines/lines-builder`
- Example: See `mol-repr/shape/loci/distance.ts` for distance line implementation

### Structure Coloring

- Overpaint: `plugin.managers.structure.overpaint`
- Color themes: `plugin.representation.structure.themes.colorTheme`

## Data Flow

```
Missing Region Detection (useMissingRegionDetection)
    ↓
missingRegionsDetectedAtom (jotai state)
    ↓
Missing Region Visuals (useMissingRegionVisuals)
    ├→ Partial: Yellow highlight (TODO)
    ├→ Complete: Distance lines (TODO)
    └→ Camera focus (✓ Working)
        ↑
Missing Region Review Section (user click)
    └→ Emits "missing-region:focus" event
```

## Next Steps

### Priority 1: Implement Distance Lines

The most straightforward approach is using Molstar's measurement API:

```typescript
// Convert coordinates to Loci
const lociA = createLociFromCoordinate(structure, startCoord, chainId);
const lociB = createLociFromCoordinate(structure, endCoord, chainId);

// Add distance measurement
await plugin.managers.structure.measurement.addDistance(lociA, lociB, {
  customText: `${regionLength} residues`,
  lineParams: {
    linesColor: ColorNames.orange,
    linesSize: 0.1
  }
});
```

### Priority 2: Implement Partial Residue Coloring

Use structure overpaint for yellow highlighting:

```typescript
// Create selection for partial residue
const selection = StructureSelection.Sequence(structure, [
  { chainId, seqId, insCode }
]);

// Apply yellow overpaint
await plugin.managers.structure.overpaint.set({
  layers: [
    {
      bundle: StructureElement.Bundle.fromSelection(selection),
      color: ColorNames.yellow,
      clear: false
    }
  ]
});
```

## Testing

1. Load 1TON.cif (has missing residues)
2. Check Missing Region Review Section for detected missing regions
3. Click on a missing region item
4. Camera should focus on missing region location (currently working)
5. Visual indicators should appear (distance lines/colors - TODO)

## References

- Missing Region Detection: `docs/missing-region-detection-implementation.md`
- Molstar Integration: `docs/mol-viewer-integration.md`
- Repair Workflow: `docs/plan.md` (Section 3)
