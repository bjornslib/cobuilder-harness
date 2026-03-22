#!/bin/bash
# Documentation Cleanup Utility
# Epic 6: Documentation Cleanup (my-project-b3d)
#
# Implements:
#   AC-20: Audit existing docs across 40+ directories, generate inventory
#   AC-21: Add status headers to PRDs and solution designs (default: draft or implemented)
#   AC-22: Validate documents in solution_designs/implemented/ have proper headers
#
# Usage:
#   .claude/utils/doc-cleanup.sh [command] [args...]
#
# Commands:
#   audit               Generate complete inventory of all documentation
#   add-headers [dir]   Add status headers to documents missing them
#   validate-implemented Validate implemented/ folder documents have headers
#   report              Generate full cleanup report (JSON)
#   help                Show this help message

set -euo pipefail

# Source document-lifecycle.sh for shared functions
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/document-lifecycle.sh" ]; then
    source "${SCRIPT_DIR}/document-lifecycle.sh"
fi

# ============================================
# CONFIGURATION
# ============================================

# Project root (my-project)
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# All documentation directories to audit (expanded list for AC-20)
AUDIT_DIRECTORIES=(
    # Primary documentation hub
    "documentation"
    "documentation/prds"
    "documentation/solution_designs"
    "documentation/scratch-pads"
    "documentation/handoffs"
    "documentation/architecture"

    # Task Master
    ".taskmaster/docs"

    # Service-specific documentation
    "my-project-backend/documentation"
    "my-project-frontend/documentation"
    "my-project-communication/documentation"
    "my-project-communication/docs"
    "my-project-communication/livekit_prototype/cli_poc/voice_agent/documentation"
    "my-project-communication/livekit_prototype/cli_poc/voice_agent/docs"

    # MCP tools
    "my-project-mcp-tools/Agent-MCP/docs"

    # Deep research
    "my-project-backend/eddy_deep_research/documentation"

    # User chat docs
    "my-project-backend/user_chat/docs"

    # Root docs
    "docs"

    # Skills documentation
    ".claude/skills"
)

# Document types for classification
DOC_TYPES=("prd" "solution_design" "claude_md" "scratch_pad" "handoff" "skill" "other")

# Files to exclude from processing
EXCLUDED_FILES=(
    "CLAUDE.md"
    "README.md"
    ".gitkeep"
)

# Directories to exclude (ephemeral or node_modules)
EXCLUDED_DIRS=(
    "node_modules"
    ".git"
    "__pycache__"
    ".venv"
    "venv"
)

# ============================================
# AC-20: AUDIT DOCUMENTATION
# ============================================

# Classify document type based on path and content
classify_document() {
    local file="$1"
    local filepath
    filepath=$(echo "$file" | tr '[:upper:]' '[:lower:]')
    local filename
    filename=$(basename "$file")

    # Check for CLAUDE.md
    if [[ "$filename" == "CLAUDE.md" ]]; then
        echo "claude_md"
        return
    fi

    # Check for SKILL.md
    if [[ "$filename" == "SKILL.md" ]]; then
        echo "skill"
        return
    fi

    # Check path patterns
    if [[ "$filepath" == *"/prds/"* ]] || [[ "$filepath" == *"-prd"* ]] || [[ "$filename" == *"prd"* ]]; then
        echo "prd"
        return
    fi

    if [[ "$filepath" == *"/solution_designs/"* ]] || [[ "$filepath" == *"/solution-design"* ]] || [[ "$filename" == *"solution"* ]]; then
        echo "solution_design"
        return
    fi

    if [[ "$filepath" == *"/scratch-pads/"* ]] || [[ "$filepath" == *"scratch-pad"* ]] || [[ "$filepath" == *"scratchpad"* ]]; then
        echo "scratch_pad"
        return
    fi

    if [[ "$filepath" == *"/handoffs/"* ]] || [[ "$filepath" == *"handoff"* ]]; then
        echo "handoff"
        return
    fi

    echo "other"
}

# Check if file should be excluded
should_exclude_file() {
    local file="$1"
    local filename
    filename=$(basename "$file")

    for excluded in "${EXCLUDED_FILES[@]}"; do
        if [[ "$filename" == "$excluded" ]]; then
            return 0  # True - should exclude
        fi
    done

    for excluded_dir in "${EXCLUDED_DIRS[@]}"; do
        if [[ "$file" == *"/$excluded_dir/"* ]]; then
            return 0  # True - should exclude
        fi
    done

    return 1  # False - should not exclude
}

# Check if document has a status header
has_status_header() {
    local file="$1"

    if [ ! -f "$file" ]; then
        echo "false"
        return
    fi

    # Look for status header patterns
    if grep -qiE '^\*\*(Current )?Status\*\*:|^## Document Status|^### Status' "$file" 2>/dev/null; then
        echo "true"
    else
        echo "false"
    fi
}

# Get current status from header if present
get_status_from_header() {
    local file="$1"

    if [ ! -f "$file" ]; then
        echo "unknown"
        return
    fi

    local status_line
    status_line=$(grep -iE '\*\*(Current )?Status\*\*:' "$file" 2>/dev/null | head -1 || echo "")

    if [ -n "$status_line" ]; then
        # Extract status value
        local status_value
        status_value=$(echo "$status_line" | sed -E 's/.*\*\*:\s*//' | tr '[:upper:]' '[:lower:]' | tr -d '*' | xargs)

        # Normalize to known states
        case "$status_value" in
            *"draft"*) echo "draft" ;;
            *"approved"*) echo "approved" ;;
            *"in-progress"*|*"in progress"*|*"implementing"*) echo "in-progress" ;;
            *"implemented"*|*"complete"*|*"done"*) echo "implemented" ;;
            *"staged"*|*"deployed"*|*"released"*|*"rolled-out"*) echo "staged" ;;
            *"ready"*) echo "approved" ;;
            *) echo "$status_value" ;;
        esac
    else
        echo "none"
    fi
}

# Generate complete documentation inventory (AC-20)
audit_documentation() {
    local output_format="${1:-json}"
    local docs_found=0
    local with_headers=0
    local without_headers=0
    local by_type_prd=0
    local by_type_solution=0
    local by_type_claude_md=0
    local by_type_scratch_pad=0
    local by_type_handoff=0
    local by_type_skill=0
    local by_type_other=0
    local directories_scanned=0

    local results='{"documents": ['
    local first=true

    cd "$PROJECT_ROOT"

    for doc_dir in "${AUDIT_DIRECTORIES[@]}"; do
        if [ -d "$doc_dir" ]; then
            directories_scanned=$((directories_scanned + 1))

            # Find all markdown files
            while IFS= read -r -d '' file; do
                # Skip excluded files
                if should_exclude_file "$file"; then
                    continue
                fi

                docs_found=$((docs_found + 1))

                # Classify document
                local doc_type
                doc_type=$(classify_document "$file")

                # Count by type
                case "$doc_type" in
                    prd) by_type_prd=$((by_type_prd + 1)) ;;
                    solution_design) by_type_solution=$((by_type_solution + 1)) ;;
                    claude_md) by_type_claude_md=$((by_type_claude_md + 1)) ;;
                    scratch_pad) by_type_scratch_pad=$((by_type_scratch_pad + 1)) ;;
                    handoff) by_type_handoff=$((by_type_handoff + 1)) ;;
                    skill) by_type_skill=$((by_type_skill + 1)) ;;
                    *) by_type_other=$((by_type_other + 1)) ;;
                esac

                # Check for status header
                local has_header
                has_header=$(has_status_header "$file")
                local current_status="none"

                if [ "$has_header" = "true" ]; then
                    with_headers=$((with_headers + 1))
                    current_status=$(get_status_from_header "$file")
                else
                    without_headers=$((without_headers + 1))
                fi

                # Check if in lifecycle folder
                local in_lifecycle_folder="false"
                local lifecycle_folder=""
                for folder in approved in-progress implemented staged; do
                    if [[ "$file" == *"/$folder/"* ]]; then
                        in_lifecycle_folder="true"
                        lifecycle_folder="$folder"
                        break
                    fi
                done

                # Get file info
                local file_size
                file_size=$(wc -c < "$file" 2>/dev/null | xargs || echo "0")
                local last_modified
                last_modified=$(stat -f "%Sm" -t "%Y-%m-%d" "$file" 2>/dev/null || stat -c "%y" "$file" 2>/dev/null | cut -d' ' -f1 || echo "unknown")

                # Add to results
                if [ "$first" = true ]; then
                    first=false
                else
                    results+=','
                fi

                results+="{"
                results+="\"path\": \"$file\","
                results+="\"type\": \"$doc_type\","
                results+="\"has_status_header\": $has_header,"
                results+="\"current_status\": \"$current_status\","
                results+="\"in_lifecycle_folder\": $in_lifecycle_folder,"
                results+="\"lifecycle_folder\": \"$lifecycle_folder\","
                results+="\"size_bytes\": $file_size,"
                results+="\"last_modified\": \"$last_modified\""
                results+="}"

            done < <(find "$doc_dir" -name "*.md" -type f -print0 2>/dev/null)
        fi
    done

    results+='],'
    results+="\"summary\": {"
    results+="\"total_documents\": $docs_found,"
    results+="\"with_status_headers\": $with_headers,"
    results+="\"without_status_headers\": $without_headers,"
    results+="\"directories_scanned\": $directories_scanned,"
    results+="\"by_type\": {"
    results+="\"prd\": $by_type_prd,"
    results+="\"solution_design\": $by_type_solution,"
    results+="\"claude_md\": $by_type_claude_md,"
    results+="\"scratch_pad\": $by_type_scratch_pad,"
    results+="\"handoff\": $by_type_handoff,"
    results+="\"skill\": $by_type_skill,"
    results+="\"other\": $by_type_other"
    results+="}}"
    results+="}"

    echo "$results"
}

# ============================================
# AC-21: ADD STATUS HEADERS
# ============================================

# Generate status header block
generate_status_header() {
    local status="$1"
    local today
    today=$(date +%Y-%m-%d)

    cat << EOF

## Document Status

**Current Status**: $status
**Last Updated**: $today
**Completion**: TBD

---

EOF
}

# Determine default status for a document
determine_default_status() {
    local file="$1"
    local doc_type="$2"

    # If in implemented/ folder, status is implemented
    if [[ "$file" == *"/implemented/"* ]]; then
        echo "implemented"
        return
    fi

    # If in approved/ folder, status is approved
    if [[ "$file" == *"/approved/"* ]]; then
        echo "approved"
        return
    fi

    # If in in-progress/ folder, status is in-progress
    if [[ "$file" == *"/in-progress/"* ]]; then
        echo "in-progress"
        return
    fi

    # If in staged/ folder, status is staged
    if [[ "$file" == *"/staged/"* ]]; then
        echo "staged"
        return
    fi

    # Check completion percentage from checkboxes
    if [ -f "$file" ]; then
        local checked_count unchecked_count
        checked_count=$(grep -cE '\[(x|X|✓|✔)\]' "$file" 2>/dev/null | tr -d '[:space:]' || echo "0")
        unchecked_count=$(grep -cE '\[( |-)\]' "$file" 2>/dev/null | tr -d '[:space:]' || echo "0")

        # Ensure numeric values
        [[ "$checked_count" =~ ^[0-9]+$ ]] || checked_count=0
        [[ "$unchecked_count" =~ ^[0-9]+$ ]] || unchecked_count=0

        local total=$((checked_count + unchecked_count))
        if [ "$total" -gt 0 ]; then
            local percentage=$((checked_count * 100 / total))
            if [ "$percentage" -eq 100 ]; then
                echo "implemented"
                return
            elif [ "$percentage" -gt 0 ]; then
                echo "in-progress"
                return
            fi
        fi
    fi

    # Default to draft
    echo "draft"
}

# Add status header to a document (AC-21)
add_status_header() {
    local file="$1"
    local force="${2:-false}"

    if [ ! -f "$file" ]; then
        echo '{"error": "File not found", "path": "'"$file"'"}'
        return 1
    fi

    # Check if already has header
    local has_header
    has_header=$(has_status_header "$file")

    if [ "$has_header" = "true" ] && [ "$force" != "true" ]; then
        echo '{"skipped": true, "reason": "Already has status header", "path": "'"$file"'"}'
        return 0
    fi

    # Determine document type and status
    local doc_type
    doc_type=$(classify_document "$file")
    local default_status
    default_status=$(determine_default_status "$file" "$doc_type")

    # Skip certain document types
    if [[ "$doc_type" == "claude_md" ]] || [[ "$doc_type" == "scratch_pad" ]] || [[ "$doc_type" == "handoff" ]]; then
        echo '{"skipped": true, "reason": "Document type excluded from headers", "type": "'"$doc_type"'", "path": "'"$file"'"}'
        return 0
    fi

    # Generate header
    local header
    header=$(generate_status_header "$default_status")

    # Create temp file with header
    local temp_file
    temp_file=$(mktemp)

    # Read first line (usually title)
    local first_line
    first_line=$(head -1 "$file")

    # Check if first line is a title
    if [[ "$first_line" =~ ^#\  ]]; then
        # Insert header after title
        {
            echo "$first_line"
            echo "$header"
            tail -n +2 "$file"
        } > "$temp_file"
    else
        # Insert header at beginning
        {
            echo "$header"
            cat "$file"
        } > "$temp_file"
    fi

    # Replace original file
    mv "$temp_file" "$file"

    echo '{"added": true, "status": "'"$default_status"'", "type": "'"$doc_type"'", "path": "'"$file"'"}'
}

# Add headers to all documents in a directory
add_headers_to_directory() {
    local target_dir="${1:-.}"
    local dry_run="${2:-false}"
    local added=0
    local skipped=0
    local errors=0

    cd "$PROJECT_ROOT"

    if [ ! -d "$target_dir" ]; then
        echo '{"error": "Directory not found", "path": "'"$target_dir"'"}'
        return 1
    fi

    local results='{"processed": ['
    local first=true

    while IFS= read -r -d '' file; do
        if should_exclude_file "$file"; then
            continue
        fi

        local doc_type
        doc_type=$(classify_document "$file")

        # Skip excluded document types
        if [[ "$doc_type" == "claude_md" ]] || [[ "$doc_type" == "scratch_pad" ]] || [[ "$doc_type" == "handoff" ]]; then
            continue
        fi

        if [ "$first" = true ]; then
            first=false
        else
            results+=','
        fi

        if [ "$dry_run" = "true" ]; then
            local has_header
            has_header=$(has_status_header "$file")
            local default_status
            default_status=$(determine_default_status "$file" "$doc_type")

            if [ "$has_header" = "true" ]; then
                results+='{"dry_run": true, "would_skip": true, "path": "'"$file"'"}'
                skipped=$((skipped + 1))
            else
                results+='{"dry_run": true, "would_add": true, "status": "'"$default_status"'", "path": "'"$file"'"}'
                added=$((added + 1))
            fi
        else
            local result
            result=$(add_status_header "$file")
            results+="$result"

            if echo "$result" | grep -q '"added": true'; then
                added=$((added + 1))
            elif echo "$result" | grep -q '"skipped": true'; then
                skipped=$((skipped + 1))
            else
                errors=$((errors + 1))
            fi
        fi
    done < <(find "$target_dir" -name "*.md" -type f -print0 2>/dev/null)

    results+='],'
    results+="\"summary\": {"
    results+="\"headers_added\": $added,"
    results+="\"skipped\": $skipped,"
    results+="\"errors\": $errors,"
    results+="\"dry_run\": $dry_run"
    results+="}}"

    echo "$results"
}

# ============================================
# AC-22: VALIDATE IMPLEMENTED DOCUMENTS
# ============================================

# Validate documents in implemented/ folders have proper headers
validate_implemented() {
    local fix="${1:-false}"
    local valid=0
    local invalid=0
    local fixed=0

    cd "$PROJECT_ROOT"

    local results='{"implemented_docs": ['
    local first=true

    # Find all implemented/ directories
    for doc_dir in "${AUDIT_DIRECTORIES[@]}"; do
        local impl_dir="${doc_dir}/implemented"

        if [ -d "$impl_dir" ]; then
            while IFS= read -r -d '' file; do
                if should_exclude_file "$file"; then
                    continue
                fi

                if [ "$first" = true ]; then
                    first=false
                else
                    results+=','
                fi

                local has_header
                has_header=$(has_status_header "$file")
                local current_status
                current_status=$(get_status_from_header "$file")

                local is_valid="false"
                local issue=""

                if [ "$has_header" = "false" ]; then
                    issue="Missing status header"
                    invalid=$((invalid + 1))

                    if [ "$fix" = "true" ]; then
                        add_status_header "$file" "true" > /dev/null
                        fixed=$((fixed + 1))
                        issue="Fixed: Added status header"
                    fi
                elif [ "$current_status" != "implemented" ]; then
                    issue="Status is '$current_status', expected 'implemented'"
                    invalid=$((invalid + 1))

                    if [ "$fix" = "true" ]; then
                        # Update status to implemented
                        local today
                        today=$(date +%Y-%m-%d)
                        sed -i.bak -E "s/(\*\*(Current )?Status\*\*:).*/\1 implemented/" "$file"
                        sed -i.bak -E "s/(\*\*Last Updated\*\*:).*/\1 $today/" "$file"
                        rm -f "${file}.bak"
                        fixed=$((fixed + 1))
                        issue="Fixed: Updated status to implemented"
                    fi
                else
                    is_valid="true"
                    valid=$((valid + 1))
                fi

                results+="{"
                results+="\"path\": \"$file\","
                results+="\"has_header\": $has_header,"
                results+="\"current_status\": \"$current_status\","
                results+="\"valid\": $is_valid,"
                results+="\"issue\": \"$issue\""
                results+="}"

            done < <(find "$impl_dir" -name "*.md" -type f -print0 2>/dev/null)
        fi
    done

    results+='],'
    results+="\"summary\": {"
    results+="\"valid\": $valid,"
    results+="\"invalid\": $invalid,"
    results+="\"fixed\": $fixed,"
    results+="\"fix_mode\": $fix"
    results+="}}"

    echo "$results"
}

# ============================================
# REPORT GENERATION
# ============================================

generate_cleanup_report() {
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local audit_result
    audit_result=$(audit_documentation)

    local validate_result
    validate_result=$(validate_implemented "false")

    cat << EOF
{
    "report_type": "documentation_cleanup",
    "timestamp": "$timestamp",
    "audit": $audit_result,
    "implemented_validation": $validate_result
}
EOF
}

# ============================================
# CLI INTERFACE
# ============================================

show_help() {
    cat << EOF
Documentation Cleanup Utility
Epic 6: Documentation Cleanup (my-project-b3d)

Usage: $0 [command] [args...]

Commands:
    audit                      Generate complete inventory of all documentation (AC-20)
    add-headers [dir] [--dry-run]  Add status headers to documents missing them (AC-21)
    validate-implemented [--fix]   Validate implemented/ folder documents (AC-22)
    report                     Generate full cleanup report (JSON)
    help                       Show this help message

Examples:
    $0 audit                              # Full documentation inventory
    $0 add-headers documentation --dry-run  # Preview header additions
    $0 add-headers documentation            # Add headers for real
    $0 validate-implemented                 # Validate implemented docs
    $0 validate-implemented --fix           # Fix invalid implemented docs
    $0 report > cleanup-report.json        # Generate full report

Acceptance Criteria Implemented:
    AC-20: Audit existing docs across 40+ directories
    AC-21: Add status headers (default: draft or implemented based on content)
    AC-22: Validate implemented/ documents have proper headers
EOF
}

main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        audit)
            audit_documentation "${1:-json}"
            ;;
        add-headers)
            local target_dir="${1:-.}"
            local dry_run="false"
            shift || true

            for arg in "$@"; do
                case "$arg" in
                    --dry-run) dry_run="true" ;;
                esac
            done

            add_headers_to_directory "$target_dir" "$dry_run"
            ;;
        validate-implemented|validate)
            local fix="false"
            for arg in "$@"; do
                case "$arg" in
                    --fix) fix="true" ;;
                esac
            done

            validate_implemented "$fix"
            ;;
        report)
            generate_cleanup_report
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo "Unknown command: $command"
            echo "Run '$0 help' for usage"
            exit 1
            ;;
    esac
}

# Run main if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
