Feature: E5 — Fix run_research.py Async Bug
  Research node completes without asyncio errors

  Scenario: Research node runs without async_generator_athrow
    When I run "python3 cobuilder/engine/run_research.py --help"
    Then exit code is 0
    # Basic check that the module loads

  Scenario: Research node completes on test pipeline
    Given the add-two-numbers-lifecycle pipeline exists
    And the research_domain node has research_queries="pytest,python-unittest"
    When the pipeline runner dispatches the research node
    Then the research node completes without "Task exception was never retrieved" error
    And the research node transitions to validated
    # Scoring: 0.0 if error, 0.5 if completes with warnings, 1.0 if clean
