# Missing Region Visualization Implementation - Summary

## Implemented Features

### 1. **Missing Region Visualization Hook** (`useMissingRegionVisuals.ts`)

Created a React hook that manages missing region visualizations in the Molstar viewer:

- **Partial Residues**: Placeholder for yellow highlighting (TODO)
- **Complete Gaps**: Distance line calculation and logging
- **Camera Focus**: Click-to-zoom functionality for gaps

### 2. **Event System**

Added `missing-region:focus` event to event bus for triggering camera movements when gaps are clicked.

### 3. **Interactive Gap List**

Modified `MissingRegionReviewSection.tsx` to make missing region items clickable:

- Hover effects for better UX
- Click handler emits `missing-region:focus` event
- Visual feedback with cursor pointer

### 4. **Integration**

Integrated `useMissingRegionVisuals` hook into `MolViewerPanel.tsx` to automatically enable after structure loading.

## Key Implementation Details

### Gap Coordinate System

Gap detection stores:

- `startResId/endResId`: The **missing** residue IDs (e.g., 80-86)
- `startAuthSeqId`: The residue **BEFORE** the missing region (e.g., 79)
- `endAuthSeqId`: The residue **AFTER** the missing region (e.g., 87)

For visualization, we use:

- **Start coordinate**: C atom of `startAuthSeqId` (residue before gap)
- **End coordinate**: N atom of `endAuthSeqId` (residue after gap)

### Distance Calculation

```typescript
const distance = Vec3.distance(
  C_atom_of_residue_before_gap,
  N_atom_of_residue_after_gap
);
```

### Camera Focus

```typescript
plugin.canvas3d?.camera.focus(
  centerCoord,
  radius,
  500 // 0.5s animation
);
```

## Current Status

### ✅ Working

1. Gap detection integration
2. Click handlers on missing region items
3. Camera focus calculation
4. Distance calculation (logged to console)
5. Debug logging for troubleshooting

### 🚧 Pending (TODO)

1. **Visual Distance Lines**: Create actual orange lines in 3D view
   - Using Molstar's measurement API or Shape/Lines geometry
2. **Yellow Highlighting**: Color partial residues yellow
   - Using Molstar's overpaint or color theme API

## Testing

Test with 1TON.cif which has:

- Missing residues (complete gaps)
- Partial residues (missing sidechain atoms)

Expected behavior:

1. Gaps appear in Missing Region Review Section
2. Clicking a missing region triggers camera focus
3. Console shows distance calculations
4. (TODO) Visual distance lines appear in 3D view
5. (TODO) Partial residues shown in yellow

## Console Output Example

```
[Gap Visuals] Applying visualization for 2 gaps
[Gap Visuals] Finding C atom for chain A, seqId 79
  ✓ Found C at [12.34, 45.67, 78.90]
[Gap Visuals] Finding N atom for chain A, seqId 87
  ✓ Found N at [15.23, 48.56, 81.23]
[Gap Visuals] ✓ Distance line for chain_A_gap_80_86: 23.5 Å (7 residues)
[Gap Visuals] Focusing on missing region chain_A_gap_80_86
  ✓ Found C at [12.34, 45.67, 78.90]
```

## Next Steps

1. **Implement Visual Distance Lines**
   - Research Molstar measurement API
   - Or create custom Shape with Lines geometry
   - Add labels showing distance and residue count

2. **Implement Partial Residue Coloring**
   - Use structure overpaint API
   - Apply yellow color to partial residues
   - Test with different structure representations

3. **Polish UX**
   - Add visual indicators in Missing Region Review Section
   - Color-code missing region items (orange for complete, yellow for partial)
   - Show distance in missing region item UI

## Files Modified

1. `src/renderer/src/components/mol-viewer/useMissingRegionVisuals.ts` - New hook
2. `src/renderer/src/lib/event-bus.ts` - Added `missing-region:focus` event
3. `src/renderer/src/components/repair/MissingRegionReviewSection.tsx` - Click handlers
4. `src/renderer/src/components/MolViewerPanel.tsx` - Hook integration
5. `docs/missing-region-visualization.md` - Implementation documentation

## References

- Molstar measurement examples: `mol-plugin-ui/structure/measurements.tsx`
- Distance representation: `mol-repr/shape/loci/distance.ts`
- Shape creation: `mol-model/shape/shape.ts`
