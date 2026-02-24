# Sequence Viewer Integration & Gap Synchronization

## Overview

The Sequence Viewer has been enhanced to automatically respond to missing region detection events and show the relevant chain when a missing region is selected in the UI. This provides seamless integration between the 3D structure viewer, missing region detection system, and sequence visualization.

## Architecture

### Components

1. **`useSequenceViewer`** hook - Manages sequence viewer rendering and chain selection
2. **`MissingRegionReviewSection`** - UI component for missing region list and selection
3. **Event Bus** - Communicates missing region focus events across components
4. **Mol\* SequenceView** - React component for sequence visualization

### Data Flow

```
User clicks missing region in MissingRegionReviewSection
    ↓
emit "missing-region:focus" event (missing region ID)
    ↓
useSequenceViewer listens to event
    ↓
Extract chainId from gap
    ↓
Select chain in 3D viewer (Script selection)
    ↓
Find chain in sequence options
    ↓
Call SequenceView.setState() to change displayed chain
    ↓
Sequence panel now shows target chain
    ↓
User sees selected residue highlighted in both 3D and sequence
```

## Implementation Details

### 1. Sequence Viewer Rendering

The sequence viewer is rendered in a separate React root to avoid conflicts with Mol\*'s internal layout system:

```tsx
const root = createRoot(container);
root.render(
  <PluginContextContainer plugin={plugin}>
    <SequenceView ref={sequenceViewRef} />
  </PluginContextContainer>
);
```

**Key Point**: Using a `ref` callback allows us to capture the SequenceView instance for programmatic control.

### 2. Gap Focus Event Handling

When a missing region is clicked:

```typescript
const handleGapFocus = (regionId: string): void => {
  // 1. Find missing region in state
  const missing region = gaps.find(g => g.regionId === regionId);

  // 2. Select chain in 3D viewer (visual highlighting)
  const script = Script.getStructureSelection(...);
  plugin.managers.structure.selection.fromLoci("add", selection);

  // 3. Find matching chain in sequence options
  const chainOptions = getChainOptions(structure, modelEntityId);

  // 4. Update SequenceView to show that chain
  sequenceViewRef.current.setState({
    modelEntityId,
    chainGroupId,
    mode: "single"
  });
};
```

### 3. Chain Matching Logic

Chain labels in Mol\* have format: `"A [auth B]"` where:

- `A` = internal label
- `auth B` = PDB auth_asym_id (actual chain ID)

The matcher checks both:

```typescript
if (
  chainLabel.includes(gap.chainId) ||
  chainLabel.includes(`[auth ${gap.chainId}]`)
) {
  // Found matching chain
}
```

## Features

### ✨ Chain Auto-Selection

- When user clicks a gap/partial residue, the sequence panel automatically switches to show that chain
- No need to manually select the chain from dropdown
- Works for all chain types (protein, DNA, RNA)

### 🔗 Linked Selection

- 3D viewer selection (residues highlighted)
- Sequence panel selection (chain displayed)
- Both stay in sync through the selection manager

### 📊 Multi-chain Support

- Detects gaps across all chains in structure
- Each missing region is tagged with its chainId
- Sequence viewer can switch between chains seamlessly

## Event Flow Details

### Event Bus Events

```typescript
// Emitted from MissingRegionReviewSection
bus.emit("missing-region:focus", regionId);

// Listened to in useSequenceViewer
bus.on("missing-region:focus", handleGapFocus);
```

### Selection Management

```typescript
// Clear previous
plugin.managers.structure.selection.clear();

// Add new chain
plugin.managers.structure.selection.fromLoci("add", selection);
```

The selection triggers visual updates in:

- 3D viewer (residues highlighted)
- Sequence panel (through selection manager)

### SequenceView State Update

```typescript
sequenceViewRef.current.setState({
  modelEntityId, // Entity/polymer type
  chainGroupId, // Internal chain identifier
  mode: "single" // Show single chain (vs "all" or "polymers")
});
```

## Debugging

Enable console logs to see the entire flow:

```typescript
[Sequence Viewer] === missing-region:focus event received ===
[Sequence Viewer] Looking for missing region ID: chain_B_partial_594
[Sequence Viewer] Found gap: chainId=B, type=partial
[Sequence Viewer] Structures available: 1
[Sequence Viewer] Creating selection script for chain B
[Sequence Viewer] Selection loci created: {kind: 'element-loci', elements: 3}
[Sequence Viewer] Attempting to change sequence view to chain B
[Sequence Viewer] Found matching chain! Setting state...
[Sequence Viewer] ✓ Changed sequence view to chain B
```

## Technical Challenges & Solutions

### Challenge 1: Mol\* SequenceView Instance Access

**Problem**: SequenceView is a React class component rendered in a separate root, making it inaccessible.

**Solution**: Use `ref` callback to capture the instance:

```tsx
<SequenceView
  ref={(ref: SequenceView | null) => {
    sequenceViewRef.current = ref;
  }}
/>
```

### Challenge 2: Chain Identifier Mapping

**Problem**: Mol\* uses different chain identifiers (label_asym_id, auth_asym_id, chainGroupId) with different formats.

**Solution**:

1. Get chain options with `getChainOptions()`
2. Parse chain label format `"A [auth B]"`
3. Match against both label and auth_asym_id

### Challenge 3: DOM Isolation

**Problem**: React and Mol\* have separate reconciliation systems; DOM conflicts can occur.

**Solution**: Render SequenceView in a separate React root outside Mol\*'s DOM tree.

## Performance Considerations

- **Ref Callback**: Lightweight, no state updates on ref assignment
- **Event Listener**: Single listener per component instance
- **Selection Script**: Computed only on missing region focus (lazy evaluation)
- **Chain Matching**: O(n) linear search through chain options (typically < 10 chains)

## Future Enhancements

1. **Residue-level Sync**: Highlight specific residue in sequence when clicking in 3D
2. **Range Selection**: Select residue ranges in sequence panel and highlight in 3D
3. **Color Theme**: Custom coloring for missing region residues in sequence panel
4. **Keyboard Navigation**: Arrow keys to cycle through gaps and chain

## See Also

- [missing-region-visualization-complete.md](missing-region-visualization-complete.md) - Gap visualization features
- [mol-viewer-integration.md](mol-viewer-integration.md) - Mol\* architecture
- [IMPLEMENTATION_NOTES.md](IMPLEMENTATION_NOTES.md) - General implementation guidelines
