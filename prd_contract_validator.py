#!/usr/bin/env python3
"""
PRD Contract Validator

Validates PRD contracts against their compliance requirements.
"""

import argparse
import os
import sys
import yaml
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple


def load_prd_contract(contract_path: str) -> Dict[str, Any]:
    """Load a PRD contract from a markdown file with YAML frontmatter."""
    with open(contract_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract YAML frontmatter
    if content.startswith('---'):
        end_frontmatter = content.find('---', 3)
        if end_frontmatter != -1:
            frontmatter = content[3:end_frontmatter].strip()
            try:
                metadata = yaml.safe_load(frontmatter)
            except yaml.YAMLError as e:
                raise ValueError(f"Invalid YAML frontmatter in {contract_path}: {e}")

            # Return both metadata and content parts
            return {
                'metadata': metadata,
                'content': content[end_frontmatter + 3:].strip()
            }

    raise ValueError(f"No YAML frontmatter found in {contract_path}")


def validate_domain_invariants(contract_content: str, invariants: List[str]) -> Tuple[bool, List[str]]:
    """Validate that domain invariants are present in the contract."""
    errors = []

    # Parse the content to extract domain invariants section
    lines = contract_content.split('\n')
    in_section = False
    found_invariants = []

    for line in lines:
        if 'Domain Invariants' in line:
            in_section = True
            continue

        if in_section:
            if line.strip().startswith('#'):  # New section
                break

            # Look for invariant patterns (1., 2., etc.)
            if line.strip().startswith(('1.', '2.', '3.', '4.', '5.')):
                found_invariants.append(line.strip())

    if len(found_invariants) == 0:
        errors.append("No domain invariants found in the contract")
    elif len(found_invariants) < 3:
        errors.append(f"Too few domain invariants found ({len(found_invariants)}), minimum 3 required")
    elif len(found_invariants) > 5:
        errors.append(f"Too many domain invariants found ({len(found_invariants)}), maximum 5 required")

    return len(errors) == 0, errors


def validate_scope_freeze(contract_content: str) -> Tuple[bool, List[str]]:
    """Validate that scope freeze section exists."""
    errors = []

    if 'Scope Freeze' not in contract_content:
        errors.append("Scope Freeze section not found in contract")

    if 'In Scope' not in contract_content:
        errors.append("'In Scope' subsection not found in contract")

    if 'Out of Scope' not in contract_content.replace('Explicitly Out of Scope', 'Out of Scope'):
        errors.append("'Out of Scope' subsection not found in contract")

    return len(errors) == 0, errors


def validate_compliance_flags(contract_content: str) -> Tuple[bool, List[str]]:
    """Validate that compliance flags are properly defined."""
    errors = []

    # Look for the compliance flags table
    if 'Compliance Flags' not in contract_content:
        errors.append("Compliance Flags section not found in contract")
    elif '|' not in contract_content or 'Flag' not in contract_content:
        errors.append("Compliance Flags table not found in contract")

    return len(errors) == 0, errors


def validate_amendment_log(contract_content: str) -> Tuple[bool, List[str]]:
    """Validate that amendment log exists."""
    errors = []

    if 'Amendment Log' not in contract_content:
        errors.append("Amendment Log section not found in contract")

    return len(errors) == 0, errors


def validate_contract(contract_path: str) -> Tuple[bool, List[str]]:
    """Validate a PRD contract file."""
    errors = []

    try:
        contract = load_prd_contract(contract_path)
    except ValueError as e:
        return False, [str(e)]

    # Validate metadata
    required_metadata = ['title', 'status', 'type', 'last_verified']
    for field in required_metadata:
        if field not in contract['metadata']:
            errors.append(f"Missing required metadata field: {field}")

    # Validate content sections
    is_valid, inv_errors = validate_domain_invariants(contract['content'], [])
    errors.extend(inv_errors)

    is_valid, scope_errors = validate_scope_freeze(contract['content'])
    errors.extend(scope_errors)

    is_valid, flag_errors = validate_compliance_flags(contract['content'])
    errors.extend(flag_errors)

    is_valid, amendment_errors = validate_amendment_log(contract['content'])
    errors.extend(amendment_errors)

    return len(errors) == 0, errors


def main():
    parser = argparse.ArgumentParser(description='Validate PRD Contract files')
    parser.add_argument('--contract', '-c', required=True, help='Path to PRD contract file')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed validation results')

    args = parser.parse_args()

    is_valid, errors = validate_contract(args.contract)

    if args.verbose or not is_valid:
        if is_valid:
            print(f"✓ Contract {args.contract} is valid")
        else:
            print(f"✗ Contract {args.contract} is invalid:")
            for error in errors:
                print(f"  - {error}")

    return 0 if is_valid else 1


if __name__ == '__main__':
    sys.exit(main())