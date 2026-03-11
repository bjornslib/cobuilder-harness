Feature: Epic A — Per-Step Task Creation in Verification Orchestrator
  As a system operator
  I need the verification orchestrator to create a background_tasks row per sequence step
  So the dashboard timeline has audit trail data to display

  Background:
    Given the agencheck-support-agent repository on branch "feat/dashboard-audit-perstep"
    And the database migration 052_add_task_chain_columns.sql exists

  # --- Migration ---

  @migration @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Migration adds previous_task_id and next_task_id columns
    When I inspect migration "052_add_task_chain_columns.sql"
    Then it adds column "previous_task_id" of type INTEGER to "background_tasks"
    And it adds column "next_task_id" of type INTEGER to "background_tasks"
    And both columns have foreign key references to "background_tasks(id)"
    And both columns have "ON DELETE SET NULL"
    And both columns have "IF NOT EXISTS" guards
    And partial indexes exist for both columns WHERE NOT NULL

  # --- create_step_task function ---

  @service-layer @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: create_step_task function exists with correct signature
    When I inspect "utils/background_task_helpers.py"
    Then class "BackgroundTaskService" has method "create_step_task"
    And the method accepts parameters:
      | parameter           | type     |
      | case_id             | int      |
      | customer_id         | int      |
      | step                | dict     |
      | sequence_id         | int      |
      | sequence_version    | int      |
      | check_type_config_id| int      |
      | previous_task_id    | int/None |
    And the method returns an integer (new task ID)

  @idempotency @scoring:pass=1.0,fail=0.0
  Scenario: create_step_task has idempotency guard
    When I inspect "utils/background_task_helpers.py" method "create_step_task"
    Then it checks for existing tasks with same case_id + step_order before INSERT
    And it returns the existing task_id if a duplicate is found

  @chaining @scoring:pass=1.0,fail=0.0
  Scenario: create_step_task chains previous_task_id
    When I inspect "utils/background_task_helpers.py" method "create_step_task"
    Then the INSERT sets "previous_task_id" to the provided value
    And it updates the previous task's "next_task_id" to point to the new task

  # --- Orchestrator integration ---

  @orchestrator @scoring:pass=1.0,partial=0.5,fail=0.0
  Scenario: Verification orchestrator calls create_step_task before each step dispatch
    When I inspect "prefect_flows/flows/verification_orchestrator.py"
    Then the step iteration loop calls "create_step_task" before dispatching each step
    And the step_task_id is used for the channel dispatch (not the original task_id)
    And TERMINAL_CASE_STATUSES constant is defined
    And a terminal status guard checks case status before each step iteration

  @terminal-guard @scoring:pass=1.0,fail=0.0
  Scenario: Terminal status guard prevents dispatch after case resolution
    When I inspect "prefect_flows/flows/verification_orchestrator.py"
    Then function "_check_case_status" or equivalent exists
    And it queries current case status from database
    And it returns True if status is in TERMINAL_CASE_STATUSES
    And the step loop breaks/returns when terminal status is detected
