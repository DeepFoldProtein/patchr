#!/usr/bin/env python3
"""
Comprehensive analysis of residue gaps and broken connections in protein structures.

This script analyzes multiple aspects of protein structure connectivity:
1. CA-CA distances between consecutive residues
2. C-N distances (peptide bonds)
3. Backbone atom distances (N-CA, CA-C within residues)
4. Missing backbone atoms
5. Residue number continuity
6. Torsion angles (phi, psi)

Based on standard protein structure validation criteria:
- Normal CA-CA distance: ~3.8 Å
- Normal C-N (peptide bond): ~1.33 Å
- Normal N-CA: ~1.46 Å
- Normal CA-C: ~1.52 Å
"""

import argparse
import glob
import math
import os
import sys

import numpy as np
import yaml
from Bio import PDB
from Bio.PDB import MMCIFParser


def get_structure_parser(file_path):
    """Get appropriate parser based on file extension."""
    file_ext = os.path.splitext(file_path)[1].lower()
    if file_ext in [".cif", ".mmcif"]:
        return MMCIFParser(QUIET=True)
    else:
        return PDB.PDBParser(QUIET=True)


def get_backbone_atom(residue, atom_name):
    """Safely get backbone atom from residue."""
    try:
        return residue[atom_name]
    except KeyError:
        return None


def calculate_torsion_angle(atom1, atom2, atom3, atom4):
    """Calculate torsion angle between four atoms."""
    if atom1 is None or atom2 is None or atom3 is None or atom4 is None:
        return None

    try:
        return PDB.calc_dihedral(
            atom1.get_vector(),
            atom2.get_vector(),
            atom3.get_vector(),
            atom4.get_vector(),
        )
    except:
        return None


def _build_residue_map(structure):
    """Build a mapping: chain_id -> {res_num: residue} for quick lookup."""
    mapping = {}
    for model in structure:
        for chain in model:
            chain_id = chain.id
            mapping.setdefault(chain_id, {})
            for residue in chain:
                if residue.id[0] == " ":  # standard residue
                    res_num = residue.id[1]
                    mapping[chain_id][res_num] = residue
    return mapping


def detect_inpainting_regions(template_struct, result_struct, threshold=0.5):
    """
    Compare template (masked) and result (inpainted) structures and return a map
    of chain_id -> set(residue_numbers) that are considered part of the inpainting region.

    Criteria (based on residue presence only, no distance threshold):
    - If residue exists in result but not in template (or missing CA in template) => inpainted
    - This identifies residues that were masked/inpainted
    """
    template_map = _build_residue_map(template_struct)
    result_map = _build_residue_map(result_struct)

    inpaint_map = {}
    chains = set(template_map.keys()) | set(result_map.keys())
    for chain in chains:
        t_res = template_map.get(chain, {})
        r_res = result_map.get(chain, {})
        res_nums = set(r_res.keys())  # Only check residues that exist in result
        inpaint_set = set()
        for rn in res_nums:
            tres = t_res.get(rn)
            rres = r_res.get(rn)

            # Check if residue has CA in template
            t_ca = None
            if tres is not None:
                try:
                    t_ca = tres["CA"]
                except Exception:
                    t_ca = None

            # If template doesn't have this residue or doesn't have CA, it's inpainted
            if tres is None or t_ca is None:
                inpaint_set.add(rn)

        if inpaint_set:
            inpaint_map[chain] = inpaint_set

    return inpaint_map


def detect_broken_regions_in_template(template_struct, broken_threshold=10.0):
    """
    Detect broken regions in the template structure (original PDB gaps).
    Returns a map of chain_id -> set of (res1_num, res2_num) tuples representing
    broken connections that exist in the template itself.
    
    These are gaps that were present in the original PDB, not caused by masking.
    """
    broken_regions = {}
    CA_CA_NORMAL = 3.8
    C_N_NORMAL = 1.33
    
    for model in template_struct:
        for chain in model:
            chain_id = chain.id
            broken_pairs = set()
            
            # Get all standard residues (preserve order)
            residues = [r for r in chain if r.id[0] == " "]
            
            if len(residues) < 1:
                continue
            
            # Check consecutive residue pairs for broken connections
            for i in range(len(residues) - 1):
                res1 = residues[i]
                res2 = residues[i + 1]
                
                res1_num = res1.id[1]
                res2_num = res2.id[1]
                
                # Only check consecutive residues
                if res2_num - res1_num != 1:
                    continue
                
                # Check CA-CA distance
                ca1 = get_backbone_atom(res1, "CA")
                ca2 = get_backbone_atom(res2, "CA")
                
                if ca1 and ca2:
                    ca_ca_dist = ca1 - ca2
                    if ca_ca_dist > broken_threshold:
                        broken_pairs.add((res1_num, res2_num))
                        continue
                
                # Check C-N distance (peptide bond)
                c1 = get_backbone_atom(res1, "C")
                n2 = get_backbone_atom(res2, "N")
                
                if c1 and n2:
                    c_n_dist = c1 - n2
                    if c_n_dist > C_N_NORMAL + 0.6:  # Peptide bond broken
                        broken_pairs.add((res1_num, res2_num))
            
            if broken_pairs:
                broken_regions[chain_id] = broken_pairs
    
    return broken_regions


def filter_results_by_inpainting(results, inpaint_map, template_broken_regions=None):
    """Return a copy of results filtered to only include issues that involve residues
    in the inpainting map (chain -> set(res_nums)), excluding issues that also exist
    in the template structure (original PDB gaps).
    
    Parameters
    ----------
    results : dict
        Analysis results to filter
    inpaint_map : dict
        Map of chain_id -> set(res_nums) for inpainting regions
    template_broken_regions : dict, optional
        Map of chain_id -> set((res1_num, res2_num)) for broken regions in template
    """
    filtered = {}
    for chain_id, chain_data in results.items():
        inpaint_set = inpaint_map.get(chain_id, set())
        if not inpaint_set:
            continue

        # Get broken regions in template for this chain
        template_broken = template_broken_regions.get(chain_id, set()) if template_broken_regions else set()

        # Build neighbor set (include immediate neighbors of inpaint residues)
        neighbor_set = set(inpaint_set)
        for rn in list(inpaint_set):
            neighbor_set.add(rn - 1)
            neighbor_set.add(rn + 1)

        new_chain = {
            "ca_ca_issues": [],
            "peptide_bond_issues": [],
            "backbone_atom_issues": [],
            "missing_atoms": [],
            "residue_number_gaps": [],
            "torsion_angle_issues": [],
            "all_residues": chain_data.get("all_residues", []),
        }

        for issue in chain_data.get("ca_ca_issues", []):
            res1_num = issue.get("res1_num")
            res2_num = issue.get("res2_num")
            # First, exclude if this broken connection also exists in template
            # (regardless of whether it's in inpainting region)
            if (res1_num, res2_num) in template_broken:
                continue
            # Then check if this issue involves inpainting residues
            if res1_num in inpaint_set or res2_num in inpaint_set:
                new_chain["ca_ca_issues"].append(issue)

        for issue in chain_data.get("peptide_bond_issues", []):
            res1_num = issue.get("res1_num")
            res2_num = issue.get("res2_num")
            # First, exclude if this broken connection also exists in template
            # (regardless of whether it's in inpainting region)
            if (res1_num, res2_num) in template_broken:
                continue
            # Include peptide bond issues if either residue is in inpaint_set or neighbor_set
            if res1_num in neighbor_set or res2_num in neighbor_set:
                new_chain["peptide_bond_issues"].append(issue)

        for issue in chain_data.get("backbone_atom_issues", []):
            # Report backbone atom issues for inpaint residues and their immediate neighbors
            if issue.get("res_num") in neighbor_set:
                new_chain["backbone_atom_issues"].append(issue)

        for issue in chain_data.get("missing_atoms", []):
            # Report missing-atom issues for inpaint residues and their immediate neighbors
            if issue.get("res_num") in neighbor_set:
                new_chain["missing_atoms"].append(issue)

        for issue in chain_data.get("residue_number_gaps", []):
            if (
                issue.get("res1_num") in inpaint_set
                or issue.get("res2_num") in inpaint_set
            ):
                new_chain["residue_number_gaps"].append(issue)

        for issue in chain_data.get("torsion_angle_issues", []):
            # Torsion issues might involve neighbors; include neighbor_set
            if issue.get("res_num") in neighbor_set:
                new_chain["torsion_angle_issues"].append(issue)

        # Only keep chain if any issues remain
        if any(new_chain[k] for k in new_chain if k != "all_residues"):
            filtered[chain_id] = new_chain

    return filtered


def analyze_residue_gaps(
    structure, gap_threshold=4.5, broken_threshold=10.0, inpaint_map=None, template_broken_regions=None, target_chains=None
):
    """
    Comprehensive analysis of residue gaps and connectivity issues.

    Parameters
    ----------
    structure : Bio.PDB.Structure
        The protein structure to analyze
    gap_threshold : float
        CA-CA distance threshold for potential gaps (default: 4.5 Å)
    broken_threshold : float
        CA-CA distance threshold for broken chains (default: 10.0 Å)
    target_chains : list, optional
        List of chain IDs to analyze. If None, all chains are analyzed.

    Returns
    -------
    dict
        Dictionary with chain_id as key and comprehensive analysis results
    """
    results = {}

    # Standard distance thresholds
    CA_CA_NORMAL = 3.8
    C_N_NORMAL = 1.33  # Peptide bond
    N_CA_NORMAL = 1.46
    CA_C_NORMAL = 1.52

    # Convert target_chains to set for efficient lookup
    if target_chains:
        target_chains_set = set(target_chains)
    else:
        target_chains_set = None

    for model in structure:
        for chain in model:
            chain_id = chain.id
            
            # Filter by target chains if specified
            if target_chains_set and chain_id not in target_chains_set:
                continue
            chain_results = {
                "ca_ca_issues": [],
                "peptide_bond_issues": [],
                "backbone_atom_issues": [],
                "missing_atoms": [],
                "residue_number_gaps": [],
                "torsion_angle_issues": [],
                "all_residues": [],
            }

            # Get all standard residues (preserve order)
            residues = [r for r in chain if r.id[0] == " "]

            if len(residues) < 1:
                continue

            # If an inpainting map was provided, restrict analysis to the inpaint
            # residues for this chain. We include immediate neighbors (res_num-1, +1)
            # to allow torsion/peptide checks that need neighboring atoms.
            chain_inpaint = None
            if inpaint_map and chain_id in inpaint_map:
                chain_inpaint = set(inpaint_map[chain_id])
                # Build set of residue numbers present in this chain
                present_nums = {r.id[1] for r in residues}
                analysis_nums = set()
                for rn in chain_inpaint:
                    analysis_nums.add(rn)
                    if (rn - 1) in present_nums:
                        analysis_nums.add(rn - 1)
                    if (rn + 1) in present_nums:
                        analysis_nums.add(rn + 1)

                # Filter residues to only those in analysis_nums (preserve original order)
                residues = [r for r in residues if r.id[1] in analysis_nums]

            if len(residues) < 1:
                # nothing to analyze after filtering
                continue

            # Analyze each residue and pairs
            for i, residue in enumerate(residues):
                res_num = residue.id[1]
                res_name = residue.resname

                # Check for missing backbone atoms
                missing_atoms = []
                for atom_name in ["N", "CA", "C", "O"]:
                    if atom_name not in residue:
                        missing_atoms.append(atom_name)

                if missing_atoms:
                    chain_results["missing_atoms"].append(
                        {
                            "res_num": res_num,
                            "res_name": res_name,
                            "missing": missing_atoms,
                        }
                    )

                # Check within-residue backbone distances
                n = get_backbone_atom(residue, "N")
                ca = get_backbone_atom(residue, "CA")
                c = get_backbone_atom(residue, "C")

                if n and ca:
                    n_ca_dist = n - ca
                    if abs(n_ca_dist - N_CA_NORMAL) > 0.3:  # Tolerance
                        chain_results["backbone_atom_issues"].append(
                            {
                                "res_num": res_num,
                                "res_name": res_name,
                                "atom_pair": "N-CA",
                                "distance": n_ca_dist,
                                "expected": N_CA_NORMAL,
                                "deviation": abs(n_ca_dist - N_CA_NORMAL),
                            }
                        )

                if ca and c:
                    ca_c_dist = ca - c
                    if abs(ca_c_dist - CA_C_NORMAL) > 0.3:  # Tolerance
                        chain_results["backbone_atom_issues"].append(
                            {
                                "res_num": res_num,
                                "res_name": res_name,
                                "atom_pair": "CA-C",
                                "distance": ca_c_dist,
                                "expected": CA_C_NORMAL,
                                "deviation": abs(ca_c_dist - CA_C_NORMAL),
                            }
                        )

                # Analyze consecutive residue pairs
                if i < len(residues) - 1:
                    res1 = residue
                    res2 = residues[i + 1]

                    res1_num = res1.id[1]
                    res1_name = res1.resname
                    res2_num = res2.id[1]
                    res2_name = res2.resname

                    # Check residue number continuity
                    residue_gap = res2_num - res1_num
                    is_consecutive = (residue_gap == 1)
                    
                    if residue_gap > 1:
                        chain_results["residue_number_gaps"].append(
                            {
                                "res1_num": res1_num,
                                "res2_num": res2_num,
                                "gap_size": residue_gap - 1,
                            }
                        )

                    # Only analyze connectivity (CA-CA, peptide bond) for consecutive residues
                    # Skip if residue numbers are not consecutive (they're not actually connected)
                    if not is_consecutive:
                        continue

                    # CA-CA distance
                    ca1 = get_backbone_atom(res1, "CA")
                    ca2 = get_backbone_atom(res2, "CA")

                    if ca1 and ca2:
                        ca_ca_dist = ca1 - ca2

                        gap_type = None
                        if ca_ca_dist > broken_threshold:
                            gap_type = "BROKEN"
                        elif ca_ca_dist > gap_threshold:
                            gap_type = "GAP"
                        elif ca_ca_dist > CA_CA_NORMAL + 0.7:  # Slightly abnormal
                            gap_type = "WIDE"

                        if gap_type:
                            chain_results["ca_ca_issues"].append(
                                {
                                    "res1_num": res1_num,
                                    "res1_name": res1_name,
                                    "res2_num": res2_num,
                                    "res2_name": res2_name,
                                    "distance": ca_ca_dist,
                                    "expected": CA_CA_NORMAL,
                                    "gap_type": gap_type,
                                }
                            )

                    # C-N distance (peptide bond)
                    c1 = get_backbone_atom(res1, "C")
                    n2 = get_backbone_atom(res2, "N")

                    if c1 and n2:
                        c_n_dist = c1 - n2

                        if (
                            c_n_dist > C_N_NORMAL + 0.6
                        ):  # Peptide bond should be ~1.33 Å
                            chain_results["peptide_bond_issues"].append(
                                {
                                    "res1_num": res1_num,
                                    "res1_name": res1_name,
                                    "res2_num": res2_num,
                                    "res2_name": res2_name,
                                    "distance": c_n_dist,
                                    "expected": C_N_NORMAL,
                                    "deviation": c_n_dist - C_N_NORMAL,
                                }
                            )

                    # Get backbone atoms for current residue (for torsion angles)
                    n1 = get_backbone_atom(res1, "N")
                    ca1 = get_backbone_atom(res1, "CA")
                    c1 = get_backbone_atom(res1, "C")
                    n2 = get_backbone_atom(res2, "N")

                    # Torsion angles (phi, psi)
                    # Phi angle requires previous residue to be consecutive
                    if i > 0:  # Need previous residue for phi
                        res0 = residues[i - 1]
                        res0_num = res0.id[1]
                        # Only calculate phi if previous residue is consecutive
                        if res1_num - res0_num == 1:
                            c0 = get_backbone_atom(res0, "C")

                            # Phi angle (C(i-1) - N(i) - CA(i) - C(i))
                            if c0 and n1 and ca1 and c1:
                                phi = calculate_torsion_angle(c0, n1, ca1, c1)
                                if phi is not None:
                                    phi_deg = math.degrees(phi)
                                    # Check for unusual phi angles (outside typical range)
                                    if abs(phi_deg) > 180 or (
                                        abs(phi_deg) > 120 and abs(phi_deg) < 60
                                    ):
                                        chain_results["torsion_angle_issues"].append(
                                            {
                                                "res_num": res1_num,
                                                "res_name": res1_name,
                                                "angle_type": "phi",
                                                "angle_deg": phi_deg,
                                            }
                                        )

                    # Psi angle (N(i) - CA(i) - C(i) - N(i+1))
                    if n1 and ca1 and c1 and n2:
                        psi = calculate_torsion_angle(n1, ca1, c1, n2)
                        if psi is not None:
                            psi_deg = math.degrees(psi)
                            # Check for unusual psi angles
                            if abs(psi_deg) > 180 or (
                                abs(psi_deg) > 120 and abs(psi_deg) < 60
                            ):
                                chain_results["torsion_angle_issues"].append(
                                    {
                                        "res_num": res1_num,
                                        "res_name": res1_name,
                                        "angle_type": "psi",
                                        "angle_deg": psi_deg,
                                    }
                                )

            # If inpaint_map was provided, only keep issues that involve the
            # original inpaint residues (not just neighbor residues used for
            # computation). Use filter_results_by_inpainting for consistency.
            if inpaint_map:
                filtered = filter_results_by_inpainting(
                    {chain_id: chain_results}, inpaint_map, template_broken_regions
                )
                if chain_id in filtered:
                    results[chain_id] = filtered[chain_id]
            else:
                # Only add chain if there are any issues
                if any(
                    chain_results[key] for key in chain_results if key != "all_residues"
                ):
                    results[chain_id] = chain_results

    return results


def print_analysis(results, file_path):
    """Print comprehensive analysis results in a readable format."""
    print(f"\n{'='*80}")
    # Show the absolute/full path so it's clear which file was analyzed
    print(
        f"Comprehensive Structure Connectivity Analysis: {os.path.abspath(file_path)}"
    )
    print(f"{'='*80}\n")

    if not results:
        print("✓ No connectivity issues detected.")
        print(f"  All distances and angles are within normal ranges.")
        return

    summary = {
        "ca_ca_issues": 0,
        "broken": 0,
        "gap": 0,
        "gaps": 0,  # Keep for backward compatibility
        "wide": 0,
        "peptide_bond_issues": 0,
        "backbone_atom_issues": 0,
        "missing_atoms": 0,
        "residue_number_gaps": 0,
        "torsion_angle_issues": 0,
    }

    for chain_id, chain_data in results.items():
        print(f"\n{'─'*80}")
        print(f"Chain {chain_id}")
        print(f"{'─'*80}\n")

        # 1. CA-CA Distance Issues
        if chain_data["ca_ca_issues"]:
            summary["ca_ca_issues"] += len(chain_data["ca_ca_issues"])
            print(
                f"1. CA-CA Distance Issues ({len(chain_data['ca_ca_issues'])} found):"
            )
            for issue in chain_data["ca_ca_issues"]:
                gap_type_lower = issue["gap_type"].lower()
                if gap_type_lower in summary:
                    summary[gap_type_lower] += 1
                # Also update 'gaps' for backward compatibility
                if gap_type_lower == "gap":
                    summary["gaps"] += 1
                print(
                    f"   [{issue['gap_type']}] Res {issue['res1_num']} ({issue['res1_name']}) "
                    f"→ Res {issue['res2_num']} ({issue['res2_name']})"
                )
                print(
                    f"      CA-CA distance: {issue['distance']:.2f} Å (expected: ~{issue['expected']:.2f} Å)"
                )
                if issue["gap_type"] == "BROKEN":
                    print(f"      ⚠️  CRITICAL: Chain appears broken!")
                elif issue["gap_type"] == "GAP":
                    print(f"      ⚠️  WARNING: Large gap detected")
                elif issue["gap_type"] == "WIDE":
                    print(f"      ⚠️  CAUTION: Unusually wide spacing")
            print()

        # 2. Peptide Bond (C-N) Issues
        if chain_data["peptide_bond_issues"]:
            summary["peptide_bond_issues"] += len(chain_data["peptide_bond_issues"])
            print(
                f"2. Peptide Bond (C-N) Issues ({len(chain_data['peptide_bond_issues'])} found):"
            )
            for issue in chain_data["peptide_bond_issues"]:
                print(
                    f"   Res {issue['res1_num']} ({issue['res1_name']}) C → "
                    f"Res {issue['res2_num']} ({issue['res2_name']}) N"
                )
                print(
                    f"      C-N distance: {issue['distance']:.2f} Å (expected: ~{issue['expected']:.2f} Å)"
                )
                print(f"      Deviation: +{issue['deviation']:.2f} Å")
                print(f"      ⚠️  Peptide bond may be broken or distorted")
            print()

        # 3. Backbone Atom Distance Issues
        if chain_data["backbone_atom_issues"]:
            summary["backbone_atom_issues"] += len(chain_data["backbone_atom_issues"])
            print(
                f"3. Backbone Atom Distance Issues ({len(chain_data['backbone_atom_issues'])} found):"
            )
            for issue in chain_data["backbone_atom_issues"]:
                print(
                    f"   Res {issue['res_num']} ({issue['res_name']}): {issue['atom_pair']}"
                )
                print(
                    f"      Distance: {issue['distance']:.2f} Å (expected: ~{issue['expected']:.2f} Å)"
                )
                print(f"      Deviation: {issue['deviation']:.2f} Å")
            print()

        # 4. Missing Atoms
        if chain_data["missing_atoms"]:
            summary["missing_atoms"] += len(chain_data["missing_atoms"])
            print(
                f"4. Missing Backbone Atoms ({len(chain_data['missing_atoms'])} found):"
            )
            for issue in chain_data["missing_atoms"]:
                print(
                    f"   Res {issue['res_num']} ({issue['res_name']}): "
                    f"Missing {', '.join(issue['missing'])}"
                )
            print()

        # 5. Residue Number Gaps
        if chain_data["residue_number_gaps"]:
            summary["residue_number_gaps"] += len(chain_data["residue_number_gaps"])
            print(
                f"5. Residue Number Gaps ({len(chain_data['residue_number_gaps'])} found):"
            )
            for issue in chain_data["residue_number_gaps"]:
                print(
                    f"   Res {issue['res1_num']} → Res {issue['res2_num']}: "
                    f"{issue['gap_size']} residue(s) missing in numbering"
                )
            print()

        # 6. Torsion Angle Issues
        if chain_data["torsion_angle_issues"]:
            summary["torsion_angle_issues"] += len(chain_data["torsion_angle_issues"])
            print(
                f"6. Unusual Torsion Angles ({len(chain_data['torsion_angle_issues'])} found):"
            )
            for issue in chain_data["torsion_angle_issues"]:
                print(
                    f"   Res {issue['res_num']} ({issue['res_name']}): "
                    f"{issue['angle_type'].upper()} = {issue['angle_deg']:.1f}°"
                )
            print()

    # Summary
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"  CA-CA distance issues: {summary['ca_ca_issues']}")
    print(f"    - Broken chains (>10.0 Å): {summary['broken']}")
    print(f"    - Gaps (4.5-10.0 Å): {summary['gap']}")
    if summary["wide"] > 0:
        print(f"    - Wide spacing (4.5-10.0 Å): {summary['wide']}")
    print(f"  Peptide bond (C-N) issues: {summary['peptide_bond_issues']}")
    print(f"  Backbone atom distance issues: {summary['backbone_atom_issues']}")
    print(f"  Missing backbone atoms: {summary['missing_atoms']}")
    print(f"  Residue number gaps: {summary['residue_number_gaps']}")
    print(f"  Unusual torsion angles: {summary['torsion_angle_issues']}")
    print(f"{'='*80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Analyze residue gaps and broken connections in protein structures"
    )
    parser.add_argument(
        "structure_files", nargs="+", help="PDB or CIF file(s) to analyze"
    )
    parser.add_argument(
        "--gap-threshold",
        type=float,
        default=4.5,
        help="CA-CA distance threshold for potential gaps (default: 4.5 Å)",
    )
    parser.add_argument(
        "--broken-threshold",
        type=float,
        default=10.0,
        help="CA-CA distance threshold for broken chains (default: 10.0 Å)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Output file to save results (default: print to stdout)",
    )
    parser.add_argument(
        "--compare",
        "-c",
        type=str,
        default=None,
        help="Template or masked structure to compare against (show only inpainting-region analysis)",
    )
    parser.add_argument(
        "--inpaint-threshold",
        type=float,
        default=0.5,
        help="CA displacement threshold (Å) to call a residue part of the inpainting region (default: 0.5 Å)",
    )
    parser.add_argument(
        "--auto-compare",
        action="store_true",
        help="Automatically locate the masked/template CIF in the masked DB directory using the result filename",
    )
    parser.add_argument(
        "--masked-db-dir",
        type=str,
        default="/store/wowjason/work/database/pdb40_masked",
        help="Directory to search for masked/template CIFs when using --auto-compare (default: /store/wowjason/work/database/pdb40_masked)",
    )
    parser.add_argument(
        "--chains",
        "-C",
        type=str,
        nargs="+",
        default=None,
        help="Specific chain IDs to analyze (e.g., --chains A B C). If not specified, all chains are analyzed.",
    )

    args = parser.parse_args()

    all_results = {}

    # Expand provided paths and glob patterns to a list of files to process
    structure_paths = []
    for pattern in args.structure_files:
        # If it's a glob pattern, expand it (supports ** when recursive=True)
        if glob.has_magic(pattern):
            matches = glob.glob(pattern, recursive=True)
            if not matches:
                print(
                    f"Warning: Pattern did not match any files: {pattern}",
                    file=sys.stderr,
                )
            else:
                structure_paths.extend(matches)
        elif os.path.isdir(pattern):
            # If a directory is provided, search recursively for common structure files
            matches = []
            matches += glob.glob(os.path.join(pattern, "**", "*.cif"), recursive=True)
            matches += glob.glob(os.path.join(pattern, "**", "*.mmcif"), recursive=True)
            matches += glob.glob(os.path.join(pattern, "**", "*.pdb"), recursive=True)
            if not matches:
                print(
                    f"Warning: No structure files found under directory: {pattern}",
                    file=sys.stderr,
                )
            else:
                structure_paths.extend(matches)
        elif os.path.isfile(pattern):
            structure_paths.append(pattern)
        else:
            # Not a file, directory or glob - warn and continue
            print(f"Warning: Path not found and not a glob: {pattern}", file=sys.stderr)

    # Deduplicate and sort for consistent processing order
    structure_paths = sorted(list(dict.fromkeys(structure_paths)))

    if not structure_paths:
        print("No structure files to process.", file=sys.stderr)
        return 1

    for file_path in structure_paths:
        try:
            parser_obj = get_structure_parser(file_path)
            structure = parser_obj.get_structure("structure", file_path)

            # If compare/template mode is requested, compute inpainting residues
            inpaint_map = None
            compare_path = None

            # If user asked for auto-compare, look for a matching file in masked-db-dir
            if args.auto_compare and not args.compare:
                # Try several heuristics to find the masked/template file in masked-db-dir.
                # Common pattern: result files are named like <name>_model_0.cif while
                # masked DB files are named <name>.cif (e.g. 8t3s_R_masked_model_0.cif vs 8t3s_R_masked.cif).
                basename = os.path.basename(file_path)
                candidates = []
                candidates.append(os.path.join(args.masked_db_dir, basename))

                # Strip model suffixes like _model or _model_0 etc.
                name_no_ext, ext = os.path.splitext(basename)
                import re

                m = re.sub(r"_model(_\d+)?$", "", name_no_ext)
                if m != name_no_ext:
                    # try common extensions
                    for e in [".cif", ".mmcif", ".pdb"]:
                        candidates.append(os.path.join(args.masked_db_dir, m + e))

                # Also try a loose glob search for files that contain the core name
                try:
                    glob_pattern = os.path.join(args.masked_db_dir, "**", f"*{m}*.*")
                    for p in glob.glob(glob_pattern, recursive=True):
                        candidates.append(p)
                except Exception:
                    pass

                # Check candidates in order and pick the first existing file
                found = False
                for c in candidates:
                    if os.path.exists(c):
                        # If it's a YAML file, try to extract template CIF path from it
                        if c.endswith(('.yaml', '.yml')):
                            try:
                                with open(c, 'r') as f:
                                    yaml_data = yaml.safe_load(f)
                                    if yaml_data and 'templates' in yaml_data:
                                        for template in yaml_data['templates']:
                                            if 'cif' in template:
                                                cif_path = template['cif']
                                                # Resolve relative paths relative to YAML file location
                                                if not os.path.isabs(cif_path):
                                                    cif_path = os.path.join(os.path.dirname(c), cif_path)
                                                if os.path.exists(cif_path):
                                                    compare_path = cif_path
                                                    found = True
                                                    break
                                            elif 'path' in template:
                                                # Alternative key name
                                                cif_path = template['path']
                                                if not os.path.isabs(cif_path):
                                                    cif_path = os.path.join(os.path.dirname(c), cif_path)
                                                if os.path.exists(cif_path):
                                                    compare_path = cif_path
                                                    found = True
                                                    break
                            except Exception as e:
                                # If YAML parsing fails, continue to next candidate
                                pass
                        else:
                            compare_path = c
                            found = True
                        if found:
                            break
                if not found:
                    tried = ", ".join(candidates[:5])
                    print(
                        f"Warning: --auto-compare requested but no matching file found (tried: {tried}...)",
                        file=sys.stderr,
                    )

            # If user provided --compare, try to resolve it; if it's not an existing path,
            # try to find it under the masked DB directory (so user can pass just a filename)
            if args.compare:
                if os.path.exists(args.compare):
                    compare_path = args.compare
                else:
                    candidate = os.path.join(args.masked_db_dir, args.compare)
                    if os.path.exists(candidate):
                        compare_path = candidate
                    else:
                        print(
                            f"Warning: --compare given but file not found: {args.compare} (also tried {candidate})",
                            file=sys.stderr,
                        )

            template_broken_regions = None
            if compare_path:
                try:
                    template_parser = get_structure_parser(compare_path)
                    template_struct = template_parser.get_structure(
                        "template", compare_path
                    )
                    inpaint_map = detect_inpainting_regions(
                        template_struct, structure, threshold=args.inpaint_threshold
                    )
                    # Detect broken regions in template (original PDB gaps)
                    template_broken_regions = detect_broken_regions_in_template(
                        template_struct, broken_threshold=args.broken_threshold
                    )
                except Exception as e:
                    print(
                        f"Error loading compare/template file {compare_path}: {e}",
                        file=sys.stderr,
                    )
                    inpaint_map = None
                    template_broken_regions = None

            # Analyze structure — if inpaint_map is provided, analysis will be
            # restricted internally to the inpainting region.
            results = analyze_residue_gaps(
                structure,
                gap_threshold=args.gap_threshold,
                broken_threshold=args.broken_threshold,
                inpaint_map=inpaint_map,
                template_broken_regions=template_broken_regions,
                target_chains=args.chains,
            )
            all_results[file_path] = results

            # Print results (append to output file if requested)
            if args.output:
                with open(args.output, "a") as f:
                    original_stdout = sys.stdout
                    sys.stdout = f
                    print_analysis(results, file_path)
                    sys.stdout = original_stdout
            else:
                print_analysis(results, file_path)

        except Exception as e:
            print(f"Error processing {file_path}: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            continue

    return 0


if __name__ == "__main__":
    sys.exit(main())
