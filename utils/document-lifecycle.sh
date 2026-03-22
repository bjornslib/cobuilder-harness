#!/bin/bash
# Document Lifecycle Management Utility
# Epic 4: Document Lifecycle Management (my-project-u7w)
#
# Implements:
#   AC-9: Parse acceptance criteria checkboxes and calculate completion percentage
#   AC-10: Detect and handle 5 lifecycle states (draft, approved, in-progress, implemented, staged)
#   AC-11: Auto-move approved to in-progress on code changes
#   AC-12: Auto-move in-progress to implemented at 100% completion
#   AC-13: Auto-create lifecycle subfolders when needed
#   AC-14: Scan all documentation directories
#   AC-15: Exclude ephemeral docs (scratch-pads/, handoffs/)
#
# Usage:
#   source .claude/utils/document-lifecycle.sh
#   # Then call functions directly
#
# Or run directly:
#   .claude/utils/document-lifecycle.sh [command] [args...]
#
# Commands:
#   scan              - Scan all documents and report status
#   completion <file> - Calculate completion percentage for a file
#   status <file>     - Get lifecycle status of a document
#   transition <file> - Check and apply automatic transitions
#   report            - Generate full lifecycle report (JSON)

set -euo pipefail

# ============================================
# CONFIGURATION
# ============================================

# Lifecycle states (in order)
LIFECYCLE_STATES=("draft" "approved" "in-progress" "implemented" "staged")

# Documentation directories to manage (AC-14)
DOC_DIRECTORIES=(
    "documentation/prds"
    "documentation/solution_designs"
    ".taskmaster/docs"
    "my-project-backend/documentation"
    "my-project-frontend/documentation"
    "my-project-communication/documentation"
)

# Ephemeral directories to exclude (AC-15)
EPHEMERAL_DIRS=(
    "scratch-pads"
    "handoffs"
)

# Lifecycle subfolders
LIFECYCLE_FOLDERS=("approved" "in-progress" "implemented" "staged")

# ============================================
# AC-9: COMPLETION PERCENTAGE CALCULATION
# ============================================

# Calculate completion percentage from checkboxes
# Returns: percentage (0-100), checked count, total count
calculate_completion() {
    local file="$1"

    if [ ! -f "$file" ]; then
        echo '{"error": "File not found", "percentage": 0, "checked": 0, "total": 0}'
        return 1
    fi

    # Count checked and unchecked boxes
    # Pattern: [x], [X], [✓], [✔] for checked; [ ], [-] for unchecked
    local checked_count
    local unchecked_count

    # Use grep with proper output handling - ensure numeric result
    checked_count=$(grep -cE '\[(x|X|✓|✔)\]' "$file" 2>/dev/null | tr -d '[:space:]' || true)
    unchecked_count=$(grep -cE '\[( |-)\]' "$file" 2>/dev/null | tr -d '[:space:]' || true)

    # Default to 0 if empty or non-numeric
    [[ "$checked_count" =~ ^[0-9]+$ ]] || checked_count=0
    [[ "$unchecked_count" =~ ^[0-9]+$ ]] || unchecked_count=0

    local total=$((checked_count + unchecked_count))
    local percentage=0

    if [ "$total" -gt 0 ]; then
        percentage=$((checked_count * 100 / total))
    fi

    cat << EOF
{
    "percentage": $percentage,
    "checked": $checked_count,
    "total": $total,
    "unchecked": $unchecked_count
}
EOF
}

# ============================================
# AC-10: LIFECYCLE STATE DETECTION
# ============================================

# Detect lifecycle state from document status header or path
# Status Header Format:
# ## Document Status
# **Current Status**: [draft | approved | in-progress | implemented | staged]
# **Last Updated**: YYYY-MM-DD
# **Completion**: [percentage or checklist summary]
detect_lifecycle_state() {
    local file="$1"

    if [ ! -f "$file" ]; then
        echo '{"error": "File not found", "status": "unknown", "source": "none"}'
        return 1
    fi

    local detected_status=""
    local source="none"

    # Method 1: Check status header in document
    # Look for **Current Status**: or **Status**: patterns
    local header_status
    header_status=$(grep -iE '\*\*(Current )?Status\*\*:\s*' "$file" 2>/dev/null | head -1 || echo "")

    if [ -n "$header_status" ]; then
        # Extract the status value - handle various formats
        local status_value
        status_value=$(echo "$header_status" | sed -E 's/.*\*\*:\s*//i' | tr '[:upper:]' '[:lower:]' | tr -d '*' | xargs)

        # Check if it's a valid lifecycle state
        for state in "${LIFECYCLE_STATES[@]}"; do
            if [[ "$status_value" == *"$state"* ]]; then
                detected_status="$state"
                source="header"
                break
            fi
        done
    fi

    # Method 2: Infer from directory path
    if [ -z "$detected_status" ]; then
        local dir_path
        dir_path=$(dirname "$file")
        local dir_name
        dir_name=$(basename "$dir_path")

        for state in "${LIFECYCLE_STATES[@]}"; do
            if [ "$dir_name" = "$state" ]; then
                detected_status="$state"
                source="directory"
                break
            fi
        done
    fi

    # Default to draft if no status found
    if [ -z "$detected_status" ]; then
        detected_status="draft"
        source="default"
    fi

    # Get last updated date if present
    local last_updated=""
    local updated_line
    updated_line=$(grep -iE '\*\*Last Updated\*\*:' "$file" 2>/dev/null | head -1 || echo "")
    if [ -n "$updated_line" ]; then
        last_updated=$(echo "$updated_line" | sed -E 's/.*\*\*:\s*//' | xargs)
    fi

    cat << EOF
{
    "status": "$detected_status",
    "source": "$source",
    "last_updated": "$last_updated",
    "file": "$file"
}
EOF
}

# ============================================
# AC-15: EPHEMERAL DIRECTORY CHECK
# ============================================

# Check if a path is in an ephemeral directory
is_ephemeral() {
    local file="$1"

    for ephemeral in "${EPHEMERAL_DIRS[@]}"; do
        if [[ "$file" == *"/$ephemeral/"* ]] || [[ "$file" == *"/$ephemeral" ]]; then
            echo "true"
            return 0
        fi
    done

    echo "false"
}

# ============================================
# AC-13: AUTO-CREATE LIFECYCLE SUBFOLDERS
# ============================================

# Ensure lifecycle subfolders exist in a documentation directory
ensure_lifecycle_folders() {
    local base_dir="$1"
    local created_count=0
    local created_dirs=()

    if [ ! -d "$base_dir" ]; then
        echo '{"error": "Base directory not found", "created": 0}'
        return 1
    fi

    for folder in "${LIFECYCLE_FOLDERS[@]}"; do
        local full_path="${base_dir}/${folder}"
        if [ ! -d "$full_path" ]; then
            mkdir -p "$full_path"
            created_count=$((created_count + 1))
            created_dirs+=("$folder")
        fi
    done

    # Format created dirs as JSON array
    local created_json="["
    local first=true
    for dir in "${created_dirs[@]}"; do
        if [ "$first" = true ]; then
            first=false
        else
            created_json+=","
        fi
        created_json+="\"$dir\""
    done
    created_json+="]"

    cat << EOF
{
    "base_dir": "$base_dir",
    "created_count": $created_count,
    "created_dirs": $created_json
}
EOF
}

# ============================================
# AC-11 & AC-12: AUTOMATIC STATUS TRANSITIONS
# ============================================

# Determine the target lifecycle folder for a document
get_target_folder() {
    local file="$1"
    local current_status="$2"
    local completion_pct="$3"
    local has_code_changes="${4:-false}"

    local target_status="$current_status"
    local reason=""

    # AC-11: approved -> in-progress when code changes detected
    if [ "$current_status" = "approved" ] && [ "$has_code_changes" = "true" ]; then
        target_status="in-progress"
        reason="Code changes detected for approved document"
    fi

    # AC-12: in-progress -> implemented at 100% completion
    if [ "$current_status" = "in-progress" ] && [ "$completion_pct" -eq 100 ]; then
        target_status="implemented"
        reason="100% acceptance criteria completion"
    fi

    echo "$target_status|$reason"
}

# Move document to appropriate lifecycle folder
move_to_lifecycle_folder() {
    local file="$1"
    local target_status="$2"
    local dry_run="${3:-false}"

    if [ ! -f "$file" ]; then
        echo '{"error": "File not found", "moved": false}'
        return 1
    fi

    # Get the parent documentation directory
    local current_dir
    current_dir=$(dirname "$file")
    local filename
    filename=$(basename "$file")

    # Find the base documentation directory
    local base_dir="$current_dir"
    for folder in "${LIFECYCLE_FOLDERS[@]}"; do
        if [[ "$current_dir" == *"/$folder" ]]; then
            base_dir=$(dirname "$current_dir")
            break
        fi
    done

    # Ensure target folder exists (AC-13)
    local target_dir="${base_dir}/${target_status}"

    if [ "$dry_run" = "true" ]; then
        cat << EOF
{
    "dry_run": true,
    "would_move": true,
    "from": "$file",
    "to": "${target_dir}/${filename}"
}
EOF
        return 0
    fi

    # Create folder if needed
    if [ ! -d "$target_dir" ]; then
        mkdir -p "$target_dir"
    fi

    # Move the file
    local target_path="${target_dir}/${filename}"

    if [ "$file" != "$target_path" ]; then
        mv "$file" "$target_path"
        cat << EOF
{
    "moved": true,
    "from": "$file",
    "to": "$target_path",
    "status": "$target_status"
}
EOF
    else
        cat << EOF
{
    "moved": false,
    "reason": "File already in correct location",
    "path": "$file"
}
EOF
    fi
}

# Update document status header
update_status_header() {
    local file="$1"
    local new_status="$2"
    local today
    today=$(date +%Y-%m-%d)

    if [ ! -f "$file" ]; then
        echo '{"error": "File not found", "updated": false}'
        return 1
    fi

    # Check if status header exists
    if grep -qiE '\*\*(Current )?Status\*\*:' "$file"; then
        # Update existing status
        sed -i.bak -E "s/(\*\*(Current )?Status\*\*:).*/\1 $new_status/" "$file"
        rm -f "${file}.bak"

        # Update Last Updated if present
        if grep -qiE '\*\*Last Updated\*\*:' "$file"; then
            sed -i.bak -E "s/(\*\*Last Updated\*\*:).*/\1 $today/" "$file"
            rm -f "${file}.bak"
        fi

        echo '{"updated": true, "status": "'"$new_status"'", "last_updated": "'"$today"'"}'
    else
        echo '{"updated": false, "reason": "No status header found"}'
    fi
}

# ============================================
# AC-14: SCAN ALL DOCUMENTATION DIRECTORIES
# ============================================

# Get all managed documentation files
get_managed_documents() {
    local include_ephemeral="${1:-false}"
    local docs=()

    for doc_dir in "${DOC_DIRECTORIES[@]}"; do
        if [ -d "$doc_dir" ]; then
            # Find all markdown files
            while IFS= read -r -d '' file; do
                local is_eph
                is_eph=$(is_ephemeral "$file")

                # Skip ephemeral unless explicitly included
                if [ "$include_ephemeral" = "false" ] && [ "$is_eph" = "true" ]; then
                    continue
                fi

                # Skip CLAUDE.md files
                if [[ "$(basename "$file")" == "CLAUDE.md" ]]; then
                    continue
                fi

                docs+=("$file")
            done < <(find "$doc_dir" -name "*.md" -type f -print0 2>/dev/null)
        fi
    done

    printf '%s\n' "${docs[@]}"
}

# Scan all documents and check for transitions
scan_documents() {
    local commit_range="${1:-}"
    local changed_files=()

    # Get changed code files if commit range provided
    if [ -n "$commit_range" ]; then
        # Get non-documentation file changes (actual code changes)
        while IFS= read -r file; do
            if [[ ! "$file" =~ ^documentation/ ]] && [[ ! "$file" =~ ^\.taskmaster/ ]] && [[ "$file" =~ \.(py|ts|tsx|js|jsx)$ ]]; then
                changed_files+=("$file")
            fi
        done < <(git diff --name-only "$commit_range" 2>/dev/null || echo "")
    fi

    local has_code_changes="false"
    if [ ${#changed_files[@]} -gt 0 ]; then
        has_code_changes="true"
    fi

    # Get all managed documents
    local documents
    documents=$(get_managed_documents)

    local results='{"documents": ['
    local first=true

    while IFS= read -r doc; do
        if [ -z "$doc" ]; then
            continue
        fi

        if [ "$first" = true ]; then
            first=false
        else
            results+=','
        fi

        # Get current status
        local status_json
        status_json=$(detect_lifecycle_state "$doc")
        local current_status
        current_status=$(echo "$status_json" | grep -o '"status": "[^"]*"' | sed 's/"status": "//' | tr -d '"')

        # Get completion
        local completion_json
        completion_json=$(calculate_completion "$doc")
        local completion_pct
        completion_pct=$(echo "$completion_json" | grep -o '"percentage": [0-9]*' | sed 's/"percentage": //')

        # Check for transition
        local transition_result
        transition_result=$(get_target_folder "$doc" "$current_status" "${completion_pct:-0}" "$has_code_changes")
        local target_status
        target_status=$(echo "$transition_result" | cut -d'|' -f1)
        local transition_reason
        transition_reason=$(echo "$transition_result" | cut -d'|' -f2)

        local needs_transition="false"
        if [ "$target_status" != "$current_status" ]; then
            needs_transition="true"
        fi

        results+="{"
        results+="\"file\": \"$doc\","
        results+="\"current_status\": \"$current_status\","
        results+="\"completion_percentage\": ${completion_pct:-0},"
        results+="\"needs_transition\": $needs_transition,"
        results+="\"target_status\": \"$target_status\","
        results+="\"transition_reason\": \"$transition_reason\""
        results+="}"
    done <<< "$documents"

    results+='],'
    results+="\"has_code_changes\": $has_code_changes,"
    results+="\"code_files_changed\": ${#changed_files[@]}"
    results+="}"

    echo "$results"
}

# Apply all pending transitions
apply_transitions() {
    local commit_range="${1:-}"
    local dry_run="${2:-false}"

    local scan_result
    scan_result=$(scan_documents "$commit_range")

    local applied=()
    local skipped=()

    # Parse documents needing transition
    # Using a simpler parsing approach
    local needs_transition_docs
    needs_transition_docs=$(echo "$scan_result" | grep -o '"file": "[^"]*".*"needs_transition": true' | sed 's/"file": "//' | cut -d'"' -f1)

    while IFS= read -r doc; do
        if [ -z "$doc" ]; then
            continue
        fi

        # Get target status for this doc
        local status_json
        status_json=$(detect_lifecycle_state "$doc")
        local current_status
        current_status=$(echo "$status_json" | grep -o '"status": "[^"]*"' | sed 's/"status": "//' | tr -d '"')

        local completion_json
        completion_json=$(calculate_completion "$doc")
        local completion_pct
        completion_pct=$(echo "$completion_json" | grep -o '"percentage": [0-9]*' | sed 's/"percentage": //')

        local has_code_changes="false"
        if echo "$scan_result" | grep -q '"has_code_changes": true'; then
            has_code_changes="true"
        fi

        local transition_result
        transition_result=$(get_target_folder "$doc" "$current_status" "${completion_pct:-0}" "$has_code_changes")
        local target_status
        target_status=$(echo "$transition_result" | cut -d'|' -f1)

        if [ "$target_status" != "$current_status" ]; then
            if [ "$dry_run" = "true" ]; then
                applied+=("$doc -> $target_status (dry run)")
            else
                # Update status header
                update_status_header "$doc" "$target_status" > /dev/null
                # Move to lifecycle folder
                move_to_lifecycle_folder "$doc" "$target_status" > /dev/null
                applied+=("$doc -> $target_status")
            fi
        fi
    done <<< "$needs_transition_docs"

    # Format output
    local applied_json="["
    local first=true
    for item in "${applied[@]}"; do
        if [ "$first" = true ]; then
            first=false
        else
            applied_json+=","
        fi
        applied_json+="\"$item\""
    done
    applied_json+="]"

    cat << EOF
{
    "dry_run": $dry_run,
    "transitions_applied": ${#applied[@]},
    "applied": $applied_json
}
EOF
}

# ============================================
# REPORT GENERATION
# ============================================

generate_report() {
    local commit_range="${1:-}"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    local scan_result
    scan_result=$(scan_documents "$commit_range")

    # Count by status
    local draft_count=0
    local approved_count=0
    local in_progress_count=0
    local implemented_count=0
    local staged_count=0
    local needs_transition_count=0

    # Parse counts (simplified)
    draft_count=$(echo "$scan_result" | grep -c '"current_status": "draft"' || echo "0")
    approved_count=$(echo "$scan_result" | grep -c '"current_status": "approved"' || echo "0")
    in_progress_count=$(echo "$scan_result" | grep -c '"current_status": "in-progress"' || echo "0")
    implemented_count=$(echo "$scan_result" | grep -c '"current_status": "implemented"' || echo "0")
    staged_count=$(echo "$scan_result" | grep -c '"current_status": "staged"' || echo "0")
    needs_transition_count=$(echo "$scan_result" | grep -c '"needs_transition": true' || echo "0")

    cat << EOF
{
    "timestamp": "$timestamp",
    "commit_range": "$commit_range",
    "summary": {
        "draft": $draft_count,
        "approved": $approved_count,
        "in_progress": $in_progress_count,
        "implemented": $implemented_count,
        "staged": $staged_count,
        "needs_transition": $needs_transition_count
    },
    "scan_result": $scan_result
}
EOF
}

# ============================================
# CLI INTERFACE
# ============================================

show_help() {
    cat << EOF
Document Lifecycle Management Utility

Usage: $0 [command] [args...]

Commands:
    scan [commit-range]        Scan all documents and report status
    completion <file>          Calculate completion percentage for a file
    status <file>              Get lifecycle status of a document
    transition [commit-range]  Apply automatic transitions (dry run)
    apply [commit-range]       Apply automatic transitions (for real)
    ensure-folders <dir>       Ensure lifecycle folders exist in directory
    report [commit-range]      Generate full lifecycle report (JSON)
    help                       Show this help message

Examples:
    $0 scan                              # Scan all documents
    $0 scan abc1234..HEAD                # Scan with commit range
    $0 completion documentation/prds/my-prd.md
    $0 status .taskmaster/docs/my-doc.md
    $0 transition abc1234..HEAD          # Preview transitions
    $0 apply abc1234..HEAD               # Apply transitions
    $0 report > lifecycle-report.json

Lifecycle States:
    draft       Initial document under review
    approved    Ready for implementation
    in-progress Active implementation work
    implemented All acceptance criteria complete (100%)
    staged      Released/deployed to production

Automatic Transitions (AC-11, AC-12):
    approved -> in-progress    When code changes detected
    in-progress -> implemented When 100% AC completion

Excluded Directories (AC-15):
    scratch-pads/    Ephemeral coordination docs
    handoffs/        Session transition docs
EOF
}

# Main CLI handler
main() {
    local command="${1:-help}"
    shift || true

    case "$command" in
        scan)
            scan_documents "${1:-}"
            ;;
        completion)
            if [ -z "${1:-}" ]; then
                echo '{"error": "File path required"}'
                exit 1
            fi
            calculate_completion "$1"
            ;;
        status)
            if [ -z "${1:-}" ]; then
                echo '{"error": "File path required"}'
                exit 1
            fi
            detect_lifecycle_state "$1"
            ;;
        transition)
            apply_transitions "${1:-}" "true"
            ;;
        apply)
            apply_transitions "${1:-}" "false"
            ;;
        ensure-folders)
            if [ -z "${1:-}" ]; then
                echo '{"error": "Directory path required"}'
                exit 1
            fi
            ensure_lifecycle_folders "$1"
            ;;
        report)
            generate_report "${1:-}"
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

# ============================================
# EXPORTS FOR SOURCING
# ============================================

# Export functions when sourced
export -f calculate_completion 2>/dev/null || true
export -f detect_lifecycle_state 2>/dev/null || true
export -f is_ephemeral 2>/dev/null || true
export -f ensure_lifecycle_folders 2>/dev/null || true
export -f get_target_folder 2>/dev/null || true
export -f move_to_lifecycle_folder 2>/dev/null || true
export -f update_status_header 2>/dev/null || true
export -f get_managed_documents 2>/dev/null || true
export -f scan_documents 2>/dev/null || true
export -f apply_transitions 2>/dev/null || true
export -f generate_report 2>/dev/null || true

# ============================================
# EXECUTION
# ============================================

# Determine if script is being sourced or executed directly
_lifecycle_sourced=false
if [ -n "${BASH_SOURCE:-}" ]; then
    if [ "${BASH_SOURCE[0]:-$0}" != "${0}" ]; then
        _lifecycle_sourced=true
    fi
elif [ -n "${ZSH_EVAL_CONTEXT:-}" ]; then
    case "$ZSH_EVAL_CONTEXT" in
        *:file*) _lifecycle_sourced=true ;;
    esac
fi

# Run main if executed directly
if [ "$_lifecycle_sourced" = "false" ]; then
    main "$@"
fi
